#!/usr/bin/env bash
# Self-checks for the rust-review skill. Needs git and python3; node and shellcheck are optional.
#
# Usage: tests/run-tests.sh

set -euo pipefail

skill_dir="$(realpath "$(dirname "$(realpath "${BASH_SOURCE[0]}")")/..")"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/rust-review-tests.XXXXXX")"
trap 'rm -rf "${work_dir}"' EXIT

python3 -B - "${skill_dir}" "${work_dir}" <<'PY'
import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

skill_dir, work_dir = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(skill_dir / "scripts" / "lib"))
import rust_review  # noqa: E402

failures = []


def check(name, condition, detail=""):
    suffix = f": {detail}" if detail and not condition else ""
    print(f"{'ok  ' if condition else 'FAIL'} {name}{suffix}")
    if not condition:
        failures.append(name)


# The workflow's embedded finding schema matches schemas/finding.json.
finding_schema = rust_review.load_json(skill_dir / "schemas" / "finding.json")
script = (skill_dir / "workflows" / "review.js").read_text(encoding="utf-8")
block = script.split("// BEGIN FINDING_SCHEMA\n", 1)[1].split("// END FINDING_SCHEMA", 1)[0]
embedded = json.loads(block.split("=", 1)[1])
expected = {k: v for k, v in finding_schema.items() if k not in ("$schema", "$id")}
check("workflow FINDING_SCHEMA equals schemas/finding.json", embedded == expected)

# The example report is valid, and broken copies are not.
example = rust_review.load_json(skill_dir / "schemas" / "example-report.json")
report_schema = rust_review.load_json(skill_dir / "schemas" / "report.json")
errors = rust_review.validate(example, report_schema)
check("example report matches schemas/report.json", not errors, "; ".join(errors))
broken_cases = {
    "missing field": lambda r: r["findings"][0].pop("suggestion"),
    "unknown severity": lambda r: r["findings"][0].update(severity="major"),
    "bad reference": lambda r: r["findings"][0].update(references=["error-handling.md"]),
    "extra field": lambda r: r["findings"][0].update(detected_by="ERR agent"),
    "one-element line_range": lambda r: r["findings"][0].update(line_range=[3]),
    "short commit": lambda r: r.update(commit="ea7f70e"),
}
for name, mutate in broken_cases.items():
    broken = copy.deepcopy(example)
    mutate(broken)
    check(f"report with {name} is rejected", rust_review.validate(broken, report_schema) != [])

try:
    import jsonschema

    store = {s["$id"]: s for s in (finding_schema, report_schema)}
    resolver = jsonschema.RefResolver("report.json", report_schema, store=store)
    validator_class = getattr(jsonschema, "Draft202012Validator", jsonschema.Draft7Validator)
    validator = validator_class(report_schema, resolver=resolver)
    check("example report passes the jsonschema package", validator.is_valid(example))
    broken = copy.deepcopy(example)
    broken["findings"][0]["severity"] = "major"
    check("jsonschema package rejects a broken report", not validator.is_valid(broken))
except ImportError:
    print("skip jsonschema cross-check (the jsonschema package isn't installed)")

# New-side ranges skip hunk bodies, so a `+++` body line isn't read as a file header.
diff = (
    "diff --git a/a.rs b/a.rs\n--- a/a.rs\n+++ b/a.rs\n@@ -1,0 +2,2 @@\n+++ x\n+y\n"
    "@@ -9 +10,0 @@\n-gone\n"
    "diff --git a/b.rs b/b.rs\n--- a/b.rs\n+++ b/b.rs\n@@ -4 +4 @@\n-old\n+new\n"
)
ranges = rust_review.parse_new_side_ranges(diff)
check("changed ranges from a -U0 diff", ranges == {"a.rs": [[2, 3]], "b.rs": [[4, 4]]}, str(ranges))

# check-diffs keeps a good diff, repairs a miscounted one and nulls one that doesn't apply.
repo = work_dir / "repo"
repo.mkdir()
(repo / "lib.rs").write_text("".join(f"line {n}\n" for n in range(1, 11)), encoding="utf-8")
subprocess.run(["git", "init", "-q", str(repo)], check=True)
bundle = work_dir / "bundle"
bundle.mkdir()
rust_review.write_json(bundle / "meta.json", {"worktree": str(repo)})
header = "diff --git a/lib.rs b/lib.rs\n--- a/lib.rs\n+++ b/lib.rs\n"
diffs = {
    "good": header + "@@ -2,2 +2,2 @@\n-line 2\n+line two\n line 3\n",
    "miscounted": header + "@@ -5,7 +5,9 @@\n line 5\n-line 6\n+line six\n line 7\n",
    "stale": header + "@@ -2,2 +2,2 @@\n-line 20\n+line two\n line 3\n",
}
finding = dict(example["findings"][0])
report = dict(
    example, findings=[dict(finding, id=f"F{i}", diff=d) for i, d in enumerate(diffs.values(), 1)]
)
rust_review.write_json(bundle / "report.json", report)
result = subprocess.run(
    [str(skill_dir / "scripts" / "check-diffs.sh"), str(bundle)], capture_output=True, text=True
)
checked = rust_review.load_json(bundle / "report.json")["findings"]
check("check-diffs.sh exits 0", result.returncode == 0, result.stderr)
check("a diff that applies is kept", checked[0]["diff"] == diffs["good"])
check("a diff with wrong hunk counts is recounted", "@@ -5,3 +5,3 @@" in (checked[1]["diff"] or ""))
check("a diff that doesn't apply is set to null", checked[2]["diff"] is None)
check("check-diffs.sh leaves the worktree untouched", "line 2\n" in (repo / "lib.rs").read_text())

# run-linter.sh falls back to the bundle's `linter.binary` when YSCOPE_RUST_LINTER is unset.
stub = work_dir / "stub-linter"
stub.write_text('#!/usr/bin/env bash\necho "stub-linter $*"\n', encoding="utf-8")
stub.chmod(0o755)
linter_bundle = work_dir / "linter-bundle"
linter_bundle.mkdir()
rust_review.write_json(
    linter_bundle / "meta.json",
    {"worktree": str(repo), "linter": {"binary": str(stub), "include_tests": False}},
)
(linter_bundle / "diff-rs-U0.patch").write_text(diffs["good"], encoding="utf-8")
env = {k: v for k, v in os.environ.items() if k != "YSCOPE_RUST_LINTER"}
result = subprocess.run(
    [str(skill_dir / "scripts" / "run-linter.sh"), "errors-doc", str(linter_bundle)],
    capture_output=True,
    text=True,
    env=env,
)
check("run-linter.sh exits 0 with the meta.json binary", result.returncode == 0, result.stderr)
check("run-linter.sh runs the meta.json binary", result.stdout.startswith("stub-linter --rule"))

# Every reference the prompts, SKILL.md and the example report cite exists in the guides.
guides_dir = (skill_dir / ".." / ".." / "rust").resolve()
known = {row[0] for row in rust_review.guide_index(guides_dir)}
texts = [path.read_text(encoding="utf-8") for path in (skill_dir / "prompts").glob("*.md")]
texts += [(skill_dir / "SKILL.md").read_text(encoding="utf-8"), json.dumps(example)]
cited = set()
for text in texts:
    cited.update(re.findall(r"(?:coding-style|pr-review)\.md#[a-z0-9_-]+", text))
    cited.update(re.findall(r"`([A-Z]{2,5}-[0-9]+)`", text))
for finding in example["findings"]:
    cited.update(ref for ref in finding["references"] if not ref.startswith("linter:"))
missing = sorted(cited - known)
check("every cited rule ID and anchor exists", not missing, ", ".join(missing))

# finalize.sh sorts and renumbers the findings and writes a valid report.
rust_review.write_json(
    bundle / "meta.json",
    {"worktree": str(repo), "commit": example["commit"], "base": example["base"], "target": "x"},
)
with open(bundle / "references.tsv", "w", encoding="utf-8") as file:
    file.write("reference\tlocation\ttitle\n")
    file.writelines(f"{ref}\t-\t-\n" for ref in sorted(known) + ["linter:errors-doc"])
unsorted = [dict(f, id="F9") for f in reversed(example["findings"])]
rust_review.write_json(bundle / "findings.json", {"findings": unsorted})
result = subprocess.run(
    [str(skill_dir / "scripts" / "finalize.sh"), str(bundle), str(bundle / "findings.json")],
    capture_output=True,
    text=True,
)
final = rust_review.load_json(bundle / "report.json")
check("finalize.sh exits 0", result.returncode == 0, result.stderr)
severities = [f["severity"] for f in final["findings"]]
check("finalize.sh sorts by severity", severities == ["blocking", "should-fix", "nit"])
check("finalize.sh renumbers F1..Fn", [f["id"] for f in final["findings"]] == ["F1", "F2", "F3"])
check("finalize.sh writes a valid report", not rust_review.validate(final, report_schema))

sys.exit(1 if failures else 0)
PY

if command -v node >/dev/null; then
    # A workflow script is a module body that may `return` at top level; check it as one.
    sed 's/^export const meta/const meta/' "${skill_dir}/workflows/review.js" \
        | { echo 'async function workflow(args) {'; cat; echo '}'; } >"${work_dir}/review.check.js"
    node --check "${work_dir}/review.check.js"
    echo "ok   node --check workflows/review.js"
else
    echo "skip node --check (node isn't installed)"
fi

if command -v shellcheck >/dev/null; then
    shellcheck "${skill_dir}"/scripts/*.sh "${skill_dir}"/tests/*.sh
    echo "ok   shellcheck"
else
    echo "skip shellcheck (shellcheck isn't installed)"
fi
