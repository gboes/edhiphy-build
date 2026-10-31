"""Similarity of articles: LSA over the words of the cleaned texts, and
mention profiles (which philosophers an article mentions).

LSA: words of at least two letters, lower-cased; weights (1 + log tf) *
log(N / df), rows L2-normalised; terms in fewer than ``--min-df`` articles
or in more than ``--max-df`` of them are dropped; truncated SVD with
``--dimensions`` components. Article vectors are U Σ, normalised. The term
vectors (V with the idf) allow a free-text query to be projected into the
same space: q·V.

Mention profiles: counts of ``Mentioned_Phi_ID`` per article (disambiguated
mentions only), weighted (1 + log tf) * log(N / df) and normalised, so that
philosophers mentioned everywhere count less.

LSA neighbours are computed only among articles in the corpus language
(``--lang``: English or French), i.e. with a share of its frequent
function words (``FUNCTION_WORDS``) of at least ``MIN_ENGLISH_SHARE``
(the same threshold for both lists), and at least
``MIN_WORDS`` words; mention neighbours among articles with at least one
disambiguated mention.

Outputs, in ``--out-dir``: ``lsa_articles.parquet`` and
``lsa_terms.parquet`` (vectors), ``neighbours.parquet`` (the ``--k`` most
similar articles per article and method), ``pairs.parquet`` (every
neighbour pair and a random sample of pairs, with both cosines: the
material for comparing the two notions of similarity), and
``articles.parquet`` (JSTOR language, share of function words
and number of distinct mentioned philosophers per article: the filters
of the summary), and
``similarity.md`` (a summary). The same for authors (oeuvres, see
``author_profiles``): ``authors.parquet``, ``lsa_authors.parquet``,
``author_neighbours.parquet``, ``author_pairs.parquet``, ``authors.md``.

Both representations derive from word counts and mention counts only;
neither contains or reveals word order.
"""

import re
from array import array
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import scipy.sparse as sp
from scipy.sparse.linalg import svds
from scipy.stats import spearmanr

from edhiphy.common import atomic_output, log, parser, read_parquet, setup_logging

WORD = re.compile(r"[^\W\d_]{2,}")
# Frequent English function words: their share of an article's words
# separates English from other texts (bimodal, threshold about 0.2); the
# JSTOR language field marks some French and German articles as English.
ENGLISH = frozenset(
    "the of and to in is that it as be this which not by for with are or but "
    "from an on was have at his can we there".split()
)
# The French counterpart: frequent words of two letters or more (the
# tokenizer of word_counts drops "à", "l'", "d'").
FRENCH = frozenset(
    "de la le et les des en un une du est que qui dans il pour pas par sur "
    "au ne se plus ce son sa ou aux".split()
)
FUNCTION_WORDS = {"en": ENGLISH, "fr": FRENCH}
BLOCK = 2000
NO_AUTHOR = "P:1"
MIN_ENGLISH_SHARE = 0.25
# Shorter pieces (errata, notes) have unstable LSA vectors.
MIN_WORDS = 1000


def tfidf(rows, cols, counts, n_rows, n_cols) -> sp.csr_matrix:
    X = sp.csr_matrix(
        (np.log(counts.astype(np.float64)) + 1.0, (rows, cols)), shape=(n_rows, n_cols)
    )
    X.sum_duplicates()
    df = np.bincount(X.indices, minlength=n_cols)
    idf = np.log(n_rows / np.maximum(df, 1))
    X = X @ sp.diags(idf)
    return normalise(X), idf


def normalise(X):
    norms = np.sqrt(np.asarray(X.multiply(X).sum(axis=1)).ravel())
    norms[norms == 0] = 1.0
    return sp.diags(1.0 / norms) @ X


def word_counts(texts, function_words=ENGLISH):
    """COO arrays (article, term, count), the vocabulary, and the share of
    ``function_words`` per article."""
    vocab = {}
    rows, cols, counts = array("i"), array("i"), array("i")
    english = np.zeros(len(texts))
    for i, text in enumerate(texts):
        c = {}
        words = WORD.findall(text.lower())
        for w in words:
            c[w] = c.get(w, 0) + 1
        english[i] = sum(n for w, n in c.items() if w in function_words) / max(
            len(words), 1
        )
        for w, n in c.items():
            rows.append(i)
            cols.append(vocab.setdefault(w, len(vocab)))
            counts.append(n)
    terms = np.empty(len(vocab), dtype=object)
    for w, j in vocab.items():
        terms[j] = w
    return (
        np.frombuffer(rows, np.int32),
        np.frombuffer(cols, np.int32),
        np.frombuffer(counts, np.int32),
        terms,
        english,
    )


def lsa(texts, dimensions: int, min_df: int, max_df: float, function_words=ENGLISH):
    rows, cols, counts, terms, english = word_counts(texts, function_words)
    n = len(texts)
    df = np.bincount(cols, minlength=len(terms))
    keep = (df >= min_df) & (df <= max_df * n)
    new_col = np.full(len(terms), -1)
    new_col[keep] = np.arange(keep.sum())
    sel = keep[cols]
    X, idf = tfidf(rows[sel], new_col[cols[sel]], counts[sel], n, int(keep.sum()))
    k = max(1, min(dimensions, min(X.shape) - 1))
    U, s, Vt = svds(X, k=k, solver="arpack", random_state=0)
    order = np.argsort(-s)
    U, s, Vt = U[:, order], s[order], Vt[order]
    # Fix the sign of each component: largest term loading positive.
    signs = np.sign(Vt[np.arange(k), np.abs(Vt).argmax(axis=1)])
    U, Vt = U * signs, Vt * signs[:, None]
    A = U * s
    A /= np.maximum(np.linalg.norm(A, axis=1, keepdims=True), 1e-12)
    total = X.multiply(X).sum()
    info = {
        "vocabulary": int(keep.sum()),
        "dimensions": k,
        "explained": float((s**2).sum() / total) if total else 0.0,
    }
    info["english"] = english
    return A.astype(np.float32), terms[keep], idf, Vt.T.astype(np.float32), info


def mention_profiles(mentions: pd.DataFrame, articles: pd.Index):
    known = mentions[mentions["Mentioned_Phi_ID"].notna()]
    c = (
        known.groupby(["Article_ID", "Mentioned_Phi_ID"])
        .size()
        .rename("n")
        .reset_index()
    )
    phis = pd.Index(sorted(c["Mentioned_Phi_ID"].unique()))
    M, _ = tfidf(
        articles.get_indexer(c["Article_ID"]),
        phis.get_indexer(c["Mentioned_Phi_ID"]),
        c["n"].to_numpy(),
        len(articles),
        len(phis),
    )
    return M.tocsr()


def top_k(S: np.ndarray, offset: int, k: int, valid: np.ndarray):
    """Indices and values of the k largest entries per row, excluding the
    row's own article and articles without a vector."""
    S = S.copy()
    S[np.arange(S.shape[0]), offset + np.arange(S.shape[0])] = -np.inf
    S[:, ~valid] = -np.inf
    k = min(k, S.shape[1] - 1)
    idx = np.argpartition(-S, k - 1, axis=1)[:, :k]
    vals = np.take_along_axis(S, idx, axis=1)
    order = np.lexsort((idx, -vals), axis=1)
    return np.take_along_axis(idx, order, axis=1), np.take_along_axis(
        vals, order, axis=1
    )


def neighbours(
    product, n: int, k: int, valid: np.ndarray, method: str, ids
) -> pd.DataFrame:
    frames = []
    for b in range(0, n, BLOCK):
        S = product(b, min(b + BLOCK, n))
        idx, vals = top_k(S, b, k, valid)
        rows = np.repeat(np.arange(b, b + len(idx)), idx.shape[1])
        f = pd.DataFrame(
            {
                "a": rows,
                "rank": np.tile(np.arange(1, idx.shape[1] + 1), len(idx)),
                "b": idx.ravel(),
                "cosine": vals.ravel(),
            }
        )
        frames.append(f[valid[f["a"]] & (f["cosine"] > 0)])
    f = pd.concat(frames, ignore_index=True)
    return pd.DataFrame(
        {
            "Article_ID": ids[f["a"]],
            "method": method,
            "rank": f["rank"].to_numpy(),
            "Neighbour_ID": ids[f["b"]],
            "cosine": f["cosine"].to_numpy(dtype=np.float32),
        }
    )


def both_neighbours(A, M, ids, k, valid_a, valid_m) -> pd.DataFrame:
    MT = M.T.tocsc()
    nb = pd.concat(
        [
            neighbours(lambda b, e: A[b:e] @ A.T, len(ids), k, valid_a, "lsa", ids),
            neighbours(
                lambda b, e: (M[b:e] @ MT).toarray(),
                len(ids),
                k,
                valid_m,
                "mentions",
                ids,
            ),
        ],
        ignore_index=True,
    )
    log.info("%d neighbour rows", len(nb))
    return nb


def pair_cosines(A, M, i, j):
    lsa_cos = np.einsum("ij,ij->i", A[i], A[j])
    men_cos = np.asarray(M[i].multiply(M[j]).sum(axis=1)).ravel()
    return lsa_cos.astype(np.float32), men_cos.astype(np.float32)


def divergent(nb: pd.DataFrame, n: int, q: float = 0.9):
    """Pairs in the top (1 - q) of the neighbour pairs by one cosine, sorted
    by the other cosine (lowest first): (high mentions, low LSA) and (high
    LSA, low mentions)."""
    if not len(nb):
        return nb, nb
    m_cut, l_cut = nb["mentions"].quantile(q), nb["lsa"].quantile(q)
    return (
        nb[nb["mentions"] >= m_cut].nsmallest(n, "lsa"),
        nb[nb["lsa"] >= l_cut].nsmallest(n, "mentions"),
    )


def summary(
    info, pairs: pd.DataFrame, valid_m: np.ndarray, meta, min_philosophers
) -> str:
    # Only pairs of English texts (by function-word share) that each mention
    # at least min_philosophers distinct philosophers: LSA groups articles
    # by language, and very short mention profiles give trivial cosines of 1.
    ok = meta.index[
        (meta["function_share"] >= MIN_ENGLISH_SHARE)
        & (meta["philosophers"] >= min_philosophers)
        & (meta["words"] >= MIN_WORDS)
    ]
    ok = set(ok)
    eligible = pairs["Article_ID_a"].isin(ok) & pairs["Article_ID_b"].isin(ok)
    rnd = pairs[(pairs["source"] == "random") & eligible]
    nb = pairs[(pairs["source"] != "random") & eligible]
    rho_rnd = (
        spearmanr(rnd["lsa"], rnd["mentions"]).statistic
        if len(rnd) > 2
        else float("nan")
    )
    rho_nb = (
        spearmanr(nb["lsa"], nb["mentions"]).statistic if len(nb) > 2 else float("nan")
    )
    lines = [
        "# Article similarity",
        "",
        f"LSA: vocabulary {info['vocabulary']:,} terms, {info['dimensions']} dimensions, "
        f"{info['explained']:.1%} of the TF-IDF variance. Mention profiles: "
        f"{int(valid_m.sum()):,} articles with disambiguated mentions.",
        "",
        f"Pairs below: both articles in the corpus language (its function words ≥ "
        f"{MIN_ENGLISH_SHARE:.0%} of the words), at least {MIN_WORDS:,} words long, "
        f"and with at least {min_philosophers} "
        f"distinct mentioned philosophers ({len(ok):,} articles).",
        "",
        f"Spearman ρ between LSA and mention cosine: {rho_rnd:.3f} on {len(rnd):,} random "
        f"pairs, {rho_nb:.3f} on {len(nb):,} neighbour pairs (pairs among the nearest "
        "neighbours by either method; the selection makes ρ negative there).",
        "",
    ]
    q = nb[["lsa", "mentions"]].quantile([0.1, 0.5, 0.9])
    lines += [
        "Neighbour pairs, quantiles (0.1, 0.5, 0.9): LSA "
        + ", ".join(f"{v:.3f}" for v in q["lsa"])
        + "; mentions "
        + ", ".join(f"{v:.3f}" for v in q["mentions"])
        + ".",
        "",
    ]

    def show(title, df):
        df = df.merge(meta.add_suffix("_a"), left_on="Article_ID_a", right_index=True)
        df = df.merge(meta.add_suffix("_b"), left_on="Article_ID_b", right_index=True)
        lines.extend(
            [
                f"## {title}",
                "",
                "| LSA | mentions | a | b |",
                "|---|---|---|---|",
            ]
        )
        for r in df.itertuples():
            a = f"{r.title_a} ({r.publicationYear_a}, {r.Article_ID_a.rsplit('/', 1)[1]})"
            b = f"{r.title_b} ({r.publicationYear_b}, {r.Article_ID_b.rsplit('/', 1)[1]})"
            lines.append(
                f"| {r.lsa:.3f} | {r.mentions:.3f} "
                f"| {a.replace('|', '/')} | {b.replace('|', '/')} |"
            )
        lines.append("")

    show(
        "Same philosophers, different words (top 10 % by mentions, lowest LSA)",
        divergent(nb, 20)[0],
    )
    show(
        "Same words, different philosophers (top 10 % by LSA, fewest shared mentions)",
        divergent(nb, 20)[1],
    )
    return "\n".join(lines) + "\n"


def author_profiles(A, mentions, authorship, index, lsa_ok):
    """Oeuvre level. Mention profiles: the mentions of all articles an
    author wrote or co-wrote (co-authored articles count for each author),
    without the author's mentions of themselves, weighted as for articles
    (df = number of authors). LSA: the mean of the vectors of the
    author's articles that pass the LSA filter (``lsa_ok``), normalised."""
    au = authorship[authorship["Phi_ID"] != NO_AUTHOR]
    au = au[au["Article_ID"].isin(index)].drop_duplicates(["Article_ID", "Phi_ID"])
    authors = pd.Index(sorted(au["Phi_ID"].unique()))
    known = mentions[mentions["Mentioned_Phi_ID"].notna()]
    m = known.merge(au, on="Article_ID")
    m = m[m["Mentioned_Phi_ID"] != m["Phi_ID"]]
    c = m.groupby(["Phi_ID", "Mentioned_Phi_ID"]).size().rename("n").reset_index()
    phis = pd.Index(sorted(c["Mentioned_Phi_ID"].unique()))
    M, _ = tfidf(
        authors.get_indexer(c["Phi_ID"]),
        phis.get_indexer(c["Mentioned_Phi_ID"]),
        c["n"].to_numpy(),
        len(authors),
        len(phis),
    )
    rows = authors.get_indexer(au["Phi_ID"])
    cols = index.get_indexer(au["Article_ID"])
    eng = lsa_ok[cols]
    B = sp.csr_matrix(
        (np.ones(eng.sum()), (rows[eng], cols[eng])), shape=(len(authors), len(index))
    )
    L = np.asarray(B @ A)
    L /= np.maximum(np.linalg.norm(L, axis=1, keepdims=True), 1e-12)
    stats = pd.DataFrame(
        {
            "articles": np.bincount(rows, minlength=len(authors)),
            "lsa_articles": np.asarray(B.getnnz(axis=1)),
            "philosophers": np.asarray(M.getnnz(axis=1)),
        },
        index=authors,
    )
    return authors, L.astype(np.float32), M.tocsr(), stats


def pair_table(nb, index, ids, A, M, valid, n_random, rng):
    """Neighbour pairs (unordered, once) and random pairs, with both
    cosines."""
    i = index.get_indexer(nb["Article_ID"])
    j = index.get_indexer(nb["Neighbour_ID"])
    pairs = pd.DataFrame(
        {"i": np.minimum(i, j), "j": np.maximum(i, j), "method": nb["method"]}
    )
    g = pairs.groupby(["i", "j"])["method"].agg(["nunique", "first"]).reset_index()
    g["source"] = np.where(g["nunique"] > 1, "both", g["first"])
    pairs = g[["i", "j", "source"]]
    ri, rj = rng.integers(0, len(ids), n_random), rng.integers(0, len(ids), n_random)
    ok = (ri != rj) & valid[ri] & valid[rj]
    rnd = pd.DataFrame(
        {"i": np.minimum(ri, rj)[ok], "j": np.maximum(ri, rj)[ok], "source": "random"}
    )
    pairs = pd.concat([pairs, rnd.drop_duplicates(["i", "j"])], ignore_index=True)
    pairs["lsa"], pairs["mentions"] = pair_cosines(
        A, M, pairs["i"].to_numpy(), pairs["j"].to_numpy()
    )
    pairs["both_profiles"] = valid[pairs["i"]] & valid[pairs["j"]]
    pairs.insert(0, "b", ids[pairs["j"]])
    pairs.insert(0, "a", ids[pairs["i"]])
    return pairs.drop(columns=["i", "j"])


def shared_articles(pairs: pd.DataFrame, authorship: pd.DataFrame) -> np.ndarray:
    """Number of articles the two authors of each pair wrote together."""
    au = authorship.drop_duplicates(["Article_ID", "Phi_ID"])
    co = au.merge(au, on="Article_ID")
    co = co[co["Phi_ID_x"] < co["Phi_ID_y"]].groupby(["Phi_ID_x", "Phi_ID_y"]).size()
    keys = pd.MultiIndex.from_arrays([pairs["Phi_ID_a"], pairs["Phi_ID_b"]])
    return co.reindex(keys, fill_value=0).to_numpy()


def author_summary(pairs, stats, labels, min_articles, min_philosophers) -> str:
    ok = set(
        stats.index[
            (stats["lsa_articles"] >= min_articles)
            & (stats["philosophers"] >= min_philosophers)
        ]
    )
    # Co-authors share articles, hence trivially similar profiles.
    eligible = (
        pairs["Phi_ID_a"].isin(ok)
        & pairs["Phi_ID_b"].isin(ok)
        & (pairs["shared_articles"] == 0)
    )
    rnd = pairs[(pairs["source"] == "random") & eligible]
    nb = pairs[(pairs["source"] != "random") & eligible]
    rho = (
        spearmanr(rnd["lsa"], rnd["mentions"]).statistic
        if len(rnd) > 2
        else float("nan")
    )
    lines = [
        "# Author similarity (oeuvres)",
        "",
        f"Authors: {len(stats):,}; in the lists below those with at least {min_articles} "
        f"articles that pass the LSA filter and {min_philosophers} distinct "
        f"mentioned philosophers "
        f"({len(ok):,}), and only pairs without a joint article. Spearman ρ between LSA and mention cosine on {len(rnd):,} random "
        f"pairs: {rho:.3f}.",
        "",
    ]

    def name(p):
        return f"{labels.get(p, p)} ({p}, {stats.at[p, 'articles']} art.)".replace(
            "|", "/"
        )

    high_m, high_l = divergent(nb, 25)
    for title, rows in [
        (
            "Mention the same philosophers, write differently (top 10 % by mentions, lowest LSA)",
            high_m,
        ),
        (
            "Write alike, mention different philosophers (top 10 % by LSA, fewest shared mentions)",
            high_l,
        ),
    ]:
        lines += [
            f"## {title}",
            "",
            "| LSA | mentions | author a | author b |",
            "|---|---|---|---|",
        ]
        for r in rows.itertuples():
            lines.append(
                f"| {r.lsa:.3f} | {r.mentions:.3f} "
                f"| {name(r.Phi_ID_a)} | {name(r.Phi_ID_b)} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def write(df: pd.DataFrame, path: Path) -> None:
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), path)


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--fulltexts", required=True)
    p.add_argument("--mentions", required=True)
    p.add_argument("--articles", required=True)
    p.add_argument("--dimensions", type=int, default=300)
    p.add_argument("--lang", choices=sorted(FUNCTION_WORDS), default="en")
    p.add_argument("--min-df", type=int, default=5)
    p.add_argument("--max-df", type=float, default=0.5)
    p.add_argument(
        "--k", type=int, default=20, help="neighbours per article and method"
    )
    p.add_argument("--random-pairs", type=int, default=200_000)
    p.add_argument(
        "--summary-min-philosophers",
        type=int,
        default=5,
        help="distinct philosophers an article needs to enter the summary lists",
    )
    p.add_argument("--authorship", required=True, help="authorship.parquet")
    p.add_argument(
        "--philosophers", required=True, help="philosophers.parquet (labels)"
    )
    p.add_argument("--author-min-articles", type=int, default=3)
    p.add_argument("--author-min-philosophers", type=int, default=10)
    p.add_argument("--out-dir", required=True)
    args = p.parse_args(argv)
    setup_logging()

    texts = read_parquet(
        args.fulltexts, columns=["Article_ID", "FullText", "length_words"]
    ).sort_values("Article_ID")
    words = texts["length_words"].to_numpy()
    ids = texts["Article_ID"].to_numpy()
    index = pd.Index(ids)
    A, terms, idf, V, info = lsa(
        texts["FullText"].tolist(),
        args.dimensions,
        args.min_df,
        args.max_df,
        FUNCTION_WORDS[args.lang],
    )
    del texts
    english = info.pop("english")
    log.info("LSA: %s", info)
    M = mention_profiles(
        read_parquet(args.mentions, columns=["Article_ID", "Mentioned_Phi_ID"]), index
    )
    valid_m = np.asarray(M.getnnz(axis=1) > 0)
    # LSA neighbours only among English articles of some length: the
    # vectors of short or non-English texts are unstable.
    valid_a = (english >= MIN_ENGLISH_SHARE) & (words >= MIN_WORDS)
    rng = np.random.default_rng(0)
    nb = both_neighbours(A, M, ids, args.k, valid_a, valid_m)
    pairs = pair_table(nb, index, ids, A, M, valid_a & valid_m, args.random_pairs, rng)
    pairs = pairs.rename(columns={"a": "Article_ID_a", "b": "Article_ID_b"})

    # Oeuvres
    authorship = read_parquet(args.authorship, columns=["Article_ID", "Phi_ID"])
    mentions = read_parquet(args.mentions, columns=["Article_ID", "Mentioned_Phi_ID"])
    authors, L, MA, astats = author_profiles(A, mentions, authorship, index, valid_a)
    aids = authors.to_numpy()
    valid_l = astats["lsa_articles"].to_numpy() > 0
    valid_ma = astats["philosophers"].to_numpy() > 0
    anb = both_neighbours(L, MA, aids, args.k, valid_l, valid_ma)
    anb = anb.rename(columns={"Article_ID": "Phi_ID"})
    apairs = pair_table(
        anb.rename(columns={"Phi_ID": "Article_ID"}), authors, aids, L, MA,
        valid_ma & valid_l, args.random_pairs, rng,
    )  # fmt: skip
    apairs = apairs.rename(columns={"a": "Phi_ID_a", "b": "Phi_ID_b"})
    apairs["shared_articles"] = shared_articles(apairs, authorship)
    labels = read_parquet(args.philosophers, columns=["Phi_ID", "Phi_Standard_Label"])
    labels = dict(zip(labels["Phi_ID"], labels["Phi_Standard_Label"]))
    log.info("%d authors, %d author neighbour rows", len(authors), len(anb))

    meta = read_parquet(
        args.articles, columns=["Article_ID", "title", "publicationYear", "language"]
    ).set_index("Article_ID")
    rows = index.get_indexer(meta.index)
    meta["philosophers"] = np.asarray(M.getnnz(axis=1))[rows]
    meta["function_share"] = english[rows]
    meta["words"] = words[rows]
    with atomic_output(args.out_dir, directory=True) as tmp:
        write(
            pd.DataFrame({"Article_ID": ids, "lsa": list(A)}),
            tmp / "lsa_articles.parquet",
        )
        write(
            pd.DataFrame({"term": terms, "idf": idf, "lsa": list(V)}),
            tmp / "lsa_terms.parquet",
        )
        write(nb, tmp / "neighbours.parquet")
        write(
            meta[["language", "function_share", "words", "philosophers"]]
            .rename_axis("Article_ID")
            .reset_index(),
            tmp / "articles.parquet",
        )
        write(pairs, tmp / "pairs.parquet")
        write(
            astats.assign(label=[labels.get(p) for p in aids])
            .rename_axis("Phi_ID")
            .reset_index(),
            tmp / "authors.parquet",
        )
        write(
            pd.DataFrame({"Phi_ID": aids, "lsa": list(L)}), tmp / "lsa_authors.parquet"
        )
        write(
            anb.rename(columns={"Neighbour_ID": "Neighbour_Phi_ID"}),
            tmp / "author_neighbours.parquet",
        )
        write(apairs, tmp / "author_pairs.parquet")
        (tmp / "authors.md").write_text(
            author_summary(
                apairs,
                astats,
                labels,
                args.author_min_articles,
                args.author_min_philosophers,
            ),
            encoding="UTF-8",
        )
        (tmp / "similarity.md").write_text(
            summary(info, pairs, valid_m, meta, args.summary_min_philosophers),
            encoding="UTF-8",
        )
    log.info("wrote %s", args.out_dir)


if __name__ == "__main__":
    main()
