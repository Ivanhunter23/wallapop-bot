"""Characterisation tests for the prototype's is_noise.

They pin current behaviour, including known misses and dubious hits, so
that the Phase 2 rewrite can prove it changed nothing by accident. Cases
marked "current behaviour, questionable" are reported at Checkpoint 0 and
are not endorsements.
"""

import pytest

NOISE = [
    # Real cases from docs/legacy/prototype-decisions-es.md
    "Carcasa Nintendo DSLite Celeste",
    "Dragon Quest VI nº 01/10: Los reinos oníricos",
    # Unconditional keywords, any platform mention
    "Funda Nintendo DS Lite azul",
    "Lot de 3 stylets pour Nintendo DS",
    "Peluche Pikachu 30 cm",
    "Camiseta Pokemon talla M",
    "Pokemon knuffel Pikachu",
    "Punto de cruz Pikachu hecho a mano",
    "Pokemon Diamante CÓMIC",
    # Title patterns: volume numbers, Japanese card numbers, clothing sizes
    "Pokemon Adventures tomo 3",
    "Pokemon Special vol. 2",
    "Carte Pokemon japonaise No.148",
    "Pokemon broek maat 33",
    "Sweat Pokemon taille 40",
    # Another platform, with no DS-family mention
    "Pokemon Espada Switch",
    "Pokemon Y 3DS",
    "Pokemon Esmeralda GBA",
    "Castlevania Symphony of the Night PS1",
    "Kirby Air Ride GameCube",
    # Trading cards, with no DS-family mention
    "Carta Pokemon Charizard holo",
    "Pokemon Platino FA 162/086",
    "Booster Pokemon Platino",
    "Pokemon Blanco #119",
    "Darkrai (PAF 211)",
]

NOT_NOISE = [
    # Real cases from the legacy doc
    "Kingdom Hearts 358/2 Days",
    "Zelda Spirit Tracks para DS, DS Lite, DSi, 3DS y 2DS",
    "Platino 30",
    "Pokemon Platino 30",
    "Anno 1701",
    # Plain DS listings
    "Nintendo DS Lite Plata",
    "Pokemon HeartGold completo",
    "Ghost Trick Nintendo DS",
    # The DS-family safeguard protects other-platform and card hits...
    "Pokemon Platino DS y Switch",
    "Cartas Pokemon DS",
    # ...and "cartouche"/"cartuccia" (cartridge) are not "carte"
    "Pokemon Version Noire cartouche seule",
    "Pokemon Platino cartuccia",
    # Known residual noise the legacy doc says rules cannot catch
    "Umbreon",
    "Coches de colección Citroën",
    "Salero Pimentero Robots Cuerda",
    # Empty input
    "",
]


@pytest.mark.parametrize("title", NOISE)
def test_noise_titles(watcher, title):
    assert watcher.is_noise(title) is True


@pytest.mark.parametrize("title", NOT_NOISE)
def test_not_noise_titles(watcher, title):
    assert watcher.is_noise(title) is False


@pytest.mark.parametrize(
    "title",
    [
        # Current behaviour, questionable: keywords match as plain
        # substrings, so a console sold with its charger, or with a
        # scratched screen, is flagged as an accessory and never alerted.
        "Nintendo DS Lite con cargador",
        "Nintendo DSi pantalla rayada",
        "Nintendo DS Lite con funda y juegos",
        # A game sold with its manual ("libro de instrucciones").
        "Pokemon Diamante con libro de instrucciones",
    ],
)
def test_substring_keywords_flag_whole_listings(watcher, title):
    assert watcher.is_noise(title) is True


def test_none_title_is_not_noise(watcher):
    assert watcher.is_noise(None) is False
