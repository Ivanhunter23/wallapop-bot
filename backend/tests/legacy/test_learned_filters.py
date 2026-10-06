"""Characterisation tests for learned-filter word extraction and matching.

The prototype has two Python copies (watcher and server); both are pinned
here, and a parity test checks they agree.
"""

import json

import pytest

TITLES = [
    "Folleto Mundo Misterioso Exploradores del Cielo",
    "Pokémon Mundo Misterioso Exploradores del Cielo",
    "Juego Nintendo DS Pokémon Platino para la DSi",
    "Lote 3DS + 2 juegos",
    "Ñandú Ácido Über çà",
    "DS",
    "",
]


class TestExtractWords:
    def test_lowercases_strips_accents_and_stopwords(self, server):
        words = server.extract_filter_words("Juego Nintendo DS Pokémon Platino para la DSi")
        # "juego", "nintendo", "para" are stopwords; "ds" and "la" are too short.
        assert words == ["pokemon", "platino", "dsi"]

    def test_keeps_order_and_duplicates(self, server):
        assert server.extract_filter_words("Lote lote LOTE ds") == ["lote", "lote", "lote"]

    def test_digits_count_as_word_characters(self, server):
        assert server.extract_filter_words("Lote 3DS + 2 juegos") == ["lote", "3ds"]

    def test_letters_without_ascii_decomposition_drop_the_word(self, server):
        # "ß" survives NFD and is a word character for the Unicode-aware
        # \b, so "gro" has no closing boundary and "größe" yields nothing.
        assert server.extract_filter_words("Größe M") == []

    def test_empty_title(self, server):
        assert server.extract_filter_words("") == []

    @pytest.mark.parametrize("title", TITLES)
    def test_watcher_and_server_agree(self, watcher, server, title):
        assert watcher._extract_filter_words(title) == server.extract_filter_words(title)


FOLLETO_RULE = {
    "search_term": "pokemon mundo misterioso exploradores del cielo",
    "words": ["folleto", "mundo", "misterioso", "exploradores", "cielo"],
}


class TestMatching:
    def test_title_must_contain_every_rule_word(self, server):
        rules = [FOLLETO_RULE]
        term = FOLLETO_RULE["search_term"]
        assert server.matches_learned_filter(
            "FOLLETO Mundo Misterioso Exploradores del Cielo original", term, rules
        )
        # The real game shares four of five words but lacks "folleto".
        assert not server.matches_learned_filter(
            "Pokémon Mundo Misterioso Exploradores del Cielo", term, rules
        )

    def test_rule_applies_only_to_its_exact_search_term(self, server):
        title = "Folleto Mundo Misterioso Exploradores del Cielo"
        assert not server.matches_learned_filter(title, "pokemon platino", [FOLLETO_RULE])

    def test_search_term_comparison_is_whitespace_sensitive(self, server):
        # Current behaviour, questionable: the watcher searches "pokemon negro "
        # (trailing space) while the server strips the term before saving a
        # rule, so such rules never fire in the watcher.
        rule = {"search_term": "pokemon negro", "words": ["funda"]}
        assert server.matches_learned_filter("Funda Pokemon Negro", "pokemon negro", [rule])
        assert not server.matches_learned_filter("Funda Pokemon Negro", "pokemon negro ", [rule])

    def test_one_word_rule_hides_every_title_with_that_word(self, server):
        # Current behaviour, questionable: a rule built from a short title
        # can hide a whole category.
        rule = {"search_term": "lote nintendo ds", "words": ["lote"]}
        assert server.matches_learned_filter(
            "Lote Nintendo DS Lite + 10 juegos", "lote nintendo ds", [rule]
        )

    def test_word_order_and_duplicates_are_ignored(self, server):
        rule = {"search_term": "t", "words": ["cielo", "mundo", "mundo"]}
        assert server.matches_learned_filter("Mundo del cielo", "t", [rule])

    def test_rules_without_words_never_match(self, server):
        rules = [{"search_term": "t", "words": []}, {"search_term": "t"}]
        assert not server.matches_learned_filter("anything", "t", rules)

    def test_no_rules(self, server):
        assert not server.matches_learned_filter("anything", "t", [])

    def test_watcher_reads_rules_from_learned_filters_file(self, watcher, legacy_cwd, monkeypatch):
        (legacy_cwd / "learned_filters.json").write_text(
            json.dumps({"rules": [FOLLETO_RULE], "next_id": 2}), encoding="utf-8"
        )
        monkeypatch.setattr(watcher, "_lf_mtime", 0.0)
        monkeypatch.setattr(watcher, "_lf_cache", [])
        term = FOLLETO_RULE["search_term"]
        try:
            assert watcher.is_learned_excluded(
                "Folleto Mundo Misterioso Exploradores del Cielo", term
            )
            assert not watcher.is_learned_excluded(
                "Pokémon Mundo Misterioso Exploradores del Cielo", term
            )
        finally:
            (legacy_cwd / "learned_filters.json").unlink()

    def test_watcher_without_file_excludes_nothing(self, watcher, monkeypatch):
        monkeypatch.setattr(watcher, "_lf_mtime", 0.0)
        monkeypatch.setattr(watcher, "_lf_cache", [])
        assert not watcher.is_learned_excluded("Funda", "t")
