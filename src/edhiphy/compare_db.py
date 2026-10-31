"""Compare two edhiphy databases table by table: columns, row counts and
row contents (as multisets, so row order does not matter; values compared
with their SQLite storage type). Writes a Markdown report.

Used to check that a build from frozen v1 inputs reproduces the v1
database. The full comparison report against v1 (mention recovery,
disambiguation shares) is a separate stage.
"""

import collections
import hashlib
import sqlite3

from edhiphy.common import atomic_output, log, parser, setup_logging

N_EXAMPLES = 3


def tables(conn) -> list:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' AND sql NOT LIKE 'CREATE VIRTUAL%'"
    )
    names = [r[0] for r in rows]
    # Shadow tables of virtual tables (FTS5, spellfix1) hold index data.
    virtual = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE sql LIKE 'CREATE VIRTUAL%'"
        )
    ]
    return sorted(n for n in names if not any(n.startswith(v + "_") for v in virtual))


def columns(conn, table) -> list:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def row_hashes(conn, table, cols) -> collections.Counter:
    select = ", ".join(f'"{c}"' for c in cols)
    counter = collections.Counter()
    for row in conn.execute(f'SELECT {select} FROM "{table}"'):
        counter[hashlib.blake2b(repr(row).encode(), digest_size=16).digest()] += 1
    return counter


def examples(conn, table, cols, wanted) -> list:
    select = ", ".join(f'"{c}"' for c in cols)
    found = []
    for row in conn.execute(f'SELECT {select} FROM "{table}"'):
        if hashlib.blake2b(repr(row).encode(), digest_size=16).digest() in wanted:
            found.append(row)
            if len(found) == N_EXAMPLES:
                break
    return found


def compare_table(ref, new, table) -> dict:
    ref_cols, new_cols = columns(ref, table), columns(new, table)
    common = [c for c in ref_cols if c in new_cols]
    a, b = row_hashes(ref, table, common), row_hashes(new, table, common)
    only_ref, only_new = a - b, b - a
    return {
        "table": table,
        "ref_rows": sum(a.values()),
        "new_rows": sum(b.values()),
        "only_ref": sum(only_ref.values()),
        "only_new": sum(only_new.values()),
        "missing_columns": [c for c in ref_cols if c not in new_cols],
        "extra_columns": [c for c in new_cols if c not in ref_cols],
        "examples_ref": examples(ref, table, common, set(only_ref)),
        "examples_new": examples(new, table, common, set(only_new)),
    }


def short(row, width=160) -> str:
    text = repr(row)
    return text if len(text) <= width else text[: width - 3] + "..."


def report(ref_path, new_path, results, only_ref_tables, only_new_tables) -> str:
    lines = [
        "# Database comparison",
        "",
        f"- reference: `{ref_path}`",
        f"- new: `{new_path}`",
        f"- tables only in reference: {', '.join(only_ref_tables) or 'none'}",
        f"- tables only in new: {', '.join(only_new_tables) or 'none'}",
        "",
        "| table | ref rows | new rows | only ref | only new | column differences |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in results:
        cols = []
        if r["missing_columns"]:
            cols.append("missing: " + ", ".join(r["missing_columns"]))
        if r["extra_columns"]:
            cols.append("extra: " + ", ".join(r["extra_columns"]))
        lines.append(
            f"| {r['table']} | {r['ref_rows']} | {r['new_rows']} | {r['only_ref']} "
            f"| {r['only_new']} | {'; '.join(cols)} |"
        )
    for r in results:
        if r["examples_ref"] or r["examples_new"]:
            lines += ["", f"## {r['table']}", ""]
            lines += [f"- only ref: `{short(row)}`" for row in r["examples_ref"]]
            lines += [f"- only new: `{short(row)}`" for row in r["examples_new"]]
    return "\n".join(lines) + "\n"


def compare(ref_path, new_path, ignore=()) -> tuple:
    ref = sqlite3.connect(f"file:{ref_path}?mode=ro", uri=True)
    new = sqlite3.connect(f"file:{new_path}?mode=ro", uri=True)
    ref_tables = [t for t in tables(ref) if t not in ignore]
    new_tables = [t for t in tables(new) if t not in ignore]
    results = []
    for table in ref_tables:
        if table in new_tables:
            log.info("comparing %s", table)
            results.append(compare_table(ref, new, table))
    only_ref = [t for t in ref_tables if t not in new_tables]
    only_new = [t for t in new_tables if t not in ref_tables]
    return results, only_ref, only_new


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--ref", required=True)
    p.add_argument("--new", required=True)
    p.add_argument("--ignore", action="append", default=[], help="table to skip")
    p.add_argument("--out", required=True, help="Markdown report")
    args = p.parse_args(argv)
    setup_logging()
    results, only_ref, only_new = compare(args.ref, args.new, args.ignore)
    with atomic_output(args.out) as tmp:
        tmp.write_text(report(args.ref, args.new, results, only_ref, only_new))
    differing = [r["table"] for r in results if r["only_ref"] or r["only_new"]]
    log.info("tables with differences: %s", differing or "none")


if __name__ == "__main__":
    main()
