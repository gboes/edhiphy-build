"""Language layers of the dictionary stage (phase 5): variants and
philosophers added to the frozen v1 dictionary and its corrections.

A layer consists of up to three curated inputs:

- labels and aliases of Wikidata entries in the layer's language
  (``edhiphy.wikidata_labels``, ``--layer-labels``), for the entries of
  the dictionary and of the new philosophers;
- new philosophers from Wikidata (``edhiphy.wikidata_philosophers``,
  ``--layer-philosophers``) with their Phi_IDs;
- new philosophers from the JSTOR author matching
  (``edhiphy.jstor_authors``, ``--layer-authors``), JSTOR authors not
  found in the dictionary, with their Phi_IDs.

Phi_IDs are assigned by those tools, not here, so that every corpus that
uses a layer has the same IDs and layers do not collide (F6).

Variants, by the v1 rules (``edhiphy.name_variants``), with origins:
``Wiki_<lang> label`` and ``Wiki_<lang> aliases`` (every entry);
``Wiki surname`` and ``Artificial variant`` (new Wikidata philosophers:
family names, also without a lower-case particle, and initials with
family names); ``Wiki_<lang> artificial variant`` (dictionary entries: the
first word of a label in the layer's language that ends with one of the
entry's family names, as initials with that family name, e.g. "E. Kant"
from "Emmanuel Kant"); ``JSTOR_Standard label`` (new JSTOR authors; v1
also derived a surname-only variant, ``JSTOR_Artificial surname``, from
each JSTOR author name, the French layer does not: for authors
without a Wikidata entry, a surname alone is mostly a common word or
place in the French texts, "Dieu" from "Jean de Dieu", "Montpellier",
"Raison"). With ``fold``: ``Ligature variant``, the
spelling with "oe"/"ae" of every valid variant with "œ"/"æ" (the folded
matching of stage 7 keeps ligatures). A new variant that the philosopher
already has (compared folded with ``fold``) is dropped. Variant_IDs are
``<Phi_ID>_<lang><n>``.

Issue levels of the new variants, by the v1 rules: ``Too_short`` (at
most three characters), ``Too_young_philosopher`` (Wikidata birth year
after 1960), ``Highly_problematic`` and ``Maybe_problematic`` (strings
with that level anywhere in v1), ``Unlikely_variant`` (same philosopher
and string in v1). In addition, ``Maybe_problematic`` for one-word
family-name variants of the layer that are also given names in the
dictionary ("Pierre", "Martin"): they would match given names in the
texts; ``Highly_problematic`` for variants of initials only ("R. P.",
"J.-M. D.", JSTOR signatures), as v1 flagged "A. L." by hand;
``Maybe_problematic`` for one-word JSTOR author names ("Casa", "Esprit").
Variants of the whole dictionary, v1 rows included, get
``Maybe_problematic`` if they are one-word aliases that are the
philosopher's own given name ("Jean" for Jean Gayon),
and, with ``fold``, the v1 levels Highly_problematic and
Maybe_problematic of their folded string (``flag_whole_dictionary``);
and the levels of a curated list of the layer (``--layer-issues``,
``data/manual/variant_issues_fr.csv``: given names, places and common
words that are valid one-word variants); these levels apply only to the
corpora that use the layer.
"""

import pandas as pd

from edhiphy import name_variants
from edhiphy.common import check_unique, fold_diacritics, log, read_curated_csv

MIN_LENGTH = 4
INITIALS_ONLY = r"(?:[^\W\d_]{1,2}\.[\s-]*)+"
MAX_BIRTH_YEAR = 1960
LIGATURES = {"œ": "oe", "Œ": "Oe", "æ": "ae", "Æ": "Ae"}


def _texts(labels: pd.DataFrame, kind: str) -> pd.Series:
    """Wiki_ID -> list of texts of ``kind`` (label, alias)."""
    sel = labels[labels["kind"] == kind]
    return sel.groupby("Wiki_ID")["text"].agg(lambda s: list(dict.fromkeys(s)))


def first_wiki_id(philosophers: pd.DataFrame) -> pd.Series:
    return philosophers["Wiki_ID"].astype("string").str.split("|").str[0]


def new_wikidata_philosophers(new: pd.DataFrame, labels: pd.DataFrame):
    """Philosopher, Wiki_Entry and Biography rows of the new Wikidata
    philosophers."""
    label = (
        new["Label_fr"]
        .fillna(new["Label_en"])
        .fillna(new["Wiki_ID"].str.rsplit("/", n=1).str[-1])
    )
    philosophers = pd.DataFrame(
        {
            "Phi_ID": new["Phi_ID"],
            "Phi_Standard_Label": label,
            "Wiki_ID": new["Wiki_ID"],
            "Wiki": 1,
            "JSTOR": 0,
            "Hiring": 0,
            "PhD": 0,
        }
    )
    aliases = _texts(labels, "alias")
    wiki = pd.DataFrame(
        {
            "Wiki_ID": new["Wiki_ID"],
            "Wiki_label": label,
            "Wiki_aliases": new["Wiki_ID"]
            .map(aliases)
            .map(lambda a: ", ".join(a) if isinstance(a, list) else None),
            "Wiki_description": new["Description"],
            "Wiki_birthYear": new["birthYear"].astype("Int64").astype("string"),
            "Wiki_surname": new["Surname"],
            "Wiki_firstname": new["First_name"],
            "Wiki_gender": new["Gender"],
        }
    )
    biography = pd.DataFrame(
        {
            "Phi_ID": new["Phi_ID"],
            "Surname": new["Surname"].str.split("|").str[0],
            "First_Name": new["First_name"].str.split("|").str[0],
            "Gender": new["Gender"],
            "BirthYear": new["birthYear"].astype("Int64"),
        }
    )
    return philosophers, wiki, biography


def new_jstor_philosophers(authors: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Phi_ID": authors["Phi_ID"],
            "Phi_Standard_Label": authors["Phi_Standard_Label"],
            "Wiki_ID": pd.NA,
            "Wiki": 0,
            "JSTOR": 1,
            "Hiring": 0,
            "PhD": 0,
        }
    )


def _split(v) -> list[str]:
    return [x for x in str(v).split("|") if x] if isinstance(v, str) else []


def surnames_with_particle_drop(surnames) -> list[str]:
    out = []
    for s in surnames:
        out.append(s)
        t = name_variants.without_particle(s)
        if t:
            out.append(t)
    return list(dict.fromkeys(out))


def layer_variants(lang, philosophers, wiki, labels, new_wiki, new_authors):
    """Candidate variants of the layer: rows Phi_ID, Variant,
    Variant_origin (before the duplicate check and the issue levels)."""
    rows = []
    wid = first_wiki_id(philosophers)
    label_of = _texts(labels, "label")
    alias_of = _texts(labels, "alias")
    wiki_surnames = wiki.set_index("Wiki_ID")["Wiki_surname"].map(_split)
    new_ids = set(new_wiki["Phi_ID"]) if new_wiki is not None else set()
    for phi, w in zip(philosophers["Phi_ID"], wid):
        if pd.isna(w):
            continue
        fr_labels = label_of.get(w, [])
        for t in fr_labels:
            rows.append((phi, t, f"Wiki_{lang} label"))
        for t in alias_of.get(w, []):
            rows.append((phi, t, f"Wiki_{lang} aliases"))
        if phi in new_ids:
            continue
        surnames = surnames_with_particle_drop(wiki_surnames.get(w, []))
        for t in fr_labels:
            words = t.split()
            ends = [s for s in surnames if len(words) >= 2 and t.endswith(" " + s)]
            for v in name_variants.artificial_variants(words[:1], ends):
                rows.append((phi, v, f"Wiki_{lang} artificial variant"))
    if new_wiki is not None:
        for r in new_wiki.itertuples(index=False):
            surnames = surnames_with_particle_drop(_split(r.Surname))
            for s in surnames:
                rows.append((r.Phi_ID, s, "Wiki surname"))
            for v in name_variants.artificial_variants(_split(r.First_name), surnames):
                rows.append((r.Phi_ID, v, "Artificial variant"))
    if new_authors is not None:
        for r in new_authors.itertuples(index=False):
            # No artificial surname (unlike v1): see the module docstring.
            rows.append((r.Phi_ID, r.Phi_Standard_Label, "JSTOR_Standard label"))
    out = pd.DataFrame(rows, columns=["Phi_ID", "Variant", "Variant_origin"])
    out["Variant"] = out["Variant"].str.strip()
    return out[out["Variant"].str.len() > 0]


def ligature_variants(variants: pd.DataFrame) -> pd.DataFrame:
    valid = variants[variants["Issue_level"].isna()]
    has = valid["Variant"].str.contains("[œŒæÆ]", regex=True)
    out = valid.loc[has, ["Phi_ID", "Variant"]].copy()
    for a, b in LIGATURES.items():
        out["Variant"] = out["Variant"].str.replace(a, b, regex=False)
    out["Variant_origin"] = "Ligature variant"
    return out


def drop_known(new: pd.DataFrame, variants: pd.DataFrame, fold: bool) -> pd.DataFrame:
    key = fold_diacritics if fold else (lambda s: s)
    known = set(zip(variants["Phi_ID"], variants["Variant"].map(key)))
    k = new["Variant"].map(key)
    keep = [(p, v) not in known for p, v in zip(new["Phi_ID"], k)]
    new = new[keep].assign(_k=k[keep])
    return new.drop_duplicates(["Phi_ID", "_k"]).drop(columns="_k")


def given_names(wiki: pd.DataFrame, biography: pd.DataFrame) -> set[str]:
    out = set(biography["First_Name"].dropna().astype(str))
    for v in wiki["Wiki_firstname"].dropna():
        out |= set(_split(v))
    return {g for g in out if " " not in g}


def issue_levels(new, frozen, birth_year, given) -> pd.Series:
    level = pd.Series(pd.NA, index=new.index, dtype="object")
    v1 = frozen.dropna(subset=["Issue_level"])

    def where(mask, name):
        level[level.isna() & mask] = name

    where(new["Variant"].str.len() < MIN_LENGTH, "Too_short")
    where(new["Phi_ID"].map(birth_year) > MAX_BIRTH_YEAR, "Too_young_philosopher")
    where(new["Variant"].str.fullmatch(INITIALS_ONLY), "Highly_problematic")
    for name in ("Highly_problematic", "Maybe_problematic"):
        where(
            new["Variant"].isin(set(v1.loc[v1["Issue_level"] == name, "Variant"])), name
        )
    unlikely = set(
        zip(
            *v1.loc[
                v1["Issue_level"] == "Unlikely_variant", ["Phi_ID", "Variant"]
            ].T.values
        )
    )
    where(
        pd.Series(
            [(p, v) in unlikely for p, v in zip(new["Phi_ID"], new["Variant"])],
            index=new.index,
        ),
        "Unlikely_variant",
    )
    one_word = ~new["Variant"].str.contains(" ")
    surname = new["Variant_origin"].isin(["Wiki surname", "JSTOR_Artificial surname"])
    where(surname & one_word & new["Variant"].isin(given), "Maybe_problematic")
    jstor = new["Variant_origin"] == "JSTOR_Standard label"
    where(jstor & one_word, "Maybe_problematic")
    return level


ALIASES = ["Wiki aliases", "Wiki_fr aliases"]


def flag_whole_dictionary(
    variants, frozen, given, fold, issues=None, labels=None
) -> pd.Series:
    """Issue levels that the layer sets on valid variants of the whole
    dictionary, v1 rows included: one-word aliases that are given names and
    the first, not the last, word of the philosopher's label (``labels``,
    Phi_ID -> label): "Jean" as an alias of Jean Gayon, but not "Marx" of
    Karl Marx, although "Marx" is also a given name; with ``fold``, the v1 levels
    Highly_problematic and Maybe_problematic for every variant with the
    same folded string ("París" as "Paris"); the levels of ``issues``
    (``Variant``, ``Issue_level``: a curated list of the layer, compared
    folded with ``fold``)."""
    level = variants["Issue_level"].copy()
    valid = level.isna()
    alias = variants["Variant_origin"].isin(ALIASES)
    one_word = ~variants["Variant"].str.contains(" ")
    words = variants["Phi_ID"].map(labels).astype("string").str.split()
    first = words.str[0] == variants["Variant"]
    last = words.str[-1] == variants["Variant"]
    own_given = (first & ~last).fillna(False).astype(bool)
    level[valid & alias & one_word & own_given & variants["Variant"].isin(given)] = (
        "Maybe_problematic"
    )
    key = fold_diacritics if fold else (lambda x: x)
    folded = variants["Variant"].map(key)
    if issues is not None:
        by_string = dict(zip(issues["Variant"].map(key), issues["Issue_level"]))
        level[level.isna()] = folded[level.isna()].map(by_string)
    if fold:
        v1 = frozen.dropna(subset=["Issue_level"])
        for name in ("Highly_problematic", "Maybe_problematic"):
            strings = set(
                v1.loc[v1["Issue_level"] == name, "Variant"].map(fold_diacritics)
            )
            level[level.isna() & folded.isin(strings)] = name
    return level


def number_variants(new: pd.DataFrame, lang: str) -> pd.Series:
    n = new.groupby("Phi_ID").cumcount() + 1
    return new["Phi_ID"] + f"_{lang}" + n.astype(str)


def add_layer(
    lang,
    philosophers,
    variants,
    wiki,
    biography,
    dates,
    labels=None,
    new_wiki=None,
    new_authors=None,
    fold=False,
    issues=None,
):
    """The dictionary with the layer added (see the module docstring)."""
    labels = (
        labels
        if labels is not None
        else pd.DataFrame(
            columns=["Wiki_ID", "Queried_Wiki_ID", "lang", "kind", "text"]
        )
    )
    if lang:
        labels = labels[labels["lang"] == lang]
    frozen = variants
    if new_wiki is not None:
        p, w, b = new_wikidata_philosophers(new_wiki, labels)
        clash = set(p["Phi_ID"]) & set(philosophers["Phi_ID"])
        if clash:
            raise SystemExit(
                f"layer: Phi_IDs already in the dictionary {sorted(clash)[:5]}"
            )
        known = set(philosophers["Wiki_ID"].dropna())
        if set(p["Wiki_ID"]) & known:
            raise SystemExit(
                "layer: new Wikidata philosophers already in the dictionary"
            )
        philosophers = pd.concat([philosophers, p], ignore_index=True)
        wiki = pd.concat([wiki, w], ignore_index=True)
        biography = pd.concat([biography, b], ignore_index=True)
        log.info("layer %s: %d new philosophers from Wikidata", lang, len(p))
    if new_authors is not None:
        p = new_jstor_philosophers(new_authors)
        clash = set(p["Phi_ID"]) & set(philosophers["Phi_ID"])
        if clash:
            raise SystemExit(
                f"layer: Phi_IDs already in the dictionary {sorted(clash)[:5]}"
            )
        philosophers = pd.concat([philosophers, p], ignore_index=True)
        log.info("layer %s: %d new philosophers from JSTOR authors", lang, len(p))
    check_unique(philosophers, ["Phi_ID"], "philosophers with layer")

    new = layer_variants(lang, philosophers, wiki, labels, new_wiki, new_authors)
    new = drop_known(new, variants, fold)
    birth = dates.set_index("Wiki_ID")["birthYear"]
    birth_year = pd.Series(
        first_wiki_id(philosophers).map(birth).to_numpy(), index=philosophers["Phi_ID"]
    )
    new["Issue_level"] = issue_levels(
        new, frozen, birth_year, given_names(wiki, biography)
    )
    if fold:
        lig = ligature_variants(pd.concat([variants, new], ignore_index=True))
        lig = drop_known(lig, pd.concat([variants, new], ignore_index=True), fold)
        lig["Issue_level"] = issue_levels(
            lig, frozen, birth_year, given_names(wiki, biography)
        )
        new = pd.concat([new, lig], ignore_index=True)
    new = new.reset_index(drop=True)
    new["Variant_ID"] = number_variants(new, lang)
    new["Variant_length"] = new["Variant"].str.len()
    new.index = range(variants.index.max() + 1, variants.index.max() + 1 + len(new))
    log.info(
        "layer %s: %d variants (%s), %d with an issue level",
        lang,
        len(new),
        new["Variant_origin"].value_counts().to_dict(),
        int(new["Issue_level"].notna().sum()),
    )
    variants = pd.concat([variants, new[[c for c in new if c in variants]]])
    check_unique(variants, ["Variant_ID"], "variants with layer")
    level = flag_whole_dictionary(
        variants,
        frozen,
        given_names(wiki, biography),
        fold,
        issues,
        philosophers.set_index("Phi_ID")["Phi_Standard_Label"],
    )
    changed = level.notna() & variants["Issue_level"].isna()
    log.info(
        "layer %s: issue level set on %d further variants (%d of them v1 rows)",
        lang,
        int(changed.sum()),
        int((changed & variants.index.isin(frozen.index)).sum()),
    )
    variants = variants.assign(Issue_level=level)
    return philosophers, variants, wiki, biography


def read_layer(paths):
    if not paths:
        return None
    return pd.concat([read_curated_csv(p) for p in paths], ignore_index=True)
