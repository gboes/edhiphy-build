import sqlite3

import pytest

from edhiphy import search_index
from edhiphy.export_web import index_full_texts
from edhiphy.search_index import (
    QueryError,
    Terms,
    check_tokenizer,
    compile_query,
    search,
)

TOKENIZE = "porter unicode61 remove_diacritics 2"
STABLE = "http://www.jstor.org/stable/"
TEXTS = {
    1: "The categorical imperative is Kant's. Kant wrote it. Kant again, kant.",
    2: "A categorical imperative binds. Free will; will free.",
    3: "Free will is a problem. Categorical claims: imperative moods.",
    4: "Hegel and the free will.",
    5: "Kant once. Then many other words follow here about Hegel and others.",
    6: "The philosophy of mind is hard.",
    7: "Philosophy of mind again.",
    8: "Philosophy of science. The study of mind.",
    9: "A philosophy of science and the theory of mind.",
}


@pytest.fixture(scope="module")
def web(tmp_path_factory):
    d = tmp_path_factory.mktemp("web")
    conn = sqlite3.connect(d / "web.sqlite")
    conn.execute("CREATE TABLE Full_Text (Article_ID TEXT, FullText TEXT)")
    conn.execute(
        "CREATE TABLE Full_Text_fts5_ArticleID (rowid INTEGER, Article_ID TEXT)"
    )
    conn.execute("CREATE TABLE Build_Info (key TEXT PRIMARY KEY, value TEXT)")
    conn.executemany(
        "INSERT INTO Full_Text VALUES (?, ?)",
        [(f"{STABLE}{i}", t) for i, t in TEXTS.items()],
    )
    stats = index_full_texts(conn, TOKENIZE, 2, d)
    conn.executemany(
        "INSERT INTO Build_Info VALUES (?, ?)",
        [
            ("search_index_format", search_index.INDEX_FORMAT),
            ("fts_tokenize", TOKENIZE),
            ("fts_tokenizer_probe", search_index.probe(TOKENIZE)),
        ],
    )
    conn.execute("DELETE FROM Full_Text")
    conn.commit()
    conn.execute("VACUUM")
    yield conn, stats, d / "web.sqlite"
    conn.close()


def hits(conn, query):
    return [int(a.rsplit("/", 1)[1]) for a, _ in search(conn, query, Terms(TOKENIZE))]


def vocab(conn, table, kind):
    conn.execute(f"CREATE VIRTUAL TABLE temp.v USING fts5vocab(main, {table}, {kind})")
    try:
        return conn.execute("SELECT * FROM temp.v").fetchall()
    finally:
        conn.execute("DROP TABLE temp.v")


def test_word_table_holds_counts_in_term_order(web):
    conn, stats, _ = web
    assert stats["articles"] == len(TEXTS)
    inst = vocab(conn, "Full_Text_fts5", "instance")
    doc1 = [
        term for term, doc, _, _ in sorted(inst, key=lambda r: (r[1], r[3])) if doc == 1
    ]
    # The stored sequence is sorted: positions are ranks, not text order.
    assert doc1 == sorted(doc1)
    assert doc1.count("kant") == 4 and doc1.count("s") == 1
    assert len(doc1) == 12


def test_ngrams_within_segments_and_min_df(web):
    conn, stats, _ = web
    grams = {t: n for t, n, _ in vocab(conn, "Full_Text_ngrams_fts5", "row")}
    assert grams["categor_imper"] == 2  # articles 1, 2; in 3 a ':' separates them
    assert grams["free_will"] == 3
    assert grams["philosophi_of_mind"] == 2
    assert grams["of_mind"] == 4
    assert "will_free" not in grams  # article 2 only
    assert "kant_s" not in grams  # article 1 only
    assert "theori_of_mind" not in grams  # article 9 only
    assert all(n >= 2 for n in grams.values())
    assert all(1 <= t.count("_") <= 2 for t in grams)
    triples = sum(t.count("_") == 2 for t in grams)
    assert (stats["pair_types"], stats["triple_types"]) == (
        len(grams) - triples,
        triples,
    )
    # detail=none: no positions, no counts
    assert {
        (off, col)
        for _, _, col, off in vocab(conn, "Full_Text_ngrams_fts5", "instance")
    } == {(None, None)}


def test_texts_not_in_file(web):
    _, _, path = web
    data = path.read_bytes()
    for text in TEXTS.values():
        assert text.encode() not in data
    assert b"kant wrote it" not in data.lower()


def test_words_prefixes_boolean(web):
    conn = web[0]
    assert hits(conn, "kant") == [1, 5]  # four occurrences rank first
    assert sorted(hits(conn, "kan*")) == [1, 5]
    assert sorted(hits(conn, "kant OR hegel")) == [1, 4, 5]
    assert hits(conn, "kant AND hegel") == [5]
    assert hits(conn, "kant hegel") == [5]
    assert hits(conn, "kant NOT hegel") == [1]
    assert sorted(hits(conn, "(hegel OR imperative) NOT free")) == [1, 5]


def test_phrases(web):
    conn = web[0]
    assert sorted(hits(conn, '"categorical imperatives"')) == [1, 2]
    assert sorted(hits(conn, '"free will"')) == [2, 3, 4]
    assert sorted(hits(conn, '"free will" NOT hegel')) == [2, 3]
    # A word that the tokenizer splits is a phrase.
    assert sorted(hits(conn, "categorical-imperative")) == [1, 2]
    # Pairs in fewer than min_df articles are not indexed: words only.
    c = compile_query(conn, '"will free"', Terms(TOKENIZE))
    assert c.unindexed_ngrams == ["will_free"]
    assert sorted(hits(conn, '"will free"')) == [2, 3, 4]
    # A segment break in the query phrase: no pair across it.
    c = compile_query(conn, '"categorical: imperative"', Terms(TOKENIZE))
    assert c.unindexed_ngrams == []
    assert sorted(hits(conn, '"categorical: imperative"')) == [1, 2, 3]


def test_three_word_phrases(web):
    conn = web[0]
    # Both pairs occur in articles 8 and 9, the triple only in 6 and 7.
    assert sorted(hits(conn, '"philosophy of mind"')) == [6, 7]
    # The triple and its first pair occur in one article only: the
    # remaining indexed pair and the words decide.
    c = compile_query(conn, '"theory of mind"', Terms(TOKENIZE))
    assert c.unindexed_ngrams == ["theori_of_mind", "theori_of"]
    assert hits(conn, '"theory of mind"') == [9]


@pytest.mark.parametrize(
    "query",
    [
        "",
        "NEAR(kant hegel)",
        "body:kant",
        "^kant",
        '"kant',
        "(kant",
        "kant OR",
        '"kant hegel"*',
        "self-ev*",
    ],
)
def test_unsupported_queries(web, query):
    with pytest.raises(QueryError):
        compile_query(web[0], query, Terms(TOKENIZE))


def test_check_tokenizer(web):
    conn = web[0]
    check_tokenizer(conn)
    conn.execute(
        "UPDATE Build_Info SET value = 'porter ascii' WHERE key = 'fts_tokenize'"
    )
    try:
        with pytest.raises(RuntimeError):
            check_tokenizer(conn)
    finally:
        conn.execute(
            f"UPDATE Build_Info SET value = '{TOKENIZE}' WHERE key = 'fts_tokenize'"
        )


def test_terms_match_sqlite():
    t = Terms(TOKENIZE)
    t.add(["Naïve", "imperatives", "Kant", "1920s"])
    assert [t[w] for w in ["Naïve", "imperatives", "Kant", "1920s"]] == [
        ("naiv",),
        ("imper",),
        ("kant",),
        ("1920",),
    ]
