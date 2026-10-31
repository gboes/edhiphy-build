"""Stage 6 (clean): cleaned full texts with a map back to the raw pages.

The rule set ``jstor_en_v1`` reproduces the cleaner of edhiphy 1.0
(``full_text_cleaner`` in ``src/legacy/eugenio2/Cleaner_and_NER.py``)
character for character, including its quirks: per page, the header (the
text before the first lower-case word or capitalised word, or else the
first 20 characters) is removed, the creators' names are removed on the
first and last page, and numbers after the last dot (page numbers) are
replaced; then, for the whole text, hyphenated line breaks are joined,
double quotes, abbreviations and the Saxon genitive are removed,
whitespace is collapsed, and "Surname, I." becomes "Surname I.".

The rule set ``jstor_fr`` (French deliveries) keeps the page rules of
``jstor_en_v1`` (they handle the upper-case running heads of the French
journals) and differs in the rules for the whole text: French
bibliographical abbreviations and forms of address before names
(``FR_ABBREVIATIONS``, case-sensitive and at word starts, unlike the v1
list) are removed, guillemets and curly double quotes as well as straight
ones, and there is no Saxon genitive rule; elisions ("d'Aristote") stay,
the French tokenizer of stage 7 splits them.

Every operation also carries the origin of each character, so each
character of the cleaned text maps to its position in the raw text (the
pages concatenated without separator) or to none for inserted
characters. The map is stored as segments ``(clean start, raw start,
length)`` of consecutive characters; ``page_starts`` gives the raw offset
of each page. Mention_IDs use it to name raw positions (stage 7).

Per document and independent of the other documents; the stage runs over
the parts of a source with dask.
"""

import bisect
import functools
import re
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from edhiphy.common import atomic_output, log, map_parts, parser, setup_logging

CLEAN_SCHEMA = pa.schema(
    [
        ("Article_ID", pa.string()),
        ("FullText", pa.string()),
        ("length_words", pa.int64()),
        ("length_characters", pa.int64()),
        ("page_starts", pa.list_(pa.int64())),
        ("seg_clean", pa.list_(pa.int64())),
        ("seg_raw", pa.list_(pa.int64())),
        ("seg_len", pa.list_(pa.int64())),
    ]
)

# Placeholder of v1 for documents without creators.
NO_CREATOR = "__NULL"


class Tracked:
    """A string with the raw origin of each character (-1: inserted)."""

    __slots__ = ("text", "origin")

    def __init__(self, text: str, origin: list):
        assert len(text) == len(origin)
        self.text = text
        self.origin = origin

    @classmethod
    def raw(cls, text: str, start: int = 0) -> "Tracked":
        return cls(text, list(range(start, start + len(text))))

    @classmethod
    def inserted(cls, text: str) -> "Tracked":
        return cls(text, [-1] * len(text))

    def __add__(self, other: "Tracked") -> "Tracked":
        return Tracked(self.text + other.text, self.origin + other.origin)

    def __getitem__(self, s: slice) -> "Tracked":
        return Tracked(self.text[s], self.origin[s])

    def sub(self, pattern: re.Pattern, repl: str) -> "Tracked":
        """``pattern.sub(repl, text)`` for a literal ``repl``. A replacement
        character keeps the origin of the replaced character at the same
        position if both are equal, so that every mapped character equals
        its raw character; otherwise it counts as inserted."""
        parts, origins, pos = [], [], 0
        for m in pattern.finditer(self.text):
            a, b = m.span()
            parts.append(self.text[pos:a])
            origins.append(self.origin[pos:a])
            if repl:
                parts.append(repl)
                origins.append(
                    [
                        (
                            self.origin[a + j]
                            if a + j < b and self.text[a + j] == c
                            else -1
                        )
                        for j, c in enumerate(repl)
                    ]
                )
            pos = b
        if not parts:
            return self
        parts.append(self.text[pos:])
        origins.append(self.origin[pos:])
        return Tracked("".join(parts), [o for chunk in origins for o in chunk])

    def replace(self, old: str, new: str) -> "Tracked":
        """``str.replace`` (all occurrences, left to right)."""
        if old not in self.text:
            return self
        return self.sub(re.compile(re.escape(old)), new)


HEADER_MARKER = re.compile("[a-z]+|[A-Z][a-z]")
DOT = re.compile(r"\.")
NUMBER = re.compile(r"\b[0-9]+")
PAGE_MARKER = re.compile("__Page_[0-9]+__")
ABBREVIATIONS = re.compile(
    "|".join(
        map(
            re.escape,
            [
                "c.f.", "c. f.", "cf.", "cf", "i. e.", "i.e.", "e. g.", "e.g.",
                "ibid.", "ibidem", "ibid", "op. cit.", "op.cit.",
            ],
        )
    ),
    re.IGNORECASE,
)  # fmt: skip
SPACES = re.compile(r"\s+")
SAXON = re.compile(r"'s|’s")
CITED_AUTHOR = re.compile(r"[A-Z][a-z]+,\s[A-Z]\.")


def clean_page(page: Tracked, first_or_last: bool, creators) -> Tracked:
    m = HEADER_MARKER.search(page.text)
    if m is not None:
        # v1: header = text.split(marker)[0]; the first occurrence of the
        # marker is the regex match itself.
        header = page.text[: m.start()]
        if len(header) >= 10:
            page = page.replace(header, "")
        elif len(page.text) >= 20:
            page = page[20:]
    if first_or_last:
        for a in creators:
            page = page.sub(re.compile(re.escape(a), re.IGNORECASE), "")
    dots = [d.end() for d in DOT.finditer(page.text)]
    if dots:
        last = dots[-1]
        # v1 drops the character after the last dot and inserts a space.
        page = page[:last] + Tracked.inserted(" ") + page[last + 1 :].sub(NUMBER, " ")
    return page


def clean_en_v1(pages, creators) -> Tracked:
    """The v1 cleaner on the raw pages, with origins."""
    creators = list(creators) if creators is not None and len(creators) else []
    creators = creators or [NO_CREATOR]
    text = Tracked("", [])
    start = 0
    for n, page in enumerate(pages, 1):
        t = clean_page(Tracked.raw(page, start), n == 1 or n == len(pages), creators)
        text = text + t + Tracked.inserted(f"__Page_{n}__")
        start += len(page)
    text = text.sub(PAGE_MARKER, " ")
    text = text.replace("- ", "")
    text = text.replace('"', "")
    text = text.sub(ABBREVIATIONS, " ")
    text = text.sub(SPACES, " ")
    text = text.sub(SAXON, "")
    # v1 applies each found "Surname, I." as a regular expression to the
    # whole text, in order of occurrence. A repeated pattern has no effect
    # the second time, so each is applied once.
    for cited in dict.fromkeys(CITED_AUTHOR.findall(text.text)):
        text = text.sub(re.compile(cited), cited.replace(",", ""))
    return text


# Removed by ``jstor_fr`` when not preceded by a letter, digit or dot
# (documentation/design_phases_5-7.md, section 1.3). Single lower-case
# letters only in lower case, so that the initials of names stay; "M.",
# "MM.", "Mme", "Mlle" (Monsieur etc.) stand before names, where they
# would otherwise complete initial-and-surname variants ("M. Foucault").
FR_ABBREVIATIONS = re.compile(
    r"(?<![\w.])(?:"
    + "|".join(
        map(
            re.escape,
            sorted(
                [
                    "p.", "pp.", "t.", "vol.", "Vol.", "n.", "v.", "cf.", "Cf.",
                    "ibid.", "Ibid.", "ibidem", "Ibidem", "op. cit.", "Op. cit.",
                    "op.cit.", "loc. cit.", "Loc. cit.", "art. cit.", "éd.", "Éd.",
                    "trad.", "Trad.", "chap.", "Chap.", "ch.", "sq.", "sqq.",
                    "etc.", "M.", "MM.", "Mme", "Mlle",
                ],
                key=lambda a: (-len(a), a),
            ),
        )
    )
    + r")(?!\w)"
)  # fmt: skip
FR_QUOTES = re.compile('["«»“”]')


def clean_fr(pages, creators) -> Tracked:
    """The ``jstor_fr`` rules on the raw pages, with origins."""
    creators = list(creators) if creators is not None and len(creators) else []
    creators = creators or [NO_CREATOR]
    text = Tracked("", [])
    start = 0
    for n, page in enumerate(pages, 1):
        t = clean_page(Tracked.raw(page, start), n == 1 or n == len(pages), creators)
        text = text + t + Tracked.inserted(f"__Page_{n}__")
        start += len(page)
    text = text.sub(PAGE_MARKER, " ")
    text = text.replace("- ", "")
    text = text.sub(FR_QUOTES, "")
    text = text.sub(FR_ABBREVIATIONS, " ")
    text = text.sub(SPACES, " ")
    for cited in dict.fromkeys(CITED_AUTHOR.findall(text.text)):
        text = text.sub(re.compile(re.escape(cited)), cited.replace(",", ""))
    return text


RULES = {"jstor_en_v1": clean_en_v1, "jstor_fr": clean_fr}


def segments(origin) -> tuple[list, list, list]:
    """Runs of consecutive raw positions as (clean start, raw start,
    length); inserted characters belong to no run."""
    seg_clean, seg_raw, seg_len = [], [], []
    prev = None
    for i, o in enumerate(origin):
        if o < 0:
            prev = None
            continue
        if prev is not None and o == prev + 1:
            seg_len[-1] += 1
        else:
            seg_clean.append(i)
            seg_raw.append(o)
            seg_len.append(1)
        prev = o
    return seg_clean, seg_raw, seg_len


def raw_position(row, clean_pos: int):
    """(1-based page, offset in the raw page) of a cleaned-text position,
    or None for an inserted character."""
    i = bisect.bisect_right(row["seg_clean"], clean_pos) - 1
    if i < 0 or clean_pos >= row["seg_clean"][i] + row["seg_len"][i]:
        return None
    raw = row["seg_raw"][i] + clean_pos - row["seg_clean"][i]
    page = bisect.bisect_right(row["page_starts"], raw) - 1
    return page + 1, raw - row["page_starts"][page]


def clean_record(article_id: str, pages, creators, rules: str) -> dict:
    pages = list(pages)
    t = RULES[rules](pages, creators)
    seg_clean, seg_raw, seg_len = segments(t.origin)
    starts, s = [], 0
    for p in pages:
        starts.append(s)
        s += len(p)
    return {
        "Article_ID": article_id,
        "FullText": t.text,
        "length_words": len(t.text.split()),
        "length_characters": len(t.text),
        "page_starts": starts,
        "seg_clean": seg_clean,
        "seg_raw": seg_raw,
        "seg_len": seg_len,
    }


def clean_partition(df: pd.DataFrame, rules: str) -> pd.DataFrame:
    """Clean one part of a source (columns Article_ID, pages, creator)."""
    rows = [
        clean_record(a, p, c, rules)
        for a, p, c in zip(df["Article_ID"], df["pages"], df["creator"])
    ]
    return pd.DataFrame(rows, columns=CLEAN_SCHEMA.names)


def clean_part(src: Path, dst: Path, rules: str) -> int:
    df = pq.read_table(src, columns=["Article_ID", "pages", "creator"]).to_pandas()
    out = clean_partition(df, rules)
    pq.write_table(
        pa.Table.from_pandas(out, schema=CLEAN_SCHEMA, preserve_index=False), dst
    )
    return len(out)


def _clean_part_into(part: Path, out_dir: Path, rules: str) -> int:
    return clean_part(part, out_dir / part.name, rules)


def clean_source(docs_dir, out_dir, rules: str, workers: int) -> int:
    """Clean every part of ``docs_dir`` into a part of the same name."""
    parts = sorted(Path(docs_dir).glob("part-*.parquet"))
    if not parts:
        raise SystemExit(f"{docs_dir}: no parts")
    with atomic_output(out_dir, directory=True) as tmp:
        task = functools.partial(_clean_part_into, out_dir=tmp, rules=rules)
        n = sum(map_parts(task, parts, workers))
        (tmp / "_SUCCESS").write_text(
            f"{n} documents in {len(parts)} parts, rules {rules}\n"
        )
    log.info("cleaned %d documents (%s) into %s", n, rules, out_dir)
    return n


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--docs", required=True, help="docs directory of a source")
    p.add_argument("--rules", required=True, choices=sorted(RULES))
    p.add_argument(
        "--workers", type=int, default=None, help="processes (default: all CPUs)"
    )
    p.add_argument("--out", required=True, help="output directory")
    args = p.parse_args(argv)
    setup_logging()
    clean_source(args.docs, args.out, args.rules, args.workers)


if __name__ == "__main__":
    main()
