#!/usr/bin/env python3
"""Write the synthetic French mini-corpus used by ``make CORPUS=test_fr``.

Usage: mini_corpus_fr.py OUT_DIR

The dictionary of the English mini-corpus (``mini_corpus.py``) with a
French layer: French labels of its Wikidata entries, four new Wikidata
philosophers (accents, a ligature, particles), one new JSTOR author. One
source ``test_fr`` (gzip JSONL) of a French journal with two titles. The
texts exercise the ``jstor_fr`` cleaner and the folded matching: running
heads, "M." before a name, an elision ("d'Alembert"), names without their
accents as OCR writes them ("Levinas"), "oe" for "œ", guillemets. All texts
and identifiers are invented.
"""

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mini_corpus  # noqa: E402
from mini_corpus import METADATA_COLUMNS, STABLE, write_csv  # noqa: E402

WD = "http://www.wikidata.org/entity/"

JOURNALS = [
    ("fr1", "Revue inventée", "Rev. Invent.", "Revue inventée de philosophie", 1920)
]
JOURNAL_VARIANTS = [
    ("fr1", "Revue inventée", 1920, 1939),
    ("fr1", "Revue inventée de philosophie", 1946, ""),
]

# Labels and aliases of the layer (format of edhiphy.wikidata_labels).
LABELS = [
    (WD + "Q999999902", "label", "Emmanuel Kant"),
    (WD + "Q999999903", "label", "Bertrand Russell"),
    (WD + "Q999999950", "label", "Emmanuel Lévinas"),
    (WD + "Q999999951", "label", "Paul Ricœur"),
    (WD + "Q999999952", "label", "Jean Le Rond d'Alembert"),
    (WD + "Q999999952", "alias", "D'Alembert"),
    (WD + "Q999999953", "label", "Alexis de Tocqueville"),
]

# New Wikidata philosophers (format of edhiphy.wikidata_philosophers).
NEW_PHILOSOPHERS = [
    ("P:8", "Q999999950", "Emmanuel Lévinas", "Emmanuel Levinas", "philosophe", "Lévinas", "Emmanuel", "male", 1906, 1995),
    ("P:9", "Q999999951", "Paul Ricœur", "Paul Ricœur", "philosophe", "Ricœur", "Paul", "male", 1913, 2005),
    ("P:10", "Q999999952", "Jean Le Rond d'Alembert", "Jean le Rond d'Alembert", "philosophe", "d'Alembert", "Jean", "male", 1717, 1783),
    ("P:11", "Q999999953", "Alexis de Tocqueville", "Alexis de Tocqueville", "penseur", "de Tocqueville", "Alexis", "male", 1805, 1859),
]  # fmt: skip

# New JSTOR author (format of edhiphy.jstor_authors).
NEW_AUTHORS = [("P:12", "Jeanne Testeuse", "JEANNE TESTEUSE", 2)]

JOURNAL = "Revue inventée de philosophie"
HEAD = "REVUE INVENTÉE DE PHILOSOPHIE"

# number, JSTOR title, year, subtype, language, authors [(Phi_ID, JSTOR name)], pages
ARTICLES = [
    (
        900000201,
        "Revue inventée",
        1930,
        "research-article",
        "fre",
        [("P:12", "JEANNE TESTEUSE")],
        [
            f"12 {HEAD} Selon M. Kant, la pensée de l'Encyclopédie doit tout à "
            "d'Alembert ; Tocqueville le cite (cf. p. 12, op. cit.).",
            f"{HEAD} 13 Emmanuel Kant revient : « Lévinas » n'est pas encore né.",
        ],
    ),
    (
        900000202,
        JOURNAL,
        1960,
        "research-article",
        "fre",
        [("P:12", "JEANNE TESTEUSE"), ("P:3", "Bertrand Russell")],
        [
            f"40 {HEAD} Une lecture de Levinas et de Paul Ricoeur, après "
            "E. Kant et la critique.",
            f"{HEAD} 41 Ricœur répond à Levinas ; la quuxplorée pensee reste.",
        ],
    ),
    (
        900000203,
        JOURNAL,
        1961,
        "research-article",
        "eng",
        [("P:1", "")],
        [f"7 {HEAD} An English article in a French journal: Russell on Kant."],
    ),
    (
        900000204,
        JOURNAL,
        1961,
        "book-review",
        "fre",
        [("P:1", "")],
        [f"9 {HEAD} Compte rendu qui nomme Ricœur."],
    ),
]


def main(out: Path) -> None:
    mini_corpus.main(out)
    curated = out / "curated"
    write_csv(
        curated / "tables" / "Journals_fr.csv",
        ["Journal_ID", "Journal_standard_name", "Standard_abbreviation",
         "Journal_name_JSTOR", "Foundation_Year"],
        JOURNALS,
    )  # fmt: skip
    write_csv(
        curated / "tables" / "Journals_fr_variants.csv",
        ["Journal_ID", "Journal_variant", "Starting_date", "Ending_date"],
        JOURNAL_VARIANTS,
    )
    write_csv(
        curated / "wikidata" / "labels_fr.csv",
        ["Wiki_ID", "Queried_Wiki_ID", "lang", "kind", "text"],
        [(w, w, "fr", k, t) for w, k, t in LABELS],
    )
    write_csv(
        curated / "wikidata" / "philosophers_fr.csv",
        ["Phi_ID", "Wiki_ID", "Label_fr", "Label_en", "Description", "Surname",
         "First_name", "Gender", "birthYear", "deathYear"],
        [(p, WD + q, *rest) for p, q, *rest in NEW_PHILOSOPHERS],
    )  # fmt: skip
    write_csv(
        curated / "wikidata" / "dates_fr.csv",
        ["Wiki_ID", "birthYear", "birthUncertain", "birthMult", "deathYear",
         "deathUncertain", "deathMult"],
        [(WD + q, b, 0, 0, d, 0, 0) for _, q, *_, b, d in NEW_PHILOSOPHERS]
        + [(WD + "Q999999902", 1724, 0, 0, 1804, 0, 0)],
    )  # fmt: skip
    write_csv(
        curated / "fr" / "authors_fr.csv",
        ["Phi_ID", "Phi_Standard_Label", "JSTOR_names", "N_articles"],
        NEW_AUTHORS,
    )
    write_csv(
        curated / "fr" / "authorship_fr.csv",
        ["Phi_ID", "author_position", "original_JSTOR_author", "Article_ID"],
        [
            (phi, pos if phi != "P:1" else 0, name, STABLE + str(num))
            for num, _, _, subtype, _, authors, _ in ARTICLES
            if subtype == "research-article"
            for pos, (phi, name) in enumerate(authors, 1)
        ],
    )
    raw = out / "raw" / "test_fr"
    raw.mkdir(parents=True, exist_ok=True)
    meta, docs = [], []
    for num, journal, year, subtype, lang, authors, pages in ARTICLES:
        aid = STABLE + str(num)
        names = [n for _, n in authors if n]
        meta.append(
            {
                "id": aid,
                "title": f"Article inventé {num}",
                "isPartOf": journal,
                "publicationYear": year,
                "docType": "article",
                "docSubType": subtype,
                "provider": "jstor",
                "url": aid,
                "creator": "; ".join(names),
                "language": lang,
                "pageCount": len(pages),
            }
        )
        doc = {
            "id": aid,
            "docType": "article",
            "docSubType": subtype,
            "isPartOf": journal,
            "publicationYear": year,
            "language": [lang],
            "fullText": pages,
        }
        if names:
            doc["creator"] = names
        docs.append(doc)
    write_csv(
        raw / "metadata.csv",
        METADATA_COLUMNS,
        [[m.get(c, "") for c in METADATA_COLUMNS] for m in meta],
    )
    with gzip.open(raw / "docs.jsonl.gz", "wt", encoding="UTF-8") as f:
        f.write("".join(json.dumps(d) + "\n" for d in docs))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
