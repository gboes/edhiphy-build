import pandas as pd
import pytest

from edhiphy.journals import assign_journals, title_index

JOURNALS = pd.DataFrame(
    {"Journal_ID": [1, 2], "Journal_name_JSTOR": ["Philosophy", "Mind"]}
)
VARIANTS = pd.DataFrame(
    {
        "Journal_ID": [1, 1],
        "Journal_variant": ["Journal of Philosophical Studies", "Philosophy"],
    }
)


def test_current_and_earlier_titles():
    index = title_index(JOURNALS, VARIANTS)
    articles = pd.DataFrame(
        {
            "Article_ID": ["a", "b", "c"],
            "isPartOf": ["Philosophy", "Journal of Philosophical Studies", "Mind"],
        }
    )
    assert assign_journals(articles, index)["Journal_ID"].tolist() == [1, 1, 2]


def test_unmatched_title_fails():
    index = title_index(JOURNALS, VARIANTS)
    articles = pd.DataFrame({"Article_ID": ["a"], "isPartOf": ["Nous"]})
    with pytest.raises(SystemExit, match="Nous"):
        assign_journals(articles, index)


def test_title_of_two_journals_fails():
    variants = pd.DataFrame({"Journal_ID": [2], "Journal_variant": ["Philosophy"]})
    with pytest.raises(SystemExit, match="more than one journal"):
        title_index(JOURNALS, variants)
