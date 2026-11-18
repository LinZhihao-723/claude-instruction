# Linter-only run

You run one `yscope-rust-linter` rule and convert its diagnostics into findings, without reviewing
the code by hand. This rule is trusted as-is (it is not in `linter.double_check`).

Parameters:

- `BUNDLE`: the review bundle directory.
- `LINTER_RULE`: the rule ID, for example `comment-greedy-wrap`.

## Steps

1. Read `common.md` in this directory (for the finding schema), then `BUNDLE/meta.json`.
2. Run:

   ```text
   <skill_dir>/scripts/run-linter.sh LINTER_RULE BUNDLE
   ```

   Exit code 0 means no diagnostics, 1 means diagnostics, 2 means an error. On exit code 0 or 2,
   return `{"findings": []}`.
3. Convert each `<path>:<line>:<column>: <code>: <message>` line into one finding:
   - `file`: `<path>`; `line_range`: `[<line>, <line>]`; `in_diff`: true (the linter only reports
     changed lines).
   - `references`: `linter:<code>`, where `<code>` is the code printed on the line.
   - `severity`: `nit` for `comment-greedy-wrap`, `should-fix` for every other code. Skip
     `parse-error` lines.
   - `description`: the linter's message, prefixed with the code, for example
     "`comment-greedy-wrap`: line is 40 columns wide ...".
   - `suggestion`: the fix the message asks for, in a sentence.
   - `diff`: null.

Don't add, drop or second-guess diagnostics. Return JSON only, as `common.md` describes.
