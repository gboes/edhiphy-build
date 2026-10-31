"""End-to-end run of the Makefile on the synthetic mini-corpus."""

import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from edhiphy import __version__, search_index
from edhiphy.schema import SCHEMA_VERSION

REPO = Path(__file__).resolve().parent.parent
STABLE = "http://www.jstor.org/stable/"

# Tables and columns of the edhiphy 1.4.0 web database, which edhiphy/web
# reads. Columns may be added; none of these may disappear.
WEB_CONTRACT = {
    "Article_Similarity": ["Article_ID", "Method", "Rank", "Neighbour_ID", "Cosine"],
    "Author_Similarity": ["Phi_ID", "Method", "Rank", "Neighbour_Phi_ID", "Cosine"],
    "Biography": ["Phi_ID", "Surname", "First_Name", "Gender", "BirthYear"],
    "Classification": ["Property_ID", "Phi_ID", "Property", "Type", "Source", "Manual"],
    "Full_Text": ["Article_ID", "FullText", "length_words", "length_characters"],
    "Full_Text_fts5_ArticleID": ["rowid", "Article_ID"],
    "Hire_Position": [
        "Position_ID", "Phi_ID", "Hire_Name", "Institution_ID", "Hired_year",
        "Hired_before_1930", "Hire_rank", "Left_year", "Left_after_1980", "Highest_rank",
    ],
    "Institution": ["Institution_ID", "Institution"],
    "JSTOR_Article": [
        "Article_ID", "Authors_Phi_ID", "title", "publicationYear", "doi", "docType",
        "docSubType", "provider", "collection", "datePublished", "issueNumber",
        "volumeNumber", "url", "creator", "publisher", "language", "pageStart",
        "pageEnd", "placeOfPublication", "keyphrase", "wordCount", "pageCount", "file",
        "N_authors", "Journal_ID",
    ],
    "JSTOR_Authorship": ["Phi_ID", "author_position", "original_JSTOR_author", "Article_ID"],
    "Journal": [
        "Journal_ID", "Journal_standard_name", "Standard_abbreviation",
        "Journal_name_JSTOR", "Foundation_Year",
    ],
    "Journal_Variant": ["Journal_ID", "Journal_variant", "Starting_date", "Ending_date"],
    "Mention": [
        "Mentioning_Article_ID", "Mention_ID", "Ent_text", "Ent_label",
        "Disambiguation_status", "Mentioned_Phi_ID",
    ],
    "Mention_Associated": ["Mention_ID", "Phi_ID"],
    "Mention_Disambiguated": ["Mention_ID", "Phi_ID"],
    "Mention_context": ["Mentioning_Article_ID", "Mention_ID", "Mention_context"],
    "PhD_Dissertation": ["Phi_ID", "PQ_ID", "Title", "PhD_Candidate", "PhD_Year", "Institution_ID"],
    "Philosopher": [
        "Phi_ID", "Phi_Standard_Label", "Phi_Standard_Label_legacy", "Wiki", "JSTOR",
        "Hiring", "PhD",
    ],
    "Philosopher_Merged": ["Merged_Phi_ID", "Phi_ID"],
    "Philosopher_Life_Dates": [
        "Phi_ID", "Wiki_ID", "Birth_Year", "Birth_Uncertain", "Death_Year",
        "Death_Uncertain",
    ],
    "Philosopher_Wiki_ID": ["Phi_ID", "Wiki_ID"],
    "Variant": [
        "Phi_ID", "Variant_ID", "Variant", "Variant_origin", "Variant_length",
        "Issue_level", "Ambiguity", "Matching_Phi_IDs", "N_Multiple_Phi_IDs",
    ],
    "Variant_Matching_Phi_ID": ["Variant_ID", "Phi_ID"],
    "Wiki_Entry": [
        "Wiki_ID", "Wiki_label", "Wiki_description", "Mult_years", "Mult_surn",
        "Mult_first", "Mult_gender",
    ],
    "Wiki_Entry_alias": ["Wiki_ID", "alias"],
    "Wiki_Entry_birthYear": ["Wiki_ID", "birthYear"],
    "Wiki_Entry_firstname": ["Wiki_ID", "firstname"],
    "Wiki_Entry_gender": ["Wiki_ID", "gender"],
    "Wiki_Entry_surname": ["Wiki_ID", "surname"],
}  # fmt: skip


def gnu_make():
    """A GNU Make >= 4.3, or None."""
    for name in ["gmake", "make"]:
        path = shutil.which(name)
        if not path:
            continue
        out = subprocess.run([path, "--version"], capture_output=True, text=True).stdout
        m = re.match(r"GNU Make (\d+)\.(\d+)", out)
        if m and (int(m.group(1)), int(m.group(2))) >= (4, 3):
            return path
    return None


MAKE = gnu_make()
pytestmark = pytest.mark.skipif(MAKE is None, reason="GNU Make >= 4.3 not found")


def make(build_dir, *args, check=True):
    return subprocess.run(
        [MAKE, "-C", str(REPO), "CORPUS=test", f"BUILD_DIR={build_dir}",
         f"PYTHON={sys.executable}", "SPELLFIX1=", "WORKERS=1", "EXTRACT_WORKERS=1",
         # check-web requires a commit and a clean tree; tests also run on
         # uncommitted code and in CI, where git may not report a commit.
         "GIT_COMMIT=test", "GIT_DIRTY=no", *args],
        capture_output=True, text=True, check=check,
    )  # fmt: skip


@pytest.fixture(scope="module")
def build(tmp_path_factory):
    build_dir = tmp_path_factory.mktemp("build")
    result = make(build_dir, "all", check=False)
    assert result.returncode == 0, result.stderr[-3000:]
    out = build_dir / "corpora" / "test"
    return {
        "dir": build_dir,
        "db": out / f"edhiphy-test-{__version__}.sqlite",
        "web": out / f"edhiphy-test-{__version__}-web.sqlite",
    }


def query(db, sql, *params):
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        return conn.execute(sql, params).fetchall()


def test_research_db(build):
    db = build["db"]
    assert query(db, "PRAGMA user_version") == [(SCHEMA_VERSION,)]
    articles = query(
        db,
        "SELECT Article_ID, Authors_Phi_ID, N_authors, Journal_ID FROM JSTOR_Article ORDER BY 1",
    )
    # The book review and the unlisted article are not selected; the 1910
    # article carries an earlier title of journal 1.
    assert articles == [
        (STABLE + "900000001", "P:6", 1, "1"),
        (STABLE + "900000002", "P:5;P:6", 2, "1"),
        (STABLE + "900000101", "P:1", 1, "2"),
        (STABLE + "900000102", "P:5", 1, "2"),
    ]  # fmt: skip
    assert query(db, "SELECT count(*) FROM Full_Text") == [(4,)]
    assert query(db, "SELECT count(*) FROM Mention WHERE Mentioning_Article_ID LIKE '%900000003'") == [(0,)]  # fmt: skip
    assoc = query(db, "SELECT Phi_ID FROM Mention_Associated a JOIN Mention m USING (Mention_ID) WHERE m.Ent_text = 'Moore' AND m.Mentioning_Article_ID LIKE '%900000001'")  # fmt: skip
    assert sorted(assoc) == [("P:4",), ("P:5",)]
    info = dict(query(db, "SELECT key, value FROM Build_Info"))
    assert info["corpus"] == "test"
    assert info["sources"] == "test_a test_b"
    assert info["schema_version"] == str(SCHEMA_VERSION)


def test_authorship_is_the_primary_relation(build):
    # Authors_Phi_ID and N_authors are derived from JSTOR_Authorship (#18).
    derived = query(
        build["db"],
        """SELECT a.Article_ID, a.Authors_Phi_ID, a.N_authors, w.ids, w.n
        FROM JSTOR_Article a JOIN (
            SELECT Article_ID, group_concat(Phi_ID, ';') AS ids, count(*) AS n
            FROM (SELECT * FROM JSTOR_Authorship ORDER BY Article_ID, author_position)
            GROUP BY Article_ID
        ) w USING (Article_ID)""",
    )
    assert len(derived) == len(query(build["db"], "SELECT * FROM JSTOR_Article"))
    assert all(r[1:3] == r[3:5] for r in derived)


def test_statistics_tables(build):
    db, web = build["db"], build["web"]
    resolved = query(db, "SELECT count(Mentioned_Phi_ID) FROM Mention")[0][0]
    assert resolved > 0
    totals = {
        "Philosopher_Statistics": "SELECT count(*), sum(N_mentions) FROM Philosopher_Statistics",
        "Article_Statistics": "SELECT count(*), sum(N_mentions) FROM Article_Statistics",
        "Journal_Statistics": "SELECT sum(N_articles), sum(N_mentions) FROM Journal_Statistics",
    }  # fmt: skip
    n_philosophers = query(db, "SELECT count(*) FROM Philosopher")[0][0]
    n_articles = query(db, "SELECT count(*) FROM JSTOR_Article")[0][0]
    assert query(db, totals["Philosopher_Statistics"]) == [(n_philosophers, resolved)]
    assert query(db, totals["Article_Statistics"]) == [(n_articles, resolved)]
    assert query(db, totals["Journal_Statistics"]) == [(n_articles, resolved)]
    authored = query(db, "SELECT N_authored_articles FROM Philosopher_Statistics WHERE Phi_ID = 'P:5'")  # fmt: skip
    assert authored == [(2,)]
    for table in totals:
        rows = query(db, f"SELECT * FROM {table} ORDER BY 1, 2")
        assert rows == query(web, f"SELECT * FROM {table} ORDER BY 1, 2")


def test_web_contract(build):
    web = build["web"]
    for table, columns in WEB_CONTRACT.items():
        present = [r[1] for r in query(web, f'PRAGMA table_info("{table}")')]
        assert set(columns) <= set(present), table
    names = {r[0] for r in query(web, "SELECT name FROM sqlite_master")}
    assert {
        "Full_Text_fts5",
        "Full_Text_ngrams_fts5",
        "Wiki_Entry_alias_spellfix1",
        "Build_Info",
    } <= names


def test_web_export_has_no_full_texts(build):
    web = build["web"]
    assert query(web, "SELECT count(*) FROM Full_Text") == [(0,)]
    hits = query(web, "SELECT a.Article_ID FROM Full_Text_fts5 f JOIN Full_Text_fts5_ArticleID a ON a.rowid = f.rowid WHERE Full_Text_fts5 MATCH 'quuxplorative'")  # fmt: skip
    assert hits == [(STABLE + "900000101",)]
    sentence = b"The quuxplorative passage stays private."
    assert sentence in build["db"].read_bytes()
    assert sentence not in build["web"].read_bytes()
    info = dict(query(web, "SELECT key, value FROM Build_Info"))
    assert info["search_index_format"] == search_index.INDEX_FORMAT
    assert info["fts_ngram_min_df"] == "2"
    conn = sqlite3.connect(f"file:{web}?mode=ro", uri=True)
    search_index.check_tokenizer(conn)
    terms = search_index.Terms(info["fts_tokenize"])
    assert [a for a, _ in search_index.search(conn, "quuxplorative", terms)] == [
        STABLE + "900000101"
    ]
    conn.close()


def test_web_mention_ids(build):
    db, web = build["db"], build["web"]
    mapping = dict(query(db, "SELECT Mention_ID, Web_Mention_ID FROM Mention_Web_ID"))
    assert set(mapping) == {r[0] for r in query(db, "SELECT Mention_ID FROM Mention")}
    names = {r[0] for r in query(web, "SELECT name FROM sqlite_master")}
    assert "Mention_Web_ID" not in names
    for table in [
        "Mention",
        "Mention_Associated",
        "Mention_Disambiguated",
        "Mention_context",
    ]:
        old = query(db, f"SELECT * FROM {table}")
        new = query(web, f"SELECT * FROM {table}")
        i = [r[1] for r in query(db, f"PRAGMA table_info({table})")].index("Mention_ID")
        assert sorted(r[:i] + (mapping[r[i]],) + r[i + 1 :] for r in old) == sorted(
            new
        ), table
    # Per page, k counts the mentions from 1.
    pages = {}
    for mention_id in mapping.values():
        number, page, k = re.fullmatch(r"(9\d{8})_(\d+)_(\d+)", mention_id).groups()
        pages.setdefault((number, page), []).append(int(k))
    assert all(sorted(ks) == list(range(1, len(ks) + 1)) for ks in pages.values())
    info = dict(query(web, "SELECT key, value FROM Build_Info"))
    assert info["mention_ids"] == "page_order"


def test_similarity_tables(build):
    db, web = build["db"], build["web"]
    rows = query(db, "SELECT * FROM Article_Similarity ORDER BY 1, 2, 3")
    assert rows == query(web, "SELECT * FROM Article_Similarity ORDER BY 1, 2, 3")
    # The fixture articles are shorter than similarity.MIN_WORDS: no LSA
    # neighbours, only mention neighbours with a positive cosine.
    assert rows and {r[1] for r in rows} == {"mentions"}
    assert all(r[4] > 0 for r in rows)
    orphans = "SELECT count(*) FROM Article_Similarity s LEFT JOIN JSTOR_Article a ON a.Article_ID = s.Neighbour_ID WHERE a.Article_ID IS NULL"  # fmt: skip
    assert query(db, orphans) == [(0,)]
    authors = query(db, "SELECT Method, count(*) FROM Author_Similarity GROUP BY 1")
    assert all(m == "mentions" for m, _ in authors)
    info = dict(query(db, "SELECT key, value FROM Build_Info"))
    assert (info["lsa_dimensions"], info["similar_k"]) == ("2", "2")


def test_rerun_is_noop(build):
    assert make(build["dir"], "-q", "all", check=False).returncode == 0


def stages_after_touching(build, path):
    """Stages that a real rebuild runs when ``path`` is taken as changed
    (``make -W``; a dry run does not propagate through grouped targets)."""
    ran = make(build["dir"], "-W", path, "all").stdout
    return sorted(set(re.findall(r"-m edhiphy\.(\w+)", ran)))


def test_code_change_reruns_dependent_stages_only(build):
    assert stages_after_touching(build, "src/edhiphy/export_web.py") == ["export_web"]
    assert stages_after_touching(build, "src/edhiphy/dictionary.py") == [
        "authorship", "contexts", "dictionary", "disambiguate", "export_web", "extract",
        "package", "similarity",
    ]  # fmt: skip
    assert stages_after_touching(build, "src/edhiphy/disambiguate.py") == [
        "disambiguate", "export_web", "package", "similarity",
    ]  # fmt: skip
    assert stages_after_touching(build, "src/edhiphy/similarity.py") == [
        "export_web", "package", "similarity",
    ]  # fmt: skip
    assert "ingest" in stages_after_touching(build, "src/edhiphy/common.py")


def test_rules_write_only_below_build_dir(build):
    dry = make(build["dir"], "-n", "-B", "all").stdout
    outputs = re.findall(r"--out(?:-[a-z-]+)?(?:=|\s+)(\S+)", dry)
    assert outputs
    for out in outputs:
        assert Path(out).resolve().is_relative_to(build["dir"].resolve()), out


@pytest.fixture(scope="module")
def build_fr(tmp_path_factory):
    build_dir = tmp_path_factory.mktemp("build_fr")
    result = make(build_dir, "CORPUS=test_fr", "all", check=False)
    assert result.returncode == 0, result.stderr[-3000:]
    out = build_dir / "corpora" / "test_fr"
    return {
        "db": out / "edhiphy-test-fr-0.1.sqlite",
        "web": out / "edhiphy-test-fr-0.1-web.sqlite",
    }


def test_french_corpus(build_fr):
    db = build_fr["db"]
    mentions = query(
        db,
        "SELECT substr(Mentioning_Article_ID, 29), Ent_text, Mentioned_Phi_ID FROM Mention ORDER BY rowid",
    )
    # "M." is removed before Kant; the elision, the accent-less OCR name
    # and "oe" for "œ" are matched; guillemets do not stop "Lévinas".
    assert mentions == [
        ("900000201", "Kant", "P:2"),
        ("900000201", "d'Alembert", "P:10"),
        ("900000201", "Tocqueville", "P:11"),
        ("900000201", "Emmanuel Kant", "P:2"),
        ("900000201", "Lévinas", "P:8"),
        ("900000202", "Levinas", "P:8"),
        ("900000202", "Paul Ricoeur", "P:9"),
        ("900000202", "E. Kant", "P:2"),
        ("900000202", "Ricœur", "P:9"),
        ("900000202", "Levinas", "P:8"),
        ("900000203", "Russell", "P:3"),
        ("900000203", "Kant", "P:2"),
    ]  # fmt: skip
    text = query(db, "SELECT FullText FROM Full_Text WHERE Article_ID LIKE '%201'")[0][
        0
    ]
    assert "M. " not in text and "«" not in text and "op. cit." not in text
    assert not text.startswith("12 REVUE")
    articles = query(
        db, "SELECT Authors_Phi_ID, Journal_ID, language FROM JSTOR_Article ORDER BY 1"
    )
    # The book review is not selected; the English article is kept.
    assert articles == [
        ("P:1", "fr1", "eng"),
        ("P:12", "fr1", "fre"),
        ("P:12;P:3", "fr1", "fre"),
    ]
    info = dict(query(db, "SELECT key, value FROM Build_Info"))
    assert (info["corpus_name"], info["corpus_version"], info["language"]) == (
        "test-fr",
        "0.1",
        "fr",
    )
    assert info["fold_diacritics"] == "yes"


def test_release_targets(build, build_fr):
    for b, corpus in ((build, "test"), (build_fr, "test_fr")):
        result = make(
            b["db"].parent.parent.parent, f"CORPUS={corpus}", "release", check=False
        )
        assert result.returncode == 0, result.stderr[-3000:]
        out = b["db"].parent
        assert "FAIL" not in (out / "check-web.md").read_text()
        sums = next(out.glob("*.sha256")).read_text().split()
        assert sums[1::2] == [b["db"].name, b["web"].name]


def test_french_search_folds_accents(build_fr):
    conn = sqlite3.connect(f"file:{build_fr['web']}?mode=ro", uri=True)
    info = dict(conn.execute("SELECT key, value FROM Build_Info"))
    assert "porter" not in info["fts_tokenize"]
    terms = search_index.Terms(info["fts_tokenize"])
    for q in ("pensée", "pensee", "Lévinas", "levinas"):
        hits = sorted(a for a, _ in search_index.search(conn, q, terms))
        assert hits == [STABLE + "900000201", STABLE + "900000202"], q
    conn.close()
