"""Fetch birth and death years of Wikidata entries (not a pipeline stage).

Reads the Wiki_IDs of a dictionary table (``--wiki``, column ``Wiki_ID``),
queries the Wikidata SPARQL endpoint for the statements of P569 (date of
birth) and P570 (date of death) in batches, and writes one row per entry:
``Wiki_ID``, ``birthYear``, ``birthUncertain``, ``birthMult``,
``deathYear``, ``deathUncertain``, ``deathMult``.

Years are integers in historical numbering: 535 BC is -535, there is no
year 0 (the RDF export writes 535 BC as -534, XSD 1.1). A year is
uncertain (flag 1) if the statement is qualified as circa (P1480 =
Q5727902), or if only a range is known: a date less precise than a year
(decade, century, millennium) or a statement with earliest/latest date
qualifiers (P1319, P1326); the year is then the midpoint of the range,
rounded half up. Statements with preferred rank win over normal ones,
deprecated ones are ignored; among several, a certain year wins over an
uncertain one, then the earliest year; ``*Mult`` is 1 if the kept
statements give different years. Formatting for display:
``edhiphy.life_dates``.

The output is a curated input: store it under ``DATA_DIR/curated`` with
the retrieval date in the file name and add it to ``data/MANIFEST.sha256``,
so that builds do not depend on the live endpoint.
"""

import json
import math
import time
import urllib.parse
import urllib.request

import pandas as pd

from edhiphy import __version__
from edhiphy.common import atomic_output, log, parser, read_curated_csv, setup_logging

ENDPOINT = "https://query.wikidata.org/sparql"
PREFIX = "http://www.wikidata.org/entity/"
QUERY = """
SELECT ?item ?kind ?st ?rank ?t ?precision ?circa ?early ?late WHERE {
  VALUES ?item { %s }
  VALUES (?kind ?prop ?value) {
    ("birth" p:P569 psv:P569) ("death" p:P570 psv:P570)
  }
  ?item ?prop ?st .
  ?st ?value ?node ; wikibase:rank ?rank .
  ?node wikibase:timeValue ?t ; wikibase:timePrecision ?precision .
  FILTER(?rank != wikibase:DeprecatedRank)
  OPTIONAL { ?st pq:P1480 wd:Q5727902 . BIND(true AS ?circa) }
  OPTIONAL { ?st pqv:P1319/wikibase:timeValue ?early }
  OPTIONAL { ?st pqv:P1326/wikibase:timeValue ?late }
}
"""
# wikibase:timePrecision: 6 millennium, 7 century, 8 decade, 9 year.
SPAN = {6: 1000, 7: 100, 8: 10}


def rdf_year(value: str) -> int:
    """Historical year of an xsd:dateTime literal ("-0534-01-01T00:00:00Z"
    is 535 BC)."""
    y = int(value[: value.index("-", 1)])
    return y if y > 0 else y - 1


def midpoint(a: int, b: int) -> int:
    return math.floor((a + b) / 2 + 0.5)


def year_range(y: int, precision: int) -> tuple[int, int]:
    """First and last historical year of the decade, century or
    millennium of year ``y`` (centuries as displayed by Wikidata: 1801-1900
    are the 19th century; 500 BC is in the 5th century BC)."""
    n = SPAN[precision]
    if precision == 8:
        first = abs(y) // 10 * 10
        last = first + 9
    else:
        k = math.ceil(abs(y) / n)
        first, last = (k - 1) * n + 1, k * n
    return (first, last) if y > 0 else (-last, -first)


def statement_year(s: dict) -> tuple[int, int] | None:
    """(year, uncertain) of one statement, or None if it gives no year."""
    if s.get("early") and s.get("late"):
        return midpoint(rdf_year(s["early"]), rdf_year(s["late"])), 1
    y, precision = rdf_year(s["t"]), s["precision"]
    if precision >= 9:
        return y, int(bool(s.get("circa")))
    if precision in SPAN:
        return midpoint(*year_range(y, precision)), 1
    return None


def choose(statements: list[dict]) -> tuple:
    """(year, uncertain, mult) from the statements of one entry and kind."""
    preferred = [s for s in statements if s["rank"].endswith("PreferredRank")]
    years = [statement_year(s) for s in (preferred or statements)]
    years = sorted({y for y in years if y is not None}, key=lambda t: (t[1], t[0]))
    if not years:
        return None, None, None
    year, uncertain = years[0]
    return year, uncertain, int(len({y for y, _ in years}) > 1)


def bindings(query: str, pause: float) -> list[dict]:
    """Result bindings of a query to the Wikidata SPARQL endpoint, with
    retries; waits ``pause`` seconds after a successful request."""
    data = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    request = urllib.request.Request(
        ENDPOINT,
        data=data,
        headers={
            "Accept": "application/sparql-results+json",
            "User-Agent": f"edhiphy-build/{__version__} (research; Tilburg University)",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=120) as r:
                rows = json.load(r)["results"]["bindings"]
            time.sleep(pause)
            return rows
        except Exception as e:  # network errors and 429: back off and retry
            log.warning("batch failed (%s), retry %d", e, attempt + 1)
            time.sleep(30 * (attempt + 1))
    raise SystemExit("Wikidata endpoint unavailable")


def fetch(qids: list[str], pause: float) -> list[dict]:
    rows = bindings(QUERY % " ".join(f"wd:{q}" for q in qids), pause)
    return [
        {
            "Wiki_ID": b["item"]["value"],
            "kind": b["kind"]["value"],
            "st": b["st"]["value"],
            "rank": b["rank"]["value"],
            "t": b["t"]["value"],
            "precision": int(b["precision"]["value"]),
            "circa": "circa" in b,
            "early": b.get("early", {}).get("value"),
            "late": b.get("late", {}).get("value"),
        }
        for b in rows
    ]


def normalise(rows: list[dict], wiki_ids: list[str]) -> pd.DataFrame:
    by_entry = {}
    for r in rows:
        # One record per statement (qualifiers can multiply the bindings).
        by_entry.setdefault((r["Wiki_ID"], r["kind"]), {})[r["st"]] = r
    out = pd.DataFrame({"Wiki_ID": wiki_ids})
    for kind in ("birth", "death"):
        values = [choose(list(by_entry.get((w, kind), {}).values())) for w in wiki_ids]
        for i, name in enumerate(("Year", "Uncertain", "Mult")):
            out[kind + name] = pd.array([v[i] for v in values], dtype="Int64")
    return out


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--wiki", required=True, help="CSV with a Wiki_ID column")
    p.add_argument("--batch", type=int, default=400)
    p.add_argument("--pause", type=float, default=1.0, help="seconds between batches")
    p.add_argument("--out", required=True, help="CSV")
    args = p.parse_args(argv)
    setup_logging()
    ids = read_curated_csv(args.wiki, usecols=["Wiki_ID"])["Wiki_ID"].dropna()
    qids = sorted({i[len(PREFIX) :] for i in ids if i.startswith(PREFIX)})
    rows = []
    for b in range(0, len(qids), args.batch):
        rows += fetch(qids[b : b + args.batch], args.pause)
        log.info("%d of %d entries queried", min(b + args.batch, len(qids)), len(qids))
    out = normalise(rows, [PREFIX + q for q in qids])
    log.info(
        "%d entries: birth year %d (%d uncertain), death year %d (%d uncertain)",
        len(out),
        out["birthYear"].notna().sum(),
        (out["birthUncertain"] == 1).sum(),
        out["deathYear"].notna().sum(),
        (out["deathUncertain"] == 1).sum(),
    )
    with atomic_output(args.out) as tmp:
        out.to_csv(tmp, index=False)


if __name__ == "__main__":
    main()
