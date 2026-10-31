"""Find philosophers of a language area on Wikidata that the dictionary
lacks (not a pipeline stage).

Candidates: humans (P31 Q5) with an occupation (P106) that is philosopher
(Q4964182) or one of its subclasses, and either a citizenship (P27) in
``--countries`` or a language spoken or written (P1412, P6886) in
``--languages``. Entries already in the dictionary (``--exclude``: CSVs
with a ``Wiki_ID`` column, values may be ``|``-separated, plus the
targets of a redirect status CSV with ``--redirects``) are left out, and
so are entries born in or after ``--born-before`` and entries without a
French or English label; entries without a birth year are kept only if
they have a death year.

The kept entries get new Phi_IDs after the largest one in ``--after``
(CSVs with a ``Phi_ID`` column: the v1 philosophers and any earlier
layer), in QID order, so that the IDs are deterministic and do not collide
with other layers. Outputs, all curated inputs of the dictionary stage
(store them under ``DATA_DIR/curated/wikidata`` with the retrieval date
and add them to ``data/MANIFEST.sha256``):

- ``--out``: one row per philosopher: ``Phi_ID``, ``Wiki_ID``, labels
  (``Label_fr``, ``Label_en``), ``Description``, ``Surname`` and
  ``First_name`` (labels of P734 and P735, ``|``-separated), ``Gender``,
  ``birthYear``, ``deathYear``;
- ``--out-dates``: their life dates in the format of
  ``edhiphy.wikidata_dates``;
- ``--out-labels``: their labels and aliases in ``--label-langs`` in the
  format of ``edhiphy.wikidata_labels``.
"""

import pandas as pd

from edhiphy import wikidata_dates, wikidata_labels
from edhiphy.common import atomic_output, log, parser, read_curated_csv, setup_logging
from edhiphy.wikidata_dates import PREFIX, bindings

PHILOSOPHER = "Q4964182"
# France and its earlier states (Kingdom of France, First Republic, First
# and Second Empire, Third and Fourth Republic), Belgium, Switzerland,
# Canada.
COUNTRIES = "Q142,Q70972,Q58296,Q71084,Q71092,Q70802,Q69829,Q31,Q39,Q16"
LANGUAGES = "Q150"

OCCUPATIONS = "SELECT DISTINCT ?occ WHERE { ?occ wdt:P279* wd:%s }"
# One query per occupation and condition: the union over all occupations
# times out on the public endpoint.
CANDIDATES = """
SELECT DISTINCT ?item WHERE {
  ?item wdt:P106 wd:%s ; %s ?v ; wdt:P31 wd:Q5 .
  VALUES ?v { %s }
}
"""
DETAILS = """
SELECT ?item ?label_fr ?label_en ?desc_fr ?desc_en ?gender ?surname ?first ?ord
WHERE {
  VALUES ?item { %s }
  OPTIONAL { ?item rdfs:label ?label_fr FILTER(LANG(?label_fr) = "fr") }
  OPTIONAL { ?item rdfs:label ?label_en FILTER(LANG(?label_en) = "en") }
  OPTIONAL { ?item schema:description ?desc_fr FILTER(LANG(?desc_fr) = "fr") }
  OPTIONAL { ?item schema:description ?desc_en FILTER(LANG(?desc_en) = "en") }
  OPTIONAL { ?item wdt:P21/rdfs:label ?gender FILTER(LANG(?gender) = "en") }
  OPTIONAL { ?item wdt:P734 ?s . ?s rdfs:label ?surname
             FILTER(LANG(?surname) IN ("fr", "mul", "en")) }
  OPTIONAL { ?item p:P735 ?g . ?g ps:P735 ?gn . ?gn rdfs:label ?first
             FILTER(LANG(?first) IN ("fr", "mul", "en"))
             OPTIONAL { ?g pq:P1545 ?ord } }
}
"""
COLUMNS = [
    "Phi_ID",
    "Wiki_ID",
    "Label_fr",
    "Label_en",
    "Description",
    "Surname",
    "First_name",
    "Gender",
    "birthYear",
    "deathYear",
]


def qid(uri: str) -> str:
    return uri[len(PREFIX) :]


def values(ids) -> str:
    return " ".join(f"wd:{i}" for i in ids)


def occupations(pause: float) -> list[str]:
    rows = bindings(OCCUPATIONS % PHILOSOPHER, pause)
    return sorted({qid(b["occ"]["value"]) for b in rows})


def candidates(occs, countries, languages, pause: float) -> list[str]:
    found = set()
    conditions = [
        ("wdt:P27", countries),
        ("wdt:P1412", languages),
        ("wdt:P6886", languages),
    ]
    for i, occ in enumerate(occs, 1):
        for prop, vals in conditions:
            query = CANDIDATES % (occ, prop, values(vals))
            found |= {qid(r["item"]["value"]) for r in bindings(query, pause)}
        log.info(
            "occupation %d of %d (%s): %d candidates", i, len(occs), occ, len(found)
        )
    return sorted(found, key=lambda q: int(q[1:]))


def details(ids, batch: int, pause: float) -> pd.DataFrame:
    rows = []
    for b in range(0, len(ids), batch):
        chunk = ids[b : b + batch]
        by_item = {}
        for r in bindings(DETAILS % values(chunk), pause):
            by_item.setdefault(qid(r["item"]["value"]), []).append(r)
        for q in chunk:
            rs = by_item.get(q, [])

            def one(key):
                vs = sorted({r[key]["value"] for r in rs if key in r})
                return vs[0] if vs else None

            surnames = sorted({r["surname"]["value"] for r in rs if "surname" in r})
            firsts = {}
            for r in rs:
                if "first" in r:
                    o = int(r["ord"]["value"]) if "ord" in r else 99
                    v = r["first"]["value"]
                    firsts[v] = min(o, firsts.get(v, 99))
            rows.append(
                {
                    "Wiki_ID": PREFIX + q,
                    "Label_fr": one("label_fr"),
                    "Label_en": one("label_en"),
                    "Description": one("desc_fr") or one("desc_en"),
                    "Surname": "|".join(surnames) or None,
                    "First_name": "|".join(sorted(firsts, key=lambda v: (firsts[v], v)))
                    or None,
                    "Gender": one("gender"),
                }
            )
        log.info("details %d of %d", min(b + batch, len(ids)), len(ids))
    return pd.DataFrame(rows)


def excluded(paths, redirects) -> set[str]:
    out = set()
    for path in paths:
        ids = read_curated_csv(path, usecols=["Wiki_ID"])["Wiki_ID"].dropna()
        out |= {w for v in ids for w in str(v).split("|")}
    if redirects:
        r = read_curated_csv(redirects)
        out |= set(r["Target_Wiki_ID"].dropna())
    return {qid(w) for w in out if w.startswith(PREFIX)}


def max_phi_id(paths) -> int:
    ids = pd.concat([read_curated_csv(p, usecols=["Phi_ID"])["Phi_ID"] for p in paths])
    return int(ids.str.removeprefix("P:").astype(int).max())


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--countries", default=COUNTRIES, help="comma-separated QIDs")
    p.add_argument("--languages", default=LANGUAGES, help="comma-separated QIDs")
    p.add_argument("--born-before", type=int, default=1960)
    p.add_argument("--exclude", nargs="+", required=True, help="CSVs with Wiki_ID")
    p.add_argument("--redirects", help="status CSV of edhiphy.wikidata_redirects")
    p.add_argument("--after", nargs="+", required=True, help="CSVs with Phi_ID")
    p.add_argument("--label-langs", default="fr")
    p.add_argument("--batch", type=int, default=200)
    p.add_argument("--pause", type=float, default=1.0)
    p.add_argument("--out", required=True)
    p.add_argument("--out-dates", required=True)
    p.add_argument("--out-labels", required=True)
    args = p.parse_args(argv)
    setup_logging()

    occs = occupations(args.pause)
    log.info("%d occupations under %s", len(occs), PHILOSOPHER)
    cands = candidates(
        occs,
        args.countries.split(","),
        args.languages.split(","),
        args.pause,
    )
    known = excluded(args.exclude, args.redirects)
    new = [q for q in cands if q not in known]
    log.info("%d candidates, %d not in the dictionary", len(cands), len(new))

    rows = []
    for b in range(0, len(new), 400):
        rows += wikidata_dates.fetch(new[b : b + 400], args.pause)
    dates = wikidata_dates.normalise(rows, [PREFIX + q for q in new])
    keep = (dates["birthYear"] < args.born_before) | (
        dates["birthYear"].isna() & dates["deathYear"].notna()
    )
    dates = dates[keep.fillna(False)].reset_index(drop=True)
    log.info(
        "%d born before %d (or undated birth, dated death)",
        len(dates),
        args.born_before,
    )

    ids = [qid(w) for w in dates["Wiki_ID"]]
    out = details(ids, args.batch, args.pause)
    # Entries without a French or English label have no usable name.
    out = out[out["Label_fr"].notna() | out["Label_en"].notna()].reset_index(drop=True)
    dates = dates[dates["Wiki_ID"].isin(out["Wiki_ID"])].reset_index(drop=True)
    log.info("%d with a French or English label", len(out))
    start = max_phi_id(args.after) + 1
    out.insert(0, "Phi_ID", [f"P:{start + i}" for i in range(len(out))])
    out = out.merge(dates[["Wiki_ID", "birthYear", "deathYear"]], on="Wiki_ID")
    out = out[COLUMNS]
    log.info("new Phi_IDs P:%d to P:%d", start, start + len(out) - 1)
    labels = wikidata_labels.labels(
        list(out["Wiki_ID"]), args.label_langs.split(","), None, 400, args.pause
    )
    for path, df in (
        (args.out, out),
        (args.out_dates, dates),
        (args.out_labels, labels),
    ):
        with atomic_output(path) as tmp:
            df.to_csv(tmp, index=False)
        log.info("wrote %s (%d rows)", path, len(df))


if __name__ == "__main__":
    main()
