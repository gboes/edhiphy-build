"""Fetch labels and aliases of Wikidata entries in given languages (not a
pipeline stage).

Reads the Wiki_IDs of a dictionary table (``--wiki``, column ``Wiki_ID``)
and queries the Wikidata SPARQL endpoint in batches for ``rdfs:label``
and ``skos:altLabel`` in the languages of ``--langs`` (e.g. ``fr``).
Redirected entries have no labels of their own; with ``--redirects`` (the
status CSV of ``edhiphy.wikidata_redirects``) their target is queried
instead. One row per text: ``Wiki_ID`` (the dictionary's entry),
``Queried_Wiki_ID`` (the item the text comes from), ``lang``, ``kind``
(``label``, ``alias``), ``text``.

The output is a curated input for the dictionary layer of a language
(phase 5): store it under ``DATA_DIR/curated`` with the retrieval date in
the file name and add it to ``data/MANIFEST.sha256``.
"""

import pandas as pd

from edhiphy.common import atomic_output, log, parser, read_curated_csv, setup_logging
from edhiphy.wikidata_dates import PREFIX, bindings

QUERY = """
SELECT ?item ?kind ?text WHERE {
  VALUES ?item { %s }
  { ?item rdfs:label ?text . BIND("label" AS ?kind) }
  UNION
  { ?item skos:altLabel ?text . BIND("alias" AS ?kind) }
  FILTER(LANG(?text) IN (%s))
}
"""

COLUMNS = ["Wiki_ID", "Queried_Wiki_ID", "lang", "kind", "text"]


def fetch(qids: list[str], langs: list[str], pause: float) -> list[dict]:
    query = QUERY % (
        " ".join(f"wd:{q}" for q in qids),
        ", ".join(f'"{lang}"' for lang in langs),
    )
    return [
        {
            "Queried_Wiki_ID": b["item"]["value"],
            "lang": b["text"]["xml:lang"],
            "kind": b["kind"]["value"],
            "text": b["text"]["value"],
        }
        for b in bindings(query, pause)
    ]


def queried_ids(wiki_ids: list[str], redirects: pd.DataFrame | None) -> dict:
    """Dictionary Wiki_ID -> Wiki_ID to query (the target of a redirect)."""
    target = {}
    if redirects is not None:
        r = redirects[redirects["Status"] == "redirect"]
        target = dict(zip(r["Wiki_ID"], r["Target_Wiki_ID"]))
    return {w: target.get(w, w) for w in wiki_ids}


def labels(
    wiki_ids: list[str], langs: list[str], redirects, batch: int, pause: float
) -> pd.DataFrame:
    query_of = queried_ids(wiki_ids, redirects)
    qids = sorted({q[len(PREFIX) :] for q in query_of.values()})
    rows = []
    for b in range(0, len(qids), batch):
        rows += fetch(qids[b : b + batch], langs, pause)
        log.info("%d of %d entries queried", min(b + batch, len(qids)), len(qids))
    found = pd.DataFrame(rows, columns=COLUMNS[1:])
    keys = pd.DataFrame(
        {"Wiki_ID": list(query_of), "Queried_Wiki_ID": list(query_of.values())}
    )
    out = keys.merge(found, on="Queried_Wiki_ID").drop_duplicates()
    return out.sort_values(COLUMNS).reset_index(drop=True)[COLUMNS]


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--wiki", required=True, help="CSV with a Wiki_ID column")
    p.add_argument("--langs", required=True, help="comma-separated, e.g. fr")
    p.add_argument("--redirects", help="status CSV of edhiphy.wikidata_redirects")
    p.add_argument("--batch", type=int, default=400)
    p.add_argument("--pause", type=float, default=1.0, help="seconds between batches")
    p.add_argument("--out", required=True, help="CSV")
    args = p.parse_args(argv)
    setup_logging()
    ids = read_curated_csv(args.wiki, usecols=["Wiki_ID"])["Wiki_ID"].dropna()
    ids = sorted({i for i in ids if i.startswith(PREFIX)})
    redirects = read_curated_csv(args.redirects) if args.redirects else None
    out = labels(ids, args.langs.split(","), redirects, args.batch, args.pause)
    for (lang, kind), n in out.groupby(["lang", "kind"]).size().items():
        log.info("%s %s: %d texts", lang, kind, n)
    log.info("%d of %d entries have a text", out["Wiki_ID"].nunique(), len(ids))
    with atomic_output(args.out) as tmp:
        out.to_csv(tmp, index=False)


if __name__ == "__main__":
    main()
