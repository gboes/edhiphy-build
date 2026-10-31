#!/usr/bin/env python3
"""Write the synthetic mini-corpus used by ``make CORPUS=test``.

Usage: mini_corpus.py OUT_DIR

All texts, article IDs, authors and identifiers are invented (philosopher
names apart); no JSTOR material is used. The fixture is generated rather
than committed because its file types (JSONL, tables with full texts and
contexts) are excluded from publication by ``publish/check.sh``.

Layout, mirroring DATA_DIR: ``raw/test_a`` (gzip JSONL) and ``raw/test_b``
(plain JSONL) with metadata CSVs, ``curated/tables`` (dictionary,
authorship, journals and the article list in v1 format), ``reference``
(v1-format mentions, contexts and cleaned full texts).
"""

import csv
import gzip
import json
import sys
from pathlib import Path

STABLE = "http://www.jstor.org/stable/"

JOURNALS = [
    # Journal_ID, standard name, abbreviation, JSTOR title, foundation year
    (
        1,
        "Journal of Invented Philosophy",
        "J. Invent. Philos.",
        "Journal of Invented Philosophy",
        1901,
    ),
    (2, "Synthetic Review", "Synth. Rev.", "The Synthetic Review", 1950),
]
JOURNAL_VARIANTS = [
    # Journal_ID, earlier JSTOR title, from, to
    (1, "Journal of Invented Philosophy and Method", 1901, 1920),
]

# Phi_ID, label, Wiki_ID, Wiki, JSTOR, Hiring, PhD
PHILOSOPHERS = [
    ("P:1", "[No Author]", "", 0, 1, 0, 0),
    ("P:2", "Immanuel Kant", "http://www.wikidata.org/entity/Q999999902", 1, 0, 0, 0),
    (
        "P:3",
        "Bertrand Russell",
        "http://www.wikidata.org/entity/Q999999903",
        1,
        0,
        0,
        0,
    ),
    ("P:4", "G. E. Moore", "http://www.wikidata.org/entity/Q999999904", 1, 0, 0, 0),
    ("P:5", "Dorothy Moore", "", 0, 1, 0, 1),
    ("P:6", "Ada Testwright", "", 0, 1, 1, 1),
    (
        "P:7",
        "Young Testperson",
        "http://www.wikidata.org/entity/Q999999907",
        1,
        0,
        0,
        0,
    ),
]

# Phi_ID, Variant_ID, Variant, origin, Issue_level; the ambiguity columns
# are derived below with the v1 rules.
VARIANTS = [
    ("P:1", "P:1_1", "[No Author]", "JSTOR_Standard label", ""),
    ("P:2", "P:2_1", "Immanuel Kant", "Original Wiki label", ""),
    ("P:2", "P:2_2", "Kant", "Wiki surname", ""),
    ("P:3", "P:3_1", "Bertrand Russell", "Original Wiki label", ""),
    ("P:3", "P:3_2", "Russell", "Wiki surname", ""),
    ("P:4", "P:4_1", "G. E. Moore", "Original Wiki label", ""),
    ("P:4", "P:4_2", "Moore", "Wiki surname", ""),
    ("P:5", "P:5_1", "Dorothy Moore", "JSTOR_Standard label", ""),
    ("P:5", "P:5_2", "Moore", "JSTOR_Artificial surname", ""),
    ("P:6", "P:6_1", "Ada Testwright", "JSTOR_Standard label", ""),
    ("P:6", "P:6_2", "Testwright", "JSTOR_Artificial surname", ""),
    ("P:7", "P:7_1", "Testperson", "Wiki surname", "Too_young_philosopher"),
]

WIKI = [
    # Wiki_ID, label, aliases, description, birth years, surnames, first names, genders
    (
        "Q999999902",
        "Immanuel Kant",
        "Kant, I. Kant",
        "invented description",
        "1724",
        "Kant",
        "Immanuel",
        "male",
    ),
    (
        "Q999999903",
        "Bertrand Russell",
        "Russell, B. Russell",
        "invented description",
        "1872",
        "Russell",
        "Bertrand",
        "male",
    ),
    (
        "Q999999904",
        "G. E. Moore",
        "George Edward Moore",
        "invented description",
        "1873",
        "Moore",
        "George|Edward",
        "male",
    ),
    (
        "Q999999907",
        "Young Testperson",
        "",
        "invented description",
        "1990|1991",
        "Testperson",
        "Young",
        "female",
    ),
]

FILLER = " ".join(["This sentence pads the page with neutral words."] * 5)

# source, number, journal title, year, subtype, authors [(Phi_ID, JSTOR name)], pages
ARTICLES = [
    (
        "test_a",
        900000001,
        "Journal of Invented Philosophy and Method",
        1910,
        "research-article",
        [("P:6", "Ada Testwright")],
        [
            "On the uses of synthetic examples. Kant held that examples sharpen judgement.",
            "Russell replied that Moore had shown the opposite, and Kant was silent.",
        ],
    ),
    (
        "test_a",
        900000002,
        "Journal of Invented Philosophy",
        1931,
        "research-article",
        [("P:5", "Dorothy Moore"), ("P:6", "Ada Testwright")],
        [
            "A note on Bertrand Russell and the theory of descriptions.",
            "As Moore observed, Russell's theory is not about Kant.",
        ],
    ),
    (
        "test_a",
        900000003,
        "Journal of Invented Philosophy",
        1932,
        "book-review",
        [("P:1", "")],
        ["Review of a book that mentions Kant once."],
    ),
    (
        "test_b",
        900000101,
        "The Synthetic Review",
        1955,
        "research-article",
        [("P:1", "")],
        [
            "Immanuel Kant and G. E. Moore on the good.",
            "Testperson is not mentioned here.",
            # Far from every mention, hence in no context: the web export
            # must not contain this sentence.
            f"{FILLER} The quuxplorative passage stays private. {FILLER}",
        ],
    ),
    (
        "test_b",
        900000102,
        "The Synthetic Review",
        1956,
        "research-article",
        [("P:5", "Dorothy Moore")],
        ["Moore wrote this article about Testwright and Kant."],
    ),
    (
        "test_b",
        900000103,
        "The Synthetic Review",
        1957,
        "research-article",
        [("P:6", "Ada Testwright")],
        ["Excluded from the article list; mentions Russell."],
    ),
]

# Selected articles: research articles minus 900000103.
SELECTED = [900000001, 900000002, 900000003, 900000101, 900000102]

METADATA_COLUMNS = (
    "id,title,isPartOf,publicationYear,doi,docType,docSubType,provider,collection,"
    "datePublished,issueNumber,volumeNumber,url,creator,publisher,language,pageStart,"
    "pageEnd,placeOfPublication,keyphrase,wordCount,pageCount,file"
).split(",")

CONTEXT_CHARS = 100


def raw_pages(journal: str, pages):
    """Pages as JSTOR delivers them: a running header (page number and
    upper-case journal title, removed by the cleaner) before the text."""
    return [f"{n} {journal.upper()} {p}" for n, p in enumerate(pages, 1)]


def write_csv(path: Path, header, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="UTF-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def ambiguity(variants):
    candidates = {}
    for phi, _, variant, _, issue in variants:
        if not issue:
            candidates.setdefault(variant, set()).add(phi)
    rows = []
    for phi, vid, variant, origin, issue in variants:
        if issue:
            rows.append(
                (
                    phi,
                    vid,
                    variant,
                    origin,
                    len(variant),
                    issue,
                    "Unvalid_variant",
                    "",
                    0,
                )
            )
        else:
            c = sorted(candidates[variant])
            status = "Univocal" if len(c) == 1 else "Ambiguous"
            rows.append(
                (
                    phi,
                    vid,
                    variant,
                    origin,
                    len(variant),
                    "",
                    status,
                    "|".join(c),
                    len(c),
                )
            )
    return rows


def find_mentions(text, variants):
    """Longest match at each start position, scanning left to right."""
    valid = sorted({v[2] for v in variants if not v[4]}, key=len, reverse=True)
    found, i = [], 0
    while i < len(text):
        for v in valid:
            end = i + len(v)
            if (
                text.startswith(v, i)
                and (i == 0 or not text[i - 1].isalnum())
                and (end == len(text) or not text[end].isalnum())
            ):
                found.append((i, v))
                i = end
                break
        else:
            i += 1
    return found


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tables = out / "curated" / "tables"

    write_csv(
        tables / "Journals_table.csv",
        [
            "Journal_ID",
            "Journal_standard_name",
            "Standard_abbreviation",
            "Journal_name_JSTOR",
            "Foundation_Year",
        ],
        JOURNALS,
    )
    write_csv(
        tables / "Journals_variants.csv",
        ["Journal_ID", "Journal_variant", "Starting_date", "Ending_date"],
        JOURNAL_VARIANTS,
    )
    write_csv(
        tables / "Philosophers_table.csv",
        ["Phi_ID", "Phi_Standard_Label", "Wiki_ID", "Wiki", "JSTOR", "Hiring", "PhD"],
        PHILOSOPHERS,
    )
    variant_rows = ambiguity(VARIANTS)
    write_csv(
        tables / "Variants_table.csv",
        [
            "Phi_ID",
            "Variant_ID",
            "Variant",
            "Variant_origin",
            "Variant_length",
            "Issue_level",
            "Ambiguity",
            "Matching_Phi_IDs",
            "N_Multiple_Phi_IDs",
        ],
        variant_rows,
    )
    write_csv(
        tables / "Wiki_data_table.csv",
        [
            "Wiki_ID",
            "Wiki_label",
            "Wiki_aliases",
            "Wiki_description",
            "Wiki_birthYear",
            "Mult_years",
            "Wiki_surname",
            "Mult_surn",
            "Wiki_firstname",
            "Mult_first",
            "Wiki_gender",
            "Mult_gender",
        ],
        [
            (
                "http://www.wikidata.org/entity/" + q,
                label,
                aliases,
                desc,
                years,
                int("|" in years),
                surn,
                0,
                first,
                int("|" in first),
                gender,
                0,
            )
            for q, label, aliases, desc, years, surn, first, gender in WIKI
        ],
    )
    write_csv(
        tables / "Biographical_data_table.csv",
        ["Phi_ID", "Surname", "First_Name", "Gender", "BirthYear"],
        [
            ("P:2", "Kant", "Immanuel", "male", 1724),
            ("P:3", "Russell", "Bertrand", "male", 1872),
            ("P:4", "Moore", "George", "male", 1873),
            ("P:5", "Moore", "Dorothy", "female", ""),
            ("P:6", "Testwright", "Ada", "female", 1930),
        ],
    )
    write_csv(
        tables / "Institutions_table.csv",
        ["Institution_ID", "Institution"],
        [("I:1", "University of Nowhere")],
    )
    write_csv(
        tables / "PhD_Data_table.csv",
        ["Phi_ID", "PQ_ID", "Title", "PhD_Candidate", "PhD_Year", "Institution_ID"],
        [
            ("P:5", "PQ:1", "An invented dissertation", "Dorothy Moore", 1925, "I:1"),
            (
                "P:6",
                "PQ:2",
                "Another invented dissertation",
                "Ada Testwright",
                1955,
                "I:1",
            ),
        ],
    )
    write_csv(
        tables / "Classifications_table.csv",
        ["Property_ID", "Phi_ID", "Property", "Type", "Source", "Manual"],
        [("C:1", "P:6", "logic", "AOS", "invented", 1)],
    )
    write_csv(
        tables / "Hiring_data_table.csv",
        [
            "Position_ID",
            "Phi_ID",
            "Hire_Name",
            "Institution_ID",
            "Hired_year",
            "Hired_before_1930",
            "Hire_rank",
            "Left_year",
            "Left_after_1980",
            "Highest_rank",
        ],
        [("H:1", "P:6", "Ada Testwright", "I:1", 1960, 0, "Assistant", "", 1, "Full")],
    )
    write_csv(
        tables / "Authorship_table.csv",
        ["Phi_ID", "author_position", "original_JSTOR_author", "Article_ID"],
        [
            (phi, pos, name, STABLE + str(num))
            for _, num, _, _, _, authors, _ in ARTICLES
            for pos, (phi, name) in enumerate(authors, 1)
        ],
    )
    write_csv(
        tables / "Articles_list.csv",
        ["Article_ID"],
        [(STABLE + str(n),) for n in SELECTED],
    )

    by_source = {}
    for art in ARTICLES:
        by_source.setdefault(art[0], []).append(art)
    for source, arts in by_source.items():
        raw = out / "raw" / source
        meta = []
        docs = []
        for _, num, journal, year, subtype, authors, pages in arts:
            aid = STABLE + str(num)
            names = [name for _, name in authors if name]
            creator = "; ".join(names)
            meta.append(
                {
                    "id": aid,
                    "title": f"Invented article {num}",
                    "isPartOf": journal,
                    "publicationYear": year,
                    "docType": "article",
                    "docSubType": subtype,
                    "provider": "jstor",
                    "datePublished": f"{year}-01-01",
                    "issueNumber": "1",
                    "volumeNumber": str(year - 1900),
                    "url": aid,
                    "creator": creator,
                    "publisher": "Invented Press",
                    "language": "eng",
                    "pageStart": 1,
                    "pageEnd": len(pages),
                    "wordCount": sum(len(p.split()) for p in pages),
                    "pageCount": len(pages),
                    "file": f"{source}.jsonl",
                }
            )
            doc = {
                "id": aid,
                "docType": "article",
                "docSubType": subtype,
                "isPartOf": journal,
                "publicationYear": year,
                "language": ["eng"],
                "fullText": raw_pages(journal, pages),
                "pageCount": len(pages),
                "wordCount": sum(len(p.split()) for p in pages),
            }
            # As in the JSTOR deliveries, documents without creators have
            # no creator field.
            if names:
                doc["creator"] = names
            docs.append(doc)
        write_csv(
            raw / "metadata.csv",
            METADATA_COLUMNS,
            [[m.get(c, "") for c in METADATA_COLUMNS] for m in meta],
        )
        lines = "".join(json.dumps(d) + "\n" for d in docs)
        if source == "test_a":
            with gzip.open(raw / "docs.jsonl.gz", "wt", encoding="UTF-8") as f:
                f.write(lines)
        else:
            (raw / "docs.jsonl").write_text(lines, encoding="UTF-8")

    # v1-format mentions, contexts and cleaned full texts. The "cleaned"
    # text is the pages joined by a space; status labels follow v1.
    ref = out / "reference"
    candidates = {v[2]: v[7] for v in variant_rows if v[6] != "Unvalid_variant"}
    authors_of = {STABLE + str(a[1]): {phi for phi, _ in a[5]} for a in ARTICLES}
    mentions, contexts, fulltexts = [], [], []
    for _, num, _, _, _, _, pages in ARTICLES:
        aid = STABLE + str(num)
        text = " ".join(pages)
        fulltexts.append((aid, text, len(text.split()), len(text)))
        for k, (start, ent) in enumerate(find_mentions(text, VARIANTS), 1):
            mid = f"{num}_{k}"
            assoc = candidates[ent]
            ids = assoc.split("|")
            if len(ids) == 1:
                status, mentioned, disamb = "Non_ambiguous", ids[0], assoc
            elif authors_of[aid] & set(ids):
                own = sorted(authors_of[aid] & set(ids))[0]
                status, mentioned, disamb = "Disambiguated_author", own, own
            else:
                status, mentioned, disamb = "Ambiguous", "", assoc
            mentions.append(
                (aid, mid, ent, "PHILOSOPHER", assoc, disamb, status, mentioned)
            )
            end = start + len(ent)
            context = (
                "..."
                + text[max(0, start - CONTEXT_CHARS) : start]
                + ent.upper()
                + text[end : end + CONTEXT_CHARS]
                + "..."
            )
            contexts.append((aid, mid, context))
    write_csv(
        ref / "Mentions_table.csv",
        [
            "Article_ID",
            "Mention_ID",
            "Ent_text",
            "Ent_label",
            "Associated_Phi_IDs",
            "Disambiguated_ID",
            "Disambiguation_status",
            "Mentioned_Phi_ID",
        ],
        mentions,
    )
    write_csv(
        ref / "Mention_context_table.csv",
        ["Article_ID", "Mention_ID", "Mention_context"],
        contexts,
    )
    write_csv(
        ref / "Full_texts_table.csv",
        ["Article_ID", "FullText", "length_words", "length_characters"],
        fulltexts,
    )
    (out / "_SUCCESS").write_text("mini corpus\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
