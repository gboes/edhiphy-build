"""Review sheets of a corpus for subject-matter experts (not a pipeline
stage; written into ``<out-dir>`` after a build).

From the research database:

- ``mentions_sample.csv``: a random sample of mentions per
  ``Disambiguation_status`` (``--per-status``, seed ``--seed``) with the
  article's year, journal and language, the candidates, the resolved
  philosopher and the context; columns ``Correct`` (yes/no/unclear),
  ``Correct_Phi_ID``, ``Comment`` for the reviewer;
- ``top_philosophers.csv``: the ``--top`` philosophers by resolved
  mentions with their most frequent mention texts;
- ``top_variants.csv``: the ``--top`` mention texts by number, with the
  share resolved and the philosophers they resolve to (false-positive
  variants: given names, places, common words; candidates for
  ``data/manual/variant_issues_<lang>.csv``);
- ``anachronisms.csv``: resolved mentions of philosophers born after the
  publication year (``Philosopher_Life_Dates``), grouped by philosopher
  and mention text;
- ``duplicate_candidates.csv``: pairs of philosophers whose labels are
  equal with diacritics folded and case ignored (e.g. a new Wikidata entry
  and a v1 JSTOR author without Wiki_ID).

Plus a ``README.md`` describing the sheets.
"""

from pathlib import Path

import pandas as pd

from edhiphy.common import atomic_output, fold_diacritics, log, parser, setup_logging

README = """# Review sheets: {corpus} {version}

Built from `{db}` (commit {commit}). For subject-matter experts; the
build does not depend on them. Fill the empty columns and return the
files; decisions go into the curated inputs (`data/manual/`).

| Sheet | Rows | What to check |
|---|---|---|
| `mentions_sample.csv` | {n_sample} | Is the mention a reference to the resolved philosopher (`Correct`: yes/no/unclear; `Correct_Phi_ID` if another)? Sample of {per_status} per disambiguation status, seed {seed}. |
| `top_philosophers.csv` | {n_top} | Do the most mentioned philosophers make sense for the corpus? Implausible entries point to false-positive variants. |
| `top_variants.csv` | {n_variants} | Mention texts by frequency: given names, places, common words that are not names (`Issue` column: e.g. Maybe_problematic, Highly_problematic). |
| `anachronisms.csv` | {n_anachronisms} | Philosophers mentioned before their birth: wrong resolution or wrong variant. |
| `duplicate_candidates.csv` | {n_duplicates} | Same person under two Phi_IDs (`Same`: yes/no)? |
{authors}
"""


def read_sql(conn, sql) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn)


def mentions_sample(conn, per_status: int, seed: int) -> pd.DataFrame:
    m = read_sql(
        conn,
        """SELECT m.Mention_ID, m.Mentioning_Article_ID AS Article_ID,
            a.publicationYear, j.Journal_standard_name AS Journal, a.language,
            m.Ent_text, m.Disambiguation_status,
            (SELECT group_concat(Phi_ID, '|') FROM Mention_Associated x
             WHERE x.Mention_ID = m.Mention_ID) AS Associated_Phi_IDs,
            m.Mentioned_Phi_ID, p.Phi_Standard_Label AS Mentioned_label,
            c.Mention_context
        FROM Mention m
        JOIN JSTOR_Article a ON a.Article_ID = m.Mentioning_Article_ID
        JOIN Journal j ON j.Journal_ID = a.Journal_ID
        LEFT JOIN Philosopher p ON p.Phi_ID = m.Mentioned_Phi_ID
        LEFT JOIN Mention_context c ON c.Mention_ID = m.Mention_ID""",
    )
    sample = (
        m.groupby("Disambiguation_status", group_keys=False)
        .apply(lambda g: g.sample(min(per_status, len(g)), random_state=seed))
        .sort_values(["Disambiguation_status", "Article_ID", "Mention_ID"])
    )
    return sample.assign(Correct="", Correct_Phi_ID="", Comment="")


def top_philosophers(conn, top: int) -> pd.DataFrame:
    s = read_sql(
        conn,
        f"""SELECT s.Phi_ID, p.Phi_Standard_Label, (SELECT group_concat(Wiki_ID, '|') FROM Philosopher_Wiki_ID w WHERE w.Phi_ID = p.Phi_ID) AS Wiki_ID,
            s.N_mentions,
            s.N_mentioning_articles, s.First_mention_year, s.Last_mention_year
        FROM Philosopher_Statistics s JOIN Philosopher p USING (Phi_ID)
        ORDER BY s.N_mentions DESC, s.Phi_ID LIMIT {int(top)}""",
    )
    texts = read_sql(
        conn,
        """SELECT Mentioned_Phi_ID AS Phi_ID, Ent_text, count(*) AS n FROM Mention
        WHERE Mentioned_Phi_ID IS NOT NULL GROUP BY 1, 2""",
    )
    texts = texts[texts["Phi_ID"].isin(s["Phi_ID"])].sort_values(
        ["Phi_ID", "n"], ascending=[True, False]
    )
    top_texts = texts.groupby("Phi_ID").apply(
        lambda g: "; ".join(f"{t} ({n})" for t, n in zip(g["Ent_text"][:5], g["n"][:5]))
    )
    return s.assign(Mention_texts=s["Phi_ID"].map(top_texts), Plausible="", Comment="")


def top_variants(conn, top: int) -> pd.DataFrame:
    m = read_sql(
        conn,
        """SELECT m.Ent_text, m.Mentioned_Phi_ID, p.Phi_Standard_Label
        FROM Mention m LEFT JOIN Philosopher p ON p.Phi_ID = m.Mentioned_Phi_ID""",
    )
    g = m.groupby("Ent_text")
    out = pd.DataFrame(
        {
            "N_mentions": g.size(),
            "Share_resolved": g["Mentioned_Phi_ID"].agg(
                lambda s: round(s.notna().mean(), 3)
            ),
            "Resolved_to": g["Phi_Standard_Label"].agg(
                lambda s: "; ".join(
                    f"{k} ({v})" for k, v in s.value_counts().head(3).items()
                )
            ),
        }
    )
    out = out.sort_values("N_mentions", ascending=False).head(top).reset_index()
    return out.assign(Issue="", Comment="")


def anachronisms(conn) -> pd.DataFrame:
    a = read_sql(
        conn,
        """SELECT m.Mentioned_Phi_ID AS Phi_ID, p.Phi_Standard_Label, d.Birth_Year,
            m.Ent_text, m.Disambiguation_status, count(*) AS N_mentions,
            min(a.publicationYear) AS First_year, max(a.publicationYear) AS Last_year,
            min(m.Mention_ID) AS Example_mention
        FROM Mention m
        JOIN JSTOR_Article a ON a.Article_ID = m.Mentioning_Article_ID
        JOIN Philosopher_Life_Dates d ON d.Phi_ID = m.Mentioned_Phi_ID
        JOIN Philosopher p ON p.Phi_ID = m.Mentioned_Phi_ID
        WHERE d.Birth_Year > a.publicationYear
        GROUP BY 1, 2, 3, 4, 5 ORDER BY N_mentions DESC""",
    )
    return a.assign(Comment="")


def duplicate_candidates(conn) -> pd.DataFrame:
    p = read_sql(
        conn,
        """SELECT Phi_ID, Phi_Standard_Label_legacy AS Label, Wiki, JSTOR,
            (SELECT group_concat(Wiki_ID, '|') FROM Philosopher_Wiki_ID w WHERE w.Phi_ID = p.Phi_ID) AS Wiki_ID
        FROM Philosopher p""",
    )
    p["key"] = p["Label"].map(lambda s: fold_diacritics(str(s)).casefold())
    p = p[p["key"].str.contains(" ")]
    pairs = p.merge(p, on="key", suffixes=("_1", "_2"))
    pairs = pairs[
        pairs["Phi_ID_1"].str[2:].astype(int) < pairs["Phi_ID_2"].str[2:].astype(int)
    ]
    # Two Wikidata entries with the same label are usually different people
    # (unique labels, issue #9); pairs with at most one Wiki_ID are kept.
    pairs = pairs[pairs["Wiki_ID_1"].isna() | pairs["Wiki_ID_2"].isna()]
    return pairs.drop(columns="key").assign(Same="", Comment="")


def write(df: pd.DataFrame, path: Path) -> None:
    with atomic_output(path) as tmp:
        df.to_csv(tmp, index=False)
    log.info("wrote %s (%d rows)", path, len(df))


def main(argv=None):
    import sqlite3

    p = parser(__doc__.splitlines()[0])
    p.add_argument("--db", required=True, help="research database")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--per-status", type=int, default=50)
    p.add_argument("--top", type=int, default=200)
    p.add_argument("--seed", type=int, default=20261029)
    p.add_argument("--authors", help="author review sheet of edhiphy.jstor_authors")
    args = p.parse_args(argv)
    setup_logging()
    out = Path(args.out_dir)
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    info = dict(conn.execute("SELECT key, value FROM Build_Info"))
    sheets = {
        "mentions_sample.csv": mentions_sample(conn, args.per_status, args.seed),
        "top_philosophers.csv": top_philosophers(conn, args.top),
        "top_variants.csv": top_variants(conn, args.top),
        "anachronisms.csv": anachronisms(conn),
        "duplicate_candidates.csv": duplicate_candidates(conn),
    }
    conn.close()
    for name, df in sheets.items():
        write(df, out / name)
    authors = ""
    if args.authors:
        a = pd.read_csv(args.authors)
        write(a, out / "authors.csv")
        authors = (
            f"| `authors.csv` | {len(a)} | Is each JSTOR creator matched to the right "
            "philosopher (`rule`: variant, ambiguous_jstor, initials; new = new Phi_ID)? "
            "`Correct`: yes/no; for new authors: same person as an existing entry? |"
        )
    text = README.format(
        corpus=info.get("corpus_name"),
        version=info.get("corpus_version"),
        db=Path(args.db).name,
        commit=info.get("git_commit", "")[:7],
        n_sample=len(sheets["mentions_sample.csv"]),
        per_status=args.per_status,
        seed=args.seed,
        n_top=len(sheets["top_philosophers.csv"]),
        n_variants=len(sheets["top_variants.csv"]),
        n_anachronisms=len(sheets["anachronisms.csv"]),
        n_duplicates=len(sheets["duplicate_candidates.csv"]),
        authors=authors,
    )
    with atomic_output(out / "README.md") as tmp:
        tmp.write_text(text)


if __name__ == "__main__":
    main()
