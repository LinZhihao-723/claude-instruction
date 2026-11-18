export const meta = {
  name: 'rust-review',
  description: 'Review a Rust change against the y-scope Rust guidelines and linter rules',
  whenToUse:
    'Run by the rust-review skill after scripts/setup.sh, with <bundle>/workflow-args.json as args.',
  phases: [
    { title: 'Review', detail: 'one reviewer per rule set and linter rule, plus testing and style' },
    { title: 'Merge', detail: 'deduplicate the findings of all reviewers' },
    { title: 'Verify', detail: 'one verifier per merged finding' },
  ],
}

// FINDING_SCHEMA must equal schemas/finding.json without its `$schema` and `$id` keys.
// tests/run-tests.sh checks this.
// BEGIN FINDING_SCHEMA
const FINDING_SCHEMA = {
  "title": "Finding",
  "description": "One guideline violation found in the reviewed change.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "id",
    "severity",
    "description",
    "references",
    "file",
    "line_range",
    "in_diff",
    "suggestion",
    "diff"
  ],
  "properties": {
    "id": {
      "description": "F1, F2, ... Reviewers number their own findings; the final report renumbers them.",
      "type": "string",
      "pattern": "^F[1-9][0-9]*$"
    },
    "severity": {
      "type": "string",
      "enum": [
        "blocking",
        "should-fix",
        "nit"
      ]
    },
    "description": {
      "description": "What is wrong at the cited lines and why it violates the referenced rules.",
      "type": "string",
      "minLength": 1
    },
    "references": {
      "description": "Rule IDs (ERR-4), linter rules (linter:errors-doc), or guide sections without IDs (coding-style.md#test-names, pr-review.md#pr-title-convention).",
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "string",
        "pattern": "^([A-Z]+-[1-9][0-9]*|linter:[a-z0-9-]+|(coding-style|pr-review)\\.md#[^\\s#]+)$"
      }
    },
    "file": {
      "description": "Path relative to the repository root, or null for a finding about the PR itself (e.g. its title).",
      "type": [
        "string",
        "null"
      ],
      "minLength": 1
    },
    "line_range": {
      "description": "Inclusive 1-based [start, end] on the reviewed commit, or null when no line applies.",
      "type": [
        "array",
        "null"
      ],
      "minItems": 2,
      "maxItems": 2,
      "items": {
        "type": "integer",
        "minimum": 1
      }
    },
    "in_diff": {
      "description": "Whether the change under review introduced the violation; false for pre-existing problems in surrounding code.",
      "type": "boolean"
    },
    "suggestion": {
      "description": "The fix to make, in prose.",
      "type": "string",
      "minLength": 1
    },
    "diff": {
      "description": "A unified diff (a/ and b/ prefixes, paths from the repository root) that applies with `git apply` at the reviewed commit, or null.",
      "type": [
        "string",
        "null"
      ]
    }
  }
}
// END FINDING_SCHEMA

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['findings'],
  properties: {
    findings: { type: 'array', items: FINDING_SCHEMA },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['keep', 'reason', 'finding'],
  properties: {
    keep: { type: 'boolean' },
    reason: { type: 'string', minLength: 1 },
    finding: FINDING_SCHEMA,
  },
}

const input = typeof args === 'string' ? JSON.parse(args) : args || {}
for (const key of ['bundle', 'skill_dir', 'rule_sets', 'double_check', 'linter_only']) {
  if (input[key] === undefined) {
    throw new Error(`args.${key} is missing: pass <bundle>/workflow-args.json as args`)
  }
}
const bundle = input.bundle

function taskPrompt(promptFile, params, inlineJson) {
  const lines = [
    `Read \`${input.skill_dir}/prompts/${promptFile}\` and follow it with these parameters:`,
    '',
  ]
  for (const [name, value] of Object.entries(params)) {
    lines.push(`- ${name}: \`${value}\``)
  }
  for (const [name, value] of Object.entries(inlineJson || {})) {
    lines.push(`- ${name}:`, '', '```json', JSON.stringify(value, null, 2), '```')
  }
  return lines.join('\n')
}

function ruleSetName(path) {
  return path.split('/').pop().replace(/\.md$/, '')
}

function renumber(findings) {
  return findings.map((finding, index) => ({ ...finding, id: `F${index + 1}` }))
}

const reviewers = [
  ...input.rule_sets.map((ruleSet) => ({
    label: `rules: ${ruleSetName(ruleSet)}`,
    prompt: taskPrompt('rule-set.md', { BUNDLE: bundle, RULE_SET: ruleSet }),
  })),
  ...input.double_check.map((rule) => ({
    label: `linter: ${rule}`,
    prompt: taskPrompt('linter-rule.md', { BUNDLE: bundle, LINTER_RULE: rule }),
  })),
  ...input.linter_only.map((rule) => ({
    label: `linter-only: ${rule}`,
    prompt: taskPrompt('linter-only.md', { BUNDLE: bundle, LINTER_RULE: rule }),
    effort: 'low',
  })),
  { label: 'testing', prompt: taskPrompt('testing.md', { BUNDLE: bundle }) },
  { label: 'other', prompt: taskPrompt('other.md', { BUNDLE: bundle }) },
]

phase('Review')
const reviews = await parallel(
  reviewers.map((reviewer) => () => {
    const options = { label: reviewer.label, phase: 'Review', schema: FINDINGS_SCHEMA }
    if (reviewer.effort) {
      options.effort = reviewer.effort
    }
    return agent(reviewer.prompt, options)
  }),
)
const failedReviewers = reviewers
  .filter((_, index) => !reviews[index])
  .map((reviewer) => reviewer.label)
if (failedReviewers.length > 0) {
  log(`No result from ${failedReviewers.length} reviewer(s): ${failedReviewers.join(', ')}`)
}
const rawFindings = renumber(reviews.filter(Boolean).flatMap((review) => review.findings))
const reviewerCount = reviewers.length - failedReviewers.length
log(`${rawFindings.length} raw finding(s) from ${reviewerCount} reviewer(s)`)
if (rawFindings.length === 0) {
  return { findings: [], dropped: [], unverified: [], failed_reviewers: failedReviewers }
}

// Barrier: deduplication needs every reviewer's findings at once.
phase('Merge')
const merged = await agent(taskPrompt('merge.md', { BUNDLE: bundle }, { FINDINGS: rawFindings }), {
  label: 'merge',
  phase: 'Merge',
  schema: FINDINGS_SCHEMA,
})
let candidates = rawFindings
if (merged) {
  candidates = renumber(merged.findings)
  log(`${rawFindings.length} raw finding(s) merged into ${candidates.length}`)
} else {
  log('The merge agent returned no result; verifying the unmerged findings')
}

phase('Verify')
const verdicts = await pipeline(candidates, (finding) =>
  agent(taskPrompt('verify.md', { BUNDLE: bundle }, { FINDING: finding }), {
    label: `verify ${finding.id}: ${finding.references.join(', ')}`,
    phase: 'Verify',
    schema: VERDICT_SCHEMA,
  }),
)

const findings = []
const dropped = []
const unverified = []
candidates.forEach((finding, index) => {
  const verdict = verdicts[index]
  if (!verdict) {
    unverified.push(finding.id)
    findings.push(finding)
  } else if (verdict.keep) {
    findings.push({ ...verdict.finding, id: finding.id })
  } else {
    dropped.push({ id: finding.id, description: finding.description, reason: verdict.reason })
  }
})
if (unverified.length > 0) {
  log(`Kept ${unverified.length} unverified finding(s) (no verifier result): ${unverified.join(', ')}`)
}
log(`${findings.length} finding(s) kept, ${dropped.length} dropped by verification`)
return { findings, dropped, unverified, failed_reviewers: failedReviewers }
