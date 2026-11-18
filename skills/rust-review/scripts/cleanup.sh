#!/usr/bin/env bash
# Removes the worktree that setup.sh created for a bundle. The bundle (and its report.json) stays.
#
# Usage: cleanup.sh <bundle>

set -euo pipefail

script_dir="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
lib="${script_dir}/lib/rust_review.py"

if (($# != 1)); then
    echo "usage: cleanup.sh <bundle>" >&2
    exit 2
fi
meta="$1/meta.json"
[[ -f "${meta}" ]] || {
    echo "cleanup.sh: error: ${meta} not found" >&2
    exit 2
}

if [[ "$(python3 "${lib}" get "${meta}" worktree_owned)" != true ]]; then
    echo "cleanup.sh: the bundle reviews the working tree in place; nothing to remove" >&2
    exit 0
fi
repo="$(python3 "${lib}" get "${meta}" repo)"
worktree="$(python3 "${lib}" get "${meta}" worktree)"
if [[ -d "${worktree}" ]]; then
    git -C "${repo}" worktree remove --force "${worktree}"
fi
git -C "${repo}" worktree prune
echo "cleanup.sh: removed ${worktree}; the bundle is kept at $1" >&2
