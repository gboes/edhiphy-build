"""Stand-in for stages 6-9 (clean, extract, contexts, disambiguate): take
the mentions, mention contexts and cleaned full texts of edhiphy 1.0.

Used while those stages are being ported (corpus setting
``MENTIONS_FROM = v1``), so that the remaining stages can be checked
against the v1 database. Rows are restricted to the selected articles;
every selected article must have a full text.
"""

from edhiphy.common import (
    check_unique,
    log,
    parser,
    read_curated_csv,
    read_parquet,
    setup_logging,
    write_parquet,
)


def restrict(df, articles, what):
    inside = df["Article_ID"].isin(articles)
    if not inside.all():
        log.info("%s: dropping %d rows of unselected articles", what, (~inside).sum())
    return df[inside].reset_index(drop=True)


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--articles", required=True)
    p.add_argument("--mentions", required=True, help="Mentions_table_v1.csv")
    p.add_argument("--contexts", required=True, help="Mention_context_table_v1.csv")
    p.add_argument("--fulltexts", required=True, help="Full_texts_table_v1.csv")
    p.add_argument("--out-mentions", required=True)
    p.add_argument("--out-contexts", required=True)
    p.add_argument("--out-fulltexts", required=True)
    args = p.parse_args(argv)
    setup_logging()

    articles = read_parquet(args.articles, columns=["Article_ID"])["Article_ID"]

    mentions = restrict(read_curated_csv(args.mentions), articles, "mentions")
    check_unique(mentions, ["Mention_ID"], args.mentions)
    contexts = restrict(read_curated_csv(args.contexts), articles, "contexts")
    check_unique(contexts, ["Mention_ID"], args.contexts)
    orphans = set(contexts["Mention_ID"]) - set(mentions["Mention_ID"])
    if orphans:
        raise SystemExit(f"{len(orphans)} contexts without a mention")

    fulltexts = read_curated_csv(args.fulltexts).dropna(subset=["Article_ID"])
    fulltexts = restrict(fulltexts, articles, "full texts")
    check_unique(fulltexts, ["Article_ID"], args.fulltexts)
    missing = set(articles) - set(fulltexts["Article_ID"])
    if missing:
        raise SystemExit(f"{len(missing)} selected articles without a full text")
    fulltexts = fulltexts.drop(
        columns=[c for c in fulltexts.columns if c.startswith("Unnamed:")]
    )

    write_parquet(mentions, args.out_mentions)
    write_parquet(contexts, args.out_contexts)
    write_parquet(fulltexts, args.out_fulltexts)


if __name__ == "__main__":
    main()
