"""The full-text search index of the web export and the reference
translation of search queries for it.

The index holds no word positions. ``Full_Text_fts5`` holds, per
article, its words with their exact counts, in alphabetical order of the
stemmed terms (``detail=full``, so ``bm25()`` can rank); its positions
are ranks in that order and carry nothing of the text.
``Full_Text_ngrams_fts5`` holds, per article, the set of its word pairs
``a_b`` and word triples ``a_b_c`` (adjacent terms within a sentence
segment), restricted to n-grams that occur in at least ``min_df``
articles (``detail=none``: no positions, no counts). A phrase query is
answered from the n-grams; a phrase query sent to ``Full_Text_fts5``
directly gives meaningless results.

``compile_query`` is the reference for the web application: it turns a
query in a subset of the FTS5 syntax into SQL on these two tables. The
decisions, the semantics and the assumptions that the web application
must keep are in documentation/search_index.md.
"""

import functools
import itertools
import json
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

WORD_TABLE = "Full_Text_fts5"
NGRAM_TABLE = "Full_Text_ngrams_fts5"
ROWID_TABLE = "Full_Text_fts5_ArticleID"
# N-gram tokens are built from terms that the word tokenizer has already
# folded and stemmed; this tokenizer keeps them unchanged as one token.
NGRAM_TOKENIZE = "unicode61 remove_diacritics 0 tokenchars '_'"
# Longest indexed n-gram.
MAX_N = 3  # compile_query handles pairs and triples
# Recorded in Build_Info as search_index_format; documented in
# documentation/search_index.md.
INDEX_FORMAT = "2"
# Characters that end a sentence segment: no n-gram spans them.
SEGMENT_BREAK = re.compile(r"[.!?;:]")
# Input of the tokenizer check that the web application repeats against
# its own SQLite (Build_Info key fts_tokenizer_probe).
PROBE_TEXT = (
    "Categorical imperatives: Naïve realism, Æsthetik and Kant's 1920s philosophies"
)


@functools.cache
def token_pattern() -> re.Pattern:
    """Runs of the characters that may belong to a token of the unicode61
    tokenizer: letters, numbers and private-use characters (its default
    token characters) and, in addition, combining marks. The class is
    wider than that of unicode61, never narrower, so unicode61 splits each
    run into the same tokens as the original text, and those tokens stay
    adjacent."""
    # Planes 0-3 and 14 hold all assigned marks; planes 15-16 are private
    # use throughout.
    ranges = []
    for c in itertools.chain(range(0x40000), range(0xE0000, 0xF0000)):
        cat = unicodedata.category(chr(c))
        if cat[0] == "M" or cat == "Co":
            if ranges and ranges[-1][1] == c - 1:
                ranges[-1][1] = c
            else:
                ranges.append([c, c])
    ranges.append([0xF0000, sys.maxunicode])
    extra = "".join(
        re.escape(chr(a)) + ("-" + re.escape(chr(b)) if b > a else "")
        for a, b in ranges
    )
    return re.compile(f"(?:[^\\W_]|[{extra}])+")


def sql_string(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def fts_string(s: str) -> str:
    """``s`` as an FTS5 string (a phrase of the tokens of ``s``)."""
    return '"' + s.replace('"', '""') + '"'


class Terms:
    """The terms that the FTS5 tokenizer ``tokenize`` produces for a run of
    token characters, computed by SQLite itself (through a scratch table
    and ``fts5vocab``), so that stemming and folding are exactly those of
    the index. Results are cached."""

    def __init__(self, tokenize: str):
        self.tokenize = tokenize
        self.conn = sqlite3.connect(":memory:")
        self.cache: dict[str, tuple[str, ...]] = {}

    def add(self, runs) -> None:
        new = list(dict.fromkeys(r for r in runs if r not in self.cache))
        if not new:
            return
        c = self.conn
        c.execute("DROP TABLE IF EXISTS temp.v")
        c.execute("DROP TABLE IF EXISTS s")
        c.execute(
            f"CREATE VIRTUAL TABLE s USING fts5(x, tokenize = {sql_string(self.tokenize)})"
        )
        c.execute("CREATE VIRTUAL TABLE temp.v USING fts5vocab(main, s, instance)")
        c.executemany("INSERT INTO s (rowid, x) VALUES (?, ?)", enumerate(new, 1))
        found = defaultdict(list)
        for term, doc, offset in c.execute("SELECT term, doc, offset FROM temp.v"):
            found[doc].append((offset, term))
        for i, run in enumerate(new, 1):
            self.cache[run] = tuple(t for _, t in sorted(found[i]))

    def __getitem__(self, run: str) -> tuple[str, ...]:
        return self.cache[run]

    def segments(self, text: str) -> list[list[str]]:
        """The runs of ``text`` per sentence segment; adds them to the cache."""
        segs = [token_pattern().findall(s) for s in SEGMENT_BREAK.split(text)]
        self.add(r for s in segs for r in s)
        return segs


def probe(tokenize: str) -> str:
    """The Build_Info value of the tokenizer check: the terms of
    ``PROBE_TEXT``."""
    terms = Terms(tokenize)
    runs = [r for s in terms.segments(PROBE_TEXT) for r in s]
    return json.dumps(
        {"text": PROBE_TEXT, "terms": [t for r in runs for t in terms[r]]},
        ensure_ascii=False,
    )


def ngrams(seq: list[str], n: int) -> list[str]:
    """The n-gram tokens of a term sequence: terms joined by ``_``."""
    return ["_".join(seq[i : i + n]) for i in range(len(seq) - n + 1)]


def article_tokens(text: str, terms: Terms) -> tuple[str, set[str]]:
    """The two index rows of an article: its runs sorted by their terms
    (the word table indexes them as the terms with their counts, in an
    order that depends only on the multiset of terms), and the set of its
    n-grams (2 to ``MAX_N`` adjacent terms) within sentence segments."""
    segs = terms.segments(text)
    runs = [r for s in segs for r in s if terms[r]]
    words = " ".join(sorted(runs, key=terms.__getitem__))
    grams = set()
    for s in segs:
        seq = [t for r in s for t in terms[r]]
        for n in range(2, MAX_N + 1):
            grams.update(ngrams(seq, n))
    return words, grams


# --- Queries -----------------------------------------------------------


class QueryError(ValueError):
    pass


@dataclass
class Word:
    text: str
    prefix: bool = False


@dataclass
class Phrase:
    text: str


@dataclass
class Op:
    op: str  # AND, OR, NOT (binary: left NOT right)
    args: list = field(default_factory=list)


LEX = re.compile(r'\s*(?:(\()|(\))|"((?:[^"]|"")*)"|([^\s()"]+))')


def lex(query: str) -> list:
    out, pos = [], 0
    query = query.rstrip()
    while pos < len(query):
        m = LEX.match(query, pos)
        if not m:
            raise QueryError("unbalanced quotation marks")
        pos = m.end()
        if m.group(1):
            out.append("(")
        elif m.group(2):
            out.append(")")
        elif m.group(3) is not None:
            out.append(Phrase(m.group(3).replace('""', '"')))
        else:
            w = m.group(4)
            if w in ("AND", "OR", "NOT"):
                out.append(w)
            elif w == "NEAR" or w.startswith("NEAR("):
                raise QueryError("NEAR is not supported: use a phrase or AND")
            elif w[0] in "^+-" or ":" in w or "{" in w:
                raise QueryError(f"unsupported FTS5 syntax: {w}")
            elif w.endswith("*"):
                out.append(Word(w[:-1], prefix=True))
            else:
                out.append(Word(w))
    return out


def parse(query: str):
    """A subset of the FTS5 query syntax: words, ``word*`` prefixes,
    ``"phrases"``, ``AND``, ``OR``, ``NOT`` (binary), parentheses and
    implicit AND; precedence NOT > AND > OR, as in FTS5."""
    toks = lex(query)
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def take():
        nonlocal pos
        pos += 1
        return toks[pos - 1]

    def primary():
        t = peek()
        if t == "(":
            take()
            e = or_()
            if take() != ")":
                raise QueryError("missing )")
            return e
        if isinstance(t, (Word, Phrase)):
            return take()
        raise QueryError(f"unexpected {t or 'end of query'}")

    def not_():
        e = primary()
        while peek() == "NOT":
            take()
            e = Op("NOT", [e, primary()])
        return e

    def and_():
        args = [not_()]
        while peek() == "AND" or isinstance(peek(), (Word, Phrase)) or peek() == "(":
            if peek() == "AND":
                take()
            args.append(not_())
        return args[0] if len(args) == 1 else Op("AND", args)

    def or_():
        args = [and_()]
        while peek() == "OR":
            take()
            args.append(and_())
        return args[0] if len(args) == 1 else Op("OR", args)

    if not toks:
        raise QueryError("empty query")
    try:
        e = or_()
    except IndexError:
        raise QueryError("incomplete query") from None
    if pos != len(toks):
        raise QueryError(f"unexpected {toks[pos]}")
    return e


@dataclass
class Compiled:
    rowids_sql: str  # SELECT rowid ... : the matching articles
    params: list
    ranked_sql: str  # SELECT Article_ID, score ... ORDER BY score DESC
    ranked_params: list
    unindexed_ngrams: list  # phrase n-grams not in the n-gram table


def compile_query(conn: sqlite3.Connection, query: str, terms: Terms) -> Compiled:
    """SQL for ``query`` on the web export ``conn``. ``terms`` must use the
    tokenizer of the word table (Build_Info ``fts_tokenize``).

    Words and prefixes go to the word table. A phrase (or a word that the
    tokenizer splits into several terms, such as ``self-evident``) means:
    all its words, every triple of adjacent terms within a sentence segment
    that is in the n-gram table, and every adjacent pair that is in the
    n-gram table and not part of such a triple. N-grams that are not in the
    table (they occur in fewer than ``min_df`` articles, or nowhere) are
    dropped from the condition and listed in ``unindexed_ngrams``; a
    two-word phrase whose pair is not indexed is answered by its words
    only. Ranking: ``bm25`` of the word table for all words and prefixes
    outside the right side of a NOT."""
    params, rank_terms, unindexed = [], [], []

    def word_sql(expr):
        params.append(expr)
        return f"SELECT rowid FROM {WORD_TABLE} WHERE {WORD_TABLE} MATCH ?"

    def indexed(gram):
        hit = conn.execute(
            f"SELECT 1 FROM {NGRAM_TABLE} WHERE {NGRAM_TABLE} MATCH ? LIMIT 1",
            (fts_string(gram),),
        ).fetchone()
        return hit is not None

    def leaf(node, positive):
        segs = terms.segments(node.text)
        runs = [r for s in segs for r in s if terms[r]]
        if not runs:
            raise QueryError(f"no searchable word in {node.text!r}")
        n_terms = sum(len(terms[r]) for r in runs)
        if isinstance(node, Word) and node.prefix:
            if n_terms > 1:
                raise QueryError(f"a prefix must be a single word: {node.text}*")
            expr = fts_string(runs[0]) + " *"
            if positive:
                rank_terms.append(expr)
            return word_sql(expr)
        exprs = list(dict.fromkeys(fts_string(r) for r in runs))
        if positive:
            rank_terms.extend(exprs)
        parts = [word_sql(" AND ".join(exprs))]
        found, covered = [], set()
        for s in segs:
            seq = [t for r in s for t in terms[r]]
            for i in range(len(seq) - 2):
                g = "_".join(seq[i : i + 3])
                if indexed(g):
                    found.append(g)
                    covered.update(ngrams(seq[i : i + 3], 2))
                else:
                    unindexed.append(g)
            for g in ngrams(seq, 2):
                if g not in covered:
                    (found if indexed(g) else unindexed).append(g)
        if found:
            params.append(" AND ".join(fts_string(g) for g in dict.fromkeys(found)))
            parts.append(f"SELECT rowid FROM {NGRAM_TABLE} WHERE {NGRAM_TABLE} MATCH ?")
        return " INTERSECT ".join(f"SELECT rowid FROM ({p})" for p in parts)

    def sql(node, positive=True):
        if isinstance(node, (Word, Phrase)):
            return leaf(node, positive)
        if node.op == "NOT":
            left = sql(node.args[0], positive)
            right = sql(node.args[1], not positive)
            return f"SELECT rowid FROM ({left}) EXCEPT SELECT rowid FROM ({right})"
        joiner = " INTERSECT " if node.op == "AND" else " UNION "
        return joiner.join(f"SELECT rowid FROM ({sql(a, positive)})" for a in node.args)

    rowids = sql(parse(query))
    rank = " OR ".join(dict.fromkeys(rank_terms))
    # The scores are computed in one pass over the FTS5 matches and then
    # joined with the hits. "LIMIT -1" keeps SQLite from flattening the
    # subquery into the join: flattened (or with "rowid IN (...)"), FTS5
    # looks up each hit by rowid and repeats a prefix merge per hit (en_v1,
    # caus*: 57 s instead of 0.05 s).
    ranked = (
        f"WITH scored AS (SELECT rowid AS r, -bm25({WORD_TABLE}) AS score "
        f"FROM {WORD_TABLE} WHERE {WORD_TABLE} MATCH ? LIMIT -1), "
        f"hits AS ({rowids}) "
        f"SELECT m.Article_ID, scored.score FROM scored "
        f"JOIN hits ON hits.rowid = scored.r "
        f"JOIN {ROWID_TABLE} m ON m.rowid = scored.r "
        f"ORDER BY scored.score DESC, m.Article_ID"
    )
    unindexed = list(dict.fromkeys(unindexed))
    return Compiled(rowids, list(params), ranked, [rank] + params, unindexed)


def search(
    conn: sqlite3.Connection, query: str, terms: Terms
) -> list[tuple[str, float]]:
    """Matching articles of ``query``, best first: (Article_ID, score)."""
    c = compile_query(conn, query, terms)
    return conn.execute(c.ranked_sql, c.ranked_params).fetchall()


def check_tokenizer(conn: sqlite3.Connection) -> None:
    """Raise if this SQLite tokenizes differently from the one that built
    the web export ``conn`` (compares Build_Info fts_tokenizer_probe)."""
    info = dict(conn.execute("SELECT key, value FROM Build_Info"))
    if info.get("search_index_format") != INDEX_FORMAT:
        raise RuntimeError(f"search index format {info.get('search_index_format')}")
    if probe(info["fts_tokenize"]) != info["fts_tokenizer_probe"]:
        raise RuntimeError("this SQLite tokenizes differently from the build")
