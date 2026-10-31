#!/usr/bin/env bash
# Usage: publish/publish.sh TAG [PUBLIC_REMOTE_URL]
#
# Publishes the allowlisted paths of the tagged commit as one release
# commit in the public repository. The allowlist (publish/paths.txt) and
# the check (publish/check.sh) are taken from the tagged commit itself.
# Nothing is pushed without confirmation.
#
# Environment: PUBLIC_REMOTE (used if no URL is given),
#              PUBLIC_BRANCH (default: main).
set -euo pipefail

tag=${1:?usage: publish.sh TAG [PUBLIC_REMOTE_URL]}
remote=${2:-${PUBLIC_REMOTE:?pass the public repository URL or set PUBLIC_REMOTE}}
branch=${PUBLIC_BRANCH:-main}

repo=$(git rev-parse --show-toplevel)
git -C "$repo" rev-parse -q --verify "refs/tags/$tag" >/dev/null ||
	{ echo "publish.sh: unknown tag $tag" >&2; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Allowlist entries that exist in the tagged commit
paths=()
while IFS= read -r p; do
	case $p in '' | '#'*) continue ;; esac
	if [ -n "$(git -C "$repo" ls-tree -r --name-only "$tag" -- "$p")" ]; then
		paths+=("$p")
	fi
done < <(git -C "$repo" show "$tag:publish/paths.txt")
[ "${#paths[@]}" -gt 0 ] || { echo "publish.sh: nothing to publish" >&2; exit 1; }

git -C "$repo" show "$tag:publish/check.sh" >"$work/check.sh"

git clone -q "$remote" "$work/public"
pub="$work/public"
git -C "$pub" checkout -q -B "$branch"
git -C "$pub" rm -rq --ignore-unmatch -- .
git -C "$repo" archive "$tag" -- "${paths[@]}" | tar -x -C "$pub"
bash "$work/check.sh" "$pub"
git -C "$pub" add -A

if git -C "$pub" diff --cached --quiet; then
	echo "publish.sh: no changes against the public repository" >&2
	exit 1
fi
git -C "$pub" diff --cached --stat
echo
read -r -p "Review the changes above. Type 'publish' to commit, tag $tag and push: " answer
[ "$answer" = publish ] || { echo "publish.sh: aborted" >&2; exit 1; }

# Changelog since the previous public release, if that tag exists here
prev=$(git -C "$pub" describe --tags --abbrev=0 2>/dev/null || true)
{
	echo "Release $tag"
	echo
	if [ -n "$prev" ] && git -C "$repo" rev-parse -q --verify "refs/tags/$prev" >/dev/null; then
		git -C "$repo" log --no-merges --format='- %s' "$prev..$tag"
	fi
} >"$work/message"

git -C "$pub" commit -q -e -F "$work/message"
git -C "$pub" tag -a "$tag" -m "Release $tag"
git -C "$pub" push -q origin "HEAD:refs/heads/$branch" "refs/tags/$tag"
echo "publish.sh: published $tag to $remote ($branch)"
