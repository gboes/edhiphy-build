import gzip
import json

import pandas as pd
import pyarrow.parquet as pq
import pytest

from edhiphy import ingest

DOCS = [
    {
        "id": f"http://www.jstor.org/stable/{i}",
        "docType": "article",
        "docSubType": "research-article",
        "isPartOf": "J",
        "publicationYear": 1950,
        "language": ["eng"],
        "fullText": [f"page one of {i}", f"page two of {i}"],
    }
    for i in range(5)
]


def write_jsonl(path, docs, gz=False):
    text = "".join(json.dumps(d) + "\n" for d in docs) + "\n"
    if gz:
        with gzip.open(path, "wt") as f:
            f.write(text)
    else:
        path.write_text(text)


@pytest.mark.parametrize("gz", [False, True])
def test_docs_partitions_and_pages(tmp_path, gz):
    src = tmp_path / ("in.jsonl.gz" if gz else "in.jsonl")
    write_jsonl(src, DOCS, gz)
    out = tmp_path / "docs"
    assert ingest.write_docs([src], "s", out, rows_per_part=2) == 5
    parts = sorted(p.name for p in out.glob("part-*.parquet"))
    assert parts == ["part-00000.parquet", "part-00001.parquet", "part-00002.parquet"]
    table = pq.read_table(out).to_pandas()
    assert table["Article_ID"].tolist() == [d["id"] for d in DOCS]
    assert list(table["pages"].iloc[3]) == DOCS[3]["fullText"]
    assert (out / "_SUCCESS").exists()


def test_docs_multiple_files_and_duplicates(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_jsonl(a, DOCS[:3])
    write_jsonl(b, DOCS[3:])
    assert ingest.write_docs([a, b], "s", tmp_path / "docs", 100) == 5
    write_jsonl(b, DOCS[2:])
    with pytest.raises(SystemExit, match="duplicate"):
        ingest.write_docs([a, b], "s", tmp_path / "docs2", 100)
    assert not (tmp_path / "docs2").exists()


def test_metadata_keeps_strings(tmp_path):
    src = tmp_path / "m.csv"
    src.write_text("id,pageStart,issueNumber\nA,iv,1\nB,3,\n")
    df = ingest.read_metadata(src, "s")
    assert df.columns.tolist() == ["Article_ID", "source", "pageStart", "issueNumber"]
    assert df["pageStart"].tolist() == ["iv", "3"]
    assert df["issueNumber"].iloc[0] == "1"
    assert pd.isna(df["issueNumber"].iloc[1])
