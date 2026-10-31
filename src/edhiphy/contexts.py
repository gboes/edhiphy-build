"""Stage 8 (contexts): mention contexts and the full-text table.

``Mention_context`` has the v1 format: up to ``--chars`` characters of
cleaned text before and after the mention, which is upper-cased, with
"..." marking a non-empty side. v1 took ``text[start - chars:start]``, which
is empty for mentions closer than ``chars`` to the beginning of the text
(negative slice); here the left context starts at the beginning instead.

``fulltexts``: the cleaned texts of the selected articles, the
``Full_Text`` table of the research database.
"""

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from edhiphy.common import log, parser, read_parquet, setup_logging, write_parquet

FULLTEXT_COLUMNS = ["Article_ID", "FullText", "length_words", "length_characters"]


def context(text: str, start: int, end: int, ent_text: str, chars: int) -> str:
    before = text[max(start - chars, 0) : start]
    after = text[end : end + chars]
    return (
        ("..." + before if before else "")
        + ent_text.upper()
        + (after + "..." if after else "")
    )


def read_fulltexts(clean_dirs, selected) -> pd.DataFrame:
    frames = []
    for d in clean_dirs:
        for part in sorted(Path(d).glob("part-*.parquet")):
            t = pq.read_table(part, columns=FULLTEXT_COLUMNS).to_pandas()
            frames.append(t[t["Article_ID"].isin(selected)])
    texts = pd.concat(frames, ignore_index=True)
    missing = set(selected) - set(texts["Article_ID"])
    if missing:
        raise SystemExit(f"{len(missing)} selected articles have no cleaned text")
    return texts.sort_values("Article_ID").reset_index(drop=True)


def contexts(mentions: pd.DataFrame, texts: pd.DataFrame, chars: int) -> pd.DataFrame:
    full = dict(zip(texts["Article_ID"], texts["FullText"]))
    ctx = [
        context(full[a], s, e, t, chars)
        for a, s, e, t in zip(
            mentions["Article_ID"],
            mentions["start"],
            mentions["end"],
            mentions["Ent_text"],
        )
    ]
    return pd.DataFrame(
        {
            "Article_ID": mentions["Article_ID"],
            "Mention_ID": mentions["Mention_ID"],
            "Mention_context": ctx,
        }
    )


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--clean", nargs="+", required=True, help="clean directories")
    p.add_argument("--articles", required=True)
    p.add_argument("--mentions", required=True, help="raw mentions (stage 7)")
    p.add_argument("--chars", type=int, default=100)
    p.add_argument("--out-contexts", required=True)
    p.add_argument("--out-fulltexts", required=True)
    args = p.parse_args(argv)
    setup_logging()
    selected = set(read_parquet(args.articles, columns=["Article_ID"])["Article_ID"])
    texts = read_fulltexts(args.clean, selected)
    mentions = read_parquet(
        args.mentions, columns=["Article_ID", "Mention_ID", "Ent_text", "start", "end"]
    )
    out = contexts(mentions, texts, args.chars)
    log.info("%d contexts of %d characters", len(out), args.chars)
    write_parquet(out, args.out_contexts)
    write_parquet(texts, args.out_fulltexts)


if __name__ == "__main__":
    main()
