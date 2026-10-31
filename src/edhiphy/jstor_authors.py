"""Match the JSTOR creators of a delivery to the dictionary (not a
pipeline stage; for corpora without a v1 authorship table, i.e. French).

Input: the delivery's metadata CSV (research articles, ``creator``
``; ``-separated) and the dictionary of the corpus built without the
author layer (``philosophers.parquet``, ``variants.parquet`` of the
dictionary stage). Each creator name is normalised (``<prefix>`` tags and
titles such as "Abbé" removed, not "M.", which may be an initial, capitals in the usual case,
``name_variants.name_case``) and looked up, with diacritics folded,
among the valid variants with at least two words (ligatures spelt out,
case ignored), first as written, then
as first and last word:

- ``variant``: a univocal variant names the author;
- ``ambiguous_jstor``: an ambiguous variant whose candidates include
  exactly one JSTOR author of the dictionary names that author;
- ``initials``: a name of initials and surname ("P.-M. Schuhl") that is
  the initials variant of exactly one full name found by the steps above
  or among the new authors;
- ``new``: otherwise a new philosopher (JSTOR flag, no Wiki_ID), one per
  normalised name (folded); ``ambiguous_new`` if an ambiguous variant was
  found but not resolved.

Articles without creators get ``P:1`` (``[No Author]``) with position 0,
as in v1. New Phi_IDs follow the largest Phi_ID of ``--after``, in the
order of the folded names.

Outputs: ``--out-authorship`` (format of the v1 authorship table:
``Phi_ID``, ``author_position``, ``original_JSTOR_author``,
``Article_ID``), ``--out-authors`` (the new philosophers: ``Phi_ID``,
``Phi_Standard_Label``, ``JSTOR_names``, ``N_articles``; layer input of
the dictionary stage), both curated inputs (``DATA_DIR/curated/<corpus>``,
``data/MANIFEST.sha256``); ``--out-review``: one row per distinct creator
name with its match, for review by experts (columns ``Correct``,
``Comment`` empty).
"""

import re

import pandas as pd

from edhiphy import name_variants
from edhiphy.common import (
    atomic_output,
    fold_diacritics,
    log,
    parser,
    read_curated_csv,
    read_parquet,
    setup_logging,
)

NO_AUTHOR = "P:1"
TAG = re.compile(r"<(\w+)>.*?</\1>")
TITLES = re.compile(
    r"^(?:(?:Le |Le Très )?R\. ?P\. |Abbé |Mgr |Chanoine |Dom |Père |Dr\.? |"
    r"Docteur |Prof\.? |Professeur |Mme |Mlle )+"
)
INITIALS = re.compile(r"^(?:[A-ZÀ-Ý][a-zà-ÿ]?\.(?:-[A-ZÀ-Ý]\.)?\s+)+(\S.*)$")


def normalise(creator: str) -> str:
    name = TAG.sub("", creator)
    name = re.sub(r"\s+", " ", name).strip()
    name = TITLES.sub("", name).strip()
    return name_variants.name_case(name)


def key(name: str) -> str:
    """Comparison key: diacritics folded, ligatures spelt out, case folded."""
    k = fold_diacritics(name).casefold()
    return k.replace("œ", "oe").replace("æ", "ae")


def lookup_table(variants: pd.DataFrame) -> dict:
    valid = variants[variants["Issue_level"].isna()]
    valid = valid[valid["Variant"].str.contains(" ", regex=False)]
    return dict(zip(valid["Variant"].map(key), valid["Matching_Phi_IDs"]))


def match_name(name: str, table: dict, jstor: set) -> tuple:
    """(Phi_ID or None, rule, candidates)."""
    words = name.split()
    keys = [key(name)]
    if len(words) >= 3:
        keys.append(key(f"{words[0]} {words[-1]}"))
    for k in keys:
        ids = table.get(k)
        if ids is None:
            continue
        cands = ids.split("|")
        if len(cands) == 1:
            return cands[0], "variant", ids
        authors = [c for c in cands if c in jstor]
        if len(authors) == 1:
            return authors[0], "ambiguous_jstor", ids
        return None, "ambiguous_new", ids
    return None, "new", None


def initials_key(name: str):
    """Key of a name of initials and a surname ("P.-M. Schuhl"), or None
    (also for initials only, "J.-M. D.")."""
    m = INITIALS.match(name)
    if not m or "." in m.group(1) or len(m.group(1)) < 2:
        return None
    return key(name) if m.group(1)[0].isupper() else None


def full_name_keys(name: str, phi_id: str) -> list:
    words = name.split()
    if len(words) < 2 or "." in words[0]:
        return []
    return [key(v) for v in name_variants.artificial_variants(words[:1], words[-1:])]


def standard_label(names: pd.Series) -> str:
    """The most frequent spelling, preferring full given names to
    initials; ties by sort order."""
    counts = names.value_counts().sort_index()
    full = counts[[not n.split()[0].endswith(".") for n in counts.index]]
    return (full if len(full) else counts).idxmax()


def match_authors(meta: pd.DataFrame, philosophers, variants, first_id: int):
    rows = []
    for a, c in zip(meta["Article_ID"], meta["creator"]):
        if pd.isna(c) or not str(c).strip():
            rows.append((a, 0, None))
            continue
        for i, name in enumerate(str(c).split("; "), 1):
            rows.append((a, i, name))
    auth = pd.DataFrame(rows, columns=["Article_ID", "author_position", "creator"])
    names = auth["creator"].dropna().drop_duplicates()
    table = lookup_table(variants)
    jstor = set(philosophers.loc[philosophers["JSTOR"] == 1, "Phi_ID"])
    res = pd.DataFrame({"creator": names})
    res["name"] = res["creator"].map(normalise)
    matched = [match_name(n, table, jstor) for n in res["name"]]
    res["Phi_ID"] = [m[0] for m in matched]
    res["rule"] = [m[1] for m in matched]
    res["candidates"] = [m[2] for m in matched]

    # New authors: one per folded name; Phi_IDs in that order.
    res["key"] = res["name"].map(key)
    unmatched = res[res["Phi_ID"].isna()]
    # Initials names that resolve to exactly one full name (matched or new).
    full = {}
    for n, p in zip(res["name"], res["Phi_ID"].fillna(res["key"])):
        for k in full_name_keys(n, p):
            full.setdefault(k, set()).add(p)
    for i in unmatched.index:
        k = initials_key(res.at[i, "name"])
        target = full.get(k) if k else None
        if target and len(target) == 1:
            t = next(iter(target))
            if t != res.at[i, "key"]:
                res.at[i, "Phi_ID"] = t  # a Phi_ID or the key of a new author
                res.at[i, "rule"] = "initials"
    is_new = res["Phi_ID"].isna()
    new_keys = sorted(set(res.loc[is_new, "key"]))
    new_id = {k: f"P:{first_id + n}" for n, k in enumerate(new_keys)}
    res.loc[is_new, "Phi_ID"] = res.loc[is_new, "key"]
    res["Phi_ID"] = res["Phi_ID"].map(lambda p: new_id.get(p, p))
    unresolved = set(res["Phi_ID"]) - set(new_id.values()) - set(philosophers["Phi_ID"])
    if unresolved:
        # An initials name pointing at a new author whose key had no ID.
        raise SystemExit(f"unresolved author keys: {sorted(unresolved)[:5]}")

    auth = auth.merge(
        res[["creator", "name", "Phi_ID", "rule"]], on="creator", how="left"
    )
    auth["Phi_ID"] = auth["Phi_ID"].fillna(NO_AUTHOR)
    auth["rule"] = auth["rule"].fillna("no_creator")
    auth = auth.drop_duplicates(["Article_ID", "Phi_ID"])
    authorship = auth.rename(columns={"creator": "original_JSTOR_author"})[
        ["Phi_ID", "author_position", "original_JSTOR_author", "Article_ID"]
    ]

    n_articles = auth.groupby("Phi_ID")["Article_ID"].nunique()
    new = auth[auth["Phi_ID"].isin(set(new_id.values()))].rename(
        columns={"creator": "original_JSTOR_author"}
    )
    authors = (
        new.groupby("Phi_ID")
        .agg(
            Phi_Standard_Label=("name", standard_label),
            JSTOR_names=("original_JSTOR_author", lambda s: "|".join(sorted(set(s)))),
        )
        .reset_index()
    )
    authors["N_articles"] = authors["Phi_ID"].map(n_articles)
    authors = authors.sort_values(
        "Phi_ID", key=lambda s: s.str.removeprefix("P:").astype(int)
    )

    label = philosophers.set_index("Phi_ID")["Phi_Standard_Label"]
    label = pd.concat([label, authors.set_index("Phi_ID")["Phi_Standard_Label"]])
    review = res.assign(
        Phi_Standard_Label=res["Phi_ID"].map(label),
        N_articles=res["creator"].map(auth.groupby("creator")["Article_ID"].nunique()),
        Example_article=res["creator"].map(
            auth.groupby("creator")["Article_ID"].first()
        ),
        Correct="",
        Comment="",
    ).drop(columns="key")
    review = review.rename(columns={"creator": "JSTOR_creator", "name": "Normalised"})
    review = review.sort_values(["rule", "N_articles"], ascending=[True, False])
    return authorship, authors.reset_index(drop=True), review


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--metadata", required=True, help="metadata CSV of the delivery")
    p.add_argument("--doc-subtype", default="research-article")
    p.add_argument("--philosophers", required=True, help="philosophers.parquet")
    p.add_argument("--variants", required=True, help="variants.parquet")
    p.add_argument("--after", nargs="+", required=True, help="CSVs with Phi_ID")
    p.add_argument("--out-authorship", required=True)
    p.add_argument("--out-authors", required=True)
    p.add_argument("--out-review", required=True)
    args = p.parse_args(argv)
    setup_logging()

    meta = pd.read_csv(args.metadata, dtype=str, encoding="UTF-8")
    meta = meta[meta["docSubType"] == args.doc_subtype].rename(
        columns={"id": "Article_ID"}
    )
    meta = meta.sort_values("Article_ID")
    after = pd.concat([read_curated_csv(f, usecols=["Phi_ID"]) for f in args.after])
    first_id = int(after["Phi_ID"].str.removeprefix("P:").astype(int).max()) + 1
    authorship, authors, review = match_authors(
        meta,
        read_parquet(args.philosophers),
        read_parquet(args.variants),
        first_id,
    )
    log.info(
        "%d authorship rows for %d articles; %d new philosophers; rules %s",
        len(authorship),
        authorship["Article_ID"].nunique(),
        len(authors),
        review["rule"].value_counts().to_dict(),
    )
    for path, df in (
        (args.out_authorship, authorship),
        (args.out_authors, authors),
        (args.out_review, review),
    ):
        with atomic_output(path) as tmp:
            df.to_csv(tmp, index=False)
        log.info("wrote %s (%d rows)", path, len(df))


if __name__ == "__main__":
    main()
