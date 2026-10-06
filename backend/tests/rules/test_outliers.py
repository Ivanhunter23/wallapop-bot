"""Tests for the Python port of the dashboard's price-outlier detection.

The golden cases are worked by hand. The parity test runs the original
priceOutliers.js under Node on the same inputs and requires identical
output, so the port can replace the JS without changing any statistic.
"""

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from wallabot.rules.outliers import detect_price_outliers, median

JS_SOURCE = Path(__file__).parents[3] / "market_dashboard" / "src" / "lib" / "priceOutliers.js"


class TestMedian:
    def test_empty(self):
        assert median([]) is None

    def test_odd_and_even(self):
        assert median([3, 1, 2]) == 2
        assert median([4, 1, 3, 2]) == 2.5


class TestDetectPriceOutliers:
    def test_expensive_bundle_is_an_outlier(self):
        # median 30, MAD 5; z(2199) = 0.6745 * 2169 / 5 = 292.6
        items = [("a", 20), ("b", 25), ("c", 30), ("d", 35), ("e", 40), ("lot", 2199)]
        assert detect_price_outliers(items) == {"lot"}

    def test_boundary_uses_strict_greater_than(self):
        # median 10, MAD 1 -> z = 0.6745 * (p - 10): 15.18 gives 3.494, 15.2 gives 3.507
        base = [("a", 9), ("b", 10), ("c", 10), ("d", 11), ("e", 11), ("f", 9)]
        assert detect_price_outliers([*base, ("x", 15.18)]) == set()
        assert detect_price_outliers([*base, ("x", 15.2)]) == {"x"}

    def test_low_price_rule_applies_even_with_few_samples(self):
        assert detect_price_outliers([("a", 1), ("b", 2), ("c", 2.01)]) == {"a", "b"}

    def test_fewer_than_five_positive_prices_skip_mad(self):
        items = [("a", 20), ("b", 25), ("c", 30), ("lot", 2199), ("free", 0)]
        assert detect_price_outliers(items) == set()

    def test_zero_mad_flags_only_low_prices(self):
        items = [("a", 30), ("b", 30), ("c", 30), ("d", 30), ("e", 1), ("f", 500)]
        assert detect_price_outliers(items) == {"e"}

    def test_cheap_prices_count_towards_the_median_and_mad(self):
        # The low-price rule does not remove cheap listings before the MAD
        # step. Seven 1 EUR listings make the median 1 and the MAD 0, so the
        # 90 EUR listing escapes; without them it would be flagged.
        rest = [("a", 20), ("b", 22), ("c", 25), ("d", 28), ("e", 30), ("x", 90)]
        cheap = [(f"cheap{i}", 1) for i in range(7)]
        assert detect_price_outliers(rest) == {"x"}
        assert detect_price_outliers(cheap + rest) == {i for i, _ in cheap}

    @pytest.mark.parametrize("price", ["?", "30", None, True, 0, -5])
    def test_non_positive_or_non_numeric_prices_are_ignored(self, price):
        items = [("a", 20), ("b", 25), ("c", 30), ("d", 35), ("odd", price)]
        assert detect_price_outliers(items) == set()


def _random_category(rng: random.Random) -> list[dict]:
    size = rng.randint(0, 40)
    center = rng.choice([5, 15, 30, 60, 150])
    items = []
    for i in range(size):
        roll = rng.random()
        if roll < 0.05:
            price = rng.choice(["?", None, 0, -1, True])
        elif roll < 0.15:
            price = rng.choice([1, 1.5, 2, 2.5])
        elif roll < 0.25:
            price = round(center * rng.uniform(3, 60), 2)
        elif roll < 0.35:
            price = center  # ties make MAD zero in small categories
        else:
            price = round(rng.gauss(center, center / 4), rng.choice([0, 2]))
        items.append({"item_id": f"id{i}", "price": price})
    return items


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_matches_javascript_implementation(tmp_path):
    rng = random.Random(20261006)
    cases = [_random_category(rng) for _ in range(500)]

    # Copy to .mjs so Node treats it as an ES module regardless of version.
    shutil.copy(JS_SOURCE, tmp_path / "priceOutliers.mjs")
    runner = tmp_path / "run.mjs"
    runner.write_text(
        'import { readFileSync } from "node:fs";\n'
        'import { detectPriceOutliers } from "./priceOutliers.mjs";\n'
        'const cases = JSON.parse(readFileSync(0, "utf8"));\n'
        "const out = cases.map((items) => [...detectPriceOutliers(items)].sort());\n"
        "process.stdout.write(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(runner)],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        check=True,
    )
    js_outputs = json.loads(result.stdout)

    flagged = 0
    for items, js_ids in zip(cases, js_outputs, strict=True):
        py_ids = detect_price_outliers((i["item_id"], i["price"]) for i in items)
        assert sorted(py_ids) == js_ids, items
        flagged += len(js_ids)
    # Guard against a vacuous pass where neither side flags anything.
    assert flagged > 100
