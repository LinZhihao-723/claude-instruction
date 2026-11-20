#!/usr/bin/env bash
# Runs one yscope-linter rule on the changed lines of a bundle's `.rs` files.
#
# Usage: run-linter.sh <rule> <bundle>
#
# Prints one diagnostic per line (`<path>:<line>:<column>: <code> <name>: <message>`, paths relative
# to the worktree root) and saves the output to `<bundle>/linter/<rule>.txt`. Exits 0 when clean, 1
# when there are diagnostics and 2 on an error, including a missing linter. The linter binary is
# YSCOPE_LINTER if set, else the bundle's `linter.binary` (recorded by setup.sh), else the
# `yscope-linter` on PATH.

set -euo pipefail

script_dir="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
lib="${script_dir}/lib/rust_review.py"
install_hint="cargo install --locked --git https://github.com/y-scope/yscope-linter yscope-linter"

die() {
    echo "run-linter.sh: error: $*" >&2
    exit 2
}

(($# == 2)) || die "usage: run-linter.sh <rule> <bundle>"
rule="$1"
bundle="$(realpath "$2")"
meta="${bundle}/meta.json"
[[ -f "${meta}" ]] || die "${meta} not found"

linter="${YSCOPE_LINTER:-}"
linter_source=YSCOPE_LINTER
if [[ -z "${linter}" ]]; then
    linter="$(python3 "${lib}" get "${meta}" linter.binary)"
    linter_source="${meta} linter.binary"
fi
if [[ -z "${linter}" ]]; then
    linter="$(command -v yscope-linter || true)"
    linter_source=PATH
fi
[[ -n "${linter}" ]] \
    || die "yscope-linter is not installed; install it with \`${install_hint}\`, or set" \
        "YSCOPE_LINTER to a binary"
[[ -x "${linter}" ]] || die "${linter_source}=${linter} is not an executable"

worktree="$(python3 "${lib}" get "${meta}" worktree)"
diff="${bundle}/diff-rs-U0.patch"
out_dir="${bundle}/linter"
mkdir -p "${out_dir}"
out="${out_dir}/${rule}.txt"

if [[ ! -s "${diff}" ]]; then
    : >"${out}"
    exit 0
fi

args=(--rule "${rule}" --diff "${diff}" --format text)
if [[ "$(python3 "${lib}" get "${meta}" linter.include_tests)" == true ]]; then
    args+=(--include-tests)
fi

status=0
(cd "${worktree}" && "${linter}" "${args[@]}") >"${out}" || status=$?
cat "${out}"
if ((status > 1)); then
    die "yscope-linter exited with ${status}"
fi
exit "${status}"
