import pandas as pd
import pytest

from edhiphy.package import web_mention_ids


def test_web_mention_ids_rank_offsets_per_page():
    ids = pd.Series(["7_2_40", "7_1_300", "7_1_12", "8_1_5", "7_2_3"])
    assert web_mention_ids(ids).values.tolist() == [
        ["7_2_40", "7_2_2"],
        ["7_1_300", "7_1_2"],
        ["7_1_12", "7_1_1"],
        ["8_1_5", "8_1_1"],
        ["7_2_3", "7_2_1"],
    ]


def test_web_mention_ids_v1():
    ids = pd.Series(["184236_7", "184237_13"])
    assert web_mention_ids(ids)["Web_Mention_ID"].tolist() == ids.tolist()
    with pytest.raises(SystemExit):
        web_mention_ids(pd.Series(["184236_7", "7_1_12"]))
