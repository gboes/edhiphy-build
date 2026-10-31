import pandas as pd

from edhiphy.dictionary_layers import flag_whole_dictionary


def test_given_name_aliases_and_issue_list():
    variants = pd.DataFrame(
        {
            "Phi_ID": ["P:1", "P:2", "P:3", "P:3"],
            "Variant": ["Jean", "Marx", "Bull", "Hedley Bull"],
            "Variant_origin": [
                "Wiki aliases",
                "Wiki aliases",
                "Wiki surname",
                "Original Wiki label",
            ],
            "Issue_level": [None, None, None, None],
        }
    )
    labels = pd.Series({"P:1": "Jean Gayon", "P:2": "Karl Marx", "P:3": "Hedley Bull"})
    issues = pd.DataFrame({"Variant": ["Bull"], "Issue_level": ["Highly_problematic"]})
    frozen = variants.iloc[:0]
    level = flag_whole_dictionary(
        variants, frozen, {"Jean", "Marx"}, True, issues, labels
    )
    # "Jean" is Jean Gayon's given name; "Marx" is Karl Marx's surname.
    assert level.where(level.notna(), None).tolist() == [
        "Maybe_problematic",
        None,
        "Highly_problematic",
        None,
    ]
