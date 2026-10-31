"""Stage 4 (dictionary): philosophers, variants, Wikidata entries and
biographies.

The v1 tables are frozen inputs. Additive layers (French Wikidata labels,
new philosophers) follow in later phases; therefore the ambiguity of each
variant is recomputed over the whole dictionary instead of being taken
from the frozen table. Rules of v1: variants with an ``Issue_level`` are
``Unvalid_variant`` with no candidates; among the others, a variant string
shared by several philosophers is ``Ambiguous``, otherwise ``Univocal``.
``Matching_Phi_IDs`` lists the candidates sorted as strings, joined by
``|``. Rows where the recomputed values differ from the frozen ones are
written to ``--out-changes``.

Corrections layer: ``--merges`` (``data/manual/philosopher_merges.csv``)
lists philosophers that duplicate another entry (issue #14). Each merged
Phi_ID disappears; its variants move to the target (a variant string the
target already has is dropped), the source flags (Wiki, JSTOR, Hiring,
PhD) are combined, and ``merges.parquet`` maps the merged IDs to their
targets for the later stages. The optional column ``Wiki_ID`` (a QID or
an entity URL) replaces the target's Wikidata entry, e.g. by the item
that survived a merge on Wikidata; it must be in the Wikidata table. ``--drops`` removes philosophers that are
not expected in the corpus (with their variants and biography);
``--variant-additions`` adds variants by hand (``Variant_ID``
``<Phi_ID>_m<n>``, origin ``Manual``).

Unique labels (issue #9): every philosopher whose ``Phi_Standard_Label``
is shared with another gets a suffix with the life dates of its Wikidata
entry (``--wiki-dates``, from ``edhiphy.wikidata_dates``): "(1847–1939)",
"(b. 1847)" or "(d. 1939)", "(c. 535–c. 475 BC)" (text by
``edhiphy.life_dates``; "c." for uncertain years); where no year is known, or the years do not
separate the group, "(P:123)". ``Phi_Standard_Label_legacy`` keeps the v1
label. ``life_dates.parquet`` holds the numeric life dates of every
philosopher with a dated Wikidata entry (``Philosopher_Life_Dates``).

Language layers (``--layer-lang`` with ``--layer-labels``,
``--layer-philosophers``, ``--layer-authors``; ``edhiphy.dictionary_layers``)
are added after the corrections. ``--fold-diacritics`` (French corpus)
computes the ambiguity over variants with diacritics folded, as stage 7
matches them; then "Lévi" and "Levi" are one string. The changes file
compares the frozen and corrected rows only, not the layer's rows.
"""

import numpy as np
import pandas as pd

from edhiphy import dictionary_layers
from edhiphy.common import (
    atomic_output,
    check_unique,
    fold_diacritics,
    log,
    parser,
    read_curated_csv,
    setup_logging,
    write_parquet,
)
from edhiphy.life_dates import life_dates_text

AMBIGUITY_COLUMNS = ["Ambiguity", "Matching_Phi_IDs", "N_Multiple_Phi_IDs"]


def compute_ambiguity(variants: pd.DataFrame, fold: bool = False) -> pd.DataFrame:
    valid = variants["Issue_level"].isna()
    key = variants["Variant"].map(fold_diacritics) if fold else variants["Variant"]
    groups = variants[valid].groupby(key[valid])["Phi_ID"]
    matching = groups.agg(lambda s: "|".join(sorted(set(s))))
    n = groups.nunique()
    out = variants.copy()
    out["Matching_Phi_IDs"] = key.map(matching).where(valid)
    out["N_Multiple_Phi_IDs"] = key.map(n).where(valid, 0).astype(int)
    out["Ambiguity"] = np.where(
        ~valid,
        "Unvalid_variant",
        np.where(out["N_Multiple_Phi_IDs"] == 1, "Univocal", "Ambiguous"),
    )
    return out


def ambiguity_changes(frozen: pd.DataFrame, recomputed: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in AMBIGUITY_COLUMNS:
        a = frozen[column]
        b = recomputed[column]
        differs = ~((a == b) | (a.isna() & b.isna()))
        if column == "N_Multiple_Phi_IDs":
            differs &= ~(a.astype(float) == b.astype(float))
        for i in frozen.index[differs]:
            same_set = None
            if column == "Matching_Phi_IDs":
                same_set = set(str(a[i]).split("|")) == set(str(b[i]).split("|"))
            rows.append(
                {
                    "Variant_ID": frozen.at[i, "Variant_ID"],
                    "column": column,
                    "frozen": a[i],
                    "recomputed": b[i],
                    "same_set": same_set,
                }
            )
    return pd.DataFrame(
        rows, columns=["Variant_ID", "column", "frozen", "recomputed", "same_set"]
    )


FLAGS = ["Wiki", "JSTOR", "Hiring", "PhD"]


WIKIDATA_ENTITY = "http://www.wikidata.org/entity/"


def merge_wiki_ids(merges) -> dict:
    """Target Phi_ID -> Wiki_ID entity URL from the optional ``Wiki_ID``
    column of the merges; one value per target."""
    if "Wiki_ID" not in merges:
        return {}
    given = merges.dropna(subset=["Wiki_ID"])
    if given.empty:
        return {}
    given = given.assign(
        Wiki_ID=given["Wiki_ID"]
        .str.strip()
        .map(lambda w: w if w.startswith(WIKIDATA_ENTITY) else WIKIDATA_ENTITY + w)
    )
    n = given.groupby("Phi_ID")["Wiki_ID"].nunique()
    if (n > 1).any():
        raise SystemExit(f"merges: several Wiki_IDs for {sorted(n.index[n > 1])}")
    return dict(zip(given["Phi_ID"], given["Wiki_ID"]))


def apply_merges(merges, philosophers, variants, biography):
    """Merge each ``Merged_Phi_ID`` into its ``Phi_ID`` (see the module
    docstring)."""
    if merges.empty:
        return philosophers, variants, biography
    check_unique(merges, ["Merged_Phi_ID"], "merges")
    known = set(philosophers["Phi_ID"])
    missing = (set(merges["Merged_Phi_ID"]) | set(merges["Phi_ID"])) - known
    if missing:
        raise SystemExit(f"merges: unknown Phi_IDs {sorted(missing)}")
    chained = set(merges["Phi_ID"]) & set(merges["Merged_Phi_ID"])
    if chained:
        raise SystemExit(
            f"merges: targets that are merged themselves {sorted(chained)}"
        )
    target = dict(zip(merges["Merged_Phi_ID"], merges["Phi_ID"]))
    ids = philosophers["Phi_ID"].map(lambda i: target.get(i, i))
    flags = philosophers[FLAGS].groupby(ids).max()
    philosophers = philosophers[~philosophers["Phi_ID"].isin(target)].copy()
    philosophers[FLAGS] = flags.loc[philosophers["Phi_ID"]].to_numpy()
    new_wiki = merge_wiki_ids(merges)
    if new_wiki:
        is_target = philosophers["Phi_ID"].isin(new_wiki)
        philosophers.loc[is_target, "Wiki_ID"] = philosophers.loc[
            is_target, "Phi_ID"
        ].map(new_wiki)
        philosophers.loc[is_target, "Wiki"] = 1
        log.info("Wiki_ID of %d merge targets replaced", len(new_wiki))
    moved = variants["Phi_ID"].isin(target)
    variants = variants.assign(
        Phi_ID=variants["Phi_ID"].map(lambda i: target.get(i, i))
    )
    # Keep the target's own variants first, then the moved ones.
    variants = (
        variants.assign(_moved=moved)
        .sort_values("_moved", kind="stable")
        .drop_duplicates(["Phi_ID", "Variant"])
        .sort_index()
        .drop(columns="_moved")
    )
    biography = biography[~biography["Phi_ID"].isin(target)]
    kept = int(variants.index.isin(moved.index[moved]).sum())
    log.info(
        "merged %d philosophers into %d; %d variants moved, %d dropped as duplicates",
        len(target),
        merges["Phi_ID"].nunique(),
        kept,
        int(moved.sum()) - kept,
    )
    return philosophers, variants, biography


def drop_philosophers(drops, philosophers, variants, biography):
    if drops.empty:
        return philosophers, variants, biography
    missing = set(drops["Phi_ID"]) - set(philosophers["Phi_ID"])
    if missing:
        raise SystemExit(f"drops: unknown Phi_IDs {sorted(missing)}")
    gone = set(drops["Phi_ID"])
    used = philosophers[philosophers["Phi_ID"].isin(gone)]
    used = used[used[["JSTOR", "Hiring", "PhD"]].any(axis=1)]
    if not used.empty:
        raise SystemExit(
            f"drops: philosophers with JSTOR, hiring or PhD data {used['Phi_ID'].tolist()}"
        )
    log.info("dropped %d philosophers", len(gone))
    return (
        philosophers[~philosophers["Phi_ID"].isin(gone)],
        variants[~variants["Phi_ID"].isin(gone)],
        biography[~biography["Phi_ID"].isin(gone)],
    )


def add_variants(additions, philosophers, variants):
    if additions.empty:
        return variants
    missing = set(additions["Phi_ID"]) - set(philosophers["Phi_ID"])
    if missing:
        raise SystemExit(f"variant additions: unknown Phi_IDs {sorted(missing)}")
    rows = additions[["Phi_ID", "Variant"]].copy()
    rows["Variant_ID"] = (
        rows["Phi_ID"] + "_m" + (rows.groupby("Phi_ID").cumcount() + 1).astype(str)
    )
    rows["Variant_origin"] = "Manual"
    rows["Variant_length"] = rows["Variant"].str.len()
    out = pd.concat([variants, rows], ignore_index=True)
    check_unique(out, ["Variant_ID"], "variants with additions")
    log.info("added %d variants", len(rows))
    return out


DATE_COLUMNS = {
    "birthYear": "Birth_Year",
    "birthUncertain": "Birth_Uncertain",
    "deathYear": "Death_Year",
    "deathUncertain": "Death_Uncertain",
}


def philosopher_dates(philosophers, dates) -> pd.DataFrame:
    """Life dates per Phi_ID from its (first) Wiki_ID: integers, BC
    negative, with uncertainty flags (see ``edhiphy.wikidata_dates``)."""
    wiki = philosophers["Wiki_ID"].astype("string").str.split("|").str[0]
    d = dates.set_index("Wiki_ID").reindex(wiki.to_numpy())
    out = pd.DataFrame(
        {"Phi_ID": philosophers["Phi_ID"].to_numpy(), "Wiki_ID": wiki.to_numpy()}
    )
    for src, dst in DATE_COLUMNS.items():
        values = d[src] if src in d else pd.Series(pd.NA, index=d.index)
        out[dst] = pd.array(values.to_numpy(), dtype="Int64")
    return out[out["Birth_Year"].notna() | out["Death_Year"].notna()].reset_index(
        drop=True
    )


def life_dates(philosophers, dates) -> pd.Series:
    """Suffix text per Phi_ID (``edhiphy.life_dates``); None if unknown."""
    d = philosopher_dates(philosophers, dates).set_index("Phi_ID")
    d = d.reindex(philosophers["Phi_ID"])
    return pd.Series(
        [
            life_dates_text(*r)
            for r in d[list(DATE_COLUMNS.values())].itertuples(index=False)
        ],
        index=d.index,
        dtype=object,
    )


def unique_labels(philosophers, dates) -> pd.DataFrame:
    """Suffix shared labels (see the module docstring)."""
    label = philosophers["Phi_Standard_Label"]
    shared = label.duplicated(keep=False)
    years = life_dates(philosophers, dates).reindex(philosophers["Phi_ID"]).to_numpy()
    suffix = pd.Series(years, index=philosophers.index).where(shared)
    # Years that do not separate the members of a group fall back to the ID.
    clash = suffix.isna() | pd.Series(
        list(zip(label, suffix)), index=philosophers.index
    ).duplicated(keep=False)
    suffix = suffix.mask(shared & clash, philosophers["Phi_ID"])
    out = philosophers.copy()
    out["Phi_Standard_Label_legacy"] = label
    out["Phi_Standard_Label"] = label.where(~shared, label + " (" + suffix + ")")
    check_unique(out, ["Phi_Standard_Label"], "labels")
    log.info(
        "unique labels: %d philosophers in %d shared labels; %d by dates, %d by Phi_ID",
        int(shared.sum()),
        label[shared].nunique(),
        int((shared & ~clash).sum()),
        int((shared & clash).sum()),
    )
    return out


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--philosophers", required=True)
    p.add_argument("--variants", required=True)
    p.add_argument("--wiki", required=True)
    p.add_argument("--biography", required=True)
    p.add_argument("--merges", help="CSV: Merged_Phi_ID, Phi_ID, Reason")
    p.add_argument("--drops", help="CSV: Phi_ID, Reason")
    p.add_argument("--variant-additions", help="CSV: Phi_ID, Variant, Reason")
    p.add_argument("--wiki-dates", nargs="+", help="CSVs of edhiphy.wikidata_dates")
    p.add_argument("--layer-lang", help="language of the layer, e.g. fr")
    p.add_argument("--layer-labels", nargs="+", help="CSVs of edhiphy.wikidata_labels")
    p.add_argument(
        "--layer-philosophers", nargs="+", help="CSVs of edhiphy.wikidata_philosophers"
    )
    p.add_argument(
        "--layer-authors", nargs="+", help="new-author CSVs of edhiphy.jstor_authors"
    )
    p.add_argument("--layer-issues", help="CSV: Variant, Issue_level, Reason")
    p.add_argument("--fold-diacritics", action="store_true")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--out-changes", required=True, help="CSV")
    args = p.parse_args(argv)
    setup_logging()

    philosophers = read_curated_csv(args.philosophers)
    variants = read_curated_csv(args.variants)
    wiki = read_curated_csv(args.wiki)
    biography = read_curated_csv(args.biography)
    check_unique(philosophers, ["Phi_ID"], args.philosophers)
    check_unique(variants, ["Variant_ID"], args.variants)
    check_unique(wiki, ["Wiki_ID"], args.wiki)
    merges = (
        read_curated_csv(args.merges)
        if args.merges
        else pd.DataFrame(columns=["Merged_Phi_ID", "Phi_ID"])
    )
    unknown = set(merge_wiki_ids(merges).values()) - set(wiki["Wiki_ID"])
    if unknown:
        raise SystemExit(f"merges: Wiki_IDs not in {args.wiki}: {sorted(unknown)}")
    philosophers, variants, biography = apply_merges(
        merges, philosophers, variants, biography
    )
    merges = merges[["Merged_Phi_ID", "Phi_ID"]]
    if args.drops:
        philosophers, variants, biography = drop_philosophers(
            read_curated_csv(args.drops), philosophers, variants, biography
        )
    if args.variant_additions:
        variants = add_variants(
            read_curated_csv(args.variant_additions), philosophers, variants
        )
    dates = (
        pd.concat([read_curated_csv(f) for f in args.wiki_dates], ignore_index=True)
        if args.wiki_dates
        else pd.DataFrame(columns=["Wiki_ID", *DATE_COLUMNS])
    )
    check_unique(dates, ["Wiki_ID"], "wiki dates")
    corrected = variants
    if args.layer_lang:
        philosophers, variants, wiki, biography = dictionary_layers.add_layer(
            args.layer_lang,
            philosophers,
            variants,
            wiki,
            biography,
            dates,
            labels=dictionary_layers.read_layer(args.layer_labels),
            new_wiki=dictionary_layers.read_layer(args.layer_philosophers),
            new_authors=dictionary_layers.read_layer(args.layer_authors),
            fold=args.fold_diacritics,
            issues=read_curated_csv(args.layer_issues) if args.layer_issues else None,
        )
        check_unique(wiki, ["Wiki_ID"], "wiki with layer")
    philosophers = unique_labels(philosophers, dates)
    unknown = set(variants["Phi_ID"]) - set(philosophers["Phi_ID"])
    if unknown:
        raise SystemExit(f"variants of unknown philosophers: {sorted(unknown)[:5]}")

    recomputed = compute_ambiguity(variants, args.fold_diacritics)
    changes = ambiguity_changes(corrected, recomputed.loc[corrected.index])
    log.info(
        "ambiguity recomputed: %d differences to the frozen table (%d only in order)",
        len(changes),
        int(changes["same_set"].fillna(False).sum()),
    )
    with atomic_output(args.out_changes) as tmp:
        changes.to_csv(tmp, index=False)
    write_parquet(philosophers, f"{args.out_dir}/philosophers.parquet")
    write_parquet(recomputed, f"{args.out_dir}/variants.parquet")
    write_parquet(wiki, f"{args.out_dir}/wiki.parquet")
    write_parquet(biography, f"{args.out_dir}/biography.parquet")
    write_parquet(merges, f"{args.out_dir}/merges.parquet")
    write_parquet(
        philosopher_dates(philosophers, dates), f"{args.out_dir}/life_dates.parquet"
    )


if __name__ == "__main__":
    main()
