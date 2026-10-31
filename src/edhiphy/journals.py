"""Stage 3 (journals): the journal registry and the journal of each
selected article.

The registry consists of a journal table (one row per journal, with its
current JSTOR title) and a variant table (earlier JSTOR titles with their
years). An article belongs to the journal whose current title or one of
whose variant titles equals its ``isPartOf`` field. A title shared by two
journals and an article without a match are errors.
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


def title_index(journals: pd.DataFrame, variants: pd.DataFrame) -> pd.Series:
    """Map each JSTOR title to its Journal_ID."""
    titles = pd.concat(
        [
            journals[["Journal_name_JSTOR", "Journal_ID"]].rename(
                columns={"Journal_name_JSTOR": "title"}
            ),
            variants[["Journal_variant", "Journal_ID"]].rename(
                columns={"Journal_variant": "title"}
            ),
        ]
    ).drop_duplicates()
    ambiguous = titles[titles.duplicated("title", keep=False)]
    if len(ambiguous):
        raise SystemExit(
            f"titles of more than one journal: {ambiguous.to_dict('records')}"
        )
    return titles.set_index("title")["Journal_ID"]


def assign_journals(articles: pd.DataFrame, index: pd.Series) -> pd.DataFrame:
    journal_id = articles["isPartOf"].map(index)
    unmatched = articles.loc[journal_id.isna(), "isPartOf"].value_counts()
    if len(unmatched):
        raise SystemExit(
            f"{unmatched.sum()} articles without a journal; titles: {unmatched.to_dict()}"
        )
    return pd.DataFrame(
        {"Article_ID": articles["Article_ID"], "Journal_ID": journal_id.values}
    )


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--articles", required=True)
    p.add_argument("--journals", required=True, help="journal table (CSV)")
    p.add_argument("--variants", required=True, help="journal variant table (CSV)")
    p.add_argument("--out-journals", required=True)
    p.add_argument("--out-variants", required=True)
    p.add_argument("--out-article-journals", required=True)
    args = p.parse_args(argv)
    setup_logging()

    journals = read_curated_csv(args.journals)
    variants = read_curated_csv(args.variants)
    check_unique(journals, ["Journal_ID"], args.journals)
    check_unique(variants, ["Journal_variant"], args.variants)
    articles = read_parquet(args.articles, columns=["Article_ID", "isPartOf"])
    article_journals = assign_journals(articles, title_index(journals, variants))
    log.info(
        "articles per journal: %s",
        article_journals["Journal_ID"].value_counts().sort_index().to_dict(),
    )
    write_parquet(journals, args.out_journals)
    write_parquet(variants, args.out_variants)
    write_parquet(article_journals, args.out_article_journals)


if __name__ == "__main__":
    main()
