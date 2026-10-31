import re

from edhiphy.clean import Tracked, clean_en_v1, clean_record, raw_position

HEADER = "12 THE INVENTED REVIEW "


def check_map(record, pages):
    raw = "".join(pages)
    text = record["FullText"]
    for c, r, n in zip(record["seg_clean"], record["seg_raw"], record["seg_len"]):
        assert text[c : c + n] == raw[r : r + n]


def test_tracked_sub_keeps_equal_characters():
    t = Tracked.raw("a\n\nb  c")
    out = t.sub(re.compile(r"\s+"), " ")
    assert out.text == "a b c"
    # A newline replaced by a space has no origin; an unchanged space keeps it.
    assert out.origin == [0, -1, 3, 4, 6]


def test_header_page_number_and_joins():
    pages = [
        HEADER + 'Kant\'s "critique" is dis- cussed here, cf. below. 12',
        "Short",
        HEADER + "Hume, D. wrote it. 13",
    ]
    text = clean_en_v1(pages, ["Ada Testwright"]).text
    assert text == "Kant critique is discussed here, below. Short Hume D. wrote it. "


def test_short_header_drops_twenty_characters():
    # No header before the first lower-case word: v1 drops 20 characters.
    text = clean_en_v1(["On the uses of synthetic examples."], None).text
    assert text == "etic examples. "


def test_creators_removed_on_first_and_last_page_only():
    pages = [
        HEADER + "By Ada Testwright.",
        HEADER + "Ada Testwright again.",
        HEADER + "ADA TESTWRIGHT.",
    ]
    text = clean_en_v1(pages, ["Ada Testwright"]).text
    # A page without lower-case letters keeps its header (v1: "No header").
    assert text == "By . Ada Testwright again. 12 THE INVENTED REVIEW . "


def test_cited_author_pattern_is_a_regex():
    # v1 applies "Kant, I." as a regular expression: "." matches any
    # character, so "Kant, Ix" is rewritten as well.
    pages = [HEADER + "See Kant, I. and Kant, Ix here."]
    assert clean_en_v1(pages, None).text == "See Kant I. and Kant I. here. "


def test_raw_position():
    pages = [HEADER + "First page text.", HEADER + "Kant on page two."]
    r = clean_record("http://www.jstor.org/stable/1", pages, None, "jstor_en_v1")
    check_map(r, pages)
    pos = r["FullText"].index("Kant")
    assert raw_position(r, pos) == (2, len(HEADER))
    assert raw_position(r, r["FullText"].index(" Kant")) is None


def test_french_rules():
    pages = [
        "58 LES ETUDES INVENTEES Selon M. Bergson (cf. p. 12, op. cit.) « la durée » "
        "de l'œuvre d'Aristote, t. II, etc. Voir J. Wahl, Vers le con- cret. 58"
    ]
    r = clean_record(
        "http://www.jstor.org/stable/1", pages, ["Jean Testeur"], "jstor_fr"
    )
    check_map(r, pages)
    assert r["FullText"] == (
        "Selon Bergson ( 12, ) la durée de l'œuvre d'Aristote, II, "
        "Voir J. Wahl, Vers le concret. "
    )


def test_french_abbreviations_need_a_word_start():
    # "p." inside a word and the initial "P." stay; "Mme" is removed.
    text = clean_record(
        "http://www.jstor.org/stable/1",
        ["12 REVUE INVENTEE Mme Weil cite P. Valéry, cap. 3"],
        None,
        "jstor_fr",
    )["FullText"]
    assert text == " Weil cite P. Valéry, cap. "
