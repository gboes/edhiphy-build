from edhiphy.life_dates import life_dates_text, year_text


def test_year_text():
    assert year_text(1847) == "1847"
    assert year_text(-535, 1) == "c. 535 BC"
    assert year_text(-535, 0, era=False) == "535"


def test_life_dates_text():
    assert life_dates_text(1847, 0, 1939, 0) == "1847–1939"
    assert life_dates_text(-427, 1, -347, 1) == "c. 427–c. 347 BC"
    assert life_dates_text(-4, 0, 65, 1) == "4 BC–c. AD 65"
    assert life_dates_text(1962, 0, None, None) == "b. 1962"
    assert life_dates_text(None, None, -22, 1) == "d. c. 22 BC"
    assert life_dates_text(1900, 0, 1800, 0) is None
    assert life_dates_text(None, None, None, None) is None
