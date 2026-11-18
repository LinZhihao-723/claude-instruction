# Rules shared by every rust-review agent

Every other prompt in this directory starts by sending you here. Read this file in full, then go
back to your own prompt.

## The bundle

`BUNDLE` is a directory that `scripts/setup.sh` wrote. Start with `BUNDLE/meta.json`:

- `worktree`: the checkout of the reviewed code. Every path in a finding is relative to its root,
  and every line number refers to the files in it.
- `commit`, `base`, `target`, `kind` (`pr`, `branch` or `local`). For `local`, the worktree is
  the user's own working tree, uncommitted changes included.
- `pr`: the PR's `number`, `title`, `body` and `url`, or null when the target is not a PR.
- `guides`: absolute paths to `coding_style` (`coding-style.md`), `pr_review` (`pr-review.md`),
  `checklist`, `testing_rule_set` and `coding_practice_dir`. Always open the guides through these
  paths.
- `linter`: the linter rules, which of them are double-checked, `include_tests`, `rule_docs` (each
  rule's documentation, as a local path or a URL) and `suppression_doc` (how suppression comments
  work).
- `files`: the other bundle files.
- `skill_dir`: this skill's directory. In the prompts, `<skill_dir>` and `<worktree>` stand for
  these two values.

The other bundle files:

- `changed-files.json`: `{"rust": [...], "other": [...]}`. Each entry has `path`, `status` (`A`,
  `M`, `D`, `R`, ...), optional `old_path`, and `ranges`: the added or changed lines on the new
  side, as inclusive `[start, end]` pairs.
- `diff.patch` (full context), `diff-U0.patch` (no context), `diff-rs-U0.patch` (`.rs` files only).
- `commits.txt`: the commits in the change, one `<sha> <subject>` per line.
- `pr.md`: the PR title and description, when the target is a PR.
- `references.tsv`: every valid reference (`reference`, `location`, `title`): rule IDs, guide
  section anchors such as `coding-style.md#test-names`, and `linter:<rule>`. The `location` is
  `<absolute path>:<line>` of the rule or heading.

## Ground rules

- **Read only.** Never edit, create, stage, commit or delete anything in the worktree; for `local`
  it is the user's working tree. The only command that may touch it is `git apply --check`. Don't
  run `cargo build`, `cargo test` or other commands that write into it.
- **Read every changed file in full**, not only its hunks: the file as it is in the worktree, plus
  the diff to see what changed. A violation often sits next to the lines that changed, or is caused
  by them in code they didn't touch.
- **Review the change.** Focus on the code the change adds or modifies. You may report a problem in
  surrounding code, but mark it `in_diff: false`.
- **Report only what you can pin down.** Each finding cites a concrete file and line, names the
  rule it breaks, and says why that code breaks it. No speculation, no "consider ..." advice, no
  restating a rule without the code that breaks it. If a rule's **Exceptions** paragraph covers the
  code, it is not a violation.
- **One violation per finding.** The same issue at several unrelated places is several findings;
  one issue spanning adjacent lines is one finding.
- `coding-style.md` wins any conflict with the other guides on style (naming, docstrings,
  formatting, lint policy).

## The finding schema

Return findings that match `schemas/finding.json` (in this skill's directory, `meta.json`'s
`skill_dir`). Each finding has exactly these fields, and no others:

- `id`: `F1`, `F2`, ... in your own output; the final report renumbers them.
- `severity`:
  - `blocking`: a bug, a broken invariant, a security or data-loss risk, an unmarked breaking
    change, or anything that will fail at runtime or in CI.
  - `should-fix`: a clear violation of a documented rule that should be fixed before merge, but
    doesn't fail on its own.
  - `nit`: a minor style or wording issue.
- `description`: what is wrong at these lines and why it breaks the rule. Name the identifiers
  involved. One to three sentences.
- `references`: at least one. Use the exact strings from `references.tsv`:
  - a rule ID, such as `ERR-4`, for a rule in `coding-practice/`;
  - `linter:<rule>`, such as `linter:errors-doc`, for a linter rule;
  - `coding-style.md#<anchor>` or `pr-review.md#<anchor>` for a guide section without an ID. Cite
    the most specific heading that states the rule.
- `file`: the path relative to the worktree root, or null only for a finding about the PR itself
  (for example its title).
- `line_range`: `[start, end]`, inclusive, 1-based, in the worktree file. Null only when no line
  applies.
- `in_diff`: true when the change introduced the violation: the lines overlap a changed range in
  `changed-files.json`, or the change made them wrong (for example a docstring the change made
  stale). False for a pre-existing problem in surrounding code.
- `suggestion`: the fix, concretely: what to write instead, or which type, variant or call to use.
- `diff`: a unified diff with the fix, or null. Give one only for a small, local fix you are sure
  of. It must apply with `git apply` at the worktree root: `diff --git a/<path> b/<path>`,
  `--- a/<path>`, `+++ b/<path>`, exact hunk line counts, at least one unchanged context line before
  and after each change, and a trailing newline. Check it with
  `git -C <worktree> apply --check <file>`, with the file written under `BUNDLE/scratch/` (create
  it) and named after your role and finding ID so that it can't clash with another agent's. If the
  diff doesn't apply, fix it or set `diff` to null.

## Output

Return JSON only, with no prose before or after it:

```json
{"findings": [ ... ]}
```

Return `{"findings": []}` when you find nothing. When your environment gives you a structured
output tool for this, return the same object through it.
