#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.7"
# dependencies = []
# ///
"""Builds and checks the Rust coding-practice guide.

The script does two things:

- Regenerates `checklist.md` from the `## Checklist` section at the end of each rule-set file, in
  the order the rule sets appear in the README's table of contents. The part of `checklist.md`
  before the first `## Checklist: ` heading is kept as written.
- Checks that every relative markdown link and `#anchor` in the guide's files, `pr-review.md` and
  `coding-style.md` resolves, using GitHub's heading-anchor rules.

Usage:

    uv run rust/coding-practice/tools/build.py          # regenerate, then check links
    uv run rust/coding-practice/tools/build.py --check  # fail if stale or any link is broken

The script can also be run directly, as `rust/coding-practice/tools/build.py [--check]`.
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path

GUIDE_DIR = Path(__file__).resolve().parent.parent
RUST_DIR = GUIDE_DIR.parent
INDEX = GUIDE_DIR / "README.md"
CHECKLIST = GUIDE_DIR / "checklist.md"
COMPANION_FILES = [RUST_DIR / "pr-review.md", RUST_DIR / "coding-style.md"]

WRAP_WIDTH = 100
CHECKLIST_HEADING = "## Checklist"
CHECKLIST_SECTION_PREFIX = "## Checklist: "

TOC_ENTRY = re.compile(r"^\d+\. \[([^\]]+)\]\(([^)#]+\.md)\)")
RULE_HEADING = re.compile(r"^## ([A-Z]+-\d+): ")
CHECKLIST_ITEM = re.compile(r"^- \*\*([A-Z]+-\d+)\*\*:")
ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INLINE_LINK = re.compile(
    r"!?\[(?:[^\[\]]|\[[^\[\]]*\])*\]\(\s*<?([^)\s>]*)>?(?:\s+\"[^\"]*\")?\s*\)"
)
REFERENCE_DEFINITION = re.compile(r"^ {0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+\"[^\"]*\")?\s*$")
HTML_ANCHOR = re.compile(r"<a\s+(?:name|id)=\"([^\"]+)\"")
EXTERNAL_TARGET = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
LIST_MARKER = re.compile(r"^(?:[-+*]|\d+[.)])$")


class GuideError(Exception):
    pass


def iter_unfenced(lines):
    """Yields `(line_number, line)` for each line outside fenced code blocks."""
    fence = None
    for number, line in enumerate(lines, 1):
        match = FENCE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
                continue
            yield number, line
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
            if line.strip() == match.group(1):
                fence = None


def split_code_spans(text):
    """Splits text into `(is_code, segment)` pairs on inline code spans."""
    parts = []
    pos = 0
    for match in re.finditer(r"(`+)(.+?)\1(?!`)", text):
        parts.append((False, text[pos : match.start()]))
        parts.append((True, match.group(2)))
        pos = match.end()
    parts.append((False, text[pos:]))
    return parts


def heading_text(raw):
    """Approximates the text GitHub renders for a heading's inline markdown."""
    rendered = []
    for is_code, segment in split_code_spans(raw):
        if is_code:
            rendered.append(segment)
            continue
        segment = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", segment)
        segment = re.sub(r"<[^>]+>", "", segment)
        rendered.append(segment)
    return "".join(rendered)


def github_slug(text):
    """Returns GitHub's anchor slug for a heading's rendered text, before de-duplication."""
    kept = []
    for char in text.lower():
        if char in " -_" or unicodedata.category(char)[0] in "LNM":
            kept.append(char)
    return "".join(kept).replace(" ", "-")


def anchors_of(lines):
    """Returns every anchor GitHub generates for the given markdown lines."""
    anchors = set()
    occurrences = {}
    for _, line in iter_unfenced(lines):
        anchors.update(HTML_ANCHOR.findall(line))
        match = ATX_HEADING.match(line)
        if not match:
            continue
        slug = github_slug(heading_text(match.group(2)))
        count = occurrences.get(slug, 0)
        occurrences[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def read_lines(path):
    return path.read_text(encoding="utf-8").split("\n")


def rule_set_files():
    """Returns `(title, path)` for each rule set listed in the README's table of contents."""
    entries = []
    for _, line in iter_unfenced(read_lines(INDEX)):
        match = TOC_ENTRY.match(line)
        if not match or (GUIDE_DIR / match.group(2)) == CHECKLIST:
            continue
        path = GUIDE_DIR / match.group(2)
        if not path.exists():
            raise GuideError(f"{INDEX}: the table of contents lists missing file `{path.name}`")
        entries.append((match.group(1), path))
    if not entries:
        raise GuideError(f"{INDEX}: no rule-set entries found in the table of contents")
    return entries


def parse_rule_set(title, path):
    """Returns the rule anchors and the checklist body of one rule-set file."""
    lines = read_lines(path)
    if lines[0] != f"# {title}":
        raise GuideError(f"{path}: expected the first line to be `# {title}`")
    rule_anchors = {}
    occurrences = {}
    checklist_start = None
    for number, line in iter_unfenced(lines):
        match = ATX_HEADING.match(line)
        if not match:
            continue
        slug = github_slug(heading_text(match.group(2)))
        count = occurrences.get(slug, 0)
        occurrences[slug] = count + 1
        rule = RULE_HEADING.match(line)
        if rule:
            rule_anchors[rule.group(1)] = slug if count == 0 else f"{slug}-{count}"
        if line == CHECKLIST_HEADING:
            if checklist_start is not None:
                raise GuideError(f"{path}:{number}: duplicate `{CHECKLIST_HEADING}` heading")
            checklist_start = number
        elif checklist_start is not None and match.group(1) in ("#", "##"):
            raise GuideError(f"{path}:{number}: `{CHECKLIST_HEADING}` must be the last section")
    if checklist_start is None:
        raise GuideError(f"{path}: missing the `{CHECKLIST_HEADING}` section")
    body = lines[checklist_start:]
    while body and body[0] == "":
        body.pop(0)
    while body and body[-1] == "":
        body.pop()
    return rule_anchors, body


def wrap_tokens(text):
    """Splits text on spaces, keeping each inline code span as one token."""
    tokens = []
    pending = None
    for word in text.split(" "):
        if pending is not None:
            pending += " " + word
            if word.count("`") % 2 == 1:
                tokens.append(pending)
                pending = None
        elif word.count("`") % 2 == 1:
            pending = word
        else:
            tokens.append(word)
    if pending is not None:
        tokens.append(pending)
    return [token for token in tokens if token]


def fill_list_item(text):
    """Greedily wraps a `- ` list item to `WRAP_WIDTH` columns."""
    lines = [[]]
    for token in wrap_tokens(text):
        current = lines[-1]
        if current and len("- " + " ".join(current + [token])) > WRAP_WIDTH:
            carried = [current.pop()] if LIST_MARKER.match(token) and len(current) > 1 else []
            lines.append(carried + [token])
        else:
            current.append(token)
    return ["- " + " ".join(lines[0])] + ["  " + " ".join(line) for line in lines[1:]]


def link_checklist_body(body, rule_locations, path):
    """Links each item's leading rule ID to the rule's heading and re-wraps the item.

    The links are reference-style, so a link adds only two columns to the item's first line. The
    section ends with one link reference definition per cited rule, in order of first citation.
    """
    items = []
    in_item = False
    for line in body:
        if line.startswith("  ") and in_item:
            items[-1].append(line)
        else:
            items.append([line])
            in_item = line.startswith("- ")
    output = []
    definitions = {}
    for item in items:
        match = CHECKLIST_ITEM.match(item[0])
        if not match:
            output.extend(item)
            continue
        rule_id = match.group(1)
        if rule_id not in rule_locations:
            raise GuideError(f"{path}: checklist cites unknown rule {rule_id}")
        definitions.setdefault(rule_id, f"[{rule_id}]: {rule_locations[rule_id]}")
        text = " ".join([item[0][2:]] + [line[2:] for line in item[1:]])
        text = text.replace(f"**{rule_id}**", f"**[{rule_id}]**", 1)
        output.extend(fill_list_item(text))
    if definitions:
        output += [""] + list(definitions.values())
    return output


def render_checklist():
    """Returns the expected content of `checklist.md`."""
    rule_sets = []
    rule_locations = {}
    for title, path in rule_set_files():
        rule_anchors, body = parse_rule_set(title, path)
        for rule_id, anchor in rule_anchors.items():
            if rule_id in rule_locations:
                raise GuideError(f"{path}: rule {rule_id} is defined more than once")
            rule_locations[rule_id] = f"{path.name}#{anchor}"
        rule_sets.append((title, path, body))

    if not CHECKLIST.exists():
        raise GuideError(f"{CHECKLIST}: missing; it must hold at least the `# ` title and intro")
    head = []
    for line in read_lines(CHECKLIST):
        if line.startswith(CHECKLIST_SECTION_PREFIX):
            break
        head.append(line)
    while head and head[-1] == "":
        head.pop()

    output = head
    for title, path, body in rule_sets:
        output += ["", f"{CHECKLIST_SECTION_PREFIX}{title}", ""]
        output += link_checklist_body(body, rule_locations, path)
    return "\n".join(output) + "\n"


def link_targets(lines):
    """Yields `(line_number, target)` for each link outside code."""
    for number, line in iter_unfenced(lines):
        prose = "".join(
            " " * len(segment) if is_code else segment
            for is_code, segment in split_code_spans(line)
        )
        match = REFERENCE_DEFINITION.match(prose)
        if match:
            yield number, match.group(1)
            continue
        for match in INLINE_LINK.finditer(prose):
            yield number, match.group(1)


def check_links():
    """Returns a description of every broken relative link."""
    files = sorted(GUIDE_DIR.rglob("*.md")) + [path for path in COMPANION_FILES if path.exists()]
    anchor_cache = {}

    def anchors(path):
        if path not in anchor_cache:
            anchor_cache[path] = anchors_of(read_lines(path))
        return anchor_cache[path]

    broken = []
    for path in files:
        for number, target in link_targets(read_lines(path)):
            if not target or EXTERNAL_TARGET.match(target):
                continue
            file_part, _, anchor = target.partition("#")
            destination = (path.parent / file_part).resolve() if file_part else path
            location = f"{path.relative_to(RUST_DIR.parent)}:{number}"
            if not destination.exists():
                broken.append(f"{location}: `{target}`: no such file")
            elif anchor and destination.suffix == ".md" and anchor not in anchors(destination):
                broken.append(f"{location}: `{target}`: no such anchor")
    return broken


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="don't write `checklist.md`; exit non-zero if it is stale or any link is broken",
    )
    args = parser.parse_args()

    try:
        expected = render_checklist()
    except GuideError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    failed = False
    if CHECKLIST.read_text(encoding="utf-8") != expected:
        if args.check:
            print(f"error: {CHECKLIST.name} is stale; run {Path(__file__).name}", file=sys.stderr)
            failed = True
        else:
            CHECKLIST.write_text(expected, encoding="utf-8")
            print(f"Regenerated {CHECKLIST.name}.")

    broken = check_links()
    for entry in broken:
        print(f"error: broken link: {entry}", file=sys.stderr)
    return 1 if failed or broken else 0


if __name__ == "__main__":
    sys.exit(main())
