"""Stage 2 (select): choose the articles of a corpus from the metadata of
its sources.

Filters, combined by conjunction: an explicit article list (``--ids``, a
CSV with an ``Article_ID`` column; used for the English v1 corpus), and
document subtypes (``--doc-subtype``). Every listed ID must occur in the
sources. Output: the metadata rows of the selected articles, sorted by
``Article_ID``.
"""

import pandas as pd

from edhiphy.common import (
    check_unique,
    log,
    parser,
    read_parquet,
    setup_logging,
    write_parquet,
)


def select(metadata: pd.DataFrame, ids=None, doc_subtypes=None) -> pd.DataFrame:
    keep = pd.Series(True, index=metadata.index)
    if ids is not None:
        missing = sorted(set(ids) - set(metadata["Article_ID"]))
        if missing:
            raise SystemExit(
                f"{len(missing)} listed articles not in the sources, e.g. {missing[:5]}"
            )
        keep &= metadata["Article_ID"].isin(ids)
    if doc_subtypes:
        keep &= metadata["docSubType"].isin(doc_subtypes)
    out = metadata[keep].sort_values("Article_ID", kind="stable")
    return out.reset_index(drop=True)


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--metadata", nargs="+", required=True, help="per-source parquet")
    p.add_argument("--ids", help="CSV with an Article_ID column")
    p.add_argument("--doc-subtype", action="append", dest="doc_subtypes")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    setup_logging()

    metadata = pd.concat([read_parquet(f) for f in args.metadata], ignore_index=True)
    check_unique(metadata, ["Article_ID"], "metadata of all sources")
    ids = None
    if args.ids:
        ids = pd.read_csv(args.ids, usecols=["Article_ID"], dtype=str)["Article_ID"]
        check_unique(ids.to_frame(), ["Article_ID"], args.ids)
    selected = select(metadata, ids, args.doc_subtypes)
    log.info("selected %d of %d articles", len(selected), len(metadata))
    write_parquet(selected, args.out)


if __name__ == "__main__":
    main()
