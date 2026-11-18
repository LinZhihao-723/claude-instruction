#!/usr/bin/env bash
# Checks every suggested diff in a report with `git apply --check` in the bundle's worktree.
#
# Usage: check-diffs.sh <bundle> [<report>]
#
# A diff whose hunk line counts are off is kept with recounted hunk headers when that makes it
# apply. Any other diff that doesn't apply is set to null. The report (default:
# `<bundle>/report.json`) is rewritten in place.

set -euo pipefail

script_dir="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

if (($# < 1 || $# > 2)); then
    echo "usage: check-diffs.sh <bundle> [<report>]" >&2
    exit 2
fi
python3 "${script_dir}/lib/rust_review.py" check-diffs --bundle "$1" ${2:+--report "$2"}
