"""Stage 7 (extract): philosopher mentions in the cleaned texts.

A blank spaCy pipeline of the source language with an EntityRuler. Its
patterns are the valid variants of the dictionary (empty
``Issue_level``), one per distinct (``Variant``, ``Matching_Phi_IDs``),
whose id is ``Matching_Phi_IDs``. As in v1, the token pattern
``PHI_SCHOOL`` (words containing "ism") competes for overlapping spans;
the ruler keeps the longest match, so each start has at most one span.
v1 ran ``en_core_web_sm`` with the ruler before ``ner``; the statistical
components do not change the ruler's entities, so only the tokenizer and
the ruler are needed. Only ``PHILOSOPHER`` entities are kept.

With ``--fold-diacritics`` (French corpus) the ruler runs on a copy of the
text with diacritics folded (``common.fold_diacritics``, one character for
one, so offsets are those of the cleaned text) and its patterns are the
folded variants; variants that fold to the same string are one pattern
with the union of their candidates. ``Ent_text`` is the unfolded text.

``Mention_ID`` = ``<JSTOR number>_<page>_<offset>``: the 1-based page and
the character offset in the raw page text of the mention's first
character (via the map of stage 6). Rows are in corpus order: sources in
the order of the corpus, documents in delivery order, mentions by
position. ``Doc_Order`` records that order.
"""

import functools
import re
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from edhiphy.clean import raw_position
from edhiphy.common import (
    fold_diacritics,
    log,
    map_parts,
    parser,
    read_parquet,
    setup_logging,
    write_parquet,
)

STABLE = re.compile(r"^http://www\.jstor\.org/stable/(.+)$")

MENTION_COLUMNS = [
    "Article_ID",
    "Doc_Order",
    "Mention_ID",
    "Ent_text",
    "Ent_label",
    "Associated_Phi_IDs",
    "start",
    "end",
    "page",
    "raw_offset",
]

PHI_SCHOOL = {"label": "PHI_SCHOOL", "pattern": [{"LOWER": {"REGEX": r"\w*isms?\b"}}]}


def patterns(variants: pd.DataFrame, fold: bool = False) -> list[dict]:
    valid = variants[variants["Issue_level"].isna()]
    if fold:
        folded = valid["Variant"].map(fold_diacritics)
        ids = (
            valid["Matching_Phi_IDs"]
            .str.split("|")
            .groupby(folded)
            .agg(lambda s: "|".join(sorted({i for ids in s for i in ids})))
        )
        valid = pd.DataFrame(
            {"Variant": folded, "Matching_Phi_IDs": folded.map(ids)}
        ).drop_duplicates()
    valid = valid.drop_duplicates(subset=["Variant", "Matching_Phi_IDs"])
    return [
        {"label": "PHILOSOPHER", "pattern": v, "id": ids}
        for v, ids in zip(valid["Variant"], valid["Matching_Phi_IDs"])
    ]


@functools.cache
def pipeline(variants_path: str, lang: str, fold: bool = False):
    """The spaCy pipeline, built once per worker process."""
    import spacy

    nlp = spacy.blank(lang)
    nlp.max_length = 10**9
    ruler = nlp.add_pipe("entity_ruler")
    pats = patterns(read_parquet(variants_path), fold)
    ruler.add_patterns(pats + [PHI_SCHOOL])
    log.info("entity ruler with %d variant patterns", len(pats))
    return nlp


def mention_id(article_id: str, page: int, offset: int) -> str:
    m = STABLE.match(article_id)
    if not m:
        raise SystemExit(f"cannot derive a Mention_ID from {article_id!r}")
    return f"{m.group(1)}_{page}_{offset}"


def mentions_of(row, doc, doc_order: int) -> list[dict]:
    text = row["FullText"]
    out = []
    for ent in doc.ents:
        if ent.label_ != "PHILOSOPHER":
            continue
        # The first character with a raw origin; the first character of a
        # name always has one unless the v1 cleaner rewrote it.
        pos = None
        for c in range(ent.start_char, ent.end_char):
            pos = raw_position(row, c)
            if pos is not None:
                break
        if pos is None:
            raise SystemExit(
                f"{row['Article_ID']}: mention {ent.text!r} at {ent.start_char} "
                "has no raw position"
            )
        page, offset = pos
        out.append(
            {
                "Article_ID": row["Article_ID"],
                "Doc_Order": doc_order,
                "Mention_ID": mention_id(row["Article_ID"], page, offset),
                "Ent_text": text[ent.start_char : ent.end_char],
                "Ent_label": ent.label_,
                "Associated_Phi_IDs": ent.ent_id_,
                "start": ent.start_char,
                "end": ent.end_char,
                "page": page,
                "raw_offset": offset,
            }
        )
    return out


def extract_part(
    part: Path, order_base: int, selected, variants_path, lang, fold=False
) -> pd.DataFrame:
    table = pq.read_table(part).to_pandas()
    table["Doc_Order"] = range(order_base, order_base + len(table))
    table = table[table["Article_ID"].isin(selected)]
    nlp = pipeline(str(variants_path), lang, fold)
    rows = []
    records = table.to_dict("records")
    prepare = fold_diacritics if fold else str
    docs = nlp.pipe((prepare(r["FullText"]) for r in records), batch_size=20)
    for r, doc in zip(records, docs):
        rows.extend(mentions_of(r, doc, r["Doc_Order"]))
    return pd.DataFrame(rows, columns=MENTION_COLUMNS)


def _extract_task(t, selected, variants_path, fold) -> pd.DataFrame:
    part, order_base, lang = t
    return extract_part(part, order_base, selected, variants_path, lang, fold)


def extract(
    clean_dirs, langs, articles, variants_path, workers, fold=False
) -> pd.DataFrame:
    selected = frozenset(read_parquet(articles, columns=["Article_ID"])["Article_ID"])
    tasks = []
    for s, (d, lang) in enumerate(zip(clean_dirs, langs)):
        for i, part in enumerate(sorted(Path(d).glob("part-*.parquet"))):
            # Doc_Order: source, part and row; parts hold < 10^6 rows.
            tasks.append((part, (s * 10**4 + i) * 10**6, lang))
    task = functools.partial(
        _extract_task, selected=selected, variants_path=variants_path, fold=fold
    )
    frames = map_parts(task, tasks, workers)
    mentions = pd.concat(frames, ignore_index=True)
    mentions = mentions.sort_values(["Doc_Order", "start"], kind="stable")
    dup = mentions["Mention_ID"].duplicated()
    if dup.any():
        raise SystemExit(
            f"{dup.sum()} duplicate Mention_IDs, e.g. {mentions.loc[dup, 'Mention_ID'].iloc[0]}"
        )
    return mentions.reset_index(drop=True)


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument(
        "--clean", nargs="+", required=True, help="clean directories, in corpus order"
    )
    p.add_argument("--langs", nargs="+", required=True, help="language of each source")
    p.add_argument("--articles", required=True)
    p.add_argument(
        "--variants", required=True, help="variants.parquet of the dictionary"
    )
    p.add_argument("--workers", type=int, default=None)
    p.add_argument(
        "--fold-diacritics", action="store_true", help="match with diacritics folded"
    )
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    setup_logging()
    if len(args.clean) != len(args.langs):
        raise SystemExit("--clean and --langs differ in length")
    mentions = extract(
        args.clean,
        args.langs,
        args.articles,
        args.variants,
        args.workers,
        args.fold_diacritics,
    )
    log.info(
        "%d mentions in %d articles", len(mentions), mentions["Article_ID"].nunique()
    )
    write_parquet(mentions, args.out)


if __name__ == "__main__":
    main()
