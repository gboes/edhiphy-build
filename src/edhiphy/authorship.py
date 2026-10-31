"""Stage 5 (authorship): authors of the selected articles.

English corpus: the frozen v1 authorship table (one row per article and
author, ``author_position`` from 1). Every selected article must have at
least one row; articles without a known author carry ``P:1``
(``[No Author]``) in v1. Also derives the per-article columns of
``JSTOR_Article``: ``Authors_Phi_ID`` (Phi_IDs in author order, joined by
``;``) and ``N_authors``. Philosophers merged by the dictionary stage
(``--merges``) are replaced by their targets.
"""

import pandas as pd

from edhiphy.common import (
    check_unique,
    log,
    parser,
    read_curated_csv,
    read_parquet,
    setup_logging,
    write_parquet,
)


def article_authors(authorship: pd.DataFrame) -> pd.DataFrame:
    ordered = authorship.sort_values(["Article_ID", "author_position"], kind="stable")
    grouped = ordered.groupby("Article_ID", sort=True)["Phi_ID"]
    return pd.DataFrame(
        {"Authors_Phi_ID": grouped.agg(";".join), "N_authors": grouped.size()}
    ).reset_index()


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--articles", required=True)
    p.add_argument("--authorship", required=True, help="frozen authorship table (CSV)")
    p.add_argument("--merges", help="merges.parquet of the dictionary stage")
    p.add_argument("--out", required=True)
    p.add_argument("--out-article-authors", required=True)
    args = p.parse_args(argv)
    setup_logging()

    articles = read_parquet(args.articles, columns=["Article_ID"])["Article_ID"]
    authorship = read_curated_csv(args.authorship)
    check_unique(authorship, ["Article_ID", "Phi_ID"], args.authorship)
    authorship = authorship[authorship["Article_ID"].isin(articles)]
    if args.merges:
        merges = read_parquet(args.merges)
        target = dict(zip(merges["Merged_Phi_ID"], merges["Phi_ID"]))
        merged = authorship["Phi_ID"].isin(target)
        authorship = authorship.assign(Phi_ID=authorship["Phi_ID"].replace(target))
        check_unique(authorship, ["Article_ID", "Phi_ID"], "authorship after merges")
        log.info("%d authorship rows of merged philosophers reassigned", merged.sum())
    missing = sorted(set(articles) - set(authorship["Article_ID"]))
    if missing:
        raise SystemExit(
            f"{len(missing)} articles without authorship, e.g. {missing[:5]}"
        )
    log.info("%d authorship rows for %d articles", len(authorship), len(articles))
    write_parquet(authorship.reset_index(drop=True), args.out)
    write_parquet(article_authors(authorship), args.out_article_authors)


if __name__ == "__main__":
    main()
