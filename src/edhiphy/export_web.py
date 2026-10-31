"""Stage 11 (export_web): the database for the website, without full
texts.

A copy of the research database in which ``Full_Text`` is emptied and the
texts are indexed for search without word positions (see
``edhiphy.search_index`` and documentation/search_index.md): the word
table ``Full_Text_fts5`` (exact word counts per article, ranked by
``bm25``) and the n-gram table ``Full_Text_ngrams_fts5`` (word pairs and
triples within sentence segments that occur in at least
``--ngram-min-df`` articles), both contentless, rowid = numeric part of the JSTOR stable
URL, mapped back to ``Article_ID`` by ``Full_Text_fts5_ArticleID`` as in
v1. ``VACUUM`` removes the pages that held the texts.
Every ``Mention_ID`` column is rewritten with ``Mention_Web_ID``
(``<JSTOR number>_<page>_<k>``, k = order on the page), so the export
carries no character offsets; the mapping table is dropped.
``Wiki_Entry_alias_spellfix1`` is built with the SQLite spellfix1
extension when ``--spellfix`` names it; otherwise it is an empty
placeholder table, recorded in ``Build_Info``.
"""

import hashlib
import os
import re
import sqlite3
import tempfile

import numpy as np

from edhiphy import build_info, search_index
from edhiphy.search_index import NGRAM_TABLE, NGRAM_TOKENIZE, ROWID_TABLE, WORD_TABLE
from edhiphy.common import atomic_output, log, parser, setup_logging
from edhiphy.schema import SCHEMA_VERSION, Mention_Web_ID, research_only_tables

ARTICLE_URL = re.compile(r"^http://www\.jstor\.org/stable/(\d+)$")

# Column layout of the placeholder table; the real spellfix1 table has the
# same columns.
SPELLFIX_PLACEHOLDER = """
CREATE TABLE Wiki_Entry_alias_spellfix1 (
    rowid     TEXT PRIMARY KEY,
    word      TEXT NOT NULL,
    rank      INTEGER,
    distance  INTEGER,
    langid    INTEGER,
    score     INTEGER,
    matchlen  INTEGER,
    phonehash TEXT,
    top       INTEGER,
    scope     INTEGER,
    srchcnt   INTEGER,
    soundslike TEXT,
    command    TEXT
)
"""


def fts_rowid(article_id: str) -> int:
    m = ARTICLE_URL.match(article_id)
    if not m:
        raise SystemExit(f"cannot derive a full-text rowid from {article_id!r}")
    return int(m.group(1))


def ngram_table(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE {name} USING fts5(
            Ngrams,
            tokenize = {search_index.sql_string(NGRAM_TOKENIZE)},
            content = '',
            detail = none,
            columnsize = 0
        )
        """
    )


def ngram_hashes(grams) -> np.ndarray:
    """64-bit BLAKE2b hashes of n-gram tokens."""
    digest = b"".join(
        hashlib.blake2b(g.encode(), digest_size=8).digest() for g in grams
    )
    return np.frombuffer(digest, dtype="<u8")


def frequent_ngrams(texts, terms, min_df: int, scratch_dir) -> np.ndarray | None:
    """Sorted hashes of the n-grams that occur in at least ``min_df``
    articles, counted with a scratch n-gram index on disk (None: no
    restriction). Hashes instead of the tokens keep the memory small
    (8 bytes per n-gram type); a df-1 n-gram is kept by mistake only if its
    hash equals that of a frequent one (expected number for en_v1, 31 M
    types: about 1e-5)."""
    if min_df <= 1:
        return None
    with tempfile.TemporaryDirectory(dir=scratch_dir) as d:
        scratch = sqlite3.connect(os.path.join(d, "ngrams.sqlite"))
        scratch.execute("PRAGMA journal_mode = OFF")
        ngram_table(scratch, "g")
        for rowid, _, text in texts():
            _, grams = search_index.article_tokens(text, terms)
            scratch.execute(
                "INSERT INTO g (rowid, Ngrams) VALUES (?, ?)", (rowid, " ".join(grams))
            )
        scratch.commit()
        scratch.execute("CREATE VIRTUAL TABLE temp.v USING fts5vocab(main, g, row)")
        n_types, n_kept, buf = 0, 0, bytearray()
        for term, df in scratch.execute("SELECT term, doc FROM temp.v"):
            n_types += 1
            if df >= min_df:
                n_kept += 1
                buf += hashlib.blake2b(term.encode(), digest_size=8).digest()
        scratch.close()
    log.info("n-grams: %d distinct, %d in >= %d articles", n_types, n_kept, min_df)
    return np.unique(np.frombuffer(bytes(buf), dtype="<u8"))


def index_full_texts(
    conn: sqlite3.Connection, tokenize: str, min_df: int, scratch_dir
) -> dict:
    """Build the word table and the n-gram table from ``Full_Text``."""
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE {WORD_TABLE} USING fts5(
            FullText,
            tokenize = {search_index.sql_string(tokenize)},
            content = ''
        )
        """
    )
    ngram_table(conn, NGRAM_TABLE)

    def texts():
        rows = conn.execute(
            "SELECT Article_ID, FullText FROM Full_Text ORDER BY Article_ID"
        )
        for article_id, text in rows:
            yield fts_rowid(article_id), article_id, text

    terms = search_index.Terms(tokenize)
    kept = frequent_ngrams(texts, terms, min_df, scratch_dir)
    n, n_postings = 0, 0
    insert = conn.cursor()
    for rowid, article_id, text in texts():
        words, grams = search_index.article_tokens(text, terms)
        grams = sorted(grams)
        if kept is not None and not len(kept):
            grams = []
        elif kept is not None and grams:
            h = ngram_hashes(grams)
            i = np.minimum(np.searchsorted(kept, h), len(kept) - 1)
            grams = [g for g, keep in zip(grams, kept[i] == h) if keep]
        n_postings += len(grams)
        insert.execute(
            f"INSERT INTO {WORD_TABLE} (rowid, FullText) VALUES (?, ?)", (rowid, words)
        )
        insert.execute(
            f"INSERT INTO {NGRAM_TABLE} (rowid, Ngrams) VALUES (?, ?)",
            (rowid, " ".join(grams)),
        )
        insert.execute(
            f"INSERT INTO {ROWID_TABLE} (rowid, Article_ID) VALUES (?, ?)",
            (rowid, article_id),
        )
        n += 1
    for table in (WORD_TABLE, NGRAM_TABLE):
        conn.execute(f"INSERT INTO {table} ({table}) VALUES ('optimize')")
    # Each n-gram token must have become one term of the n-gram table.
    conn.execute(
        f"CREATE VIRTUAL TABLE temp.gv USING fts5vocab(main, {NGRAM_TABLE}, row)"
    )
    n_types, n_bad = conn.execute(
        "SELECT count(*), total(term NOT GLOB '?*_?*' OR term GLOB '*_*_*_*') "
        "FROM temp.gv"
    ).fetchone()
    n_pairs = conn.execute(
        "SELECT count(*) FROM temp.gv WHERE term NOT GLOB '*_*_*'"
    ).fetchone()[0]
    conn.execute("DROP TABLE temp.gv")
    if n_bad or (kept is not None and n_types < len(kept)):
        raise SystemExit(f"n-gram table: {n_types} terms ({n_bad:.0f} malformed)")
    if kept is not None and n_types > len(kept):
        log.warning("n-gram table: %d hash collisions", n_types - len(kept))
    return {
        "articles": n,
        "ngram_postings": n_postings,
        "pair_types": n_pairs,
        "triple_types": n_types - n_pairs,
    }


def mention_id_tables(conn: sqlite3.Connection) -> list[str]:
    tables = [
        name
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
        if name != Mention_Web_ID.name
    ]
    return [
        t
        for t in tables
        if any(r[1] == "Mention_ID" for r in conn.execute(f'PRAGMA table_info("{t}")'))
    ]


def rewrite_mention_ids(conn: sqlite3.Connection) -> list[str]:
    """Replace each Mention_ID by its Web_Mention_ID in all tables that
    have the column. Old and new IDs share their form, so a direct update
    could collide with a not yet rewritten row of a unique column; the
    new IDs are written with a prefix first, which is then removed."""
    tables = mention_id_tables(conn)
    for t in tables:
        n_unmapped = conn.execute(
            f'SELECT count(*) FROM "{t}" x LEFT JOIN Mention_Web_ID w '
            "USING (Mention_ID) WHERE w.Mention_ID IS NULL"
        ).fetchone()[0]
        if n_unmapped:
            raise SystemExit(f"{t}: {n_unmapped} Mention_IDs without a web ID")
        conn.execute(
            f"""UPDATE "{t}" SET Mention_ID = '~' || w.Web_Mention_ID
            FROM Mention_Web_ID w WHERE w.Mention_ID = "{t}".Mention_ID"""
        )
        conn.execute(f'UPDATE "{t}" SET Mention_ID = substr(Mention_ID, 2)')
    return tables


def spellfix_table(conn: sqlite3.Connection, extension) -> str:
    conn.execute("DROP TABLE IF EXISTS Wiki_Entry_alias_spellfix1")
    if not extension:
        conn.execute(SPELLFIX_PLACEHOLDER)
        log.warning("spellfix1 not available: Wiki_Entry_alias_spellfix1 is empty")
        return "placeholder"
    conn.enable_load_extension(True)
    conn.load_extension(extension)
    conn.enable_load_extension(False)
    conn.execute("CREATE VIRTUAL TABLE Wiki_Entry_alias_spellfix1 USING spellfix1")
    conn.execute(
        "INSERT INTO Wiki_Entry_alias_spellfix1 (word) "
        "SELECT alias FROM Wiki_Entry_alias WHERE alias IS NOT NULL"
    )
    return "extension"


def export(
    research_db, out, tokenize: str, spellfix=None, items=None, ngram_min_df: int = 2
) -> None:
    with atomic_output(out) as tmp:
        src = sqlite3.connect(f"file:{research_db}?mode=ro", uri=True)
        conn = sqlite3.connect(tmp)
        src.backup(conn)
        src.close()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise SystemExit(f"{research_db}: schema version {version}")
        with conn:
            stats = index_full_texts(
                conn, tokenize, ngram_min_df, os.path.dirname(os.path.abspath(out))
            )
            conn.execute("DELETE FROM Full_Text")
            rewritten = rewrite_mention_ids(conn)
            for table in research_only_tables:
                conn.execute(f'DROP TABLE "{table.name}"')
            spellfix = spellfix_table(conn, spellfix)
        log.info(
            "indexed %(articles)d full texts, %(ngram_postings)d n-gram postings "
            "of %(pair_types)d pair and %(triple_types)d triple types; "
            "spellfix1: %%s" % stats,
            spellfix,
        )
        log.info("Mention_IDs rewritten in %s", ", ".join(rewritten))
        info = {
            "export": "web",
            "search_index_format": search_index.INDEX_FORMAT,
            "fts_tokenize": tokenize,
            "fts_tokenizer_probe": search_index.probe(tokenize),
            "fts_ngram_tokenize": NGRAM_TOKENIZE,
            "fts_ngram_max_n": str(search_index.MAX_N),
            "fts_ngram_min_df": str(ngram_min_df),
            "spellfix1": spellfix,
            "mention_ids": "page_order",
        }
        info.update(items or {})
        info["export_date"] = build_info.build_date()
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO Build_Info (key, value) VALUES (?, ?)",
                sorted(info.items()),
            )
        conn.execute("VACUUM")
        conn.execute("ANALYZE")
        conn.close()


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--research", required=True, help="research database")
    p.add_argument("--tokenize", required=True, help="FTS5 tokenize option")
    p.add_argument("--spellfix", help="path of the spellfix1 extension")
    p.add_argument(
        "--ngram-min-df",
        type=int,
        default=2,
        help="index a word pair or triple only if it occurs in at least this "
        "many articles",
    )
    p.add_argument("--info", action="append", help="key=value for Build_Info")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    setup_logging()
    export(
        args.research,
        args.out,
        args.tokenize,
        args.spellfix,
        build_info.parse_items(args.info),
        args.ngram_min_df,
    )


if __name__ == "__main__":
    main()
