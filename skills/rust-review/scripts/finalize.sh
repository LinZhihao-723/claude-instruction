#!/usr/bin/env bash
# Writes `<bundle>/report.json` from the verified findings, then checks its diffs and its schema.
#
# Usage: finalize.sh <bundle> <findings>
#
# <findings> is a JSON file holding a findings array, or an object with a `findings` array. The
# findings are sorted by severity, file and line and renumbered F1, F2, ... Diffs that don't apply
# are set to null (see check-diffs.sh). Prints a summary and the report's path. Exits 1 if the
# report doesn't match schemas/report.json.

set -euo pipefail

script_dir="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

if (($# != 2)); then
    echo "usage: finalize.sh <bundle> <findings>" >&2
    exit 2
fi
python3 "${script_dir}/lib/rust_review.py" finalize --bundle "$1" --findings "$2"
