#!/usr/bin/env python3
"""Helpers behind the rust-review shell scripts. Standard library only.

Subcommands:

    write-bundle  Writes the bundle's JSON and index files (called by setup.sh).
    finalize      Builds report.json from the merged, verified findings (called by finalize.sh).
    check-diffs   Nulls every finding diff that doesn't apply at the reviewed commit.
    validate      Validates a JSON file against one of the skill's schemas.
    get           Prints one value from a JSON file, addressed by a dotted key.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = SKILL_DIR / "schemas"

EXCLUDED_RULE_SET_FILES = {"README.md", "checklist.md", "testing-and-observability.md"}
TESTING_RULE_SET_FILE = "testing-and-observability.md"
LINTER_META_CODES = ["invalid-suppression", "unused-suppression", "parse-error"]
SEVERITY_ORDER = {"blocking": 0, "should-fix": 1, "nit": 2}

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
RULE_HEADING = re.compile(r"^## ([A-Z]+-\d+): (.*)$")


def load_json(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def write_json(path, value):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(value, file, indent=2, ensure_ascii=False)
        file.write("\n")


def warn(message):
    print(f"rust-review: warning: {message}", file=sys.stderr)


# --- Bundle -----------------------------------------------------------------------------------


def parse_name_status(raw):
    """Parses `git diff --name-status -z` output into `(status, old_path, new_path)` tuples."""
    fields = raw.split("\0")
    entries = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        if status[0] in "RC":
            entries.append((status[0], fields[index + 1], fields[index + 2]))
            index += 3
        else:
            entries.append((status[0], fields[index + 1], fields[index + 1]))
            index += 2
    return entries


def parse_new_side_ranges(diff_text):
    """Returns `{path: [[start, end], ...]}` of the lines a `-U0` diff adds or changes."""
    ranges = {}
    path = None
    lines = diff_text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.startswith("+++ "):
            target = line[4:]
            path = None if target == "/dev/null" else target.removeprefix("b/")
            if path is not None:
                ranges.setdefault(path, [])
            continue
        match = HUNK_HEADER.match(line)
        if not match:
            continue
        old_count = 1 if match.group(2) is None else int(match.group(2))
        new_start = int(match.group(3))
        new_count = 1 if match.group(4) is None else int(match.group(4))
        if path is not None and new_count > 0:
            ranges[path].append([new_start, new_start + new_count - 1])
        # Skip the hunk body so that a body line such as `+++ x` isn't read as a file header.
        body_left = old_count + new_count
        while body_left > 0 and index < len(lines):
            if not lines[index].startswith("\\"):
                body_left -= 1
            index += 1
    return ranges


def guide_index(guides_dir):
    """Returns `(ref, location, title)` rows for every rule ID and guide section anchor."""
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(guides_dir / "coding-practice" / "tools"))
    import build  # noqa: E402  (the guide's own heading-anchor implementation)

    rows = []
    for path in sorted((guides_dir / "coding-practice").glob("*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = RULE_HEADING.match(line)
            if match:
                rows.append((match.group(1), f"{path}:{number}", match.group(2)))
    for name in ("coding-style.md", "pr-review.md"):
        path = guides_dir / name
        occurrences = {}
        for number, line in build.iter_unfenced(path.read_text(encoding="utf-8").splitlines()):
            match = build.ATX_HEADING.match(line)
            if not match:
                continue
            title = build.heading_text(match.group(2))
            slug = build.github_slug(title)
            count = occurrences.get(slug, 0)
            occurrences[slug] = count + 1
            anchor = slug if count == 0 else f"{slug}-{count}"
            heading = f"{'#' * len(match.group(1))} {title}"
            rows.append((f"{name}#{anchor}", f"{path}:{number}", heading))
    return rows


def resolve_doc(name, local_path, url, bundle):
    """Returns a local copy of a linter doc: the checkout's file, a download, or else the URL."""
    if local_path is not None and local_path.is_file():
        return str(local_path.resolve())
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            content = response.read()
    except OSError as error:
        warn(f"couldn't download the linter doc {url} ({error}); agents get the URL instead")
        return url
    download_dir = bundle / "linter-docs"
    download_dir.mkdir(exist_ok=True)
    (download_dir / name).write_bytes(content)
    return str(download_dir / name)


def resolve_linter_docs(rules, url_template, bundle):
    """Returns `({rule: doc}, suppression_doc)`, each a local path or a URL.

    `YSCOPE_LINTER_DOCS` may name a checkout's `docs/rules` directory to read them from.
    """
    local_dir = os.environ.get("YSCOPE_LINTER_DOCS")
    local_dir = Path(local_dir) if local_dir else None
    rule_docs = {
        rule: resolve_doc(
            f"{rule}.md",
            local_dir / f"{rule}.md" if local_dir else None,
            url_template.replace("{rule}", rule),
            bundle,
        )
        for rule in rules
    }
    suppression_doc = resolve_doc(
        "suppression.md",
        local_dir.parent / "suppression.md" if local_dir else None,
        url_template.replace("rules/{rule}.md", "suppression.md"),
        bundle,
    )
    return rule_docs, suppression_doc


def write_bundle(args):
    bundle = Path(args.bundle)
    guides_dir = Path(args.guides_dir)
    config = load_json(args.config)
    linter_config = config.get("linter", {})

    rules = list(linter_config.get("rules", []))
    double_check = list(linter_config.get("double_check", []))
    unknown = [rule for rule in double_check if rule not in rules]
    if unknown:
        warn(f"`linter.double_check` names rules missing from `linter.rules`: {unknown}")
        rules += unknown
    linter_only = [rule for rule in rules if rule not in double_check]

    statuses = parse_name_status((bundle / "name-status.z").read_text(encoding="utf-8"))
    ranges = parse_new_side_ranges((bundle / "diff-U0.patch").read_text(encoding="utf-8"))
    changed = {"rust": [], "other": []}
    for status, old_path, new_path in statuses:
        entry = {"path": new_path, "status": status, "ranges": ranges.get(new_path, [])}
        if old_path != new_path:
            entry["old_path"] = old_path
        changed["rust" if new_path.endswith(".rs") else "other"].append(entry)
    write_json(bundle / "changed-files.json", changed)

    with open(bundle / "references.tsv", "w", encoding="utf-8") as file:
        file.write("reference\tlocation\ttitle\n")
        for row in guide_index(guides_dir):
            file.write("\t".join(row) + "\n")
        for rule in rules + LINTER_META_CODES:
            file.write(f"linter:{rule}\t-\tyscope-linter `{rule}`\n")

    pr = None
    if args.pr_json:
        raw = load_json(args.pr_json)
        pr = {key: raw.get(key) for key in ("number", "title", "body", "url")}
        (bundle / "pr.md").write_text(f"# {pr['title']}\n\n{pr['body'] or ''}\n", encoding="utf-8")

    rule_sets = [
        str(path)
        for path in sorted((guides_dir / "coding-practice").glob("*.md"))
        if path.name not in EXCLUDED_RULE_SET_FILES
    ]
    untracked = [line for line in args.untracked.splitlines() if line]
    if untracked:
        (bundle / "untracked-rs.txt").write_text("\n".join(untracked) + "\n", encoding="utf-8")
    linter_binary = os.environ.get("YSCOPE_LINTER") or shutil.which("yscope-linter")
    rule_docs, suppression_doc = resolve_linter_docs(
        rules, linter_config.get("rule_doc_url", ""), bundle
    )
    meta = {
        "target": args.target,
        "kind": args.kind,
        "repo": args.repo,
        "worktree": args.worktree,
        "worktree_owned": args.owned == "true",
        "commit": args.commit,
        "base": args.base,
        "base_ref": args.base_ref,
        "dirty": args.dirty == "true",
        "untracked_rs_count": len(untracked),
        "pr": pr,
        "skill_dir": str(SKILL_DIR),
        "config": str(Path(args.config).resolve()),
        "guides": {
            "coding_practice_dir": str(guides_dir / "coding-practice"),
            "checklist": str(guides_dir / "coding-practice" / "checklist.md"),
            "testing_rule_set": str(guides_dir / "coding-practice" / TESTING_RULE_SET_FILE),
            "coding_style": str(guides_dir / "coding-style.md"),
            "pr_review": str(guides_dir / "pr-review.md"),
        },
        "rule_sets": rule_sets,
        "linter": {
            "binary": linter_binary,
            "rules": rules,
            "double_check": double_check,
            "linter_only": linter_only,
            "include_tests": bool(linter_config.get("include_tests", False)),
            "rule_docs": rule_docs,
            "suppression_doc": suppression_doc,
        },
        "files": {
            "changed_files": str(bundle / "changed-files.json"),
            "diff": str(bundle / "diff.patch"),
            "diff_u0": str(bundle / "diff-U0.patch"),
            "diff_rs_u0": str(bundle / "diff-rs-U0.patch"),
            "commits": str(bundle / "commits.txt"),
            "references": str(bundle / "references.tsv"),
            "pr": str(bundle / "pr.md") if pr else None,
            "report": str(bundle / "report.json"),
        },
    }
    write_json(bundle / "meta.json", meta)
    write_json(
        bundle / "workflow-args.json",
        {
            "bundle": str(bundle),
            "skill_dir": str(SKILL_DIR),
            "rule_sets": rule_sets,
            "double_check": double_check,
            "linter_only": linter_only,
        },
    )
    if linter_binary is None:
        warn(
            "yscope-linter isn't installed, so linter runs will fail. Install it with "
            "`cargo install --locked --git https://github.com/y-scope/yscope-linter yscope-linter`"
            ", or point YSCOPE_LINTER at a binary."
        )
    if untracked:
        warn(
            f"{len(untracked)} untracked .rs file(s) are not in the diff (listed in "
            f"{bundle / 'untracked-rs.txt'}); `git add -N <file>` the ones to review"
        )


# --- Schema validation ------------------------------------------------------------------------

JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def type_matches(value, name):
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, JSON_TYPES[name])


def validate(value, schema, path="$"):
    """Returns the errors of `value` against the JSON Schema subset the skill's schemas use."""
    if "$ref" in schema:
        return validate(value, load_json(SCHEMA_DIR / schema["$ref"]), path)
    errors = []
    types = schema.get("type")
    if types is not None:
        types = types if isinstance(types, list) else [types]
        if not any(type_matches(value, name) for name in types):
            return [f"{path}: expected {' or '.join(types)}, got {json.dumps(value)[:60]}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {json.dumps(value)} is not one of {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {json.dumps(value)} doesn't match {schema['pattern']}")
    if isinstance(value, int) and not isinstance(value, bool) and "minimum" in schema:
        if value < schema["minimum"]:
            errors.append(f"{path}: {value} is below {schema['minimum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for index, item in enumerate(value):
                errors += validate(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing `{key}`")
        for key, item in value.items():
            if key in properties:
                errors += validate(item, properties[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected `{key}`")
    return errors


def validate_command(args):
    errors = validate(load_json(args.file), load_json(SCHEMA_DIR / args.schema))
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


# --- Diff checks ------------------------------------------------------------------------------


def recount_hunks(diff_text):
    """Rewrites every hunk header's line counts from the hunk body, and ends the diff in `\\n`."""
    lines = diff_text.splitlines()
    output = []
    index = 0
    while index < len(lines):
        match = HUNK_HEADER.match(lines[index])
        if not match:
            output.append(lines[index])
            index += 1
            continue
        body = []
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.startswith("@@") or line.startswith("diff --git "):
                break
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            if line.startswith("--- ") and next_line.startswith("+++ "):
                break
            body.append(" " if line == "" else line)
            index += 1
        old_count = sum(1 for line in body if line[0] in " -")
        new_count = sum(1 for line in body if line[0] in " +")
        old_start, new_start, tail = match.group(1), match.group(3), match.group(5)
        output.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{tail}")
        output += body
    return "\n".join(output) + "\n"


def git_apply_check(worktree, patch_path):
    result = subprocess.run(
        ["git", "-C", worktree, "apply", "--check", str(patch_path)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stderr.strip()


def check_diffs(bundle, report_path):
    """Nulls each finding diff that `git apply --check` rejects; returns `(checked, nulled)`."""
    meta = load_json(bundle / "meta.json")
    report = load_json(report_path)
    check_dir = bundle / "diff-check"
    check_dir.mkdir(exist_ok=True)
    checked = nulled = 0
    for finding in report["findings"]:
        diff = finding.get("diff")
        if diff is None:
            continue
        checked += 1
        patch_path = check_dir / f"{finding['id']}.patch"
        patch_path.write_text(diff if diff.endswith("\n") else diff + "\n", encoding="utf-8")
        applies, error = git_apply_check(meta["worktree"], patch_path)
        if applies:
            finding["diff"] = patch_path.read_text(encoding="utf-8")
            continue
        recounted = recount_hunks(diff)
        patch_path.write_text(recounted, encoding="utf-8")
        if git_apply_check(meta["worktree"], patch_path)[0]:
            finding["diff"] = recounted
            continue
        reason = error.splitlines()[0] if error else "unknown error"
        warn(f"{finding['id']}: diff doesn't apply, set to null: {reason}")
        finding["diff"] = None
        nulled += 1
    write_json(report_path, report)
    return checked, nulled


def check_diffs_command(args):
    bundle = Path(args.bundle)
    report_path = Path(args.report) if args.report else bundle / "report.json"
    checked, nulled = check_diffs(bundle, report_path)
    print(f"{checked} diff(s) checked, {checked - nulled} apply, {nulled} set to null")
    return 0


# --- Report -----------------------------------------------------------------------------------


def finding_sort_key(finding):
    line_range = finding.get("line_range") or [0, 0]
    return (
        SEVERITY_ORDER.get(finding.get("severity"), len(SEVERITY_ORDER)),
        finding.get("file") or "",
        line_range[0],
    )


def known_references(bundle):
    with open(bundle / "references.tsv", encoding="utf-8") as file:
        return {line.split("\t", 1)[0] for line in file.read().splitlines()[1:]}


def finalize(args):
    bundle = Path(args.bundle)
    meta = load_json(bundle / "meta.json")
    findings = load_json(args.findings)
    if isinstance(findings, dict):
        findings = findings["findings"]
    findings = sorted(findings, key=finding_sort_key)
    for number, finding in enumerate(findings, 1):
        finding["id"] = f"F{number}"
    report = {
        "commit": meta["commit"],
        "base": meta["base"],
        "target": meta["target"],
        "findings": findings,
    }
    report_path = bundle / "report.json"
    write_json(report_path, report)

    checked, nulled = check_diffs(bundle, report_path)
    report = load_json(report_path)

    known = known_references(bundle)
    for finding in report["findings"]:
        unknown = [ref for ref in finding.get("references", []) if ref not in known]
        if unknown:
            warn(f"{finding['id']}: unknown reference(s) {unknown}")
    errors = validate(report, load_json(SCHEMA_DIR / "report.json"))
    for error in errors:
        print(f"report.json: {error}", file=sys.stderr)

    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for finding in report["findings"]:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    summary = ", ".join(f"{count} {severity}" for severity, count in counts.items())
    print(f"{len(report['findings'])} finding(s): {summary}")
    print(f"{checked} diff(s) checked, {checked - nulled} apply, {nulled} set to null")
    print(report_path)
    return 1 if errors else 0


def get_command(args):
    value = load_json(args.file)
    for key in args.key.split("."):
        value = value[key]
    if isinstance(value, (dict, list)):
        print(json.dumps(value))
    elif isinstance(value, bool):
        print("true" if value else "false")
    elif value is not None:
        print(value)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    bundle = commands.add_parser("write-bundle")
    for option in (
        "bundle",
        "guides-dir",
        "config",
        "target",
        "kind",
        "repo",
        "worktree",
        "owned",
        "commit",
        "base",
        "base-ref",
        "dirty",
    ):
        bundle.add_argument(f"--{option}", required=True)
    bundle.add_argument("--pr-json")
    bundle.add_argument("--untracked", default="")

    report = commands.add_parser("finalize")
    report.add_argument("--bundle", required=True)
    report.add_argument("--findings", required=True)

    diffs = commands.add_parser("check-diffs")
    diffs.add_argument("--bundle", required=True)
    diffs.add_argument("--report")

    schema = commands.add_parser("validate")
    schema.add_argument("--schema", required=True, help="schema file name, e.g. report.json")
    schema.add_argument("file")

    get = commands.add_parser("get")
    get.add_argument("file")
    get.add_argument("key")

    args = parser.parse_args()
    handlers = {
        "write-bundle": write_bundle,
        "finalize": finalize,
        "check-diffs": check_diffs_command,
        "validate": validate_command,
        "get": get_command,
    }
    return handlers[args.command](args) or 0


if __name__ == "__main__":
    sys.exit(main())
