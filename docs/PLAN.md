# PLAN.md — phased rebuild of wallapop-bot

Work through the phases in order. Each phase runs on its own branch and ends with a PR (see AGENTS.md, "Git and GitHub workflow"). Tick the boxes in the Status section when a phase's done-criteria are met and Ivan has merged its PR.

Phase 2 comes early on purpose: time-on-market data only starts accumulating once the scraper writes to PostgreSQL. Every week of delay is a week less data for Phase 5.

---

## Phase 0 — Repo hygiene and safety net

Steps:

1. Move the old context file: `git mv CLAUDE.md docs/legacy/prototype-decisions-es.md`. Add `AGENTS.md`, a new `CLAUDE.md` containing only `@AGENTS.md`, and this file.
2. Move the Python code under `backend/` with `git mv`. Create a `uv` project and configure `ruff` and `pytest`.
   - The prototype must keep running after the move. Temporary entry-point shims are fine.
3. Write characterisation tests for current behaviour, before any refactor. Use the real cases documented in the legacy doc:
   - `is_noise`. Must be noise: "Carcasa Nintendo DSLite Celeste", "Dragon Quest VI nº 01/10: Los reinos oníricos". Must not be noise: "Kingdom Hearts 358/2 Days", the Zelda Spirit Tracks title that mentions "DS, DS Lite, DSi, 3DS y 2DS", "Platino 30". Add more from the code's own comments.
   - Both item normalisers, and learned-filter matching.
   - The MAD outlier logic from `priceOutliers.js`. Port it to Python, and test that it gives the same outputs as the JS on the same inputs.
4. Data audit of the local legacy files: the JSONL and the `*.json` state files. These stay uncommitted. Write `docs/data_audit.md` covering:
   - line counts, date range, rows per source and per term,
   - how often prices change, field null rates,
   - state-file sizes, and how many `reviewed.json` ids are not in `exclusions.json` (the legacy label trap).
5. Seed `DECISIONS.md` with the decisions already listed in AGENTS.md.
6. Set up a CI skeleton: a GitHub Actions workflow running `ruff` and `pytest`.

🛑 **Checkpoint 0.** Present the audit, the characterisation test list, and anything in the prototype that looks buggy (report it; don't fix it silently).

## Phase 1 — PostgreSQL schema and legacy import

Steps:

1. Docker Compose service for Postgres with a named volume, plus `.env.example`.
2. SQLAlchemy models and an initial Alembic migration implementing the data model in AGENTS.md.
3. `importers/`, idempotent: re-running changes nothing.
   - JSONL → `search_terms`, `listings`, `listing_snapshots`, with `history_origin='legacy_jsonl'`. Set `last_seen_at` from the latest line and note that it is a lower bound. Strip the `v:` prefix from Vinted ids.
   - `exclusions.json` → `exclusions`, plus `review_decisions(discard, origin='legacy_excluded')`.
   - `reviewed.json` minus the excluded ids → `review_decisions(origin='legacy_unknown')`.
   - `learned_filters.json` → `learned_filter_rules`.
   - `seen.json` → enough state that the new scraper won't re-notify old listings.
4. A reconciliation report comparing the database against the files: unique ids per source and term, snapshot counts, price-change counts.
5. Integration tests with testcontainers.

🛑 **Checkpoint 1.** Show the reconciliation report. Every mismatch is explained or fixed.

## Phase 2 — Scraper on PostgreSQL

Steps:

1. Restructure the scraper into `scraper/` (watcher, `wallapop.py`, `vinted.py`, `telegram.py`). Behaviour stays identical; the Phase 0 tests prove it.
2. Write each scan to the database in one transaction:
   - upsert listings, update `last_seen_at`, link the search term;
   - insert a snapshot when a listing is new or its price or title changed;
   - record the `scan_runs` row: pages, items, `hit_page_cap`, status, duration.
3. Replace `seen.json` and the warm-up flags with database-derived logic. Warm-up means no previous successful scan for that (source, term). Keep the Telegram queue and rate-limit behaviour.
4. Disappearance job: a listing is gone when every term it is linked to has had at least K consecutive successful, non-capped scans since its `last_seen_at` without returning it. `gone_at` is the first of those scans.
   - Choose K and justify it in DECISIONS.md.
   - Capped or failed scans never count: an absence there is not evidence.
5. Keep dual-writing the JSONL behind a flag, on by default, as a safety net. Remove it in a later commit once Ivan confirms the database is trustworthy.
6. The scraper runs on the host and in Compose.

🛑 **Checkpoint 2.** After a 24-hour run, present:
- `scan_runs` stats: success rate, capped scans, durations;
- counts of new and gone listings;
- 10 random gone listings for Ivan to open and check by hand.

## Phase 3 — FastAPI backend

Steps:

1. Endpoints, at parity with `market_server.py` plus improvements:
   - listings: paged, sorted, filtered by source, term, noise, exclusion state and text;
   - listing detail with price history;
   - per-term stats: median, min, max and count via `percentile_cont`, excluding noise, price outliers and `exclude_from_calc` listings;
   - exclusions, the review queue and review decisions, learned-filter CRUD, `/health`.
2. Outlier detection (MAD modified z-score with threshold 3.5, plus the ≤ 2 € rule) lives in `rules/` and is used by the API.
3. Unit tests and API tests against testcontainers Postgres.
4. `market_server.py` stays until Phase 4 reaches parity.

🛑 **Checkpoint 3.** Walk Ivan through the OpenAPI docs and the test coverage of each endpoint.

## Phase 4 — Angular frontend

Steps:

1. Scaffold `web/` with the Angular CLI, with a dev proxy to the API. Port the design tokens from the React app's `index.css`.
2. Parity checklist from the React app. Copy it into the PR and tick each item:
   - [ ] market table: sort by clicking headers (server-side), source badges
   - [ ] filters: source, search term, noise toggle, text search
   - [ ] virtual scrolling, replacing the "show more" chunking
   - [ ] stat cards
   - [ ] keyword ranking by median price
   - [ ] review queue: approve / discard, with optimistic update and rollback on error
   - [ ] both exclusion types, with optimistic update and rollback
   - [ ] learned-filters view
   - [ ] auto-refresh
3. New: a listing detail view with a price-history chart.
4. Tests for services and key components, plus one Playwright smoke test.
5. Once the checklist is complete and Ivan confirms, remove `market_dashboard/` and `market_server.py` in a dedicated commit.

🛑 **Checkpoint 4.** Ivan uses the new dashboard for a day before the old one is deleted.

## Phase 5 — Data science: canonical products and market analysis

### 5a. Taxonomy

Write `docs/labeling_guidelines.md` with these fields:

- `item_type`: console | game | accessory | lot | other_platform | noise
- `game_title`: a canonical list derived from the search terms
- `completeness` (games): loose_cart | boxed | cib | sealed | unknown
- `model` (consoles): ds_original | ds_lite | dsi | dsi_xl | unknown
- `for_parts`: broken, not working, sold for parts
- `confidence`, `notes`

Include an edge-case section with a decision for each case.

🛑 Ivan approves the guidelines.

### 5b. Labels

1. Draw a stratified sample of 500 listings (by term, source and price quantile) with a fixed seed. Split it into 300 `dev` and 200 `test`. Copy 100 test ids and titles to `ivan_blind.csv` with empty labels.
2. Label the dev set in batches of 50. Label the test set in its own dedicated session, commit, and never open it again while working on the matcher or the model.
3. Never relabel to make a model look better. Corrections are allowed only per the guidelines, logged in `data/labels/CHANGELOG.md`.

🛑 Ivan labels `ivan_blind.csv` without seeing Claude's labels. Compute Cohen's kappa per field and adjudicate disagreements. Phase 5c can run in parallel.

### 5c. Matcher (`catalog/`)

1. Normalise text, then apply rules, then rapidfuzz matching against canonical titles.
2. The baseline is the search term alone. Tune on dev only.
3. Freeze with tag `catalog-v1`, then evaluate once on test: per-field precision, recall and F1, a confusion matrix, and the worst errors.
4. Write the results to a `listing_catalog` table: canonical fields, confidence and matcher version.

### 5d. SQL marts (`analytics` schema)

- `listing_facts`: one row per listing, with canonical fields, first and last price, price cuts, status and time on market.
- `daily_market`: one row per day, source and term.

### 5e. Analysis notebooks

Notebooks use pandas and read the marts. Statistical conventions for every question:

- The unit of analysis is the listing; the asking price is the first observed price unless a decision says otherwise.
- Use medians and IQR, with 95% bootstrap CIs (B = 10,000, seed from config) that resample listings, not snapshots.
- Groups below `min_n` are reported as "insufficient data" and never ranked.
- Each notebook ends with two sections: "What this shows" and "What this does not show".

The questions:

- **Q1. Price per canonical product.** Median, IQR, CI and n for each product.
- **Q2. Completeness premium.** For games, complete-in-box vs loose cartridge; for consoles, boxed vs unboxed. Compare within each product, with a bootstrap CI, and check robustness with a quantile regression. State the confounder: owners who kept the box may also have kept the item in better condition, so this is association, not causation.
- **Q3. Wallapop vs Vinted** for the same product: the price ratio with a CI. Caveat: the platforms differ in buyer fees and shipping, so this compares asking prices, not what buyers pay.
- **Q4. Do underpriced listings disappear faster?**
  - Population: database-era listings only, using Wallapop's `created_at` as the origin. Vinted dates are a photo-timestamp proxy, so state how they are handled.
  - The event lies in the interval (`last_seen_at`, `gone_at`].
  - Method: Kaplan–Meier curves by price-ratio group, a log-rank test, and a Cox model as robustness.
  - Disappearance ≠ sale: say so next to the results.
  - Do not run until a data threshold set in config is met, e.g. a minimum number of gone listings.
- **Q5. Price cuts.** Both legacy and database snapshots are valid here. Report the share of listings with at least one cut, the cut size as a percentage, and the time to first cut via Kaplan–Meier.

**Pre-register Q3–Q5.** Write their definitions and thresholds in DECISIONS.md and commit before running them.

🛑 **Checkpoint 5.** Present the findings, with CIs and n, and their limitations.

## Phase 6 — ML: listing-relevance classifier with active learning

1. **Task.** Predict whether a listing is relevant to the term that found it: the actual DS game or console, as opposed to noise, other platforms or accessories when a game was searched. Inputs: title, term, price.
2. **Labels.** Human review decisions (`human`, `legacy_excluded`) plus the Phase 5 labels mapped to relevant / irrelevant. Never use `legacy_unknown`.
3. **Baselines.** Start with the current rules (`is_noise` plus learned filters). The model is a scikit-learn `Pipeline`: TF-IDF on words and character n-grams, then `LogisticRegression`. Try at most one alternative model.
4. **Evaluation.**
   - Split by time: train on older listings, test on newer ones. Explain why: new listing styles appear over time, and a random split would hide that.
   - Report precision, recall and F1 for the irrelevant class, and a PR curve.
   - Choose the threshold for the alert use case and justify it: missing a real deal vs. sending a junk alert.
5. **Tracking.** Log runs to MLflow with a local file store: params, metrics and the artifact.
6. **Serving.**
   - The API loads the joblib artifact at startup and falls back to the rules if it is missing.
   - The review queue is ordered by uncertainty (probability closest to 0.5), so every review teaches the model the most. That is active learning.
   - `make train` retrains on the new decisions.
   - Model-based alert suppression stays behind a flag, with the rules still applied.
7. **UI.** Show the model score in the review queue and the table.

🛑 **Checkpoint 6.** Present metrics against the rules baseline. Ivan decides whether to enable model-based alert suppression.

## Phase 7 — Ship

1. `docker compose up` works from a clean clone plus `.env`.
2. CI covers the backend (lint, tests with a Postgres service) and the frontend (lint, tests, build). The e2e smoke test is optional in CI.
3. `README.md`, in English:
   - a one-paragraph pitch, screenshots or a GIF, and a Mermaid architecture diagram;
   - key DS findings with CI and n, and ML results against the baseline;
   - how to run it, the project structure and limitations;
   - a data note: collected for personal research and not redistributed.
4. `DECISIONS.md` complete.
5. `INTERVIEW.md`: 15–20 questions with answers grounded in this repo, covering:
   - backend: schema design, upserts, migrations, why FastAPI;
   - frontend: signals, virtual scroll, optimistic updates;
   - DS: medians, bootstrap, censoring, kappa, confounding;
   - ML: baselines, time-based splits, threshold choice, active learning.

🛑 **Checkpoint 7.** Ivan reviews before pinning the repo on his profile.

---

## Status

- [ ] Phase 0 — Repo hygiene and safety net
- [ ] Phase 1 — PostgreSQL schema and legacy import
- [ ] Phase 2 — Scraper on PostgreSQL (JSONL dual-write removed: [ ])
- [ ] Phase 3 — FastAPI backend
- [ ] Phase 4 — Angular frontend (React dashboard removed: [ ])
- [ ] Phase 5 — Data science (guidelines approved: [ ], kappa computed: [ ], `catalog-v1` tagged: [ ], Q3–Q5 pre-registered: [ ])
- [ ] Phase 6 — ML relevance classifier
- [ ] Phase 7 — Ship
