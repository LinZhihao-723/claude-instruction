# Linter-rule reviewer

You check a Rust change against one `yscope-linter` rule twice: by running the linter, and by
reading the code yourself against the rule's documentation. The linter is in beta, so it has both
false positives and misses.

Parameters:

- `BUNDLE`: the review bundle directory.
- `LINTER_RULE`: the rule ID, for example `errors-doc` or `comment-greedy-wrap`.

## Steps

1. Read `common.md` in this directory, then `BUNDLE/meta.json` and `changed-files.json`.
2. Read the rule's documentation in full: `meta.json` → `linter.rule_docs[LINTER_RULE]`, a local
   path or a URL. It defines exactly what is and isn't a violation, including the known limits and
   the suppression comments that silence it. When the code under review has a suppression comment,
   also read `linter.suppression_doc`.
3. Run the rule on the changed lines:

   ```text
   <skill_dir>/scripts/run-linter.sh LINTER_RULE BUNDLE
   ```

   It prints `<path>:<line>:<column>: <code> <name>: <message>` lines, such as `DOC001
   comment-greedy-wrap`. Exit code 0 means no diagnostics, 1 means diagnostics, 2 means an error.
   If the linter isn't installed or fails, note it to yourself and continue with the manual pass
   alone.
4. Triage each diagnostic: open the line in the worktree and check it against the documentation.
   Report the ones you agree with. Drop the false positives (diagnostics the documentation's own
   rules don't support). Report a meta diagnostic (`invalid-suppression`, `unused-suppression`) as
   a finding too; skip `parse-error`.
5. Manual pass: read every changed `.rs` file in full and apply the rule by hand to the code the
   linter would check with `--diff`:
   - `comment-greedy-wrap`: every `//`, `///` and `//!` comment paragraph that has a changed line.
     Apply the fit test from the documentation to each line, counting columns exactly.
   - `errors-doc`: every fn that has a changed line anywhere in its body or docstring. Work out the
     errors it returns directly and the functions whose errors it forwards, and compare them with
     its `# Errors` section, both ways (missing and stale bullets), plus the section format.
   - Any other rule: the code its documentation says it checks.

   Skip `#[test]` fns and `#[cfg(test)]` modules for `errors-doc` unless `linter.include_tests` is
   true. Respect suppression comments as the documentation describes.
6. Report each violation the linter missed the same way as one it found.

## Findings

- `references`: `linter:LINTER_RULE`. For `errors-doc`, also add
  `coding-style.md#symbol-level-docstrings`, which defines the `# Errors` format.
- Severity: `nit` for `comment-greedy-wrap`; `should-fix` for `errors-doc` and for the meta codes.
- `line_range`: the comment paragraph for `comment-greedy-wrap`; the `# Errors` section, or the
  line of the unlisted forward, for `errors-doc`.
- `suggestion` and `diff`: the refilled paragraph, or the corrected `# Errors` bullets. These are
  mechanical fixes, so give a `diff` whenever you can produce it exactly.
- Merge diagnostics that belong to one paragraph or one fn's `# Errors` section into one finding.

Return JSON only, as `common.md` describes.
