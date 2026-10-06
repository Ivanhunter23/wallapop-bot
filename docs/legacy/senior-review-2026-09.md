# Senior Engineering Review: Wallapop/Vinted market watcher

**Scope:** `wallapop_watcher.py`, `market_server.py`, `marketwatch/` (untracked, in progress), `market_dashboard/` (React + Vite), and the runtime data in `data/` and in the sibling snapshot directory `../wallabotdata/`.
**Method:** I read every source file. I then profiled the real datasets, ran the Python and JS noise filters side by side on all 25,227 unique titles, and exercised the real HTTP handler on an ephemeral port. Numbers quoted below come from those runs, not from estimates.
**Constraint respected:** no code was modified. (One side effect happened during testing; see the end of §6.)

---

## TL;DR

1. **The data you're collecting can't yet support price prediction.** Deduplication is solid: it uses Wallapop's stable item ID. But since the late-June "compaction" change, the scraper only writes a row when a price changes. So there is **no `last_seen`**, **no way to detect sold or removed listings**, and the "Avistado" (seen) column in the dashboard actually counts price changes. The raw API payload is thrown away, keeping only 8 fields. **18% of stored `is_noise` flags already disagree with the current rules.**
2. **Move to SQLite now**, before you collect more data. JSONL forced a bad trade-off: write every scan (it reached 640 MB in 3 days) or write on change (lose `last_seen` and disappearance). An upsert-capable store removes that trade-off.
3. **Noise detection is duplicated in Python and JS.** Today the two agree on 100% of real titles, but I found concrete Unicode inputs where they diverge. Learned-filter word extraction already diverges on 9 real titles. All classification, stats and outlier logic belongs in the backend. That is also what makes the Angular port small.
4. **Security/portfolio blockers:** the static file handler has a **confirmed path traversal** (`GET /../../pyproject.toml` returns 200). A **Playwright session file with Wallapop auth cookies** (`../wallabotdata/state.json`) sits in a data folder. The half-finished `marketwatch/` package describes shims, parity scripts and a JSON-driven frontend that don't exist.
5. **Correctness bugs you can hit today:** 95 of 368 learned rules are silently dead (trailing-space search terms vs `.strip()`). Some one-word rules (`['lote']`, `['3ds']`) hide whole swaths of a category. Since "Paso 1" moved the data into `data/`, running either root script from the repo root starts from an empty state, because both use cwd-relative paths.

---

## 1. Overview: the architecture as it actually is

### Processes and files

```
                        ┌──────────────────────────── wallapop_watcher.py (1 process, asyncio) ───────────────────────────┐
                        │ 1 Chromium ─ 1 BrowserContext ─ 62 Pages  (31 SEARCHES × 2 sources, one watch_search task each)  │
 Wallapop web ──────────┤  page.goto(search) + expect_response("/api/v3/search/section")  → capture URL + signed headers    │
 Wallapop API ◄─────────┤  context.request.get(url + next_page=TOKEN) × ≤40 pages          (replay, no rendering)           │
 Vinted web ────────────┤  page.goto(/catalog) only to seed cookies                                                        │
 Vinted API ◄───────────┤  context.request.get(/api/v2/catalog/items?page=N) × ≤20 pages                                   │
                        │        │ raw items ──► normalize_*_item() ──► 7 fields (+ search_term, scanned_at, is_noise)     │
                        │        ▼                                                                                          │
                        │  process_items():  if price != last_price_by_item[id] → append row to wallapop_data.jsonl         │
                        │                    if id not in seen → seen.add, save_seen() (rewrite seen.json)                 │
                        │                        → skip if is_noise / learned rule / warming-up                           │
                        │                        → telegram_queue.put(msg) ──► telegram_sender_worker (≥3.5 s spacing)   │
                        └──────────────────────────────────────────────────────────────────────────────────────────────────┘
                                   │ wallapop_data.jsonl  seen.json          ▲ learned_filters.json (reloaded on mtime)
                                   ▼                                         │
 market_server.py (stdlib ThreadingHTTPServer, 127.0.0.1:8765)                │
   GET /api/data            → re-reads + parses the ENTIRE JSONL on every call; returns every row
   GET /api/exclusions      → exclusions.json
   GET /api/pending         → dedupe rows, minus reviewed.json, minus excluded, minus learned rules
   GET /api/learned_filters → learned_filters.json
   POST /api/exclusions | /api/review | /api/learned_filters → read-modify-write JSON files (writes learned rules)
   GET /*                   → market_dashboard/dist (Vite build)
                                   │ JSON over HTTP, polled every 60 s
                                   ▼
 React app (market_dashboard/src)
   buildMarketView(): dedupe rows → isNoise() → learned rules → MAD outliers per category → median/min/max
   → filter / sort / "deal" ratio → render ≤500 rows
```

### Data flow, end to end

1. **Scrape.** For Wallapop, the first page is loaded in a real tab. `expect_response` captures the XHR's URL and headers (`wallapop_watcher.py:848-861`). Later pages are *replayed* through `context.request` using the `meta.next_page` token (`:891-918`). This is less "intercepting API responses" than "intercept once, then call the API yourself". It's a good technique: cheap, and it inherits cookies and signed headers. For Vinted, the page load only seeds cookies (`:965`); the API URL is built by hand (`:1005`).
2. **Normalize.** `normalize_wallapop_item` / `normalize_vinted_item` (`:609-671`) reduce each raw item to `item_id, title, price, currency, created, url, source`. **Everything else in the payload is discarded here.**
3. **Persist.** `process_items` (`:674`) appends a JSONL row **only when the price differs from the last stored price** (`:718`). Separately, it adds unseen IDs to `seen` and rewrites `seen.json` (`:733-773`).
4. **Notify.** New, non-noise, non-learned-excluded, non-warming items are queued. A single worker drains the queue to Telegram with spacing and 429 handling (`:556-575`).
5. **Serve.** `market_server.py` re-reads the whole JSONL on every request and ships all rows to the browser (`market_server.py:319-325`).
6. **Analyze in the browser.** The React app dedupes rows into items, classifies noise, applies learned rules, detects outliers, computes per-category stats, filters, sorts and renders (`src/lib/marketData.js:299`, `src/App.jsx:175-256`).
7. **Feedback loop.** Dashboard actions write `exclusions.json`, `reviewed.json` and `learned_filters.json`. The watcher reloads `learned_filters.json` by mtime, which changes future Telegram alerts.

### Repository state (important context)

- The git history has two commits: "Baseline" and "Paso 1: higiene del repositorio". Paso 1 moved runtime state into `data/`.
- `marketwatch/` is **untracked** and only partially written. It contains `config.py`, `searches.py`, `storage.py` and `filters/`. Its docstrings describe `sources/`, `watcher/`, `server/` and `scripts/check_noise_parity.py`, and say the root scripts "are shims that delegate here". **None of that exists**, and the root scripts don't import `marketwatch` at all.
- `../wallabotdata/` (the directory this review was launched from) is an **older snapshot**, June 21–24. It holds a per-scan JSONL (162 MB, 514,693 rows, 3,225 items), state JSON files, and a Playwright `state.json` with session cookies.

---

## 2. Module verdicts (ordered by impact)

"Impact" here means how much fixing it unlocks for the two goals: the ML dataset and the Angular migration.

| # | Module | Verdict | Why (concrete) |
|---|--------|---------|----------------|
| 1 | Persistence in `wallapop_watcher.py` (`process_items`, `append_sighting`, `seen`/`save_seen`, `last_price_by_item`, `load_last_prices`) | **REWRITE** | Write-on-price-change loses `last_seen` and disappearance (§3). It keeps a single `search_term` per item, while 32% of items match several searches. `seen.json` is rewritten non-atomically on every pass with new items (`:455`); a crash mid-write leaves invalid JSON, and the unguarded `json.load` at import (`:363-365`) then stops the watcher from starting. State loads at **import time** (`:363`, `:494`), so the module can't be imported by tests without touching the disk. Notification is at-most-once: the ID is marked seen before the message is sent, and the queue lives in memory. Replace all of this with a repository layer over SQLite. |
| 2 | `market_server.py` | **REWRITE** | Path traversal (confirmed, §6). Parses the entire dataset on every request and returns all of it. Routing is `startswith`, so `/api/database` would hit `/api/data`. Corrupt state files are treated as "empty", so the next write persists the empty state (`:214-218`). Writes are non-atomic. No request logging: `log_message` is a no-op, and that also silences `log_error`. No schema or contract that Angular could generate types from. Salvage the exclusion/review/learned-rule *semantics* into a service layer. |
| 3 | `src/lib/marketData.js`, `priceOutliers.js`, `noiseDetection.js` | **REWRITE (move to backend)** | This is domain logic running in the view layer: dedupe, classification, statistics. Porting it to Angular would mean a *third* copy. Moving it to Python makes the frontend a thin view and makes stats available to Telegram and ML too (§4, §5). |
| 4 | Fetchers `fetch_all_items`, `fetch_all_items_vinted` | **REFACTOR** | The approach is good; keep it. Missing: (a) keep the raw item JSON; (b) return scan completeness (hit the page cap? stopped on an error?), because disappearance detection depends on it; (c) recover from a crashed/closed `Page`, since `watch_search` creates the page once (`:1071`) and a dead page errors forever; (d) back off on 403/429 instead of retrying at the same rate; (e) Vinted reloads `/catalog` in 31 tabs every cycle just to refresh shared cookies, which one seeding task could do. |
| 5 | Telegram (`enqueue_telegram`, `telegram_sender_worker`) | **REFACTOR** | The queue plus rate limit plus `retry_after` design is right; keep it. Two problems: messages are lost on restart (in-memory queue, IDs already in `seen`), and nothing watches the worker task, so if it dies alerts stop silently. Make it a persistent **outbox** table (`notifications.sent_at IS NULL`). |
| 6 | Noise rules (`marketwatch/filters/filter_rules.json` + `noise.py`) | **KEEP** | These rules encode real domain knowledge (the `\b` "PlatiNO 30" fix, the DS-family safeguard, card codes with 2–3 digits so "358/2 Days" survives). The JSON form is good. Change who owns the rules (backend only), attach a `rules_version`, and add golden tests. |
| 7 | Learned filters (`learned.py` / server / JS copy) | **REFACTOR** | The semantics have real bugs (§6): search-term whitespace mismatch, one-word rules, duplicated words, and no preview of what a rule will hide. The idea (turn user feedback into rules) is valuable. It's also your best source of ML labels. |
| 8 | `marketwatch/storage.py`, `config.py`, `searches.py` | **KEEP (commit it)** | `storage.py` gets two things right that the running code gets wrong: atomic writes (tmp + fsync + `os.replace`) and fail-closed reads. `config.py` has absolute, env-overridable paths, which fixes the cwd bug. But it's **untracked** (one `git clean` from gone), and its docstrings claim things that aren't true. Commit it and fix the docs. |
| 9 | React components (`App.jsx`, `MarketRow`, `Controls`, `ReviewQueue`, `KeywordRanking`, `StatCard`) | **REPLACE (Angular)**; use as a spec | Don't invest in refactoring code you're about to delete. Do use it as the feature checklist in §5, and don't port its bugs (§5.4). |
| 10 | `src/index.css` | **KEEP** | Token-based theme (per CLAUDE.md §12). Port the `:root` tokens into Angular global styles almost verbatim. |
| 11 | `README.md`, `CLAUDE.md` | **REWRITE** | Both still say noise rules must be edited "in both files". CLAUDE.md is a 23 KB narrative of a chat session ("se diagnosticó en esta conversación"). For a portfolio, turn it into a README, an architecture doc and short ADRs. |

**Why this order:** 1–3 decide whether the data is usable and whether the Angular app is thin or fat. 4–5 decide whether the data you collect from now on is trustworthy. 6–11 are cheaper and mostly independent.

---

## 3. Data model audit (most important)

### 3.1 Is deduplication based on the stable item ID or on the title?

**The stable ID. This part is right.**

- Within a scan: `accumulate()` dedupes on the raw `it.get("id")` (`wallapop_watcher.py:875`, `:993`).
- Across searches and scans: the global `seen` set is keyed on `item["item_id"]` (`:701`, `:733`). Price tracking is keyed on `item_id` (`:718`).
- Vinted IDs are namespaced `v:<id>` (`:662`) so they can't collide with Wallapop's. Wallapop IDs are left unprefixed for backward compatibility. That's reasonable, but it gives you an **asymmetric key**. In SQL, use a composite key `(source, external_id)` and drop string prefixes.
- Evidence it works: in the live data, 89 items changed title and kept the same ID (e.g. `v6gp5m9r476e`: "Nintendo DSi rojo completo en funcionamiento" → "Nintendo DSi rojo funcional"). Title-based dedup would have split them.

**The fragile part is the *category*, not the identity.** An item that matches several searches keeps only one `search_term`:

- The watcher writes the `search_term` of whichever task happened to see the price change first (`:721`).
- The frontend keeps the `search_term` of the **first** row and never updates it (`marketData.js:263-266`; the update branch at `:273-278` doesn't touch it).
- In the per-scan snapshot, **1,044 of 3,225 items (32%)** appeared under more than one search term. Example: `v6gpv8gry76e` appeared under 9 terms, including "pokemon diamante DS", "pokemon negro DS" and "dsi".

For ML this matters a lot: `search_term` is your de-facto product label, and for a third of items it's decided by a scheduling race. Model the item↔search relationship as many-to-many (`listing_search_hits`, §3.6) and derive the product label separately.

### 3.2 Are first_seen / last_seen / published timestamps stored?

| Timestamp | Stored? | Evidence / caveat |
|---|---|---|
| **published** | Partly | Wallapop: `created_at` (epoch ms from the API) → `datetime.fromtimestamp()` (`:614`), a **naive local time**. Vinted: no real publish date; `photo.high_resolution.timestamp` is used as a proxy (`:629-646`) but stored in the **same `created_at` field**, so a model can't tell real dates from proxies. |
| **first_seen** | Implicitly | It's the `scanned_at` of an item's first row. It isn't a column; the frontend computes it (`marketData.js:268`). |
| **last_seen** | **No** | Since the compaction change, a row is written only on the first sighting or a price change (`:709-731`). A listing seen at the same price for 3 weeks produces **1 row**. The frontend's `lastSeen` (`marketData.js:269,273`) really means "last price change". |
| **scan time zone** | Naive | `datetime.now().isoformat()` (`:689`) has no offset. Europe/Madrid has DST, so the last Sunday of October has a repeated hour. Store UTC (`...Z`). |

Evidence from the live data: 27,891 items, 29,747 rows; **26,473 items (95%) have exactly one row**. The data cannot tell you whether those items were still listed a day or a month later.

### 3.3 Are price changes recorded as history or overwritten?

**Recorded as history (append-only).** This is the one thing the compaction change kept on purpose. In the live data, 1,362 items have more than one distinct price. You can rebuild each item's price series with `groupby(item_id).sort(scanned_at)`.

Caveats:

- The in-memory `last_price_by_item` is rebuilt by reading the **whole** JSONL at import (`:474-494`). Startup cost grows with the dataset.
- Price comparison is `!=` on floats or the string `"?"` (`:619`, `:658`). No `"?"` exists in current data (all 29,747 prices are floats), but the code allows mixed types, and any float jitter would create a fake "change". Store integer cents.
- **Title changes are not history.** If the title changes but the price doesn't, nothing is written. The 89 title changes observed only survived because the price changed too. For ML, title and description edits are signal ("¡¡¡COMO NUEVAS!!!" was added to an item as its price moved).

### 3.4 Do we detect and record when a listing disappears (sold/removed)?

**No.** Nothing in the code compares a scan's results against the previously active set. Worse, the current storage format makes it impossible to reconstruct after the fact, because there's no `last_seen`.

The pre-compaction snapshot shows what's being lost. Of 3,225 items in a 3-day window, **734 (23%) weren't seen in the final 24 hours**. That's the signal behind "time to sell" and "price at which it disappeared", which are arguably the most valuable targets for price prediction. **Asking prices ≠ market prices;** a listing that vanishes 2 days after posting at €40 tells you more than one that sits for 3 weeks at €40.

Why this is subtle, and why §3.6 has a `scan_runs` table: **"not in this scan's results" is not the same as "gone".** Reasons a live listing can be missing:

- the scan was truncated (`max_pages=40`/`20`, `:820`, `:934`) or aborted on an HTTP error (`:904-909`). Right now these outcomes are only printed;
- the seller edited the title, so it no longer matches the search;
- search ranking shifted it past the page cap;
- it's reserved (Wallapop has a reserved state; check the raw payload).

So a disappearance should be declared only after **N consecutive complete scans** of *every* search the listing ever matched. It should be labeled `gone`, not `sold`. Optionally confirm it later with an item-detail request.

### 3.5 Is the raw API response kept, or only pre-filtered fields?

**Only pre-filtered fields.** The normalizers keep ID, title, price, currency, created and URL (`:616-624`, `:661-669`). The row adds `scanned_at`, `search_term`, `source` and `is_noise` (`:720-730`). The raw `data` dicts are thrown away after `normalize_*`.

For price prediction this is the biggest avoidable loss. Listing APIs typically also carry description text, condition, location, shipping availability, image URLs and counts, reserved/sold flags, seller info and category IDs. I haven't verified the exact field names here; dump one response and look. Features like "includes box/manual", "PAL/JP", "shipping available" and "seller city" are highly predictive for retro games. You can't backfill them later.

The **stored derived field is also a problem.** `is_noise` is computed at write time with the rules of that moment (`:707`, `:729`). Re-running today's rules over the live data, **5,391 of 29,747 rows (18%) disagree** with their stored flag (5,380 are now noise, 11 no longer are). The frontend already ignores the stored flag and recomputes it (`marketData.js:313`). **Store facts, derive classifications.** If you do persist a classification, stamp it with `rules_version`.

### 3.6 Is JSONL still a good fit? → Move to SQLite

**No, not anymore.** JSONL was a reasonable first choice (CLAUDE.md §3: append-only, crash-tolerant, no dependencies). The project has now outgrown it in ways you can measure:

| Need | JSONL | Evidence |
|---|---|---|
| Update `last_seen` without a new row | Impossible (append-only) | You had to pick between 1.98M rows / 640 MB in ~3 days (`data/backups/wallapop_data.jsonl.bak`) and losing `last_seen`. |
| Read a filtered subset | Parse everything | The server parses the full file for every `/api/data` and `/api/pending` call, every 60 s, per browser tab. |
| Atomic multi-file update (mark seen + write row + queue alert) | No transactions | Four separate JSON files, each read-modify-written non-atomically. |
| Many-to-many (item ↔ search term) | Denormalized | 32% of items lose search membership (§3.1). |
| Concurrency (watcher writes, server reads) | "Discard the half-written line" | Works, but only because the server never writes the JSONL. |
| ML access | `pd.read_json(lines=True)` over everything | Workable, but `pd.read_sql` with indexes is better, and you can export Parquet. |

**Why SQLite and not Postgres or Parquet?**

- **SQLite:** single file, stdlib `sqlite3`, and ACID transactions. In WAL mode one writer (the watcher) and many readers (the server) work without locking each other. That's exactly your topology. It's easy to ship as a portfolio artifact.
- **Postgres** would be the answer with multiple machines or writers. You'd pay for a server and ops for no present benefit, and the schema below ports directly if you ever need it.
- **Parquet** is the right *export* format for ML (columnar, typed, fast in pandas/polars) but the wrong *operational* store (no row-level upserts). Use both: SQLite as the source of truth, with a periodic Parquet export for notebooks.

#### Proposed schema

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- One row per physical listing. Current state only; history lives in child tables.
CREATE TABLE listings (
    source            TEXT    NOT NULL CHECK (source IN ('wallapop','vinted')),
    external_id       TEXT    NOT NULL,             -- raw marketplace id, no "v:" prefix
    url               TEXT    NOT NULL,
    title             TEXT    NOT NULL,
    description       TEXT,                         -- if the payload has it
    price_cents       INTEGER,                      -- NULL = unknown; never "?"
    currency          TEXT    NOT NULL DEFAULT 'EUR',
    published_at      TEXT,                         -- UTC ISO-8601
    published_is_proxy INTEGER NOT NULL DEFAULT 0,  -- 1 for Vinted photo timestamp
    first_seen_at     TEXT    NOT NULL,             -- UTC
    last_seen_at      TEXT    NOT NULL,             -- updated on EVERY sighting (cheap UPDATE)
    status            TEXT    NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active','reserved','gone')),
    gone_at           TEXT,                         -- first complete scan where it was missing (confirmed)
    missed_scans      INTEGER NOT NULL DEFAULT 0,   -- consecutive complete scans without it
    PRIMARY KEY (source, external_id)
);
CREATE INDEX ix_listings_status_seen ON listings(status, last_seen_at);

-- Every price the listing has had (append on change, like today, but in a proper table).
CREATE TABLE price_history (
    source       TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    observed_at  TEXT NOT NULL,
    price_cents  INTEGER,
    PRIMARY KEY (source, external_id, observed_at),
    FOREIGN KEY (source, external_id) REFERENCES listings(source, external_id)
);

-- Title/description edits (append on change). Cheap and useful signal.
CREATE TABLE text_history (
    source TEXT NOT NULL, external_id TEXT NOT NULL, observed_at TEXT NOT NULL,
    title TEXT NOT NULL, description TEXT,
    PRIMARY KEY (source, external_id, observed_at),
    FOREIGN KEY (source, external_id) REFERENCES listings(source, external_id)
);

-- Which searches each listing matched (many-to-many). Fixes the "first search term wins" label.
CREATE TABLE listing_search_hits (
    source TEXT NOT NULL, external_id TEXT NOT NULL, search_term TEXT NOT NULL,
    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    PRIMARY KEY (source, external_id, search_term),
    FOREIGN KEY (source, external_id) REFERENCES listings(source, external_id)
);

-- One row per (source, search) scan. Required to make "missing" mean anything.
CREATE TABLE scan_runs (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,
    search_term   TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    pages_fetched INTEGER NOT NULL DEFAULT 0,
    items_returned INTEGER NOT NULL DEFAULT 0,
    complete      INTEGER NOT NULL DEFAULT 0,   -- 1 only if pagination ended naturally
    error         TEXT
);
CREATE INDEX ix_scan_runs_term ON scan_runs(source, search_term, started_at);

-- Raw payloads, stored only when their hash changes (dedup keeps size sane).
CREATE TABLE raw_payloads (
    source TEXT NOT NULL, external_id TEXT NOT NULL, fetched_at TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_json   TEXT NOT NULL,            -- or BLOB with zlib if size matters
    PRIMARY KEY (source, external_id, payload_sha256)
);

-- Human decisions. These are also your gold-standard ML labels (see note below).
CREATE TABLE user_labels (
    source TEXT NOT NULL, external_id TEXT NOT NULL,
    label  TEXT NOT NULL CHECK (label IN ('excluded','excluded_from_calc','approved','discarded')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (source, external_id, label)
);

CREATE TABLE learned_rules (
    id INTEGER PRIMARY KEY, search_term TEXT NOT NULL, words_json TEXT NOT NULL,
    origin_title TEXT, origin_source TEXT, origin_external_id TEXT,
    created_at TEXT NOT NULL, UNIQUE (search_term, words_json)
);

-- Telegram outbox: replaces the in-memory queue. At-least-once delivery, survives restarts.
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'new_listing', body TEXT NOT NULL,
    queued_at TEXT NOT NULL, sent_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
    UNIQUE (source, external_id, kind)
);
```

**Design choices worth understanding:**

- **Snapshot plus change-logs, not a row per sighting.** `last_seen_at` is a single `UPDATE` per item per scan. That's cheap, and it avoids the 640 MB problem while keeping the information. `price_history` and `text_history` stay append-on-change, which is your current behavior for price.
- **`seen.json` disappears.** "Seen" is simply "a row exists in `listings`". Making `INSERT` + `INSERT INTO notifications` one transaction removes the at-most-once bug.
- **`scan_runs.complete`** is what makes disappearance detection honest. A listing becomes `gone` only after `missed_scans ≥ N` across complete runs of all its `listing_search_hits` terms.
- **No stored `is_noise`.** Compute it in the backend at read time; it's cheap for about 25k titles. If you later need it persisted (for example, as an ML feature snapshot), add `classifications(source, external_id, rules_version, is_noise, reason)`.
- **`user_labels` is your hidden asset.** You already have 741 manual exclusions, 15,333 reviewed IDs and 368 rules. That's labeled data for training a *learned* noise classifier (TF-IDF plus logistic regression on titles is a good first ML milestone), which could eventually replace the hand-written regexes.
- **Backfill** from `data/wallapop_data.jsonl`, the compacted backups, the 640 MB per-scan `.bak`, and `../wallabotdata/wallapop_data.jsonl`. The per-scan files are the **only** place real `last_seen` and disappearances exist for June 21–27. **Don't delete them.**

---

## 4. Duplicated logic: noise detection in Python and JS

### Where it lives

| Copy | File | Consumers |
|---|---|---|
| Python #1 | `wallapop_watcher.py:132-267` (hard-coded lists) | Telegram decisions, stored `is_noise` |
| Python #2 | `marketwatch/filters/noise.py` + `filter_rules.json` (untracked) | Nothing yet |
| JS | `market_dashboard/src/lib/noiseDetection.js` (hard-coded lists) | Main table (`marketData.js:313`), review queue (`App.jsx:303`) |

Learned-filter matching is also triplicated: `wallapop_watcher.py:291-340`, `market_server.py:82-124` (plus `marketwatch/filters/learned.py`), and `marketData.js:213-244`.

Note: `noise.py` and `filter_rules.json` state that the JS "consumes the same file". **It doesn't.** `noiseDetection.js` still has its own hard-coded arrays.

### Differences, measured

I ran all three implementations on the 25,227 unique titles from both datasets.

- **`is_noise` (Python watcher vs `marketwatch` vs JS): 0 differences on real titles.** The lists are currently in sync, and the earlier parity effort worked.
- **But they aren't the same function.** Python `re` on `str` is Unicode-aware (`\b`, `\w` and `\d` treat `ñ`, `é`, `３` as word characters or digits). JS `RegExp` without the `u` flag uses ASCII `\w`, `\b` and `\d`. Targeted inputs that diverge today:

  | Title | Python | JS | Why |
  |---|---|---|---|
  | `Switch DSñ` | noise | not noise | Python: no `\b` between `S` and `ñ`, so the DS safeguard misses and "switch" fires. JS: `ñ` is a non-word char, so `\bds\b` matches and the safeguard protects it. |
  | `Juego Switch versión DSé` | noise | not noise | Same mechanism. |
  | `Wii ÜDS` | noise | not noise | Same mechanism, prefix side. |
  | `Tomo ３ Dragon Quest` | noise | not noise | Python `\d` matches fullwidth `３`; JS `\d` doesn't. |

  These are rare in Spanish/French titles. Vinted is international, though, and Japanese imports use fullwidth digits.
- **Learned-filter word extraction: 9 real titles differ.** Python strips every Unicode `Mn` combining mark (`unicodedata.category == "Mn"`); JS strips only `U+0300–U+036F`. `\b` differs as above. So `"Phœnix Wright Ace Attorney"` gives Python `['wright','ace','attorney']` and JS `['nix','wright','ace','attorney']`, and `"Blue dragon RalΩgrad"` gives Python `['blue','dragon']` and JS `['blue','dragon','ral','grad']`. Rules are *created* in Python and *matched* in both, so the dashboard table (JS matching) and the Telegram/pending decisions (Python matching) can disagree about the same item.
- **When classification runs differs:** Python freezes `is_noise` into the row at scrape time; JS recomputes it with today's rules. That's why 18% of stored flags are stale (§3.5).
- **Where the review queue is filtered differs:** `/api/pending` applies exclusions and learned rules in Python but **not** noise. The React app then drops noise client-side (`App.jsx:303`). So the endpoint's "pending" count is wrong for any other client, and Angular would have to know to re-filter.

### Proposal: the backend owns all classification

1. Keep `filter_rules.json` as data, owned by the Python package only. Add a `rules_version` (a hash of the file).
2. A single `classify(listing, rules, learned_rules, user_labels) -> Classification` returns `is_noise`, `noise_reason` (which pattern fired, useful in the UI and for debugging), `is_learned_excluded` (+ `rule_id`), `is_price_outlier`, `excluded`, `excluded_from_calc`.
3. The watcher calls it before notifying. The API calls it when serving. The frontend gets booleans and reasons and runs **zero** regexes.
4. Before deleting the JS copy, freeze its behavior: export `{title: isNoise(title)}` for all 25k titles as a **golden file** and add a pytest that asserts Python matches it, with the Unicode cases above as documented, intentional exceptions. That turns "we checked parity once with a script" into a permanent regression test.

**Why the backend and not a shared JSON consumed by both?** Shared *data* still leaves two *engines* with different regex semantics, as shown above. You would also need to rebuild the frontend whenever rules change, and a third engine appears when you add Angular. One engine removes the class of bug entirely. The cost is a server round-trip for classification, which you already pay because the data comes from the server anyway.

---

## 5. API contract for the Angular migration

### 5.1 Endpoints the React app calls today (`src/lib/api.js`)

| Call site | Method + path | Request | Response | Notes |
|---|---|---|---|---|
| `fetchMarketData` (on load + every 60 s) | `GET /api/data` | — | `{ rows: Row[], error: string\|null }` | Returns **every row of the JSONL**. Missing file → HTTP 200 with `{rows: [], error}`. |
| `fetchExclusions` (on load only) | `GET /api/exclusions` | — | `{ excluded: string[], excludedFromCalc: string[] }` | camelCase, while everything else is snake_case. |
| `updateExclusion` | `POST /api/exclusions` | `{ item_id, action: "exclude"\|"unexclude"\|"excludeFromCalc"\|"unexcludeFromCalc", title?, search_term? }` | `{ excluded, excludedFromCalc }` | Side effect: `exclude` with title + search_term **also creates a learned rule**. |
| `fetchPending` (on load only) | `GET /api/pending` | — | `{ pending: Row[] }` (deduped, newest `created_at` first) | The first call ever writes `reviewed.json` with all IDs and returns `[]`. Doesn't filter noise. |
| `submitReview` | `POST /api/review` | `{ item_id, action: "approve"\|"discard", title?, search_term? }` | `{ ok: true }` | `discard` = mark reviewed + `exclude` + learned rule. |
| `fetchLearnedFilters` (load + after exclude/discard) | `GET /api/learned_filters` | — | `{ rules: Rule[] }` | |
| `deleteLearnedFilter` | `POST /api/learned_filters` | `{ action: "delete", rule_id: number }` | `{ rules: Rule[] }` | RPC-style POST for a delete. |

```ts
// Shapes as they actually appear on the wire today
interface Row {
  scanned_at: string;          // naive local ISO, "2026-07-09T14:37:55"
  search_term: string;         // may have a trailing space ("pokemon negro ")
  source?: 'wallapop' | 'vinted'; // missing on 13,589 older rows → treat as 'wallapop'
  item_id: string;             // Wallapop raw id | "v:<vinted id>"
  title: string;
  price: number;               // code allows the string "?"; none in current data
  currency: string;
  created_at: string | null;   // naive local ISO; Vinted = photo timestamp proxy
  url: string;
  is_noise?: boolean;          // stale; the frontend ignores it
}
interface Rule {
  id: number; search_term: string; title: string; words: string[];
  excluded_item_id: string; created_at: string;
}
```

### 5.2 Frontend features to preserve (parity checklist)

**Layout** (from `App.jsx`, and CLAUDE.md §11–12 for CSS details): centered `.wrap` with `max-width: 1600px`; sticky glass header showing the source label, title, and an "Actualizado HH:MM:SS" status that turns into the error message when stale; a two-column `.layout` with the main table and a right-hand ranking sidebar, both with height `calc(100vh - 300px)`; breakpoints at 1100px and 720px; `prefers-reduced-motion`; CSS tokens on `:root`.

**Review queue** (`ReviewQueue.jsx`): collapsible panel with a count badge; per item: title link (new tab), category, price, date, "✓ Me interesa" / "✗ Descartar"; "✕" dismisses the queue for this session only; renders 50 at a time with "Mostrar N más".

**Stat cards** (6): unique listings, categories, total sightings (really the row count), median, min and max price. These respect `excludeZero` and skip noise, outliers and calc-excluded items.

**Controls**: free-text search (title or category, case-insensitive substring); category `<select>`; source `<select>` (all / wallapop / vinted); "published on day" filter with a "Hoy" toggle, a date input capped at today, and "Todos" to clear; checkbox "Excluir precio 0€" (**default on**); checkbox "Ocultar ruido" (**default on**; hides noise **and** price outliers).

**Info banners**: noise/outlier count, with different wording depending on whether they're hidden or shown. There's also a collapsible "learned filters" panel listing `[search_term] title ✕`, where ✕ deletes the rule.

**Table**:
- Columns: Anuncio (source badge, status badges, title link), Categoría, Precio, Posición en mercado, Publicado, Avistado, Acciones.
- Sortable columns: Categoría, Precio, Posición en mercado (`price / category median`), Publicado, Avistado. The first click sorts ascending, the next click on the same column flips it, and clicking another column resets to ascending. Default: price ascending.
- Outlier/noise highlighting: badges "ruido auto" (red), "precio atípico" (amber), "excluido del cálculo" (grey); a row is **dimmed** if any of them applies.
- Position bar: a marker placed between the category min and max. It's green "Buena oferta" when the ratio is ≤ 0.85, red "Por encima" when ≥ 1.25, grey "En línea" otherwise.
- Actions: "Excluir" (permanent; also creates a learned rule) and "Excluir del cálculo" ⇄ "Incluir en cálculo".
- Renders 500 rows with "Mostrar N más (M restantes)". The limit resets on filter or sort change but **not** on the 60-second refresh.

**Ranking sidebar**: categories sorted by median ascending; clicking one sets the category filter; the active one is highlighted.

**Behaviors**: data polling every 60 s; optimistic updates for exclude, exclude-from-calc and review, with rollback and an `alert` on failure.

### 5.3 Logic that lives in the frontend but belongs in the backend

| Logic | Where now | Why it belongs in the backend |
|---|---|---|
| Rows → items dedupe (`deduplicateByItem`) | `marketData.js:252` | It's a data-model concern; SQLite `listings` already *is* the deduped view. Shipping all rows to dedupe them in the browser is the main scalability problem. |
| Noise classification | `noiseDetection.js`, `App.jsx:303` | §4. |
| Learned-rule matching | `marketData.js:218-244` | Third copy; already diverges (§4). |
| MAD outliers + ≤€2 rule | `priceOutliers.js` | Statistics that Telegram ("good deal" alerts) and ML need too. CLAUDE.md §6 says it's "analysis only"; that stops being true the moment you want deal alerts. |
| Per-category median/min/max | `marketData.js:333-365` | Same reason. It's also recomputed from scratch on every render input change. |
| Global stats | `App.jsx:233-256` | Also questionable as a metric: a median across consoles *and* €20 games mixes different products. Consider dropping it or making it per category. |
| Deal ratio + labels (0.85/1.25) | `App.jsx:220-228`, `MarketRow.jsx:3-28` | Return `price_ratio` (and ideally `deal_band`) from the API so Telegram and UI use the same thresholds. |
| Filtering by category, source, day, zero price, text | `App.jsx:180-231` | Needed as server query params once you paginate. Sorting can stay client-side within a page, but server-side sort is simpler once paginated. |
| "Exclude also creates a rule" coupling | `api.js:28-33` + server `:407-410` | Make it explicit: separate endpoints and a UI checkbox ("also hide similar"). The current implicit behavior created one-word rules that hide whole categories (§6). |

### 5.4 Proposed v2 API (for Angular)

Use **FastAPI + Pydantic**. It provides request validation, an OpenAPI schema, and from that **generated TypeScript types or services for Angular** (`openapi-typescript` or `ng-openapi-gen`). The contract is then enforced by the compiler instead of by reading `api.js`. The trade-off is one more dependency than the stdlib server. Given that you already need `playwright` and `httpx`, and the value of a typed contract in an Angular portfolio piece, that trade-off is clearly worth it.

```
GET    /api/v2/listings?search_term=&source=&published_on=&min_price=&include_noise=false
                       &q=&sort=price|-price|published_at|price_ratio|...&page=1&page_size=100
       → { total, page, page_size, items: ListingView[] }
GET    /api/v2/categories               → CategoryStats[]   (median/min/max/count/count_for_calc)
GET    /api/v2/summary                  → { listings, categories, sightings, ... }
GET    /api/v2/review-queue?page=       → { total, items: ListingView[] }   (already noise-filtered)
POST   /api/v2/listings/{source}/{id}/labels        { label: 'excluded'|'excluded_from_calc'|'approved'|'discarded' }
DELETE /api/v2/listings/{source}/{id}/labels/{label}
POST   /api/v2/learned-rules            { search_term, from_listing: {source,id} } → preview-able
GET    /api/v2/learned-rules            → Rule[] (with match_count, so you can see what a rule hides)
DELETE /api/v2/learned-rules/{id}
GET    /api/v2/listings/{source}/{id}/history → { prices: [...], titles: [...] }   (new: price chart)
GET    /api/v2/health                   → last complete scan per (source, term), outbox backlog
```

`ListingView` carries server-computed fields: `is_noise`, `noise_reason`, `is_price_outlier`, `excluded_from_calc`, `price_ratio`, `deal_band`, `search_terms[]`, `first_seen_at`, `last_seen_at`, `status`.

**Keep the v1 endpoints running until the React app is retired** (strangler pattern), so you're never without a working dashboard.

### 5.5 React bugs not to port

- `handleDiscard` rollback does `setPendingItems(prev => [...prev])` (`App.jsx:133`). That copies the already-filtered list and **doesn't restore the item**.
- `handleApprove` has no rollback at all (`:116-123`).
- Exclusions, learned rules and the review queue load **once**; only `/api/data` is polled (`:107-114`). Changes made by another tab or device never show up.
- An empty but valid data file gives `rows: []` and `error: null`, which leaves the loading spinner up **forever** (`:272`).
- The "Avistado" column shows `sightingCount`, which is really the number of price changes plus 1 (§3.2).
- Price sort with a non-number (`"?"`) produces `NaN` comparisons and an unstable order (`:209`).
- `alert()` for errors. Use an Angular snackbar/toast.
- The 500-row render cap is a workaround for rendering everything client-side. In Angular, use server pagination plus the CDK virtual scroll instead.

---

## 6. Other issues

### Security

- **Path traversal in static serving (confirmed).** `file_path = DIST_DIR / clean_path.lstrip("/")` (`market_server.py:489`) never normalizes `..`. Against the real `Handler`, `GET /../../pyproject.toml` returned **200** with the file contents, and so did `/../../market_server.py`. Any file readable by your user (for example `~/.ssh/*`) is reachable by anything that can open a TCP connection to 127.0.0.1:8765. Browsers normalize `..` so a web page can't exploit it, but local processes and `curl --path-as-is` can. Fix: `resolved = (DIST_DIR / p).resolve(); if not resolved.is_relative_to(DIST_DIR.resolve()): 404`. Or let FastAPI's `StaticFiles` handle it.
- **`Access-Control-Allow-Origin: *` on state-changing endpoints** (`:287`, `:313`). The frontend is same-origin, so CORS is unnecessary. As written, any website you visit can read your entire dataset via `fetch('http://localhost:8765/api/data')` and send POSTs that pass preflight. Remove CORS, or restrict it to the Angular dev-server origin in development.
- **Session cookies at rest:** `../wallabotdata/state.json` is a Playwright storage state containing `AUTH_SESSION_ID` and `KC_RESTART` for `accounts.wallapop.com`. No current code references it. Treat it as a credential: delete it (or move it outside any project folder), and log that session out on Wallapop. **Never** let it reach git or a portfolio upload. Add `state.json`/`*storage_state*` to `.gitignore` defensively.
- **Telegram token:** handled correctly via environment variables (`:346-347`); nothing is hard-coded. Two improvements: support a `.env` file (with `.env` gitignored and `.env.example` committed) so the README doesn't tell people to `export` secrets in shell history; and validate at startup (`getMe`) instead of warning on every message (`:550-552`). The token is embedded in the request URL (`:518`); be careful never to log `r.request.url` or full httpx exceptions at debug level.
- `.claude/settings.local.json` grants `Read(//home/ivan/.ssh/**)`. It's gitignored, but it's a broad permission to leave lying around.

### Correctness bugs (beyond the data model)

- **Dead learned rules (search-term whitespace).** `SEARCHES` contains `"pokemon negro "` and `"pokemon blanco "` with trailing spaces (`wallapop_watcher.py:32-33`), and rows store them verbatim. Rules are created with `search_term.strip()` (`market_server.py:408`, `:460`), and all three matchers compare with exact `==`/`!==`. Result: **95 of 368 rules (76 + 19) can never match anything.** Fix: normalize search terms once at the source (and in the migration), not at every comparison.
- **Over-broad learned rules.** Extraction can leave a single generic word. Examples in `data/learned_filters.json`: `nintendo dsi → ['lote']` (hides *every* DSi lot), `nintendo dsi → ['nuevos']`, `ace attorney DS → ['3ds']` (hides "compatible con 3DS" listings), `last window DS → ['partir']`. Six rules also contain duplicate words (e.g. `['pokemon','tcg','caja','pokemon',...]`). Add a minimum of 2 distinct significant words, a preview ("this rule would hide N listings"), and dedupe the words.
- **The cwd-relative paths broke with "Paso 1".** Both root scripts use bare filenames (`wallapop_watcher.py:60-61,281`, `market_server.py:41-44`), but the files now live in `data/`. Running from the repo root silently starts a fresh `seen.json` (full warm-up), a new JSONL (history split in two), and an empty dashboard. `marketwatch/config.py` has the correct absolute paths, but nothing uses it yet.
- **Latent 500 in `/api/pending`.** `pending.sort(key=lambda x: x.get("created_at", ""))` (`:371`): when a row has `"created_at": null`, `.get` returns `None`, and sorting `None` against `str` raises `TypeError`. It can't happen with today's data (no nulls), but `normalize_vinted_item` produces `None` whenever the photo timestamp is missing.
- **A dead `Page` is never recreated.** `watch_search` creates its page once (`:1071`). If Chromium kills the tab, every later cycle throws, gets caught, gets printed, and sleeps, forever.
- **Silent total failure.** If Wallapop starts returning 403 to all 31 searches, you get console lines and no Telegram alerts, which looks exactly like "nothing new on the market". A health endpoint (§5.4) plus a Telegram alert for "no complete scan in 30 min" fixes this.
- `/api/pending` first-run auto-init: if `reviewed.json` is missing it snapshots all current IDs. If it exists but is empty, **everything** becomes pending (see the side-effect note below).

### Error handling and robustness

- Broad `except Exception` with `print(f"...{e}")` (`:1083-1084`, `:865`, `:911`) loses tracebacks. Use `log.exception(...)`.
- Server state reads swallow corruption and return an empty state (`market_server.py:137-138`, `:214-218`, `:234-235`); the next write then persists that empty state. `marketwatch/storage.py` already has the right answer (fail closed with `CorruptStateError`); wire it in.
- Non-atomic writes of every JSON state file (`wallapop_watcher.py:455-457`, `market_server.py:141-143,221-223,238-240`). `storage.write_json_atomic` fixes this; SQLite makes it moot.
- `int(self.headers.get("Content-Length", 0))` crashes on a malformed header; there's no body size limit.
- Blocking file I/O (`open` per appended row, `seen.json` rewrite) inside the `asyncio` lock, on the event loop. Fine at 31 searches, but it's the kind of thing a reviewer notices. With SQLite, batch each scan into one transaction.
- Hard-coded `Chrome/124` user agent (`:1127`) no longer matches the bundled Chromium version. A UA/engine mismatch is itself a bot signal. Derive it from `browser.version` or drop the override.

### Logging

- Everything is `print()` with emojis. Replace it with `logging`: `log = logging.getLogger(__name__)`, a single `basicConfig` with timestamps and levels, and a structured `extra` for `source`/`search_term`. The untracked `marketwatch` already started this.
- The server discards **all** request and error logs (`market_server.py:277-278`: overriding `log_message` also silences `log_error`).

### Tests

- **There are none.** `pyproject.toml` sets `testpaths = ["tests"]`, and `tests/` doesn't exist. For a portfolio, this is the single most visible gap. It's also cheap to start, because the most valuable tests are pure functions:
  - `is_noise`: golden file from the 25k real titles, plus the documented edge cases (`PlatiNO 30`, `358/2 Days`, `cartouche`, DS safeguard).
  - `extract_filter_words` / rule matching (including the whitespace bug as a regression test).
  - `detect_price_outliers` once it's ported (MAD = 0, fewer than 5 samples, ≤€2 rule).
  - Normalizers, using a **recorded real API response** as a fixture (this also documents the payload).
  - Repository layer against a temporary SQLite DB: upsert, `last_seen` update, price-change row, disappearance after N complete scans, but *not* after an incomplete one.
  - API: FastAPI `TestClient`, including a path-traversal regression test.
  - Frontend: Playwright e2e for the parity checklist (§5.2). Write them against React first, then run the same suite against Angular.
- Module-level side effects (loading `seen.json`, reading the whole JSONL and printing at import, `wallapop_watcher.py:363-494`) make the watcher untestable as it stands. Move them into `main()`.

### Things that would embarrass you in a portfolio

1. Path traversal (above).
2. Credentials file (`state.json`) in a data folder.
3. Documentation that describes code that doesn't exist (`marketwatch/__init__.py`, `noise.py`, `filter_rules.json` comments), and comments that contradict the code. The "NOTAS" block at the bottom of `wallapop_watcher.py` (`:1209-1216`) still says a line is written per sighting per scan; `:119` still refers to `market.html`. Reviewers read comments; a stale one reads as "doesn't know their own code".
4. No tests, despite a configured test runner.
5. `pip install ... --break-system-packages` in the README. Use a venv or `uv` with the existing `pyproject.toml`.
6. A duplicate `import re` (`wallapop_watcher.py:5` and `:130`), and a 1,250-line single-file scraper with module-level global state.
7. `CLAUDE.md` reads as a chat transcript. Turn the valuable parts (anti-detection rationale, MAD vs std-dev, warm-up design) into `docs/architecture.md` plus ADRs. Those decisions are good and deserve to be presented well.
8. The in-progress refactor is uncommitted. Commit early and often; the diffable history of a refactor is itself portfolio material.
9. Scraping and anti-bot measures (`navigator.webdriver` override, UA spoofing). In a public repo, add a short "responsible use" note (personal use, low request rate, respects robots/ToS as you understand them), and **don't publish the raw dataset**: it contains other people's listings and URLs. Publish aggregate or anonymized features instead.
10. Mixed Spanish/English. The identifiers are already English; making comments and docs English too broadens your audience. This is lower priority, but cheap to do during the rewrite.

### ⚠️ Side effect from this review (please act)

While verifying the path traversal, I started the real `Handler` on an ephemeral port and also called `/api/pending`. Because the server resolves `reviewed.json` relative to the cwd (the cwd-path bug above), it **created a new file `wallapop-bot/reviewed.json` containing `{"reviewed": []}`** (timestamp 2026-09-27 21:00:10). My attempt to delete it was blocked by the session's permission policy. Please delete it yourself (`rm wallapop-bot/reviewed.json`). It's gitignored and harmless *unless* you start `market_server.py` from the repo root with the data files there: an empty-but-present `reviewed.json` makes **every** item pending. Your real `data/reviewed.json` was not touched.

---

## 7. Plan: prioritized milestones

The principle behind the order: **fix what loses data first, then what's hard to change later, then what's visible.** Every day the current scraper runs, it produces data without `last_seen`, disappearances or raw payloads, and that loss is permanent. A React-to-Angular port can happen any week with no loss. That asymmetry sets the order.

### M0: Safety net (½–1 day)

1. Delete the probe-created `reviewed.json`. Move or delete `../wallabotdata/state.json` and log out that session.
2. **Back up** `data/` and `../wallabotdata/` somewhere outside the repo. The per-scan backups are irreplaceable (§3.6).
3. Commit `marketwatch/` as-is on a branch (`refactor/marketwatch`), with its docstrings corrected to describe what exists.
4. Fix the path-traversal bug and remove the wildcard CORS in `market_server.py`. These are two small patches, and they come first because the server is running *now*.
5. Point both root scripts at `marketwatch.config` paths, so the next run uses `data/`.
6. Create `tests/` with the `is_noise` golden test (generated from the current JS and Python outputs) and the learned-rule whitespace regression test.

*Why first:* everything after this is a refactor, and refactoring without a test net or a backup is how you silently lose the thing you're refactoring. None of it changes behavior, so the risk is close to zero.

*Trade-off:* you delay "real" work by a day. You gain the ability to change code without fear.

### M1: Data layer (2–4 days)

1. `marketwatch/db.py`: the schema from §3.6, created with plain `sqlite3` and a tiny migrations table (`schema_version`). Skip Alembic or an ORM for now; you'll learn more writing the SQL, and the schema is small.
2. `marketwatch/repository.py`: `upsert_listing(scan_run, normalized, raw)`, `start_scan`/`finish_scan(complete=…)`, `mark_missing(scan_run)`, `enqueue_notification`, `pending_notifications()`. Pure functions over a connection, fully unit-tested against `:memory:`.
3. `scripts/import_jsonl.py`: an idempotent backfill from all JSONL sources (live, compacted backups, the 640 MB per-scan `.bak`, the wallabotdata snapshot) and the four JSON state files. Normalize search terms (strip) and convert to UTC with an explicit Europe/Madrid assumption for old naive timestamps. Price becomes cents.
4. Validate it: row counts, item counts, and spot-check a few items' price histories against the JSONL.

*Why before touching the scraper:* the scraper's new behavior (last_seen, scan completeness, raw payloads) needs somewhere to go. Building the store first lets you test it in isolation with fixtures, without Wallapop in the loop.

*Trade-offs:*
- *Dual-write vs cut-over:* for one week, write to both JSONL and SQLite and compare daily; then drop JSONL. It costs a little code and buys confidence. Recommended.
- *Raw payload size:* storing each payload only when its hash changes keeps growth close to linear in *changes*, not scans. If it still grows too fast, zlib-compress the JSON (typically 5–10× on this kind of data).

### M2: Scraper on the new store (2–3 days)

1. Split `wallapop_watcher.py` into `marketwatch/sources/wallapop.py` and `vinted.py` (fetch returns raw items plus a `ScanResult(pages, complete, error)`), `marketwatch/watcher/loop.py`, and `marketwatch/notify/telegram.py` (outbox worker).
2. Each scan: `start_scan`, then upsert every item (updating `last_seen_at`, appending price/text history on change, storing the raw payload on hash change, recording the search hit), then `finish_scan(complete)`, then `mark_missing` **only if complete**. Wrap all of it in one transaction per scan.
3. Telegram reads from the `notifications` outbox. This gives at-least-once delivery that survives restarts. The warm-up logic becomes "don't enqueue on a (source, term)'s first complete scan".
4. Robustness: recreate a crashed `Page`; exponential backoff on 403/429; one cookie-seeding task for Vinted; UA derived from the browser; `logging` everywhere; nothing runs at import time.
5. Health: expose the last complete scan per (source, term), and send a Telegram alert if nothing completes for 30 minutes.

*Why here:* this is the milestone that makes the **collected data ML-grade** (§3). It comes after M1 because it depends on the repository API, and before any API or UI work because every day of delay is data you can't get back.

*Trade-off:* the split into modules is where the most regressions can sneak in. Mitigate this with recorded API fixtures, so the normalizers and pagination are tested offline, and by running old and new watchers side by side for a day (with `ENABLE_*` flags, and Telegram enabled on only one of them).

### M3: One classification engine in the backend (1–2 days)

1. `marketwatch/analysis/`: `classify()` (noise + reason, learned rules, user labels), `price_outliers()` (a port of `priceOutliers.js`: MAD, modified Z > 3.5, n ≥ 5, ≤ €2 rule), and `category_stats()`.
2. Port the JS outlier tests as Python tests *before* porting the code: write the expected outputs from the JS implementation on real categories, then make Python match.
3. Learned rules: require at least 2 distinct words, dedupe words, add `match_count`, and support a preview.

*Why before the API:* the API is a thin shell over these functions. Designing the endpoints first would bake today's split into the contract. It also makes the watcher and the dashboard agree by construction (§4).

*Trade-off:* the frontend loses the ability to reclassify instantly when you edit rules, and now needs a round-trip. At about 25k listings, classification takes milliseconds server-side, so it's not a real cost.

### M4: API v2 with FastAPI (2–3 days)

1. FastAPI app in `marketwatch/server/`, with Pydantic response models (`ListingView`, `CategoryStats`, …) and the endpoints from §5.4. Serve the Vite/Angular build with `StaticFiles` (which is safe against path traversal).
2. Keep v1 endpoints as thin adapters over the same repository until React is retired, so nothing breaks mid-migration.
3. Pagination and filtering in SQL. `/api/v2/listings` returns about 100 rows, not the entire dataset.
4. `TestClient` tests for every endpoint, including the traversal regression test.
5. Export `openapi.json` as a build artifact.

*Why before Angular:* Angular's services and types should be **generated** from this contract. Starting Angular against the v1 shapes means writing the port twice.

*Trade-off: stdlib vs FastAPI.* The stdlib server avoided a dependency, and that was a fair call when the only client was a hand-written fetch wrapper. With a typed frontend, validation, OpenAPI and safe static serving, FastAPI replaces hand-written code you'd otherwise have to test yourself. It's also more recognizable in a portfolio.

### M5 (optional but recommended): point React at v2 (½–1 day)

Swap `api.js` to v2 and delete `noiseDetection.js`, `priceOutliers.js` and most of `marketData.js`.

*Why:* it proves the v2 API covers every feature of a UI you know works, *before* you write the Angular app. If a feature is missing from the API, you find out in half a day, not halfway through Angular. It also gives you a baseline for e2e tests.

*Trade-off:* this is throwaway work on React. If you're time-constrained, skip it and let the Playwright parity suite (M6) do the checking.

### M6: Angular (4–7 days)

1. `ng new` with standalone components, signals for state, `HttpClient` services **generated from `openapi.json`**, and a dev proxy to FastAPI (so there's no CORS in development either).
2. Routes: `/` market (table + ranking), `/review` (queue), `/rules` (learned rules with match counts). React crammed everything onto one page; routing is an easy UX win and shows off Angular's router.
3. Table: Angular CDK table (or Material table) with server-side sort and pagination, and CDK virtual scroll. This replaces the 500-row hack.
4. State: a store service per feature using signals, `computed` for derived view state, optimistic updates with a *correct* rollback (§5.5), and polling via `interval` + `switchMap` (or refetch on focus).
5. Port the CSS tokens from `index.css` into global styles; components use them.
6. Run the Playwright parity checklist (§5.2) against Angular until it's green. Then delete `market_dashboard/`.
7. New features that are now cheap: a price-history chart per listing (`/history`), and filters by status (active/gone) and time-to-disappear.

*Why last:* it's the most visible piece but the least urgent. It depends on a stable contract (M4). Doing it earlier would mean porting logic that you'd then have to delete from Angular as well.

### M7: ML groundwork (ongoing, starts in parallel after M2)

1. `scripts/export_parquet.py`: listings + price history + search hits + labels → Parquet snapshots with a documented schema (a "dataset card": what each column means, known biases such as asking price ≠ sale price, Vinted date proxies, and search-term labeling).
2. First model: a **noise classifier** trained on `user_labels` plus rule outputs (TF-IDF + logistic regression). It's small and measurable, and it directly improves the product.
3. Then price prediction: the target is the last asking price before `gone`, or the time to `gone`. Features: title tokens, product (normalized from search hits), condition/box/region keywords, source, and the payload fields you're now keeping. Split train/test by **time**, not randomly, or you'll leak future prices.

*Why this sits in parallel and not first:* the model is only as good as the data M1–M2 start collecting. Starting the notebook work early helps you discover which raw fields matter, so check the payload early in M2 and add whatever else you need.

---

### Effort summary

| Milestone | Effort | Unblocks |
|---|---|---|
| M0 Safety net | ½–1 d | Everything (safe to change code) |
| M1 Data layer | 2–4 d | M2, backfill |
| M2 Scraper on SQLite | 2–3 d | **ML-grade data collection starts** |
| M3 Backend classification | 1–2 d | M4, consistent Telegram and UI |
| M4 API v2 | 2–3 d | Angular with generated types |
| M5 React on v2 (optional) | ½–1 d | API validated before Angular |
| M6 Angular | 4–7 d | Portfolio frontend |
| M7 ML | ongoing | The actual project goal |
