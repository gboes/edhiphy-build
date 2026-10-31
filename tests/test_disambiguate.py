import pandas as pd
import pytest

from edhiphy.contexts import context
from edhiphy.disambiguate import V1_STRATEGIES, cosine, disambiguate, s4_choice

A, B, C = (f"http://www.jstor.org/stable/{n}" for n in (1, 2, 3))


def mentions(rows):
    return pd.DataFrame(
        [
            (a, f"{a[-1]}_{i}", e, "PHILOSOPHER", ids)
            for i, (a, e, ids) in enumerate(rows)
        ],
        columns=[
            "Article_ID",
            "Mention_ID",
            "Ent_text",
            "Ent_label",
            "Associated_Phi_IDs",
        ],
    )


def statuses(out):
    return list(zip(out["Disambiguation_status"], out["Disambiguated_ID"]))


def test_s1_to_s3():
    m = mentions(
        [
            (A, "Moore", "P:4|P:5"),  # S1: G. E. Moore is named in A
            (A, "G. E. Moore", "P:4"),
            (B, "Moore", "P:4|P:5"),  # S2: same author as A
            (C, "Smith", "P:8|P:9"),  # S3: P:9 has no mention, P:8 has
            (C, "Adam Smith", "P:8"),
            (B, "Place", "P:6358|P:7"),  # S3: false positive and zero mentions
        ]
    )
    authorship = pd.DataFrame(
        {"Article_ID": [A, B, C], "Phi_ID": ["P:20", "P:20", "P:1"]}
    )
    out = disambiguate(m, authorship, {"P:6358"}, 0.01, 0.25, V1_STRATEGIES)
    assert statuses(out) == [
        ("Disambiguated_article", "P:4"),
        ("Non_ambiguous", "P:4"),
        ("Disambiguated_author", "P:4"),
        ("Disambiguated_article", "P:8"),
        ("Non_ambiguous", "P:8"),
        ("Ambiguous", "P:6358|P:7"),
    ]
    assert out["Mentioned_Phi_ID"].isna().tolist() == [False] * 5 + [True]


def test_s4_choice():
    # A clear winner above alpha.
    assert s4_choice([("P:1", 0.2), ("P:2", 0.5)], 0.01, 0.25) == "P:2"
    # Drop below beta: both survive, in ranked order.
    assert s4_choice([("P:1", 0.45), ("P:2", 0.5)], 0.01, 0.25) == "P:2|P:1"
    # Winner below alpha, or only zeros: unchanged.
    assert s4_choice([("P:1", 0.001), ("P:2", 0.0)], 0.01, 0.25) is None
    assert s4_choice([("P:1", 0), ("P:2", 0)], 0.01, 0.25) is None


def test_cosine_matches_scipy():
    from scipy.spatial.distance import cosine as scipy_cosine

    u, v = [1.0, 2.0, 0.0, 4.0], [3.0, 0.0, 1.0, 2.0]
    uv = sum(a * b for a, b in zip(u, v))
    assert cosine(uv, sum(a * a for a in u), sum(b * b for b in v)) == pytest.approx(
        1 - scipy_cosine(u, v), abs=1e-15
    )


def test_context():
    text = "abc Kant def"
    assert context(text, 4, 8, "Kant", 100) == "...abc KANT def..."
    assert context(text, 0, 3, "abc", 2) == "ABC K..."


def test_life_dates_and_recent_strategies():
    D = "http://www.jstor.org/stable/4"
    m = mentions(
        [
            (A, "Russell", "P:1"),
            (A, "Smith", "P:2|P:3|P:4"),
            (B, "Smith", "P:2|P:3"),
            (C, "Jones Sr.", "P:5"),
            (D, "Jones", "P:5|P:6"),
        ]
    )
    authorship = pd.DataFrame(columns=["Article_ID", "Phi_ID"])
    years = pd.Series({A: 1950, B: 1930, C: 1949, D: 1950})
    # P:3 is born 1935: too young in 1950 (min. age 20) and not yet born in
    # 1930; P:4 has no birth year and stays.
    births = pd.Series({"P:2": 1900, "P:3": 1935, "P:5": 1890, "P:6": 1890})

    def run(strategies):
        out = disambiguate(m, authorship, set(), 0.01, 0.25, strategies, years, births)
        return statuses(out)

    assert run("S1,L")[1:] == [
        ("Ambiguous", "P:2|P:4"),
        ("Disambiguated_life_dates", "P:2"),
        ("Non_ambiguous", "P:5"),
        ("Ambiguous", "P:5|P:6"),
    ]
    # P:5 is resolved in 1949, within a year of D; P:2 only in 1930.
    assert run("S1,L,T")[1:] == [
        ("Ambiguous", "P:2|P:4"),
        ("Disambiguated_life_dates", "P:2"),
        ("Non_ambiguous", "P:5"),
        ("Disambiguated_recent", "P:5"),
    ]
    # The default sequence: L after S1, no T.
    assert run("S1,L,S2,S3,S4") == statuses(
        disambiguate(m, authorship, set(), 0.01, 0.25, years=years, births=births)
    )
    for bad in ["S1,X", "L,S1", "S1,T,T"]:
        with pytest.raises(SystemExit):
            run(bad)
    with pytest.raises(SystemExit):
        disambiguate(m, authorship, set(), 0.01, 0.25, "S1,T")
