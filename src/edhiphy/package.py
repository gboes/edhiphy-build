"""Stage 10 (package): write the research database (all tables, including
``Full_Text``) with ``Build_Info`` and ``PRAGMA user_version``.

Ported from the v1 ``build_database.py``: the same schema, the same
column renames, and the same split of multi-valued columns into
subsidiary tables (e.g. ``Mention.Associated_Phi_IDs`` into
``Mention_Associated``). ``JSTOR_Article`` is assembled here from the
selected metadata, the authorship summary and the journal assignment.
``Mention_Web_ID`` maps each Mention_ID to the one of the web export
(``<JSTOR number>_<page>_<k>``, k = order of the mention on its page).
The statistics tables (``Philosopher_Statistics``, ``Article_Statistics``,
``Journal_Statistics``, ``Institution_Statistics``; web issue #8) are
computed from the loaded tables. ``Article_Similarity`` and
``Author_Similarity`` hold the neighbour lists
of the similarity stage. ``Philosopher_Merged`` and ``Philosopher_Life_Dates``
come from the dictionary stage; curated tables keyed by Phi_ID (PhD,
classifications, hiring) are mapped through the merges.
"""

import re
import urllib.parse
from types import MappingProxyType

import pandas as pd
import sqlalchemy

from edhiphy import build_info
from edhiphy.common import (
    atomic_output,
    log,
    parser,
    read_curated_csv,
    read_parquet,
    setup_logging,
)
from edhiphy.schema import (
    Article_Similarity,
    Article_Statistics,
    Author_Similarity,
    Biography,
    Classification,
    Full_Text,
    Hire_Position,
    Institution,
    Institution_Statistics,
    JSTOR_Article,
    JSTOR_Authorship,
    Journal,
    Journal_Statistics,
    Journal_Variant,
    Mention,
    Mention_associated,
    Mention_context,
    Mention_disambiguated,
    Mention_Web_ID,
    PhD_Dissertation,
    Philosopher,
    Philosopher_Life_Dates,
    Philosopher_Merged,
    Philosopher_Statistics,
    Philosopher_Wiki_ID,
    Variant,
    Variant_Matching_Phi_ID,
    Wiki_Entry,
    Wiki_Entry_alias,
    Wiki_Entry_birthYear,
    Wiki_Entry_firstname,
    Wiki_Entry_gender,
    Wiki_Entry_surname,
    metadata,
    virtual_tables,
)

# Input columns renamed in the database.
COLUMN_RENAME = {
    Mention.name: {"Article_ID": Mention.c.Mentioning_Article_ID.name},
    Mention_context.name: {"Article_ID": Mention_context.c.Mentioning_Article_ID.name},
    Article_Similarity.name: {"method": "Method", "rank": "Rank", "cosine": "Cosine"},
    Author_Similarity.name: {"method": "Method", "rank": "Rank", "cosine": "Cosine"},
}

# Multi-valued input columns, split into subsidiary tables. Keyed on table
# name; each entry maps an input column to the column of the destination
# table that receives one row per value.
COLUMN_SPLIT = {
    Philosopher.name: {"Wiki_ID": Philosopher_Wiki_ID.c.Wiki_ID},
    Variant.name: {"Matching_Phi_IDs": Variant_Matching_Phi_ID.c.Phi_ID},
    Mention.name: {
        "Associated_Phi_IDs": Mention_associated.c.Phi_ID,
        "Disambiguated_ID": Mention_disambiguated.c.Phi_ID,
    },
    Wiki_Entry.name: {
        "Wiki_aliases": Wiki_Entry_alias.c.alias,
        "Wiki_birthYear": Wiki_Entry_birthYear.c.birthYear,
        "Wiki_surname": Wiki_Entry_surname.c.surname,
        "Wiki_firstname": Wiki_Entry_firstname.c.firstname,
        "Wiki_gender": Wiki_Entry_gender.c.gender,
    },
}

# Separators of the multi-valued columns (pandas str.split), default "|".
SPLIT_SEPARATOR = {Wiki_Entry.name: {"Wiki_aliases": r"\s*,\s*"}}

EMPTY = MappingProxyType({})

CHUNKSIZE = 50_000

PIPELINE_MENTION_ID = re.compile(r"^(\d+)_(\d+)_(\d+)$")


def web_mention_ids(mention_ids: pd.Series) -> pd.DataFrame:
    """Mention_ID -> Web_Mention_ID: the raw offset of
    ``<JSTOR number>_<page>_<offset>`` replaced by the rank of the offset
    on its page (1-based). Mentions imported from v1 (``<JSTOR
    number>_<n>``) carry no offset and keep their ID."""
    parts = mention_ids.str.extract(PIPELINE_MENTION_ID)
    matched = parts[0].notna()
    if not matched.any():
        log.info("\tMention_IDs without offsets: web IDs unchanged")
        return pd.DataFrame({"Mention_ID": mention_ids, "Web_Mention_ID": mention_ids})
    if not matched.all():
        bad = mention_ids[~matched].iloc[0]
        raise SystemExit(
            f"{(~matched).sum()} Mention_IDs of another form, e.g. {bad!r}"
        )
    offset = parts[2].astype("int64")
    k = offset.groupby([parts[0], parts[1]]).rank(method="first").astype("int64")
    return pd.DataFrame(
        {
            "Mention_ID": mention_ids,
            "Web_Mention_ID": parts[0] + "_" + parts[1] + "_" + k.astype(str),
        }
    )


# Statistics tables, computed in SQL from the loaded tables. Resolved
# mentions have a Mentioned_Phi_ID; ambiguous ones list their candidates in
# Mention_Associated.
STATISTICS = [
    (
        Philosopher_Statistics,
        """
        WITH m AS (
            SELECT Mentioned_Phi_ID AS Phi_ID, count(*) AS n,
                count(DISTINCT Mentioning_Article_ID) AS n_articles,
                min(a.publicationYear) AS first, max(a.publicationYear) AS last
            FROM Mention JOIN JSTOR_Article a ON a.Article_ID = Mentioning_Article_ID
            WHERE Mentioned_Phi_ID IS NOT NULL GROUP BY 1
        ), amb AS (
            SELECT x.Phi_ID, count(*) AS n FROM Mention_Associated x
            JOIN Mention USING (Mention_ID)
            WHERE Mentioned_Phi_ID IS NULL GROUP BY 1
        ), au AS (
            SELECT Phi_ID, count(*) AS n FROM JSTOR_Authorship GROUP BY 1
        )
        SELECT p.Phi_ID, coalesce(m.n, 0), coalesce(m.n_articles, 0),
            coalesce(amb.n, 0), coalesce(au.n, 0), m.first, m.last
        FROM Philosopher p LEFT JOIN m USING (Phi_ID) LEFT JOIN amb USING (Phi_ID)
            LEFT JOIN au USING (Phi_ID)
        """,
    ),
    (
        Article_Statistics,
        """
        WITH m AS (
            SELECT Mentioning_Article_ID AS Article_ID,
                count(Mentioned_Phi_ID) AS n,
                count(*) - count(Mentioned_Phi_ID) AS n_ambiguous,
                count(DISTINCT Mentioned_Phi_ID) AS n_philosophers
            FROM Mention GROUP BY 1
        )
        SELECT a.Article_ID, coalesce(m.n, 0), coalesce(m.n_ambiguous, 0),
            coalesce(m.n_philosophers, 0)
        FROM JSTOR_Article a LEFT JOIN m USING (Article_ID)
        """,
    ),
    (
        Journal_Statistics,
        """
        WITH ar AS (
            SELECT Journal_ID, publicationYear, count(*) AS n
            FROM JSTOR_Article GROUP BY 1, 2
        ), au AS (
            SELECT Journal_ID, publicationYear, count(DISTINCT w.Phi_ID) AS n
            FROM JSTOR_Article JOIN JSTOR_Authorship w USING (Article_ID)
            WHERE w.Phi_ID != 'P:1' GROUP BY 1, 2
        ), m AS (
            SELECT Journal_ID, publicationYear, count(Mentioned_Phi_ID) AS n,
                count(DISTINCT Mentioned_Phi_ID) AS n_philosophers
            FROM Mention JOIN JSTOR_Article ON Article_ID = Mentioning_Article_ID
            GROUP BY 1, 2
        )
        SELECT ar.Journal_ID, ar.publicationYear, ar.n, coalesce(au.n, 0),
            coalesce(m.n, 0), coalesce(m.n_philosophers, 0)
        FROM ar LEFT JOIN au USING (Journal_ID, publicationYear)
            LEFT JOIN m USING (Journal_ID, publicationYear)
        """,
    ),
    (
        Institution_Statistics,
        """
        WITH phd AS (
            SELECT Institution_ID, count(*) AS n FROM PhD_Dissertation GROUP BY 1
        ), h AS (
            SELECT Institution_ID, count(*) AS n, count(DISTINCT Phi_ID) AS n_phi
            FROM Hire_Position GROUP BY 1
        )
        SELECT i.Institution_ID, coalesce(phd.n, 0), coalesce(h.n, 0),
            coalesce(h.n_phi, 0)
        FROM Institution i LEFT JOIN phd USING (Institution_ID)
            LEFT JOIN h USING (Institution_ID)
        """,
    ),
]


def jstor_articles(
    articles: pd.DataFrame,
    article_authors: pd.DataFrame,
    article_journals: pd.DataFrame,
) -> pd.DataFrame:
    df = articles.merge(article_authors, on="Article_ID", how="left").merge(
        article_journals, on="Article_ID", how="left"
    )
    for required in ["Authors_Phi_ID", "Journal_ID"]:
        if df[required].isna().any():
            raise SystemExit(f"articles without {required}")
    columns = [c.name for c in JSTOR_Article.columns]
    return df.reindex(columns=columns)


def insert_table(conn, table: sqlalchemy.Table, df: pd.DataFrame) -> None:
    df = df.rename(columns=COLUMN_RENAME.get(table.name, EMPTY))
    for column, split_column in COLUMN_SPLIT.get(table.name, EMPTY).items():
        separator = SPLIT_SEPARATOR.get(table.name, EMPTY).get(column, "|")
        key = table.primary_key.columns.keys()
        values = (
            df[column]
            .str.split(separator, expand=True)
            .stack()
            .reset_index(level=1, drop=True)
            .rename(split_column.name)
        )
        rows = df[key].merge(values, left_index=True, right_index=True)
        log.info("\t%s: %d rows", split_column.table.name, len(rows))
        rows.to_sql(
            split_column.table.name,
            conn,
            index=False,
            if_exists="append",
            chunksize=CHUNKSIZE,
        )
        df = df.drop(columns=[column])
    log.info("\t%s: %d rows", table.name, len(df))
    df.to_sql(table.name, conn, index=False, if_exists="append", chunksize=CHUNKSIZE)


def build(path, tables, info: dict) -> None:
    engine = sqlalchemy.create_engine(f"sqlite:///{urllib.parse.quote(str(path))}")
    metadata.create_all(
        engine, [t for t in metadata.tables.values() if t not in virtual_tables]
    )
    with engine.connect() as conn:
        for table, load in tables:
            with conn.begin():
                log.info("%s:", table.name)
                insert_table(conn, table, load())
        for table, select in STATISTICS:
            with conn.begin():
                columns = ", ".join(c.name for c in table.columns)
                conn.exec_driver_sql(f"INSERT INTO {table.name} ({columns}) {select}")
                n = conn.exec_driver_sql(f"SELECT count(*) FROM {table.name}")
                log.info("%s: %d rows", table.name, n.scalar())
        with conn.begin():
            build_info.write(conn, build_info.collect(info))
        conn.exec_driver_sql("ANALYZE")
    engine.dispose()


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    for name in [
        "articles",
        "article-authors",
        "article-journals",
        "authorship",
        "journals",
        "journal-variants",
        "philosophers",
        "variants",
        "wiki",
        "biography",
        "mentions",
        "contexts",
        "fulltexts",
        "article-similarity",
        "author-similarity",
        "merges",
        "life-dates",
    ]:
        p.add_argument(f"--{name}", required=True, help="parquet")
    for name in ["institutions", "phd", "classifications", "hiring"]:
        p.add_argument(f"--{name}", required=True, help="curated CSV")
    p.add_argument("--info", action="append", help="key=value for Build_Info")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    setup_logging()

    merges = read_parquet(args.merges)
    known = set(read_parquet(args.philosophers, columns=["Phi_ID"])["Phi_ID"])

    def current_ids(df: pd.DataFrame) -> pd.DataFrame:
        """Curated tables keyed by Phi_ID: merged IDs become their targets.
        IDs that are not in the dictionary are logged (v1 has 3 such PhD
        rows); the dictionary stage refuses to drop philosophers with
        JSTOR, hiring or PhD data."""
        df = df.assign(
            Phi_ID=df["Phi_ID"].replace(
                dict(zip(merges["Merged_Phi_ID"], merges["Phi_ID"]))
            )
        )
        unknown = sorted(set(df["Phi_ID"].dropna()) - known)
        if unknown:
            log.warning("rows of unknown philosophers: %s", ", ".join(unknown))
        return df

    tables = [
        (Philosopher, lambda: read_parquet(args.philosophers)),
        (Variant, lambda: read_parquet(args.variants)),
        (Biography, lambda: read_parquet(args.biography)),
        (Journal, lambda: read_parquet(args.journals)),
        (Journal_Variant, lambda: read_parquet(args.journal_variants)),
        (
            JSTOR_Article,
            lambda: jstor_articles(
                read_parquet(args.articles),
                read_parquet(args.article_authors),
                read_parquet(args.article_journals),
            ),
        ),
        (JSTOR_Authorship, lambda: read_parquet(args.authorship)),
        (Full_Text, lambda: read_parquet(args.fulltexts)),
        (Wiki_Entry, lambda: read_parquet(args.wiki)),
        (Mention, lambda: read_parquet(args.mentions)),
        (Mention_context, lambda: read_parquet(args.contexts)),
        (
            Mention_Web_ID,
            lambda: web_mention_ids(
                read_parquet(args.mentions, columns=["Mention_ID"])["Mention_ID"]
            ),
        ),
        (Institution, lambda: read_curated_csv(args.institutions)),
        (PhD_Dissertation, lambda: current_ids(read_curated_csv(args.phd))),
        (
            Classification,
            lambda: current_ids(read_curated_csv(args.classifications)),
        ),
        (Hire_Position, lambda: current_ids(read_curated_csv(args.hiring))),
        (Philosopher_Merged, lambda: merges),
        (Philosopher_Life_Dates, lambda: read_parquet(args.life_dates)),
        (Article_Similarity, lambda: read_parquet(args.article_similarity)),
        (Author_Similarity, lambda: read_parquet(args.author_similarity)),
    ]
    with atomic_output(args.out) as tmp:
        build(tmp, tables, build_info.parse_items(args.info))


if __name__ == "__main__":
    main()
