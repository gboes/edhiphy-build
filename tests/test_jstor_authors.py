import pandas as pd

from edhiphy.jstor_authors import match_authors, normalise

STABLE = "http://www.jstor.org/stable/"


def test_normalise():
    assert normalise("<prefix>M.</prefix> Solovine") == "Solovine"
    assert normalise("Abbé Jules MARTIN") == "Jules Martin"


def test_match_authors():
    philosophers = pd.DataFrame(
        {
            "Phi_ID": ["P:1", "P:2", "P:3", "P:4"],
            "Phi_Standard_Label": [
                "[No Author]",
                "Paul Ricœur",
                "Jean Wahl",
                "Jean Wahl",
            ],
            "JSTOR": [1, 0, 1, 0],
        }
    )
    variants = pd.DataFrame(
        {
            "Phi_ID": ["P:2", "P:3", "P:4"],
            "Variant": ["Paul Ricœur", "Jean Wahl", "Jean Wahl"],
            "Issue_level": [None, None, None],
            "Matching_Phi_IDs": ["P:2", "P:3|P:4", "P:3|P:4"],
        }
    )
    meta = pd.DataFrame(
        {
            "Article_ID": [STABLE + str(i) for i in range(1, 6)],
            "creator": [
                "PAUL RICOEUR",
                "Jean Wahl; Pierre-Maxime Schuhl",
                "P.-M. Schuhl",
                None,
                "Pierre-Maxime Schuhl",
            ],
        }
    )
    authorship, authors, review = match_authors(meta, philosophers, variants, 100)
    got = sorted(
        zip(
            authorship["Article_ID"].str[28:],
            authorship["author_position"],
            authorship["Phi_ID"],
        )
    )
    assert got == [
        ("1", 1, "P:2"),
        ("2", 1, "P:3"),
        ("2", 2, "P:100"),
        ("3", 1, "P:100"),
        ("4", 0, "P:1"),
        ("5", 1, "P:100"),
    ]
    assert authors.to_dict("records") == [
        {"Phi_ID": "P:100", "Phi_Standard_Label": "Pierre-Maxime Schuhl",
         "JSTOR_names": "P.-M. Schuhl|Pierre-Maxime Schuhl", "N_articles": 3}
    ]  # fmt: skip
    rules = dict(zip(review["JSTOR_creator"], review["rule"]))
    assert rules == {
        "PAUL RICOEUR": "variant",
        "Jean Wahl": "ambiguous_jstor",
        "Pierre-Maxime Schuhl": "new",
        "P.-M. Schuhl": "initials",
    }
