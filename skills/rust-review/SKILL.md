---
name: rust-review
description: Review Rust code changes against the y-scope Rust guidelines (coding-practice rule sets, coding-style.md, pr-review.md) and the yscope-rust-linter rules, producing a JSON report of verified findings. Use when asked to review a Rust PR, branch, commit or local diff in a y-scope repository (Spider, CLP Rust components), or to check Rust changes against the y-scope guidelines.
---

# Rust review

Reviews one Rust change with parallel reviewers, merges and verifies their findings, and writes
`<bundle>/report.json` (schema: `schemas/report.json`; example: `schemas/example-report.json`).

`<skill>` below is this skill's directory. Run every script from inside the repository under
review, or pass `--repo <dir>` to `setup.sh`.

## Prerequisites

- `git` and `python3`. `gh` (authenticated) for PR targets.
- `yscope-rust-linter`, optional but expected. Install it with
  `cargo install --git https://github.com/LinZhihao-723/yscope-rust-linter --locked`, or set
  `YSCOPE_RUST_LINTER` to a binary. Set `YSCOPE_RUST_LINTER_DOCS` to a checkout's `docs/rules`
  directory to read the rule docs locally instead of downloading them.

## Configuration (`config.json`)

- `base_branch`: the branch that branch and `local` targets are diffed against (merge base).
  Default `main`. `setup.sh --base <ref>` overrides it.
- `linter.rules`: the linter rules to run.
- `linter.double_check`: the rules that also get a manual review against their documentation
  (default: all of them, as the linter is in beta). Every other rule in `linter.rules` gets a
  linter-only run whose diagnostics become findings without review.
- `linter.include_tests`: pass `--include-tests` to the linter (checks `#[test]` fns and
  `#[cfg(test)]` modules in `errors-doc`).
- `linter.rule_doc_url`: where to download each rule's documentation; `{rule}` is the rule ID.

## Step 1: Set up the bundle

```text
<skill>/scripts/setup.sh <target> [--repo <dir>] [--base <ref>]
```

`<target>` is a PR number or URL, a branch (or commit), or `local` (the working tree, uncommitted
changes included). The script checks the PR or branch out in a detached worktree in a temp dir,
writes the bundle, and prints the bundle's path on its last line. Relay its warnings to the user
(the linter is missing, untracked `.rs` files are left out of the diff). Stop if it fails.

The bundle holds `meta.json` (commit, base, worktree, PR title and description, absolute paths to
the guides, the config and the rule docs), `changed-files.json` (changed `.rs` and other files
with their changed line ranges), `diff.patch`, `diff-U0.patch`, `references.tsv` (every valid
finding reference) and `workflow-args.json`.

## Step 2: Review, merge and verify

Every agent gets the same kind of task, with its parameters filled in:

```text
Read `<skill>/prompts/<prompt>.md` and follow it with these parameters:
- BUNDLE: `<bundle>`
- <NAME>: `<value>`
```

The agents (lists from `<bundle>/workflow-args.json`):

| Agent | Prompt | Parameters |
| ----- | ------ | ---------- |
| one per entry of `rule_sets` | `rule-set.md` | `BUNDLE`, `RULE_SET` |
| one per entry of `double_check` | `linter-rule.md` | `BUNDLE`, `LINTER_RULE` |
| one per entry of `linter_only` | `linter-only.md` | `BUNDLE`, `LINTER_RULE` |
| test coverage | `testing.md` | `BUNDLE` |
| style and PR conventions | `other.md` | `BUNDLE` |
| merge, after all reviewers | `merge.md` | `BUNDLE`, `FINDINGS` (inline JSON array) |
| verify, one per merged finding | `verify.md` | `BUNDLE`, `FINDING` (inline JSON) |

Reviewers and the merge agent return `{"findings": [...]}` (each item matches
`schemas/finding.json`); a verifier returns `{"keep", "reason", "finding"}`. Use the first of these
execution paths that your environment supports.

### (a) Workflow tool

If a dynamic-workflow tool is available (Claude Code's Workflow tool), run
`<skill>/workflows/review.js` through its `scriptPath`, with the JSON object in
`<bundle>/workflow-args.json` as `args` (an object, not a string). It runs the reviewers in
parallel, merges, verifies each merged finding, and returns
`{findings, dropped, unverified, failed_reviewers}`. Write `findings` to
`<bundle>/findings.json`.

### (b) Subagents

If you can spawn subagents:

1. Spawn every reviewer from the table at once, in parallel. Save each result as
   `<bundle>/findings/<agent>.json`. If one fails, retry it once, then note the gap for the user.
2. Concatenate all reviewer findings, renumber them `F1`, `F2`, ..., and spawn one merge agent
   with them as `FINDINGS`.
3. Spawn one verifier per merged finding, in parallel. Keep each `finding` whose verdict has
   `keep: true`; keep the original finding of a verifier that failed, and tell the user.
4. Write the kept findings to `<bundle>/findings.json`.

### (c) One context

Otherwise, do the same steps yourself, one at a time: each reviewer prompt in turn (save each
result under `<bundle>/findings/` before starting the next, and work from those files rather than
from memory), then `merge.md` over all of them, then `verify.md` for each merged finding. Use the
same prompts and schema, and write the kept findings to `<bundle>/findings.json`.

## Step 3: Write the report

```text
<skill>/scripts/finalize.sh <bundle> <bundle>/findings.json
```

It sorts and renumbers the findings, writes `<bundle>/report.json`, runs `check-diffs.sh` (each
suggested diff gets `git apply --check` in the worktree, and one that doesn't apply becomes
`null`), warns about unknown references, and validates the report against the schema. Fix the
findings file and rerun it if validation fails.

## Step 4: Summarize and clean up

Give the user a short summary: the number of findings per severity, one line for each `blocking`
finding (file, line, rule), any reviewer that failed or finding left unverified, and the path to
`report.json`. Don't paste the whole report.

Then remove the worktree (the bundle and its report stay):

```text
<skill>/scripts/cleanup.sh <bundle>
```

## Other scripts

- `scripts/run-linter.sh <rule> <bundle>`: runs one linter rule on the changed lines; used by the
  linter prompts.
- `scripts/check-diffs.sh <bundle> [<report>]`: the diff check on its own.
- `tests/run-tests.sh`: the skill's self-checks, including that the finding schema embedded in
  `workflows/review.js` matches `schemas/finding.json`. Run it after changing either.
