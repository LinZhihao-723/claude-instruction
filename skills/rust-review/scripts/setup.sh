#!/usr/bin/env bash
# Prepares a review bundle for a Rust change and prints the bundle's path.
#
# Usage: setup.sh <target> [--repo <dir>] [--base <ref>]
#
#   <target>  A PR number (`123`, `#123`) or PR URL, a branch (or any commit-ish), or `local` for
#             the working tree against its merge base with the base branch.
#   --repo    The repository to review. Default: the repository containing the current directory.
#   --base    The base branch for branch and `local` targets. Default: `base_branch` in config.json.
#             PR targets always use the PR's own base branch.
#
# PR and branch targets are checked out in a detached worktree under a new temp dir; `local`
# reviews the working tree in place. Run cleanup.sh on the bundle when the review is done.

set -euo pipefail

script_dir="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
skill_dir="$(realpath "${script_dir}/..")"
guides_dir="$(realpath "${skill_dir}/../../rust")"
config="${skill_dir}/config.json"
lib="${script_dir}/lib/rust_review.py"

die() {
    echo "setup.sh: error: $*" >&2
    exit 2
}

usage() {
    sed -n '2,13s/^# \{0,1\}//p' "${BASH_SOURCE[0]}" >&2
    exit 2
}

target=""
repo_arg="."
base_arg=""
while (($# > 0)); do
    case "$1" in
        --repo)
            repo_arg="${2:?--repo needs a value}"
            shift 2
            ;;
        --base)
            base_arg="${2:?--base needs a value}"
            shift 2
            ;;
        -h | --help) usage ;;
        -*) die "unknown option: $1" ;;
        *)
            [[ -z "${target}" ]] || die "more than one target given"
            target="$1"
            shift
            ;;
    esac
done
[[ -n "${target}" ]] || usage

command -v git >/dev/null || die "git is required"
command -v python3 >/dev/null || die "python3 is required"
[[ -d "${guides_dir}/coding-practice" ]] || die "guidelines not found at ${guides_dir}"

repo="$(git -C "${repo_arg}" rev-parse --show-toplevel 2>/dev/null)" \
    || die "${repo_arg} is not inside a git repository"
base_ref="${base_arg:-$(python3 "${lib}" get "${config}" base_branch)}"

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/rust-review.XXXXXX")"
bundle="${tmp_dir}/bundle"
worktree="${tmp_dir}/worktree"
mkdir "${bundle}"
setup_done=false
on_exit() {
    if [[ "${setup_done}" != true ]]; then
        if [[ -d "${worktree}" ]]; then
            git -C "${repo}" worktree remove --force "${worktree}" >/dev/null 2>&1 || true
        fi
        rm -rf "${tmp_dir}"
    fi
}
trap on_exit EXIT

merge_base() {
    git -C "${repo}" merge-base "$1" "$2" 2>/dev/null \
        || die "no merge base between $1 and $2 (pass --base <ref> to pick another base)"
}

pr_json=""
dirty=false
untracked=""
if [[ "${target}" == local ]]; then
    kind=local
    owned=false
    worktree="${repo}"
    commit="$(git -C "${repo}" rev-parse HEAD)"
    base="$(merge_base HEAD "${base_ref}")"
    diff_revs=("${base}")
    if [[ -n "$(git -C "${repo}" status --porcelain --untracked-files=no)" ]]; then
        dirty=true
    fi
    untracked="$(git -C "${repo}" ls-files --others --exclude-standard -- '*.rs' \
        | grep -v '^target/' || true)"
elif [[ "${target}" =~ ^#?[0-9]+$ || "${target}" =~ ^https://[^/]+/[^/]+/[^/]+/pull/[0-9]+ ]]; then
    kind=pr
    owned=true
    command -v gh >/dev/null || die "gh is required for PR targets (https://cli.github.com)"
    pr_json="${bundle}/pr.json"
    (cd "${repo}" && gh pr view "${target#\#}" \
        --json number,title,body,url,headRefOid,baseRefName,baseRefOid) >"${pr_json}" \
        || die "gh pr view ${target} failed"
    pr_number="$(python3 "${lib}" get "${pr_json}" number)"
    pr_url="$(python3 "${lib}" get "${pr_json}" url)"
    commit="$(python3 "${lib}" get "${pr_json}" headRefOid)"
    base_ref="$(python3 "${lib}" get "${pr_json}" baseRefName)"
    base_tip="$(python3 "${lib}" get "${pr_json}" baseRefOid)"
    git -C "${repo}" fetch --quiet --no-tags "${pr_url%/pull/*}.git" \
        "refs/pull/${pr_number}/head" "refs/heads/${base_ref}" \
        || die "couldn't fetch PR #${pr_number} from ${pr_url%/pull/*}"
    git -C "${repo}" cat-file -e "${commit}^{commit}" 2>/dev/null \
        || die "PR head ${commit} is missing after the fetch"
    base="$(merge_base "${commit}" "${base_tip}")"
    git -C "${repo}" worktree add --quiet --detach "${worktree}" "${commit}" >&2
    diff_revs=("${base}" "${commit}")
else
    kind=branch
    owned=true
    commit="$(git -C "${repo}" rev-parse --verify --quiet "${target}^{commit}")" \
        || die "${target} is not a PR, a branch or a commit in ${repo}"
    base="$(merge_base "${commit}" "${base_ref}")"
    git -C "${repo}" worktree add --quiet --detach "${worktree}" "${commit}" >&2
    diff_revs=("${base}" "${commit}")
fi

git_diff=(git -C "${worktree}" -c core.quotePath=false diff --no-ext-diff --no-color
    --src-prefix=a/ --dst-prefix=b/ -M)
"${git_diff[@]}" "${diff_revs[@]}" >"${bundle}/diff.patch"
"${git_diff[@]}" -U0 "${diff_revs[@]}" >"${bundle}/diff-U0.patch"
"${git_diff[@]}" -U0 "${diff_revs[@]}" -- '*.rs' >"${bundle}/diff-rs-U0.patch"
"${git_diff[@]}" --name-status -z "${diff_revs[@]}" >"${bundle}/name-status.z"
git -C "${repo}" log --format='%H %s' "${base}..${commit}" >"${bundle}/commits.txt"

python3 "${lib}" write-bundle \
    --bundle "${bundle}" \
    --guides-dir "${guides_dir}" \
    --config "${config}" \
    --target "${target}" \
    --kind "${kind}" \
    --repo "${repo}" \
    --worktree "${worktree}" \
    --owned "${owned}" \
    --commit "${commit}" \
    --base "${base}" \
    --base-ref "${base_ref}" \
    --dirty "${dirty}" \
    --untracked "${untracked}" \
    ${pr_json:+--pr-json "${pr_json}"}

if [[ ! -s "${bundle}/diff.patch" ]]; then
    echo "setup.sh: warning: the change is empty (${base}..${commit})" >&2
fi
setup_done=true
echo "${bundle}"
