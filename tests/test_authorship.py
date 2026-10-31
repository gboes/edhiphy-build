import pandas as pd

from edhiphy.authorship import article_authors


def test_authors_in_position_order():
    authorship = pd.DataFrame(
        {
            "Article_ID": ["a", "a", "b"],
            "Phi_ID": ["P:830", "P:6265", "P:1"],
            "author_position": [2, 1, 1],
        }
    )
    out = article_authors(authorship).set_index("Article_ID")
    assert out.loc["a", "Authors_Phi_ID"] == "P:6265;P:830"
    assert out.loc["a", "N_authors"] == 2
    assert out.loc["b", "Authors_Phi_ID"] == "P:1"
