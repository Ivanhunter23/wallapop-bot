"""Characterisation tests for the prototype's item normalisers.

Raw items are hand-written with only the fields the normalisers read.
"""

from datetime import datetime

import pytest

# 2026-06-21 13:10:49 in Europe/Madrid (CEST, UTC+2)
CREATED_EPOCH_S = 1782040249
CREATED_LOCAL = datetime(2026, 6, 21, 13, 10, 49)


def wallapop_item(**overrides):
    item = {
        "id": "8z88nq82ndz3",
        "title": "Nintendo DS Lite Negra",
        "price": {"amount": 30.0, "currency": "EUR"},
        "created_at": CREATED_EPOCH_S * 1000,
        "web_slug": "nintendo-ds-lite-negra-1274440146",
    }
    item.update(overrides)
    return item


def vinted_item(**overrides):
    item = {
        "id": 696701196,
        "title": "Pokemon Platino",
        "price": {"amount": "12.0", "currency_code": "EUR"},
        "url": "https://www.vinted.es/items/696701196-pokemon-platino",
        "photo": {"high_resolution": {"timestamp": CREATED_EPOCH_S}},
    }
    item.update(overrides)
    return item


class TestNormaliseWallapop:
    def test_full_item(self, watcher):
        assert watcher.normalize_wallapop_item(wallapop_item()) == {
            "item_id": "8z88nq82ndz3",
            "title": "Nintendo DS Lite Negra",
            "price": 30.0,
            "currency": "EUR",
            "created": CREATED_LOCAL,
            "url": "https://es.wallapop.com/item/nintendo-ds-lite-negra-1274440146",
            "source": "wallapop",
        }

    def test_created_is_naive_local_time(self, watcher):
        created = watcher.normalize_wallapop_item(wallapop_item())["created"]
        assert created.tzinfo is None

    @pytest.mark.parametrize("missing", ["id", "web_slug"])
    def test_missing_required_field_returns_none(self, watcher, missing):
        item = wallapop_item()
        del item[missing]
        assert watcher.normalize_wallapop_item(item) is None

    def test_missing_optional_fields_use_defaults(self, watcher):
        item = wallapop_item()
        del item["title"], item["price"], item["created_at"]
        result = watcher.normalize_wallapop_item(item)
        assert result["title"] == ""
        assert result["price"] == "?"
        assert result["currency"] == "EUR"
        assert result["created"] is None

    def test_price_amount_is_passed_through_unconverted(self, watcher):
        result = watcher.normalize_wallapop_item(wallapop_item(price={"amount": "30"}))
        assert result["price"] == "30"

    def test_zero_created_at_means_unknown(self, watcher):
        assert watcher.normalize_wallapop_item(wallapop_item(created_at=0))["created"] is None


class TestNormaliseVinted:
    def test_full_item(self, watcher):
        assert watcher.normalize_vinted_item(vinted_item()) == {
            "item_id": "v:696701196",
            "title": "Pokemon Platino",
            "price": 12.0,
            "currency": "EUR",
            "created": CREATED_LOCAL,
            "url": "https://www.vinted.es/items/696701196-pokemon-platino",
            "source": "vinted",
        }

    def test_missing_id_returns_none(self, watcher):
        item = vinted_item()
        del item["id"]
        assert watcher.normalize_vinted_item(item) is None

    @pytest.mark.parametrize(
        "price",
        [{"amount": None}, {"amount": "gratis"}, {}, None],
    )
    def test_unparseable_price_becomes_question_mark(self, watcher, price):
        assert watcher.normalize_vinted_item(vinted_item(price=price))["price"] == "?"

    def test_missing_optional_fields_use_defaults(self, watcher):
        item = vinted_item()
        del item["title"], item["url"], item["photo"]
        result = watcher.normalize_vinted_item(item)
        assert result["title"] == ""
        assert result["url"] == ""
        assert result["created"] is None

    @pytest.mark.parametrize(
        "photo",
        [
            None,
            {},
            {"high_resolution": None},
            {"high_resolution": {"timestamp": None}},
            {"high_resolution": {"timestamp": "not-a-number"}},
            {"high_resolution": {"timestamp": 10**20}},
        ],
    )
    def test_bad_photo_timestamp_means_unknown(self, watcher, photo):
        assert watcher.normalize_vinted_item(vinted_item(photo=photo))["created"] is None

    def test_photo_timestamp_as_string_is_accepted(self, watcher):
        photo = {"high_resolution": {"timestamp": str(CREATED_EPOCH_S)}}
        assert watcher.normalize_vinted_item(vinted_item(photo=photo))["created"] == CREATED_LOCAL


class TestWallapopPagination:
    def test_extract_items(self, watcher):
        data = {"data": {"section": {"items": [{"id": "a"}]}}}
        assert watcher.extract_items(data) == [{"id": "a"}]

    @pytest.mark.parametrize(
        "data",
        [{}, {"data": None}, {"data": {"section": {}}}, {"data": {"section": {"items": None}}}],
    )
    def test_extract_items_tolerates_missing_section(self, watcher, data):
        assert watcher.extract_items(data) == []

    def test_extract_next_page(self, watcher):
        assert watcher.extract_next_page({"meta": {"next_page": "tok"}}) == "tok"
        assert watcher.extract_next_page({"meta": None}) is None
        assert watcher.extract_next_page({}) is None
