#!/usr/bin/env bash
# Usage: publish/check.sh DIR
#
# Exits with status 1 if DIR contains files that must never be published:
# data directories, data and database file types, private documents,
# files larger than MAX_BYTES, and tables or JSON lines that carry full
# texts or mention contexts. The .git directory is skipped.
set -euo pipefail

dir=${1:?usage: check.sh DIR}
max_bytes=${MAX_BYTES:-1048576}
fail=0

report() {
	printf 'FORBIDDEN %s: %s\n' "$1" "$2" >&2
	fail=1
}

while IFS= read -r -d '' path; do
	rel=${path#"$dir"/}

	case $rel in
	data/raw/* | data/tables/* | data/intermediate/* | data/external/* | \
		data/releases/* | data/scraped/* | data/feedback/* | data/processed/* | \
		data/interim/*)
		report "$rel" "data directory" ;;
	documentation/ERC-* | documentation/Software_Management_Plan*)
		report "$rel" "private document" ;;
	esac

	case $rel in
	*.jsonl | *.gz | *.xz | *.zip | *.sqlite | *.sqlite3 | *.db | *.db3 | \
		*.parquet | *.pickle | *.pkl | *.docx)
		report "$rel" "data or document file type" ;;
	esac

	size=$(wc -c <"$path" | tr -d ' ')
	if [ "$size" -gt "$max_bytes" ]; then
		report "$rel" "larger than $max_bytes bytes ($size)"
	fi

	case $rel in
	*.csv | *.tsv)
		if head -n 1 "$path" | grep -qiE 'full_?text|mention_context'; then
			report "$rel" "table with full-text or context column"
		fi ;;
	*.json)
		if grep -q '"fullText"' "$path"; then
			report "$rel" "JSON with fullText field"
		fi ;;
	esac
done < <(find "$dir" -path "$dir/.git" -prune -o -type f -print0)

if [ "$fail" -ne 0 ]; then
	echo "check.sh: forbidden files found in $dir" >&2
	exit 1
fi
echo "check.sh: no forbidden files in $dir"
