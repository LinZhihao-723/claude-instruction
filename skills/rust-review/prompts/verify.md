# Verify one finding

You decide whether one review finding holds, and correct it if it does. Reviewers over-report, so
start from doubt: keep the finding only when you can confirm it yourself from the code.

Parameters:

- `BUNDLE`: the review bundle directory.
- `FINDING`: one finding as JSON, given inline.

## Steps

1. Read `common.md` in this directory, then `BUNDLE/meta.json` and `changed-files.json`.
2. Re-read the code: the cited lines of `file` in the worktree, the whole enclosing item (fn, impl,
   type, comment block), and whatever the claim depends on (callers, trait definitions, types, the
   diff). For a PR-level finding (`file` null), read `pr.md` and the diff.
3. Open the text of every reference (`references.tsv` gives each one's location): the rule's
   **Rule**, **Review** and **Exceptions** paragraphs, the guide section, or the linter rule's
   documentation (`meta.json` → `linter.rule_docs`). For a `linter:` finding, you may re-run
   `<skill_dir>/scripts/run-linter.sh <rule> BUNDLE` and apply the documentation's rules by hand.
4. Confirm a concrete violation. Point to the exact code and say how it breaks the rule. For a rule
   about failures (cancellation, panics, lost errors, races, unbounded growth), describe the
   concrete input or interleaving that produces the failure. If you can't, drop the finding.
5. Check the rule's **Exceptions** and any precedence note (`coding-style.md` wins style
   conflicts). Drop the finding if an exception applies or the code already does what the rule
   asks.
6. If the finding holds, correct it:
   - `line_range` and `file` so that they point at the violating lines;
   - `in_diff`, against the changed ranges in `changed-files.json` and the definition in
     `common.md`;
   - `references`: remove any that the code doesn't actually break, keeping at least one;
   - `severity`, using the definitions in `common.md`;
   - `suggestion`, so that it fixes the violation without breaking another rule;
   - `diff`: check it with `git apply --check` as `common.md` describes. Fix it, or set it to null,
     if it doesn't apply or doesn't implement the suggestion.

## Output

Return JSON only:

```json
{"keep": true, "reason": "...", "finding": { ... }}
```

- `keep`: whether the finding holds.
- `reason`: one or two sentences: the confirmed violation, or why it doesn't hold.
- `finding`: the corrected finding when `keep` is true; the input finding unchanged when it is
  false. Keep its `id`.

When your environment gives you a structured output tool for this, return the same object through
it.
