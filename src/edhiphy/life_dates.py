"""Display of life dates.

The databases store years as integers in historical numbering (535 BC is
-535, no year 0) with a flag for uncertain years (circa, or the midpoint
of a range): ``Philosopher_Life_Dates``. This module turns them into text,
for the label suffixes of the dictionary stage and for the web app:
"1847–1939", "c. 535–c. 475 BC", "4 BC–AD 65", "b. 1962", "d. c. 22 BC".
"""

import pandas as pd


def _missing(v) -> bool:
    return v is None or pd.isna(v)


def year_text(year: int, uncertain=False, era: bool = True) -> str:
    """``year`` as text; ``era=False`` omits "BC" (for the first year of a
    span that ends BC)."""
    c = "c. " if not _missing(uncertain) and uncertain else ""
    if year > 0:
        return f"{c}{year}"
    return f"{c}{-year}" + (" BC" if era else "")


def life_dates_text(birth, birth_uncertain, death, death_uncertain) -> str | None:
    """Text of a philosopher's life dates, or None if no usable year. A
    birth year after the death year is treated as unknown."""
    b = None if _missing(birth) else int(birth)
    d = None if _missing(death) else int(death)
    if b is not None and d is not None:
        if b > d:
            return None
        if b < 0 < d:
            c = "c. " if not _missing(death_uncertain) and death_uncertain else ""
            return f"{year_text(b, birth_uncertain)}–{c}AD {d}"
        return (
            f"{year_text(b, birth_uncertain, era=False)}–"
            f"{year_text(d, death_uncertain)}"
        )
    if b is not None:
        return f"b. {year_text(b, birth_uncertain)}"
    if d is not None:
        return f"d. {year_text(d, death_uncertain)}"
    return None
