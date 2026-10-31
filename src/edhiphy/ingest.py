"""Stage 1 (ingest): read one JSTOR/Constellate delivery into parquet.

``metadata``: the delivered metadata CSV, all columns as strings, ``id``
renamed to ``Article_ID``, plus a ``source`` column. Values are converted
to the types of the database schema only when the database is written, so
nothing is lost here (e.g. page numbers such as ``iv``).

``docs``: the full-text JSONL (plain or gzip, one or more files) as a
directory of parquet parts with ``--rows-per-part`` documents each. Pages
are kept as a list in the delivered order; page *n* of a document is
element *n* - 1, which the Mention_ID scheme relies on. ``creator`` is
the delivered list of creator names (used by the cleaner).
"""

import gzip
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from edhiphy.common import (
    atomic_output,
    check_unique,
    log,
    parser,
    setup_logging,
    write_parquet,
)

DOCS_SCHEMA = pa.schema(
    [
        ("Article_ID", pa.string()),
        ("source", pa.string()),
        ("docType", pa.string()),
        ("docSubType", pa.string()),
        ("isPartOf", pa.string()),
        ("publicationYear", pa.int64()),
        ("language", pa.list_(pa.string())),
        ("creator", pa.list_(pa.string())),
        ("pages", pa.list_(pa.string())),
    ]
)


def read_metadata(path, source: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, encoding="UTF-8")
    df = df.rename(columns={"id": "Article_ID"})
    df.insert(1, "source", source)
    check_unique(df, ["Article_ID"], f"metadata {path}")
    return df


def iter_jsonl(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="UTF-8") as f:
        for lineno, line in enumerate(f, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise SystemExit(f"{path}:{lineno}: {e}")


def doc_record(d: dict, source: str) -> dict:
    year = d.get("publicationYear")
    return {
        "Article_ID": d["id"],
        "source": source,
        "docType": d.get("docType"),
        "docSubType": d.get("docSubType"),
        "isPartOf": d.get("isPartOf"),
        "publicationYear": int(year) if year is not None else None,
        "language": list(d.get("language") or []),
        # None when the delivery has no creator field: the v1 cleaner
        # distinguishes it from an empty list.
        "creator": list(d["creator"]) if "creator" in d else None,
        "pages": list(d.get("fullText") or []),
    }


def write_docs(paths, source: str, out_dir, rows_per_part: int) -> int:
    seen = set()
    n_parts = 0
    batch = []

    def flush(tmp):
        nonlocal n_parts, batch
        table = pa.Table.from_pylist(batch, schema=DOCS_SCHEMA)
        pq.write_table(table, tmp / f"part-{n_parts:05d}.parquet")
        n_parts += 1
        batch = []

    with atomic_output(out_dir, directory=True) as tmp:
        for path in paths:
            for d in iter_jsonl(path):
                rec = doc_record(d, source)
                if rec["Article_ID"] in seen:
                    raise SystemExit(f"{path}: duplicate document {rec['Article_ID']}")
                seen.add(rec["Article_ID"])
                batch.append(rec)
                if len(batch) == rows_per_part:
                    flush(tmp)
        if batch or n_parts == 0:
            flush(tmp)
        (tmp / "_SUCCESS").write_text(f"{len(seen)} documents in {n_parts} parts\n")
    log.info("wrote %s (%d documents, %d parts)", out_dir, len(seen), n_parts)
    return len(seen)


def main(argv=None):
    p = parser(__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="what", required=True)
    m = sub.add_parser("metadata")
    m.add_argument("--source", required=True)
    m.add_argument("--in", dest="input", required=True)
    m.add_argument("--out", required=True)
    d = sub.add_parser("docs")
    d.add_argument("--source", required=True)
    d.add_argument("--out", required=True, help="output directory")
    d.add_argument("--rows-per-part", type=int, default=2000)
    d.add_argument("inputs", nargs="+", help="JSONL files (.jsonl or .jsonl.gz)")
    args = p.parse_args(argv)
    setup_logging()
    if args.what == "metadata":
        write_parquet(read_metadata(args.input, args.source), args.out)
    else:
        write_docs(args.inputs, args.source, args.out, args.rows_per_part)


if __name__ == "__main__":
    main()
