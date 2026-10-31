import os

import pandas as pd
import pytest

from edhiphy.common import atomic_output, check_unique, parquet_safe, write_parquet


def test_atomic_output_replaces_file(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("old")
    with atomic_output(target) as tmp:
        tmp.write_text("new")
    assert target.read_text() == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["out.txt"]


def test_atomic_output_keeps_old_file_on_failure(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("old")
    with pytest.raises(RuntimeError):
        with atomic_output(target) as tmp:
            tmp.write_text("partial")
            raise RuntimeError
    assert target.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["out.txt"]


def test_atomic_output_directory(tmp_path):
    target = tmp_path / "docs"
    for content in ["first", "second"]:
        with atomic_output(target, directory=True) as tmp:
            (tmp / "part").write_text(content)
    assert (target / "part").read_text() == "second"
    assert [p.name for p in tmp_path.iterdir()] == ["docs"]


def test_atomic_output_permissions_follow_umask(tmp_path):
    old = os.umask(0o022)
    try:
        with atomic_output(tmp_path / "f") as tmp:
            tmp.write_text("x")
    finally:
        os.umask(old)
    assert (tmp_path / "f").stat().st_mode & 0o777 == 0o644


def test_parquet_safe_converts_mixed_columns(tmp_path):
    df = pd.DataFrame({"mixed": [1, "iv", None], "ints": [1, 2, 3]})
    safe = parquet_safe(df)
    assert safe["mixed"].tolist()[:2] == ["1", "iv"]
    assert safe["ints"].tolist() == [1, 2, 3]
    write_parquet(df, tmp_path / "t.parquet")
    assert len(pd.read_parquet(tmp_path / "t.parquet")) == 3


def test_check_unique():
    df = pd.DataFrame({"a": [1, 1, 2]})
    with pytest.raises(SystemExit, match="duplicate"):
        check_unique(df, ["a"], "t")
    check_unique(df.drop_duplicates(), ["a"], "t")


def test_fold_diacritics_keeps_length():
    from edhiphy.common import fold_diacritics

    s = "Lévinas, Ricœur, Ibn Rušd, Émile, ß"
    assert fold_diacritics(s) == "Levinas, Ricœur, Ibn Rusd, Emile, ß"
    assert len(fold_diacritics(s)) == len(s)
