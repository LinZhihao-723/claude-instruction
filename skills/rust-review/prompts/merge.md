# Merge reviewer findings

You merge the findings of all reviewers into one list with one entry per violation. Don't judge
whether a finding is right; a verifier does that next.

Parameters:

- `BUNDLE`: the review bundle directory.
- `FINDINGS`: a JSON array of findings from every reviewer, given inline.

## Steps

1. Read `common.md` in this directory for the finding schema.
2. Group the findings that describe the same violation: the same `file` (or both null), overlapping
   or adjacent `line_range`s (or both null), and the same underlying issue. Different reviewers
   often describe one issue under different rules, for example a `String` error payload under
   `ERR-3` and `ERR-4`, or a missing `# Errors` bullet under `linter:errors-doc` and
   `coding-style.md#symbol-level-docstrings`. Those belong together. Two different issues on the
   same lines stay separate. When in doubt, open the code in the worktree (`BUNDLE/meta.json` →
   `worktree`).
3. Merge each group into one finding:
   - `references`: every reference of every member, without duplicates, the most specific first.
   - `severity`: the highest in the group (`blocking` > `should-fix` > `nit`).
   - `line_range`: the smallest range that covers the members' ranges.
   - `in_diff`: true if any member's is true.
   - `description` and `suggestion`: one text that keeps every distinct point the members make,
     without repeating the shared ones.
   - `diff`: the member diff that implements the merged suggestion, or null when the members'
     diffs conflict and none covers the whole fix.
4. Keep every finding that has no duplicate unchanged. Don't drop findings, and don't add new ones.
5. Number the result `F1`, `F2`, ... in order of severity, then file, then line.

Return JSON only, as `common.md` describes.
