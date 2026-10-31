"""Stage 9 (disambiguate): the four disambiguation strategies of v1.

Input: the mentions of stage 7 in corpus order, with ``Associated_Phi_IDs``
(the ``|``-separated candidates of the variant). Output: the ``Mention``
table columns of v1. The strategies run in sequence; each one only
touches mentions that are still ``Ambiguous``. The rules, including the
quirks listed in ``src/legacy/README.md``, follow the v1 scripts in
``src/legacy/eugenio2/``:

- S1 article (``Disambiguated_article``): the candidates that are also
  mentioned univocally in the same article; exactly one wins.
- S2 oeuvre (``Disambiguated_author``): the same, over all articles of the
  author. Articles without author (``P:1``) are excluded, and a
  multi-author article belongs to the oeuvre of the author who comes first
  in corpus order.
- S3 zero mentions (``Disambiguated_0_mentions``): candidates without any
  mention so far, and the listed false positives, are dropped. One
  remaining candidate wins; several remain as a reduced candidate set.
- S4 co-mention (``Algorithmically_Disambiguated``): the cosine between
  the article's mention counts and each candidate's co-mention vector,
  i.e. the mention counts in all articles that mention the candidate.
  Candidates are ranked by cosine. The ranking is cut at the first
  relative drop of at least β; several survivors remain as a reduced set,
  and a single survivor wins if its cosine exceeds α.

Temporal strategies (issue #16), not part of v1. The default sequence
(``--strategies``, which must start with S1) is ``S1,L,S2,S3,S4``; T is
off by default and belongs between S2 and S3 (``S1,L,S2,T,S3,S4``). The
v1 sequence is ``S1,S2,S3,S4``.

- L life dates (``Disambiguated_life_dates``): candidates born less than
  ``--min-age`` years before the publication year are dropped
  (``Philosopher_Life_Dates``; candidates without a birth year stay). One
  remaining candidate wins, several remain as a reduced set; if none would
  remain, the mention is left unchanged.
- T recent (``Disambiguated_recent``): for a mention that is still
  ambiguous, the candidates (of its current, possibly reduced, set) that
  have at least one resolved mention anywhere in the corpus in the
  publication year or the ``--window`` preceding years; if exactly one
  candidate qualifies, it wins, otherwise the mention is unchanged. The
  resolved mentions are those at the start of T (T's own results do not
  count). T was considered and deliberately left off by default: it
  assumes too much. A philosopher who has not been mentioned for a year
  (or a few) does not thereby become irrelevant, nor one mentioned
  recently the only possible referent; the field changes too slowly for
  that assumption, and a corpus can be too small for one year's mentions
  to be representative.
"""

import math

import numpy as np
import pandas as pd
import scipy.sparse as sp

from edhiphy.common import (
    log,
    parser,
    read_parquet,
    setup_logging,
    write_parquet,
)

MENTION_COLUMNS = [
    "Article_ID",
    "Mention_ID",
    "Ent_text",
    "Ent_label",
    "Associated_Phi_IDs",
    "Disambiguated_ID",
    "Disambiguation_status",
    "Mentioned_Phi_ID",
]
AMBIGUOUS = "Ambiguous"
NO_AUTHOR = "P:1"


def ambiguous(ids: str) -> bool:
    return "|" in ids


def set_mentioned(m: pd.DataFrame) -> pd.DataFrame:
    m["Mentioned_Phi_ID"] = m["Disambiguated_ID"].where(
        m["Disambiguation_status"] != AMBIGUOUS
    )
    return m


def resolve(candidates: str, univocal: set):
    """The single candidate in ``univocal``, or None."""
    hit = set(candidates.split("|")) & univocal
    return next(iter(hit)) if len(hit) == 1 else None


def s1_article(m: pd.DataFrame) -> pd.DataFrame:
    m = m.copy()
    amb = m["Associated_Phi_IDs"].map(ambiguous)
    m["Disambiguated_ID"] = m["Associated_Phi_IDs"]
    m["Disambiguation_status"] = np.where(amb, AMBIGUOUS, "Non_ambiguous")
    univocal = m[~amb].groupby("Article_ID")["Associated_Phi_IDs"].agg(set)
    for i, (a, ids) in m.loc[amb, ["Article_ID", "Associated_Phi_IDs"]].iterrows():
        hit = resolve(ids, univocal.get(a, set()))
        if hit is not None:
            m.at[i, "Disambiguated_ID"] = hit
            m.at[i, "Disambiguation_status"] = "Disambiguated_article"
    return set_mentioned(m)


def oeuvres(m: pd.DataFrame, authorship: pd.DataFrame) -> pd.Series:
    """Article -> author whose oeuvre it joins (v1 rules), for the articles
    with mentions and an author other than P:1."""
    authors = authorship.groupby("Article_ID", sort=False)["Phi_ID"].agg(list)
    order = {}
    for a in m["Article_ID"].unique():
        for p in authors.get(a, []):
            if p != NO_AUTHOR:
                order.setdefault(p, len(order))
    owner = {}
    for a in m["Article_ID"].unique():
        ps = [p for p in authors.get(a, []) if p != NO_AUTHOR]
        if ps:
            owner[a] = min(ps, key=order.__getitem__)
    return pd.Series(owner, dtype=object)


def s2_oeuvre(m: pd.DataFrame, authorship: pd.DataFrame) -> pd.DataFrame:
    authors = authorship.groupby("Article_ID")["Phi_ID"].agg(set)
    mixed = [a for a, ps in authors.items() if NO_AUTHOR in ps and len(ps) > 1]
    mixed = set(mixed) & set(m["Article_ID"])
    if mixed:
        # v1 would duplicate the mentions of such articles.
        raise SystemExit(f"{len(mixed)} articles list P:1 next to other authors")
    without = ~m["Article_ID"].isin(authors.index)
    if without.any():
        # v1 joined the authorship table with an inner join.
        log.warning(
            "S2: dropping %d mentions of %d articles without authorship rows",
            without.sum(),
            m.loc[without, "Article_ID"].nunique(),
        )
        m = m[~without]
    m = m.copy()
    owner = m["Article_ID"].map(oeuvres(m, authorship))
    known = m["Disambiguation_status"] != AMBIGUOUS
    univocal = m[known & owner.notna()].groupby(owner)["Mentioned_Phi_ID"].agg(set)
    todo = (~known) & owner.notna()
    for i in m.index[todo]:
        hit = resolve(m.at[i, "Associated_Phi_IDs"], univocal.get(owner[i], set()))
        if hit is not None:
            m.at[i, "Disambiguated_ID"] = hit
            m.at[i, "Disambiguation_status"] = "Disambiguated_author"
    return set_mentioned(m)


def read_false_positives(path) -> set:
    fp = pd.read_csv(path, sep=";", encoding="UTF-8-SIG", dtype=str)
    return set(fp["Phi_ID"])


def s3_zero_mentions(m: pd.DataFrame, false_positives: set) -> pd.DataFrame:
    m = m.copy()
    counts = m["Disambiguated_ID"].value_counts()
    amb = m["Disambiguation_status"] == AMBIGUOUS
    reduced = {}
    for ids in m.loc[amb, "Disambiguated_ID"].unique():
        keep = [
            c
            for c in ids.split("|")
            if counts.get(c, 0) != 0 and c not in false_positives
        ]
        if keep:
            reduced[ids] = "|".join(keep)
    new = m.loc[amb, "Disambiguated_ID"].map(reduced)
    m.loc[amb, "Disambiguated_ID"] = new.fillna(m.loc[amb, "Disambiguated_ID"])
    won = amb & ~m["Disambiguated_ID"].map(ambiguous)
    m.loc[won, "Disambiguation_status"] = "Disambiguated_0_mentions"
    return set_mentioned(m)


def cosine(uv: float, uu: float, vv: float) -> float:
    """1 - scipy.spatial.distance.cosine for count vectors (exact sums)."""
    return 1.0 - min(max(1.0 - uv / math.sqrt(uu * vv), 0.0), 2.0)


def s4_choice(cosines: list, alpha: float, beta: float):
    """v1's decision for one ambiguous candidate set: a single Phi_ID, a
    reduced ``|``-set, or None (unchanged). ``cosines`` lists (Phi_ID,
    cosine) in candidate order."""
    if all(c == 0 for _, c in cosines):
        return None
    ranked = sorted(cosines, key=lambda pc: -pc[1])
    keep = [ranked[0][0]]
    for (_, prev), (p, c) in zip(ranked, ranked[1:]):
        # pandas pct_change, negated: the relative drop from prev to c.
        if -(c / prev - 1) < beta:
            keep.append(p)
        else:
            break
    if len(keep) > 1:
        return "|".join(keep)
    return keep[0] if ranked[0][1] > alpha else None


def s4_co_mention(m: pd.DataFrame, alpha: float, beta: float) -> pd.DataFrame:
    m = m.copy()
    amb = m["Disambiguation_status"] == AMBIGUOUS
    candidates = sorted(
        {c for ids in m.loc[amb, "Disambiguated_ID"].unique() for c in ids.split("|")}
    )
    known = m[m["Mentioned_Phi_ID"].notna()]
    arts = pd.Index(m["Article_ID"].unique())
    phis = pd.Index(sorted(set(known["Mentioned_Phi_ID"]) | set(candidates)))
    counts = (
        known.groupby(["Article_ID", "Mentioned_Phi_ID"])
        .size()
        .rename("n")
        .reset_index()
    )
    C = sp.csr_matrix(
        (
            counts["n"].to_numpy(dtype=np.float64),
            (
                arts.get_indexer(counts["Article_ID"]),
                phis.get_indexer(counts["Mentioned_Phi_ID"]),
            ),
        ),
        shape=(len(arts), len(phis)),
    )
    B = (C > 0).astype(np.float64)
    cand = phis.get_indexer(candidates)
    # Co-mention vectors of the candidates (rows) and their squared norms;
    # all entries are integer counts, so the sums are exact.
    V = (B[:, cand].T @ C).tocsr()
    vv = np.asarray(V.multiply(V).sum(axis=1)).ravel()
    row_of = dict(zip(candidates, range(len(candidates))))

    results = {}
    for a, group in m[amb].groupby("Article_ID", sort=False):
        u = C[arts.get_loc(a)]
        if u.nnz == 0:
            continue  # v1: no non-ambiguous mention in the article
        uu = float(u.multiply(u).sum())
        for ids in group["Disambiguated_ID"].unique():
            cos = []
            for c in ids.split("|"):
                r = row_of[c]
                if vv[r] == 0:
                    cos.append((c, 0))
                    continue
                uv = float(u.multiply(V[r]).sum())
                cos.append((c, cosine(uv, uu, float(vv[r]))))
            choice = s4_choice(cos, alpha, beta)
            if choice is not None:
                results[(a, ids)] = choice
    keys = list(zip(m.loc[amb, "Article_ID"], m.loc[amb, "Disambiguated_ID"]))
    new = pd.Series([results.get(k) for k in keys], index=m.index[amb], dtype=object)
    m.loc[amb, "Disambiguated_ID"] = new.fillna(m.loc[amb, "Disambiguated_ID"])
    won = amb & ~m["Disambiguated_ID"].map(ambiguous)
    m.loc[won, "Disambiguation_status"] = "Algorithmically_Disambiguated"
    return set_mentioned(m)


def reduce_candidates(m: pd.DataFrame, keep, status: str) -> pd.DataFrame:
    """Apply ``keep(article, candidates) -> list`` to the ambiguous mentions:
    a single kept candidate wins with ``status``, several form a reduced
    set; an empty list leaves the mention unchanged."""
    m = m.copy()
    amb = m["Disambiguation_status"] == AMBIGUOUS
    keys = list(zip(m.loc[amb, "Article_ID"], m.loc[amb, "Disambiguated_ID"]))
    choice = {}
    for a, ids in set(keys):
        kept = keep(a, ids.split("|"))
        if kept:
            choice[(a, ids)] = "|".join(kept)
    new = pd.Series([choice.get(k) for k in keys], index=m.index[amb], dtype=object)
    m.loc[amb, "Disambiguated_ID"] = new.fillna(m.loc[amb, "Disambiguated_ID"])
    won = amb & ~m["Disambiguated_ID"].map(ambiguous)
    m.loc[won, "Disambiguation_status"] = status
    return set_mentioned(m)


def s_life_dates(
    m: pd.DataFrame, years: pd.Series, births: pd.Series, min_age: int
) -> pd.DataFrame:
    """Strategy L: drop candidates born after ``year - min_age``."""
    birth = births.dropna().to_dict()

    def keep(a, candidates):
        latest = years[a] - min_age
        kept = [c for c in candidates if not birth.get(c, latest) > latest]
        return kept if len(kept) < len(candidates) else []

    return reduce_candidates(m, keep, "Disambiguated_life_dates")


def s_recent(m: pd.DataFrame, years: pd.Series, window: int) -> pd.DataFrame:
    """Strategy T: the only candidate resolved in years [y - window, y]."""
    known = m[m["Mentioned_Phi_ID"].notna()]
    active = (
        pd.DataFrame(
            {
                "Phi_ID": known["Mentioned_Phi_ID"],
                "year": known["Article_ID"].map(years),
            }
        )
        .drop_duplicates()
        .groupby("Phi_ID")["year"]
        .agg(frozenset)
        .to_dict()
    )

    def keep(a, candidates):
        y = years[a]
        recent = range(y - window, y + 1)
        hit = [c for c in candidates if any(t in active.get(c, ()) for t in recent)]
        return hit if len(hit) == 1 else []

    return reduce_candidates(m, keep, "Disambiguated_recent")


STRATEGIES = ("S1", "S2", "S3", "S4", "L", "T")
V1_STRATEGIES = "S1,S2,S3,S4"
DEFAULT_STRATEGIES = "S1,L,S2,S3,S4"


def disambiguate(
    m,
    authorship,
    false_positives,
    alpha,
    beta,
    strategies=DEFAULT_STRATEGIES,
    years=None,
    births=None,
    min_age=20,
    window=1,
) -> pd.DataFrame:
    names = strategies.split(",")
    unknown = set(names) - set(STRATEGIES)
    if unknown or len(set(names)) < len(names) or names[0] != "S1":
        # S1 sets the initial status of every mention.
        raise SystemExit(
            f"strategies {strategies!r}: S1 first, then each of {STRATEGIES} once"
        )
    if {"L", "T"} & set(names) and years is None:
        raise SystemExit("strategies L and T need the publication years")
    if "L" in names and births is None:
        raise SystemExit("strategy L needs the life dates")
    steps = {
        "S1": lambda x: s1_article(x),
        "S2": lambda x: s2_oeuvre(x, authorship),
        "S3": lambda x: s3_zero_mentions(x, false_positives),
        "S4": lambda x: s4_co_mention(x, alpha, beta),
        "L": lambda x: s_life_dates(x, years, births, min_age),
        "T": lambda x: s_recent(x, years, window),
    }
    m = m.reset_index(drop=True)
    for name in names:
        m = steps[name](m)
        n = (m["Disambiguation_status"] == AMBIGUOUS).sum()
        log.info("after %s: %d of %d mentions ambiguous", name, n, len(m))
    return m[MENTION_COLUMNS].reset_index(drop=True)


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--mentions", required=True, help="raw mentions (stage 7)")
    p.add_argument("--authorship", required=True, help="authorship.parquet")
    p.add_argument("--false-positives", required=True, help="CSV with a Phi_ID column")
    p.add_argument("--alpha", type=float, default=0.01, help="minimal cosine")
    p.add_argument(
        "--beta", type=float, default=0.25, help="relative drop that cuts the ranking"
    )
    p.add_argument(
        "--strategies",
        default=DEFAULT_STRATEGIES,
        help=f"comma-separated sequence of {', '.join(STRATEGIES)}",
    )
    p.add_argument("--articles", help="articles.parquet (strategies L, T)")
    p.add_argument("--life-dates", help="life_dates.parquet (strategy L)")
    p.add_argument("--min-age", type=int, default=20, help="strategy L")
    p.add_argument("--window", type=int, default=1, help="strategy T, in years")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    setup_logging()
    mentions = read_parquet(args.mentions)
    authorship = read_parquet(args.authorship, columns=["Article_ID", "Phi_ID"])
    years = births = None
    if args.articles:
        a = read_parquet(args.articles, columns=["Article_ID", "publicationYear"])
        years = a.set_index("Article_ID")["publicationYear"].astype(int)
    if args.life_dates:
        d = read_parquet(args.life_dates, columns=["Phi_ID", "Birth_Year"])
        births = d.set_index("Phi_ID")["Birth_Year"]
    out = disambiguate(
        mentions,
        authorship,
        read_false_positives(args.false_positives),
        args.alpha,
        args.beta,
        args.strategies,
        years,
        births,
        args.min_age,
        args.window,
    )
    for status, n in out["Disambiguation_status"].value_counts().items():
        log.info("%s: %d", status, n)
    write_parquet(out, args.out)


if __name__ == "__main__":
    main()
