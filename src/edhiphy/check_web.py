"""Check a web export before release (not part of ``all``; target
``check-web``).

The web database may hold no form of the full texts beyond the search
index of documentation/search_index.md (JSTOR agreement). Checks:

- schema version and ``Build_Info`` (``export`` = web, corpus name and
  version, git commit, ``git_dirty`` = no);
- ``Full_Text`` is empty; the research-only tables (``Mention_Web_ID``)
  are absent;
- every Mention_ID has the web form ``<JSTOR number>_<page>_<k>`` with
  k = 1, ..., n on each page (not a character offset);
- every mention context is at most ``2 * --context-chars`` characters
  plus the mention and the two ellipses;
- no text value of any other table is longer than ``--max-text``
  characters (no full text elsewhere).

Writes a Markdown report; exits with status 1 if a check fails.
"""

import re
import sqlite3
from collections import defaultdict

from edhiphy.common import atomic_output, log, parser, setup_logging
from edhiphy.schema import SCHEMA_VERSION, research_only_tables

WEB_MENTION_ID = re.compile(r"([^_\s]+)_(\d+)_(\d+)")
MENTION_TABLES = [
    "Mention",
    "Mention_Associated",
    "Mention_Disambiguated",
    "Mention_context",
]
# Tables of the search index and the spellfix1 vocabulary: checked by
# their own construction, not by text length.
INDEX_PREFIXES = (
    "Full_Text_fts5",
    "Full_Text_ngrams_fts5",
    "Wiki_Entry_alias_spellfix1",
)


def checks(conn: sqlite3.Connection, context_chars: int, max_text: int):
    """(name, passed, detail) per check."""
    out = []
    tables = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    out.append(("schema version", version == SCHEMA_VERSION, str(version)))
    info = dict(conn.execute("SELECT key, value FROM Build_Info"))
    for key, expected in (("export", "web"), ("git_dirty", "no")):
        out.append((f"Build_Info {key}", info.get(key) == expected, str(info.get(key))))
    for key in (
        "corpus_name",
        "corpus_version",
        "git_commit",
        "language",
        "fts_tokenize",
    ):
        out.append((f"Build_Info {key}", bool(info.get(key)), str(info.get(key))))
    n = conn.execute("SELECT count(*) FROM Full_Text").fetchone()[0]
    out.append(("Full_Text empty", n == 0, f"{n} rows"))
    present = sorted(t.name for t in research_only_tables if t.name in tables)
    out.append(
        ("research-only tables absent", not present, ", ".join(present) or "none")
    )

    bad, pages = [], defaultdict(set)
    for (mid,) in conn.execute("SELECT Mention_ID FROM Mention"):
        m = WEB_MENTION_ID.fullmatch(mid)
        if not m:
            bad.append(mid)
            continue
        pages[m.group(1), m.group(2)].add(int(m.group(3)))
    gaps = [p for p, ks in pages.items() if ks != set(range(1, len(ks) + 1))]
    out.append(("Mention_ID form", not bad, f"{len(bad)} malformed, e.g. {bad[:3]}"))
    out.append(
        (
            "Mention_ID k = 1..n per page",
            not gaps,
            f"{len(gaps)} pages differ, e.g. {gaps[:3]}",
        )
    )
    ids = {r[0] for r in conn.execute("SELECT Mention_ID FROM Mention")}
    for t in MENTION_TABLES[1:]:
        orphans = sum(
            1
            for (mid,) in conn.execute(f"SELECT Mention_ID FROM {t}")
            if mid not in ids
        )
        out.append(
            (f"{t} Mention_IDs in Mention", orphans == 0, f"{orphans} not in Mention")
        )

    # The context writes the mention in capitals, which can be longer than
    # the mention ("Größe" -> "GRÖSSE"): candidates by SQL, then the exact
    # bound in Python.
    candidates = conn.execute(
        """SELECT m.Ent_text, length(c.Mention_context)
        FROM Mention_context c JOIN Mention m USING (Mention_ID)
        WHERE length(c.Mention_context) > length(m.Ent_text) + 6 + 2 * ?""",
        (context_chars,),
    ).fetchall()
    excess = [n - len(e.upper()) - 6 - 2 * context_chars for e, n in candidates]
    excess = [x for x in excess if x > 0]
    out.append(
        (
            "context length",
            not excess,
            f"{len(excess)} longer, max excess {max(excess, default=0)}",
        )
    )

    over = []
    for t in sorted(tables):
        if t.startswith(INDEX_PREFIXES) or t.startswith("sqlite_"):
            continue
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]
        for c in cols:
            v = conn.execute(
                f'SELECT max(length("{c}")) FROM "{t}" WHERE typeof("{c}") = \'text\''
            ).fetchone()[0]
            if v and v > max_text:
                over.append(f"{t}.{c} ({v})")
    out.append(
        (
            f"no text value over {max_text} characters",
            not over,
            ", ".join(over) or "none",
        )
    )
    return out


def report(results, db) -> str:
    lines = [
        f"# Web export check: {db}",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'pass' if ok else 'FAIL'} | {detail} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--web", required=True, help="web database")
    p.add_argument("--context-chars", type=int, required=True)
    p.add_argument("--max-text", type=int, default=2000)
    p.add_argument("--out", required=True, help="Markdown report")
    args = p.parse_args(argv)
    setup_logging()
    conn = sqlite3.connect(f"file:{args.web}?mode=ro", uri=True)
    results = checks(conn, args.context_chars, args.max_text)
    conn.close()
    failed = [name for name, ok, _ in results if not ok]
    text = report(results, args.web)
    if failed:
        # The report is written either way; make treats the failed target
        # as not built (.DELETE_ON_ERROR does not apply to a renamed file,
        # hence the report goes next to it).
        with atomic_output(f"{args.out}.failed") as tmp:
            tmp.write_text(text)
        raise SystemExit(f"web export check failed: {', '.join(failed)}")
    with atomic_output(args.out) as tmp:
        tmp.write_text(text)
    log.info("web export check passed (%d checks)", len(results))


if __name__ == "__main__":
    main()
