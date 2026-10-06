"""Settings, thresholds and seeds: the single source of truth.

Phase 0 only holds the rule thresholds ported from the prototype. Runtime
settings (DATABASE_URL and friends) arrive with the database in Phase 1.
"""

# Price outliers (ported from market_dashboard/src/lib/priceOutliers.js).
# 3.5 is the modified z-score cut-off recommended by Iglewicz & Hoyle.
OUTLIER_MODIFIED_Z_THRESHOLD = 3.5
# Prices at or below this are "make me an offer" placeholders, not market prices.
OUTLIER_LOW_PRICE_THRESHOLD = 2.0
# Below this many positive prices, MAD says nothing useful about a category.
OUTLIER_MIN_SAMPLES = 5
