import pandas as pd

from edhiphy import wikidata_labels
from edhiphy.wikidata_labels import labels

Q = "http://www.wikidata.org/entity/"


def test_labels_follow_redirects(monkeypatch):
    texts = {"Q2": [("fr", "label", "Héraclite"), ("fr", "alias", "Heraclite")]}

    def fetch(qids, langs, pause):
        return [
            {"Queried_Wiki_ID": Q + q, "lang": l, "kind": k, "text": t}
            for q in qids
            for l, k, t in texts.get(q, [])
        ]

    monkeypatch.setattr(wikidata_labels, "fetch", fetch)
    redirects = pd.DataFrame(
        {"Wiki_ID": [Q + "Q1"], "Status": ["redirect"], "Target_Wiki_ID": [Q + "Q2"]}
    )
    out = labels([Q + "Q1", Q + "Q2", Q + "Q3"], ["fr"], redirects, 1, 0)
    assert out.values.tolist() == [
        [Q + "Q1", Q + "Q2", "fr", "alias", "Heraclite"],
        [Q + "Q1", Q + "Q2", "fr", "label", "Héraclite"],
        [Q + "Q2", Q + "Q2", "fr", "alias", "Heraclite"],
        [Q + "Q2", Q + "Q2", "fr", "label", "Héraclite"],
    ]
