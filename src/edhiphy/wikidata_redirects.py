"""Check the Wikidata entries of the dictionary for redirects and deleted
items (not a pipeline stage).

Reads the Wiki_IDs of a dictionary table (``--wiki``, column ``Wiki_ID``)
and asks the Wikidata SPARQL endpoint, in batches, whether each item
exists (``schema:version``) or redirects to another item
(``owl:sameAs``, the form in which the query service stores merged
items). Redirect chains are followed. ``--out`` gets one row per entry:
``Wiki_ID``, ``Status`` (``ok``, ``redirect``, ``missing``: deleted or
never created; a redirect also has a ``schema:version``) and ``Target_Wiki_ID`` (the item a redirect ends at).
Like ``edhiphy.wikidata_dates``, the output is a curated input: store it
under ``DATA_DIR/curated`` with the retrieval date in the file name.

``--review`` writes a review sheet for ``data/manual/review/``: one row
per philosopher (``--philosophers``, with ``|``-joined Wiki_IDs) that
carries a redirected or missing entry, with the philosophers that already
carry the target and a proposal: ``merge`` into the philosopher that
holds the target (a duplicate, as in issue #14), ``update`` the Wiki_ID
to the target, or ``check`` a missing item. Philosophers already merged
by ``--merges`` are marked; the source flags (JSTOR, Hiring, PhD) show
which entries carry data. The ``Decision`` column is left empty for
the project lead.
"""

import pandas as pd

from edhiphy.common import atomic_output, log, parser, read_curated_csv, setup_logging
from edhiphy.wikidata_dates import PREFIX, bindings

QUERY = """
SELECT ?item ?target ?exists WHERE {
  VALUES ?item { %s }
  OPTIONAL { ?item owl:sameAs ?target . }
  OPTIONAL { ?item schema:version ?version . BIND(true AS ?exists) }
}
"""

MAX_CHAIN = 5


def fetch(qids: list[str], pause: float) -> dict[str, tuple[str, str | None]]:
    """QID -> (status, target QID) for one batch."""
    out = {}
    for b in bindings(QUERY % " ".join(f"wd:{q}" for q in qids), pause):
        qid = b["item"]["value"][len(PREFIX) :]
        # A redirect also has a schema:version.
        if "target" in b:
            out[qid] = ("redirect", b["target"]["value"][len(PREFIX) :])
        elif "exists" in b:
            out.setdefault(qid, ("ok", None))
    return {q: out.get(q, ("missing", None)) for q in qids}


def check(qids: list[str], batch: int, pause: float) -> pd.DataFrame:
    status = {}
    todo = sorted(set(qids))
    for _ in range(MAX_CHAIN):
        for b in range(0, len(todo), batch):
            status.update(fetch(todo[b : b + batch], pause))
            log.info("%d of %d entries checked", min(b + batch, len(todo)), len(todo))
        # Targets of redirects that are not known yet (chains).
        todo = sorted(
            {t for s, t in status.values() if s == "redirect" and t not in status}
        )
        if not todo:
            break

    def final(q):
        for _ in range(MAX_CHAIN):
            s, t = status[q]
            if s != "redirect":
                return q
            q = t
        raise SystemExit(f"redirect chain longer than {MAX_CHAIN} from {q}")

    rows = []
    for q in sorted(set(qids)):
        s, _ = status[q]
        target = final(q) if s == "redirect" else None
        rows.append(
            {
                "Wiki_ID": PREFIX + q,
                "Status": s,
                "Target_Wiki_ID": PREFIX + target if target else None,
            }
        )
    return pd.DataFrame(rows)


def review(
    status: pd.DataFrame, philosophers: pd.DataFrame, merges: pd.DataFrame
) -> pd.DataFrame:
    """One row per philosopher and redirected or missing Wiki_ID."""
    flags = [c for c in ["JSTOR", "Hiring", "PhD"] if c in philosophers]
    links = (
        philosophers[["Phi_ID", "Phi_Standard_Label", "Wiki_ID", *flags]]
        .dropna(subset=["Wiki_ID"])
        .assign(Wiki_ID=lambda d: d["Wiki_ID"].str.split("|"))
        .explode("Wiki_ID")
    )
    holders = links.groupby("Wiki_ID")["Phi_ID"].agg(lambda s: "|".join(sorted(s)))
    bad = status[status["Status"] != "ok"]
    out = links.merge(bad, on="Wiki_ID")
    merged = dict(zip(merges["Merged_Phi_ID"], merges["Phi_ID"]))
    out["Target_Phi_IDs"] = out["Target_Wiki_ID"].map(holders)
    out["Merged_into"] = out["Phi_ID"].map(merged)

    def proposal(r):
        if r["Status"] == "missing":
            return "check"
        if pd.notna(r["Target_Phi_IDs"]):
            return "merge"
        return "update"

    out["Proposal"] = out.apply(proposal, axis=1)
    out["Decision"] = None
    return out.sort_values(["Proposal", "Phi_Standard_Label", "Phi_ID"])[
        [
            "Phi_ID",
            "Phi_Standard_Label",
            "Wiki_ID",
            "Status",
            "Target_Wiki_ID",
            "Target_Phi_IDs",
            "Merged_into",
            *flags,
            "Proposal",
            "Decision",
        ]
    ]


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--wiki", help="CSV with a Wiki_ID column")
    p.add_argument("--batch", type=int, default=400)
    p.add_argument("--pause", type=float, default=1.0, help="seconds between batches")
    p.add_argument("--status", help="reuse a status CSV instead of querying")
    p.add_argument("--out", help="status CSV")
    p.add_argument("--philosophers", help="philosophers CSV (for --review)")
    p.add_argument("--merges", help="philosopher_merges.csv (for --review)")
    p.add_argument("--review", help="review CSV")
    args = p.parse_args(argv)
    setup_logging()
    if args.status:
        status = read_curated_csv(args.status)
    elif not args.wiki:
        raise SystemExit("give --wiki or --status")
    else:
        ids = read_curated_csv(args.wiki, usecols=["Wiki_ID"])["Wiki_ID"].dropna()
        qids = [i[len(PREFIX) :] for i in ids if i.startswith(PREFIX)]
        status = check(qids, args.batch, args.pause)
    log.info("entries: %s", status["Status"].value_counts().to_dict())
    if args.out:
        with atomic_output(args.out) as tmp:
            status.to_csv(tmp, index=False)
    if args.review:
        if not args.philosophers:
            raise SystemExit("--review needs --philosophers")
        merges = (
            read_curated_csv(args.merges)
            if args.merges
            else pd.DataFrame(columns=["Merged_Phi_ID", "Phi_ID"])
        )
        sheet = review(status, read_curated_csv(args.philosophers), merges)
        log.info("review: %s", sheet["Proposal"].value_counts().to_dict())
        with atomic_output(args.review) as tmp:
            sheet.to_csv(tmp, index=False)


if __name__ == "__main__":
    main()
