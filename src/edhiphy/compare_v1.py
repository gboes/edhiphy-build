"""Comparison of the text stages with edhiphy 1.0 (Phase 3 report).

Compares the cleaned texts, mentions, contexts and disambiguation of a
pipeline build with the v1 tables, on the same article set and
dictionary, and writes a Markdown report plus the mapping between v1 and
new Mention_IDs. v1 mentions are matched to new ones by (article,
``Ent_text``, n-th occurrence of that ``Ent_text`` in the article); v1's
own IDs number all spaCy entities and cannot be recomputed. The report
contains counts, identifiers and variant strings only, no text.

Differences listed in ``--known-deviations`` (CSV: ``kind``, ``key``,
``reason``) are reported as accepted.
"""

import difflib
import numbers
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

from edhiphy.common import (
    atomic_output,
    log,
    parser,
    read_curated_csv,
    read_parquet,
    setup_logging,
    write_parquet,
)

# Provisional thresholds (src/legacy/README.md).
THRESHOLDS = {
    "clean_exact": 0.999,
    "mentions_recovered": 0.995,
    "mentions_new": 0.005,
    "contexts_equal": 0.995,
    "disambiguation_agree": 0.99,
    "status_share_points": 0.2,
}


# Character diffs (quadratic) are computed for this many articles only.
MAX_DIFFS = 100


def occurrence_key(df: pd.DataFrame) -> pd.Series:
    n = df.groupby(["Article_ID", "Ent_text"]).cumcount()
    return df["Article_ID"] + "\t" + df["Ent_text"] + "\t" + n.astype(str)


def first_difference(a: str, b: str) -> int:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


def compare_texts(new: pd.DataFrame, v1: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    j = v1.merge(
        new, on="Article_ID", how="outer", suffixes=("_v1", "_new"), indicator=True
    )
    both = j[j["_merge"] == "both"]
    equal = both["FullText_v1"] == both["FullText_new"]
    diffs = []
    for k, (_, r) in enumerate(both[~equal].iterrows()):
        a, b = r["FullText_v1"], r["FullText_new"]
        changed = None
        if k < MAX_DIFFS:
            sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
            changed = sum(
                max(i2 - i1, j2 - j1)
                for op, i1, i2, j1, j2 in sm.get_opcodes()
                if op != "equal"
            )
        diffs.append(
            {
                "Article_ID": r["Article_ID"],
                "len_v1": len(a),
                "len_new": len(b),
                "first_difference": first_difference(a, b),
                "changed_chars": changed,
            }
        )
    stats = {
        "articles_v1": int((j["_merge"] != "right_only").sum()),
        "articles_new": int((j["_merge"] != "left_only").sum()),
        "only_v1": int((j["_merge"] == "left_only").sum()),
        "only_new": int((j["_merge"] == "right_only").sum()),
        "equal": int(equal.sum()),
        "exact_rate": float(equal.mean()) if len(both) else 1.0,
    }
    return stats, pd.DataFrame(diffs)


def match_mentions(new: pd.DataFrame, v1: pd.DataFrame) -> pd.DataFrame:
    new = new.assign(key=occurrence_key(new))
    v1 = v1.assign(key=occurrence_key(v1))
    return v1.merge(
        new, on="key", how="outer", suffixes=("_v1", "_new"), indicator=True
    )


def idset(s: pd.Series) -> pd.Series:
    return s.map(
        lambda x: frozenset(x.split("|")) if isinstance(x, str) else frozenset()
    )


def table(df: pd.DataFrame) -> str:
    """A DataFrame as a Markdown table."""
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(fmt(v) for v in row) + " |")
    return "\n".join(lines)


def fmt(v) -> str:
    if isinstance(v, numbers.Real) and not isinstance(v, numbers.Integral):
        v = float(v)
        return f"{v:,.4f}" if abs(v) < 1000 else f"{v:,.0f}"
    if isinstance(v, numbers.Integral) and not isinstance(v, bool):
        return f"{v:,}"
    return str(v).replace("|", "\\|")


def gate(name: str, ok: bool) -> str:
    return f"**{'pass' if ok else 'FAIL'}** ({name})"


def report(args) -> tuple[str, pd.DataFrame]:
    out = []
    known = (
        read_curated_csv(args.known_deviations)
        if args.known_deviations
        else pd.DataFrame(columns=["kind", "key", "reason"])
    )
    accepted = {(k, key) for k, key in zip(known["kind"], known["key"])}

    # Texts
    new_texts = read_parquet(args.fulltexts, columns=["Article_ID", "FullText"])
    v1_texts = read_curated_csv(args.v1_fulltexts, usecols=["Article_ID", "FullText"])
    v1_texts = v1_texts.dropna(subset=["Article_ID"])
    v1_texts = v1_texts[v1_texts["Article_ID"].isin(set(new_texts["Article_ID"]))]
    ts, tdiff = compare_texts(new_texts, v1_texts)
    out += [
        "## 1. Cleaned texts (stage 6)",
        "",
        f"Articles: {ts['articles_new']:,} (v1: {ts['articles_v1']:,} of the selection; "
        f"only in v1 {ts['only_v1']}, only new {ts['only_new']}). "
        f"Identical cleaned text: {ts['equal']:,} ({ts['exact_rate']:.4%}). "
        + gate(
            f"≥ {THRESHOLDS['clean_exact']:.1%}",
            ts["exact_rate"] >= THRESHOLDS["clean_exact"],
        ),
        "",
    ]
    if len(tdiff):
        tdiff["accepted"] = [("text", a) in accepted for a in tdiff["Article_ID"]]
        out += [table(tdiff.sort_values("changed_chars", ascending=False).head(30)), ""]

    # Mentions
    raw = read_parquet(args.raw_mentions, columns=["Mention_ID", "start"])
    new = read_parquet(args.mentions).merge(raw, on="Mention_ID", how="left")
    v1 = read_curated_csv(args.v1_mentions)
    v1 = v1[v1["Article_ID"].isin(set(new_texts["Article_ID"]))]
    j = match_mentions(new, v1)
    both = j[j["_merge"] == "both"]
    only_v1 = j[j["_merge"] == "left_only"]
    only_new = j[j["_merge"] == "right_only"]
    recovered = len(both) / len(v1) if len(v1) else 1.0
    extra = len(only_new) / len(new) if len(new) else 0.0
    out += [
        "## 2. Mentions (stage 7)",
        "",
        f"v1: {len(v1):,} mentions; new: {len(new):,}. Matched by (article, Ent_text, "
        f"occurrence): {len(both):,}. Recovered {recovered:.4%} "
        + gate(
            f"≥ {THRESHOLDS['mentions_recovered']:.1%}",
            recovered >= THRESHOLDS["mentions_recovered"],
        )
        + f"; new mentions not in v1 {len(only_new):,} ({extra:.4%}) "
        + gate(
            f"≤ {THRESHOLDS['mentions_new']:.1%}", extra <= THRESHOLDS["mentions_new"]
        )
        + ".",
        "",
    ]
    for what, part in [("only in v1", only_v1), ("only new", only_new)]:
        col = "Ent_text_v1" if what == "only in v1" else "Ent_text_new"
        if len(part):
            top = (
                part[col]
                .value_counts()
                .head(15)
                .rename_axis("Ent_text")
                .reset_index(name="mentions")
            )
            out += [f"Most frequent variants {what}:", "", table(top), ""]

    # Contexts
    ctx_new = read_parquet(args.contexts, columns=["Mention_ID", "Mention_context"])
    ctx_v1 = read_curated_csv(
        args.v1_contexts, usecols=["Mention_ID", "Mention_context"]
    )
    m = both[["Mention_ID_v1", "Mention_ID_new", "start"]]
    m = m.merge(
        ctx_v1.rename(
            columns={"Mention_ID": "Mention_ID_v1", "Mention_context": "ctx_v1"}
        ),
        on="Mention_ID_v1",
    )
    m = m.merge(
        ctx_new.rename(
            columns={"Mention_ID": "Mention_ID_new", "Mention_context": "ctx_new"}
        ),
        on="Mention_ID_new",
    )
    near = m["start"] < args.context_chars
    eq = m["ctx_v1"] == m["ctx_new"]
    rate = eq[~near].mean() if (~near).any() else 1.0
    out += [
        "## 3. Contexts (stage 8)",
        "",
        f"Matched mentions with both contexts: {len(m):,}. Mentions starting within "
        f"{args.context_chars} characters of the text start (v1 left context empty, fixed): "
        f"{near.sum():,}, of which identical {eq[near].sum():,}. Other mentions: identical "
        f"{eq[~near].sum():,} of {(~near).sum():,} ({rate:.4%}) "
        + gate(
            f"≥ {THRESHOLDS['contexts_equal']:.1%}",
            rate >= THRESHOLDS["contexts_equal"],
        )
        + ".",
        "",
    ]

    # Disambiguation
    sv = v1["Disambiguation_status"].value_counts(normalize=True).rename("v1")
    sn = new["Disambiguation_status"].value_counts(normalize=True).rename("new")
    shares = pd.concat([sv, sn], axis=1).fillna(0.0)
    shares["difference (points)"] = (shares["new"] - shares["v1"]) * 100
    counts = (
        pd.concat(
            [
                v1["Disambiguation_status"].value_counts().rename("v1 n"),
                new["Disambiguation_status"].value_counts().rename("new n"),
            ],
            axis=1,
        )
        .fillna(0)
        .astype(int)
    )
    shares = shares.join(counts).rename_axis("status").reset_index()
    max_points = shares["difference (points)"].abs().max()
    same_status = both["Disambiguation_status_v1"] == both["Disambiguation_status_new"]
    same_id = idset(both["Disambiguated_ID_v1"]) == idset(both["Disambiguated_ID_new"])
    agree = (same_status & same_id).mean() if len(both) else 1.0
    out += [
        "## 4. Disambiguation (stage 9)",
        "",
        table(shares),
        "",
        f"Largest share difference: {max_points:.3f} points "
        + gate(
            f"≤ {THRESHOLDS['status_share_points']}",
            max_points <= THRESHOLDS["status_share_points"],
        )
        + f". Per matched mention, same status and Disambiguated_ID (as set): {agree:.4%} "
        + gate(
            f"≥ {THRESHOLDS['disambiguation_agree']:.0%}",
            agree >= THRESHOLDS["disambiguation_agree"],
        )
        + ".",
        "",
    ]
    diff = both[~(same_status & same_id)]
    if len(diff):
        ct = pd.crosstab(
            diff["Disambiguation_status_v1"], diff["Disambiguation_status_new"]
        )
        ct = ct.rename_axis(None, axis=1).rename_axis("v1 \\ new").reset_index()
        out += [
            "Disagreements (rows: v1 status, columns: new status):",
            "",
            table(ct),
            "",
        ]

    # Per philosopher
    cv = v1["Mentioned_Phi_ID"].value_counts().rename("v1")
    cn = new["Mentioned_Phi_ID"].value_counts().rename("new")
    per = pd.concat([cv, cn], axis=1).fillna(0).astype(int)
    rho = spearmanr(per["v1"], per["new"]).statistic if len(per) > 1 else 1.0
    top = per.sort_values("v1", ascending=False).head(1000)
    rho_top = spearmanr(top["v1"], top["new"]).statistic if len(top) > 1 else 1.0
    per["difference"] = per["new"] - per["v1"]
    big = per.reindex(per["difference"].abs().sort_values(ascending=False).index).head(
        15
    )
    out += [
        "## 5. Mentions per philosopher (Mentioned_Phi_ID)",
        "",
        f"Philosophers with mentions: v1 {int((per['v1'] > 0).sum()):,}, new "
        f"{int((per['new'] > 0).sum()):,}. Spearman ρ of the counts: {rho:.5f} (all), "
        f"{rho_top:.5f} (top 1,000 of v1).",
        "",
    ]
    if (big["difference"] != 0).any():
        out += [
            "Largest differences:",
            "",
            table(big.rename_axis("Phi_ID").reset_index()),
            "",
        ]

    mapping = both[["Mention_ID_v1", "Mention_ID_new"]].rename(
        columns={"Mention_ID_v1": "Mention_ID_v1", "Mention_ID_new": "Mention_ID"}
    )
    header = [
        "# Comparison with edhiphy 1.0",
        "",
        "Generated by `make compare-v1`. Thresholds are provisional (see "
        "`src/legacy/README.md`). The mapping of v1 to new Mention_IDs is in "
        "`v1_mention_map.parquet` next to this report.",
        "",
    ]
    return "\n".join(header + out) + "\n", mapping


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--fulltexts", required=True)
    p.add_argument("--raw-mentions", required=True)
    p.add_argument("--mentions", required=True)
    p.add_argument("--contexts", required=True)
    p.add_argument("--v1-fulltexts", required=True)
    p.add_argument("--v1-mentions", required=True)
    p.add_argument("--v1-contexts", required=True)
    p.add_argument("--known-deviations")
    p.add_argument("--context-chars", type=int, default=100)
    p.add_argument("--out", required=True, help="Markdown report")
    p.add_argument("--out-map", required=True, help="v1 -> new Mention_ID (parquet)")
    args = p.parse_args(argv)
    setup_logging()
    text, mapping = report(args)
    with atomic_output(args.out) as tmp:
        Path(tmp).write_text(text, encoding="UTF-8")
    log.info("wrote %s", args.out)
    write_parquet(mapping, args.out_map)


if __name__ == "__main__":
    main()
