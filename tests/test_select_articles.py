import pandas as pd
import pytest

from edhiphy.select_articles import select

META = pd.DataFrame(
    {
        "Article_ID": ["c", "a", "b", "d"],
        "docSubType": ["research-article", "research-article", "book-review", "misc"],
    }
)


def test_ids_and_subtypes():
    out = select(META, ids=["a", "b", "c"], doc_subtypes=["research-article"])
    assert out["Article_ID"].tolist() == ["a", "c"]


def test_no_filter_sorts():
    assert select(META)["Article_ID"].tolist() == ["a", "b", "c", "d"]


def test_missing_ids_fail():
    with pytest.raises(SystemExit, match="1 listed articles"):
        select(META, ids=["a", "x"])
