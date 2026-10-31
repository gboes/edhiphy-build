from edhiphy.name_variants import (
    NO_SURNAME,
    artificial_variants,
    name_case,
    v1_surname,
    without_particle,
)


def test_name_case():
    assert name_case("JEAN-LOUIS BACKÈS") == "Jean-Louis Backès"
    assert name_case("Georges LABICA") == "Georges Labica"
    assert name_case("CHARLES DE KONINCK") == "Charles de Koninck"
    assert name_case("JEAN D'ALEMBERT") == "Jean d'Alembert"
    assert name_case("J.-M. D.") == "J.-M. D."


def test_particles_and_initials():
    assert without_particle("de Tocqueville") == "Tocqueville"
    assert without_particle("d'Alembert") == "Alembert"
    assert without_particle("de La Mettrie") == "La Mettrie"
    assert without_particle("Descartes") is None
    assert artificial_variants(["Jean-Paul"], ["Sartre"]) == [
        "J. Sartre", "Sartre J.", "J.-P. Sartre", "Sartre J.-P.",
    ]  # fmt: skip


def test_v1_surname():
    assert v1_surname("Paul Ricœur") == "Ricœur"
    assert v1_surname("M. De Wulf") == "De Wulf"
    assert v1_surname("J.-M. D.") == NO_SURNAME
