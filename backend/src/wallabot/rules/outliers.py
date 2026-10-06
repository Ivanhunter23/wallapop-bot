"""Price-outlier detection, ported from the prototype dashboard's JS.

Why MAD and not the standard deviation: categories are small and the
outliers are extreme (a 2199 EUR bundle among 20-50 EUR games). The
standard deviation is inflated by the very outlier it should detect, so
the threshold stops working. The median and the MAD are robust to it.

MAD alone misses the cheap "1 EUR, make me an offer" listings, because
prices run continuously from 1 EUR upwards in many categories. A separate
low-price rule catches those regardless of sample size.
"""

from collections.abc import Iterable, Sequence

from wallabot import config

# Scales the MAD so it estimates the standard deviation under a normal distribution.
_MAD_TO_SIGMA = 0.6745


def median(values: Sequence[float]) -> float | None:
    """Median of the values, or None when there are none."""
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _is_positive_number(price: object) -> bool:
    # Mirrors the JS check `typeof price === "number" && price > 0`:
    # bools and numeric strings such as "?" or "30" are not prices.
    return isinstance(price, int | float) and not isinstance(price, bool) and price > 0


def detect_price_outliers(
    items: Iterable[tuple[str, object]],
    *,
    threshold: float = config.OUTLIER_MODIFIED_Z_THRESHOLD,
    low_price: float = config.OUTLIER_LOW_PRICE_THRESHOLD,
    min_samples: int = config.OUTLIER_MIN_SAMPLES,
) -> set[str]:
    """Return the ids whose price should not count towards category stats.

    `items` are (item_id, price) pairs from one category (search term),
    with noise already removed: noise left in would shift the median that
    every distance is measured from.
    """
    priced = [(item_id, price) for item_id, price in items if _is_positive_number(price)]

    outliers = {item_id for item_id, price in priced if price <= low_price}

    if len(priced) < min_samples:
        return outliers

    prices = [price for _, price in priced]
    center = median(prices)
    mad = median([abs(price - center) for price in prices])
    # MAD is 0 when at least half the prices are identical; there is no
    # spread to measure against, so only the low-price rule applies.
    if not mad:
        return outliers

    for item_id, price in priced:
        if abs(_MAD_TO_SIGMA * (price - center) / mad) > threshold:
            outliers.add(item_id)
    return outliers
