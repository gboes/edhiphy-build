import numpy as np
import pytest
import pandas as pd

from edhiphy.dictionary import (
    merge_wiki_ids,
    ambiguity_changes,
    apply_merges,
    compute_ambiguity,
    life_dates,
    philosopher_dates,
    unique_labels,
)


def variants():
    return pd.DataFrame(
        {
            "Phi_ID": ["P:10", "P:9", "P:9", "P:11", "P:12"],
            "Variant_ID": ["P:10_1", "P:9_1", "P:9_2", "P:11_1", "P:12_1"],
            "Variant": ["Moore", "Moore", "G. E. Moore", "Moore", "Kant"],
            "Issue_level": [np.nan, np.nan, np.nan, "Too_short", np.nan],
        }
    )


def test_v1_rules():
    out = compute_ambiguity(variants()).set_index("Variant_ID")
    # String order of candidates, as in v1; invalid variants are no candidates.
    assert out.loc["P:10_1", "Matching_Phi_IDs"] == "P:10|P:9"
    assert out.loc["P:10_1", "Ambiguity"] == "Ambiguous"
    assert out.loc["P:10_1", "N_Multiple_Phi_IDs"] == 2
    assert out.loc["P:9_2", "Ambiguity"] == "Univocal"
    assert out.loc["P:9_2", "Matching_Phi_IDs"] == "P:9"
    assert out.loc["P:11_1", "Ambiguity"] == "Unvalid_variant"
    assert pd.isna(out.loc["P:11_1", "Matching_Phi_IDs"])
    assert out.loc["P:11_1", "N_Multiple_Phi_IDs"] == 0


def test_changes_report_order_only_differences():
    frozen = compute_ambiguity(variants())
    frozen.loc[0, "Matching_Phi_IDs"] = "P:9|P:10"
    changes = ambiguity_changes(frozen, compute_ambiguity(variants()))
    assert changes[["Variant_ID", "column", "same_set"]].values.tolist() == [
        ["P:10_1", "Matching_Phi_IDs", True]
    ]


def test_no_changes_when_consistent():
    frozen = compute_ambiguity(variants())
    frozen["N_Multiple_Phi_IDs"] = frozen["N_Multiple_Phi_IDs"].astype(float)
    assert ambiguity_changes(frozen, compute_ambiguity(variants())).empty


def test_apply_merges():
    philosophers = pd.DataFrame(
        {
            "Phi_ID": ["P:1", "P:2", "P:3"],
            "Phi_Standard_Label": ["A. B. Smith", "Anne Smith", "Anne Smith"],
            "Wiki": [0, 1, 1],
            "JSTOR": [1, 0, 0],
            "Hiring": [0, 1, 0],
            "PhD": [0, 0, 1],
        }
    )
    variants = pd.DataFrame(
        {
            "Phi_ID": ["P:1", "P:1", "P:2", "P:3"],
            "Variant_ID": ["P:1_1", "P:1_2", "P:2_1", "P:3_1"],
            "Variant": ["A. B. Smith", "Smith", "Smith", "Smith"],
        }
    )
    biography = pd.DataFrame(
        {"Phi_ID": ["P:1", "P:2", "P:3"], "Surname": ["Smith"] * 3}
    )
    merges = pd.DataFrame({"Merged_Phi_ID": ["P:1", "P:3"], "Phi_ID": ["P:2", "P:2"]})
    p, v, b = apply_merges(merges, philosophers, variants, biography)
    assert p.to_dict("records") == [
        {
            "Phi_ID": "P:2",
            "Phi_Standard_Label": "Anne Smith",
            "Wiki": 1,
            "JSTOR": 1,
            "Hiring": 1,
            "PhD": 1,
        }
    ]
    # The target's own "Smith" is kept; the moved duplicates are dropped.
    assert v[["Phi_ID", "Variant_ID"]].values.tolist() == [
        ["P:2", "P:1_1"],
        ["P:2", "P:2_1"],
    ]
    assert b["Phi_ID"].tolist() == ["P:2"]
    with pytest.raises(SystemExit):
        apply_merges(
            pd.DataFrame({"Merged_Phi_ID": ["P:1"], "Phi_ID": ["P:9"]}), p, v, b
        )


def test_unique_labels():
    q = "http://www.wikidata.org/entity/Q"
    philosophers = pd.DataFrame(
        {
            "Phi_ID": ["P:1", "P:2", "P:3", "P:4", "P:5", "P:6"],
            "Phi_Standard_Label": ["John Watson"] * 2 + ["Kant"] + ["Anon"] * 3,
            "Wiki_ID": [q + "1", q + "2", q + "3", q + "4", q + "5", None],
        }
    )
    dates = pd.DataFrame(
        {
            "Wiki_ID": [q + "1", q + "2", q + "4", q + "5"],
            "birthYear": [1771, 1847, 1900, 1900],
            "deathYear": [1802, None, None, None],
        }
    )
    out = unique_labels(philosophers, dates)
    assert out["Phi_Standard_Label"].tolist() == [
        "John Watson (1771–1802)",
        "John Watson (b. 1847)",
        "Kant",
        # Equal years and missing years do not separate: Phi_ID.
        "Anon (P:4)",
        "Anon (P:5)",
        "Anon (P:6)",
    ]
    assert (
        out["Phi_Standard_Label_legacy"].tolist()
        == philosophers["Phi_Standard_Label"].tolist()
    )


def test_life_dates_numeric_and_text():
    q = "http://www.wikidata.org/entity/Q"
    philosophers = pd.DataFrame(
        {
            "Phi_ID": ["P:1", "P:2", "P:3", "P:4", "P:5"],
            "Wiki_ID": [q + str(i) for i in range(1, 5)] + [None],
        }
    )
    dates = pd.DataFrame(
        {
            "Wiki_ID": [q + str(i) for i in range(1, 5)],
            "birthYear": [-535, -4, 1900, -469],
            "birthUncertain": [1, 0, 0, 0],
            "deathYear": [-475, 65, None, -501],
            "deathUncertain": [1, 1, None, 1],
        }
    )
    numeric = philosopher_dates(philosophers, dates)
    assert numeric["Phi_ID"].tolist() == ["P:1", "P:2", "P:3", "P:4"]
    assert numeric["Birth_Year"].tolist() == [-535, -4, 1900, -469]
    assert life_dates(philosophers, dates).tolist() == [
        "c. 535–c. 475 BC",
        "4 BC–c. AD 65",
        "b. 1900",
        None,  # birth after death: unreliable
        None,
    ]


def test_merge_wiki_ids():
    q = "http://www.wikidata.org/entity/"
    philosophers = pd.DataFrame(
        {
            "Phi_ID": ["P:1", "P:2"],
            "Phi_Standard_Label": ["Stephen Read", "Stephen Read"],
            "Wiki_ID": [q + "Q112512513", q + "Q16405380"],
            "Wiki": [1, 1],
            "JSTOR": [1, 0],
            "Hiring": [0, 0],
            "PhD": [0, 0],
        }
    )
    variants = pd.DataFrame(
        {
            "Phi_ID": ["P:1", "P:2"],
            "Variant_ID": ["P:1_1", "P:2_1"],
            "Variant": ["Read"] * 2,
        }
    )
    biography = pd.DataFrame({"Phi_ID": ["P:1", "P:2"]})
    merges = pd.DataFrame(
        {"Merged_Phi_ID": ["P:2"], "Phi_ID": ["P:1"], "Wiki_ID": ["Q16405380"]}
    )
    p, _, _ = apply_merges(merges, philosophers, variants, biography)
    assert p[["Phi_ID", "Wiki_ID"]].values.tolist() == [["P:1", q + "Q16405380"]]
    assert merge_wiki_ids(merges.assign(Wiki_ID=[None])) == {}
    two = pd.concat([merges, merges.assign(Merged_Phi_ID="P:3", Wiki_ID="Q1")])
    with pytest.raises(SystemExit):
        merge_wiki_ids(two)
