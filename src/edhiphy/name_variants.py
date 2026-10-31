"""Name variants by the rules of the v1 dictionary, for the language layers
of the dictionary stage and the JSTOR author matching.

v1 (``src/handover/generate_surname_variants.py``) derived from each
Wikidata entry its label, its aliases, its family names (P734) and, for
every given name (P735) and family name, the artificial variants
"I. Surname" and "Surname I."; from a JSTOR author name it derived an
"artificial surname" (``v1_surname``). The French layer adds: family
names with a leading lower-case particle ("de Tocqueville") also without
it ("Tocqueville"); for a hyphenated given name also the French initials
("J.-P. Sartre").
"""

import re

# Lower-case particles that may start a family name and are dropped for
# the particle-free variant (longest first).
PARTICLES = sorted(
    ["de la ", "de l'", "de l’", "de ", "d'", "d’", "du ", "des ", "van ", "von ",
     "van der ", "van den ", "von der ", "del ", "della ", "di ", "da "],
    key=len,
    reverse=True,
)  # fmt: skip

# Capitalised particles of v1 (``surname`` in generate_surname_variants.py).
V1_PARTICLES = {
    "Af", "Al", "Ben", "Da", "Dal", "De", "Degli", "Del", "Dela", "Della",
    "Den", "Der", "Des", "Di", "Do", "Du", "D'", "E", "El", "In", "La", "Le",
    "Lo", "Los", "Mac", "Mc", "MaC", "O", "Of", "Perin", "San", "St", "T",
    "'T", "Te", "Ten", "Ter", "Tot", "Van", "Vanden", "Vander", "Von",
    "Vonden", "Vonder", "Zu",
}  # fmt: skip

NO_SURNAME = "[No surname detected]"


def without_particle(surname: str) -> str | None:
    """``surname`` without a leading lower-case particle, or None if it has
    none (or nothing would remain)."""
    for p in PARTICLES:
        if surname.startswith(p) and len(surname) > len(p):
            rest = surname[len(p) :]
            return rest if rest[0].isupper() else None
    return None


def initials(given: str) -> list[str]:
    """Initials of a given name: "J." and, for "Jean-Paul", also "J.-P."."""
    given = given.strip()
    if not given or not given[0].isalpha():
        return []
    out = [given[0] + "."]
    parts = given.split("-")
    if len(parts) > 1 and all(p[:1].isalpha() for p in parts):
        out.append("-".join(p[0] + "." for p in parts))
    return out


def artificial_variants(given_names, surnames) -> list[str]:
    """v1 artificial variants "I. Surname" and "Surname I."."""
    out = []
    for g in given_names:
        for i in initials(g):
            for s in surnames:
                out += [f"{i} {s}", f"{s} {i}"]
    return list(dict.fromkeys(out))


def v1_surname(label: str) -> str:
    """The v1 "artificial surname" of a JSTOR author name (``surname`` in
    generate_surname_variants.py, without its error branches): the last
    word that is not an initial, or the words from the first capitalised
    particle on; initials only give ``NO_SURNAME``."""
    s = label
    for jesuit in (", S. J.", ", S.j.", ", C. S. J.", ", 3d"):
        s = s.replace(jesuit, "")
    words = s.replace(",", "").split()
    if not words or all("." in w for w in words):
        return NO_SURNAME
    kept = []
    for i, w in enumerate(words):
        if i == len(words) - 1 and "." in w:
            kept.append(w)
            if len(kept) >= 2:
                kept = kept[:-2] + [kept[-2] + " " + kept[-1]]
        if "." not in w:
            kept.append(w)
    particles = [w for w in kept if w in V1_PARTICLES]
    if particles:
        return " ".join(kept[kept.index(particles[0]) :])
    return kept[-1]


WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
LOWER_PARTICLES = {
    "de",
    "du",
    "des",
    "la",
    "le",
    "van",
    "von",
    "der",
    "den",
    "di",
    "da",
}


def name_case(name: str) -> str:
    """A JSTOR creator name with words in capitals ("JEAN-LOUIS BACKÈS",
    "Georges LABICA") in the usual case ("Jean-Louis Backès"); particles
    after the first word in lower case ("CHARLES DE KONINCK" -> "Charles de
    Koninck"), an elided one too ("D'"). Words with lower-case letters and
    initials stay as they are."""
    first = True

    def word(m):
        nonlocal first
        w = m.group(0)
        at_start = first
        first = False
        if len(w) < 2 or not w.isupper():
            return w
        w = w.lower()
        if not at_start and w in LOWER_PARTICLES:
            return w
        return w[0].upper() + w[1:]

    out = WORD.sub(word, name)
    # An elided particle in capitals before a name: "Jean D'Alembert".
    return re.sub(r"(?<=\s)D(?=['’][A-Z])", "d", out)
