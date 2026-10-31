import numpy as np
import pandas as pd

from edhiphy.similarity import author_profiles, lsa, mention_profiles, top_k

TEXTS = [
    "logic proof theorem axiom logic proof",
    "logic theorem axiom proof proof",
    "virtue ethics happiness virtue good life",
    "ethics virtue good happiness life",
    "perception colour sense data perception",
]


def test_lsa_groups_similar_texts():
    A, terms, idf, V, info = lsa(TEXTS, dimensions=3, min_df=1, max_df=1.0)
    assert A.shape == (5, 3) and V.shape == (len(terms), 3)
    S = A @ A.T
    assert S[0, 1] > 0.9 and S[2, 3] > 0.9
    assert S[0, 1] > S[0, 2] and S[2, 3] > S[2, 4]
    # A query projected with the term vectors lands near its texts.
    q = np.zeros(len(terms))
    q[list(terms).index("virtue")] = idf[list(terms).index("virtue")]
    qv = q @ V
    assert np.argmax(A @ (qv / np.linalg.norm(qv))) in (2, 3)


def test_mention_profiles_downweight_ubiquitous_philosophers():
    ids = pd.Index(["a", "b", "c"])
    m = pd.DataFrame(
        {
            "Article_ID": ["a", "a", "b", "b", "c", "c"],
            "Mentioned_Phi_ID": ["P:2", "P:3", "P:2", "P:3", "P:2", "P:4"],
        }
    )
    M = mention_profiles(m, ids).toarray()
    # P:2 is mentioned in every article: idf 0.
    assert np.allclose(M[:, 0], 0)
    assert np.isclose(M[0] @ M[1], 1.0) and np.isclose(M[0] @ M[2], 0.0)


def test_top_k_excludes_self_and_invalid():
    S = np.array([[1.0, 0.9, 0.5], [0.9, 1.0, 0.8], [0.5, 0.8, 1.0]])
    idx, vals = top_k(S, 0, 2, np.array([True, True, False]))
    assert idx[:, 0].tolist() == [1, 0, 1]
    # Rows 0 and 1 have one valid neighbour each, row 2 has two.
    assert np.isneginf(vals[:2, 1]).all()
    assert idx[2].tolist() == [1, 0] and vals[2].tolist() == [0.8, 0.5]


def test_author_profiles():
    index = pd.Index(["a", "b", "c"])
    A = np.eye(3, dtype=np.float32)
    mentions = pd.DataFrame(
        {
            "Article_ID": ["a", "a", "b", "c", "c"],
            "Mentioned_Phi_ID": ["P:2", "P:10", "P:3", "P:2", "P:4"],
        }
    )
    # P:10 writes a and b (b with P:11); P:12 writes c; c fails the LSA filter.
    authorship = pd.DataFrame(
        {
            "Article_ID": ["a", "b", "b", "c"],
            "Phi_ID": ["P:10", "P:10", "P:11", "P:12"],
        }
    )
    lsa_ok = np.array([True, True, False])
    authors, L, M, stats = author_profiles(A, mentions, authorship, index, lsa_ok)
    assert list(authors) == ["P:10", "P:11", "P:12"]
    assert stats["articles"].tolist() == [2, 1, 1]
    assert stats["lsa_articles"].tolist() == [2, 1, 0]
    # P:10's own mention of P:10 is dropped; the co-authored b counts for P:11.
    assert stats["philosophers"].tolist() == [2, 1, 2]
    assert np.allclose(L[0], [2**-0.5, 2**-0.5, 0]) and np.allclose(L[2], 0)


def test_function_word_share_per_language():
    from edhiphy.similarity import ENGLISH, FRENCH, word_counts

    texts = ["la pensée de Kant et le temps", "the mind of Kant and the time"]
    fr = word_counts(texts, FRENCH)[4]
    en = word_counts(texts, ENGLISH)[4]
    assert fr[0] > 0.5 > fr[1] and en[1] > 0.5 > en[0]
