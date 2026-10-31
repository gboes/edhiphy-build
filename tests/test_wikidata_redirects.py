import pandas as pd

from edhiphy import wikidata_redirects
from edhiphy.wikidata_redirects import check, review

Q = "http://www.wikidata.org/entity/"


def test_check_follows_redirect_chains(monkeypatch):
    status = {"Q1": ("redirect", "Q2"), "Q2": ("redirect", "Q3"), "Q3": ("ok", None)}
    status["Q9"] = ("missing", None)
    monkeypatch.setattr(
        wikidata_redirects, "fetch", lambda qids, pause: {q: status[q] for q in qids}
    )
    out = check(["Q1", "Q3", "Q9"], batch=2, pause=0)
    assert out.values.tolist() == [
        [Q + "Q1", "redirect", Q + "Q3"],
        [Q + "Q3", "ok", None],
        [Q + "Q9", "missing", None],
    ]


def test_review_proposals():
    status = pd.DataFrame(
        {
            "Wiki_ID": [Q + "Q1", Q + "Q2", Q + "Q3", Q + "Q9"],
            "Status": ["redirect", "redirect", "ok", "missing"],
            "Target_Wiki_ID": [Q + "Q3", Q + "Q4", None, None],
        }
    )
    philosophers = pd.DataFrame(
        {
            "Phi_ID": ["P:1", "P:2", "P:3", "P:4", "P:5"],
            "Phi_Standard_Label": ["A", "B", "A", "C", "D"],
            "Wiki_ID": [Q + "Q1", Q + "Q2", Q + "Q3", Q + "Q9|" + Q + "Q3", None],
        }
    )
    merges = pd.DataFrame({"Merged_Phi_ID": ["P:1"], "Phi_ID": ["P:3"]})
    out = review(status, philosophers, merges)
    rows = out[["Phi_ID", "Target_Phi_IDs", "Merged_into", "Proposal"]]
    assert rows.where(rows.notna(), None).values.tolist() == [
        ["P:4", None, None, "check"],
        ["P:1", "P:3|P:4", "P:3", "merge"],
        ["P:2", None, None, "update"],
    ]
