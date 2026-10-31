import sqlite3

import pytest

from edhiphy.export_web import fts_rowid, rewrite_mention_ids


def test_fts_rowid():
    assert fts_rowid("http://www.jstor.org/stable/2103741") == 2103741
    with pytest.raises(SystemExit):
        fts_rowid("http://www.jstor.org/stable/10.2307/2103741")


def test_rewrite_mention_ids():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE Mention (Mention_ID TEXT PRIMARY KEY);
        CREATE TABLE Mention_Associated (Mention_ID TEXT, Phi_ID TEXT);
        CREATE TABLE Mention_Web_ID (Mention_ID TEXT PRIMARY KEY, Web_Mention_ID TEXT UNIQUE);
        INSERT INTO Mention VALUES ('7_1_2'), ('7_1_9');
        INSERT INTO Mention_Associated VALUES ('7_1_9', 'P:1'), ('7_1_9', 'P:2');
        INSERT INTO Mention_Web_ID VALUES ('7_1_2', '7_1_1'), ('7_1_9', '7_1_2');
        """
    )
    # 7_1_9 -> 7_1_2 collides with the old 7_1_2 in a direct update.
    assert rewrite_mention_ids(conn) == ["Mention", "Mention_Associated"]
    assert conn.execute("SELECT * FROM Mention ORDER BY 1").fetchall() == [
        ("7_1_1",),
        ("7_1_2",),
    ]
    assert conn.execute("SELECT * FROM Mention_Associated").fetchall() == [
        ("7_1_2", "P:1"),
        ("7_1_2", "P:2"),
    ]
    conn.execute("INSERT INTO Mention VALUES ('7_2_5')")
    with pytest.raises(SystemExit):
        rewrite_mention_ids(conn)
