# AGENTS.md — wallapop-bot

Instructions for coding agents working in this repository. Read this whole file before doing anything.

## What this project is

A market-intelligence system for retro Nintendo DS games and consoles on second-hand marketplaces (Wallapop and Vinted). It:
- scrapes listings and sends Telegram alerts for new relevant ones,
- stores their history in PostgreSQL,
- serves it through a FastAPI backend to an Angular dashboard,
- turns it into data science and ML outputs: price analysis and a listing-relevance classifier.

The current code is a working prototype: a Python scraper writing JSONL, a stdlib HTTP server and a React dashboard. We are rebuilding it into a portfolio-grade project, step by step.

- **Owner:** Ivan. He reviews every phase and must be able to explain every decision in an interview.
- **Audience:** hiring managers for junior data, backend and full-stack roles in Spain.

**The phase plan lives in `docs/PLAN.md`.** At the start of every session, read it, find the first unchecked phase, and continue from there.

**The prototype's design history** lives in `docs/legacy/prototype-decisions-es.md` (the old CLAUDE.md, in Spanish). Read it before touching scraper code. It documents hard-won fixes: anti-bot settings, Vinted cookie seeding, per-source warm-up, noise-filter edge cases.

## Ground rules (non-negotiable)

1. **Keep it working.** Every commit leaves the system runnable with tests green. The scraper is in daily use: never break data collection.
2. **Never lose data.** The legacy JSONL and JSON state files are a read-only archive. Migrate by idempotent import, never by editing them.
3. **Never invent numbers.** Every number in `README.md`, `DECISIONS.md`, `INTERVIEW.md` or any report is produced by code in this repo and is reproducible.
4. **Characterise before refactoring.** Before restructuring a piece of logic, add tests that pin down its current behaviour (noise rules, normalisers, learned filters, price outliers).
5. **One source of truth for business rules.** Noise rules, learned filters, outlier detection and market stats live in Python only. The frontend displays what the API returns and never reimplements rules. This removes the prototype's duplicated Python/JS noise filter.
6. **Stop at checkpoints** (🛑 in `docs/PLAN.md`). Summarise what you found, what you decided and what is uncertain, then wait for Ivan.
7. **Privacy.** Never store or expose seller identifiers. Never commit data, database dumps, `.env` or trained model artifacts. Test fixtures are synthetic or hand-written.
8. **Secrets only via environment variables.** Commit `.env.example`; keep `.env` ignored.
9. **No new dependencies** outside the stack below without an entry in `DECISIONS.md`.
10. **English for everything written to disk**: code, comments, docs, commits, PRs. Chat with Ivan may be in Spanish.
11. **Analysis integrity.** Pre-register analysis definitions before seeing results. Never read held-out labels while developing a model or matcher (details in `docs/PLAN.md`).

## Architecture

```
Wallapop / Vinted ──► scraper (Playwright) ──► PostgreSQL ◄── api (FastAPI) ◄── web (Angular)
                           │                       ▲               │
                           └──► Telegram           │               └── relevance model (scikit-learn, in-process)
                                       analytics/ (SQL marts, notebooks, training)
```

Decisions already made. Record each in `DECISIONS.md` during Phase 0 with these reasons:

- **PostgreSQL over MySQL.** Medians are central to this project, and Postgres has `percentile_cont` as an aggregate; MySQL has no built-in median or percentile aggregate. Postgres also has JSONB, partial indexes and `INSERT … ON CONFLICT` upserts, and Ivan already uses it in his Spring Boot projects.
- **FastAPI over Spring Boot.** Scraper, rules, analytics and ML are all Python. A Python backend means one copy of the noise rules and the ML model served in-process. Ivan's other portfolio projects already cover Spring Boot. Accepted tradeoff: Spring Boot appears in more Spanish junior backend offers overall.
- **Angular over React.** It is Ivan's preferred frontend for his target offers.
- **pandas over polars for analysis.** pandas is what Spanish job offers name.
- **No Power BI.** Its desktop authoring tool is Windows-only and Ivan works on Linux. The SQL marts make a BI report trivial to add later.
- **Track disappearance in the database.** The prototype writes a JSONL line only when an item is new or its price changes, so "last seen" cannot be reconstructed from the legacy data. The database records `last_seen_at` on every scan, plus a `scan_runs` table. This is what makes time-on-market analysis possible, from the migration date onward.

**Scraper in Docker.** Headless Chromium inside a container can change the fingerprint Wallapop sees. The scraper must run both in Compose and directly on the host, configured through `DATABASE_URL`. If it gets blocked in Docker, run it on the host and document that.

## Stack

- **Backend:** Python 3.12, `uv`, `playwright`, `httpx`, SQLAlchemy 2 + psycopg 3, Alembic, FastAPI, Pydantic v2, pytest, testcontainers, ruff.
- **Data/ML:** pandas, numpy, scipy, statsmodels, lifelines, scikit-learn, rapidfuzz, matplotlib, jupyter + jupytext, mlflow (local file store), joblib.
- **Frontend:**
  - Angular (latest stable: standalone components, signals, strict TypeScript), `@angular/cdk` for virtual scrolling, angular-eslint.
  - Chart library: choose in Phase 4 and log it. Prefer one with native boxplots, e.g. ECharts via ngx-echarts.
  - Tests: the CLI's default runner, plus Playwright for one end-to-end smoke test.
- **Infra:** Docker Compose (postgres, api, web; scraper optional), GitHub Actions CI.

## Target repository layout

```
wallapop-bot/
├── AGENTS.md  CLAUDE.md  README.md  DECISIONS.md  INTERVIEW.md
├── docker-compose.yml  .env.example  Makefile
├── .github/workflows/ci.yml
├── docs/                    # PLAN.md, data_audit.md, labeling_guidelines.md, legacy/
├── backend/
│   ├── pyproject.toml  uv.lock  alembic.ini  alembic/
│   ├── src/wallabot/
│   │   ├── config.py        # settings, thresholds, seeds — single source of truth
│   │   ├── db/              # models, session, repositories
│   │   ├── rules/           # noise rules, learned filters, price outliers
│   │   ├── scraper/         # watcher, wallapop.py, vinted.py, telegram.py
│   │   ├── importers/       # legacy JSONL / state-file backfill
│   │   ├── api/             # FastAPI app, routers, schemas
│   │   ├── catalog/         # canonical products: normalisation, rules, fuzzy matching
│   │   └── ml/              # relevance classifier: features, train, predict
│   └── tests/
├── analytics/
│   ├── sql/                 # analytics schema: views / materialized views
│   ├── notebooks/           # jupytext .py sources + executed .ipynb
│   └── reports/             # figures/, tables/
├── data/                    # gitignored (data/* + !data/labels/)
│   └── labels/              # committed: labelled samples + CHANGELOG.md
└── web/                     # Angular app
```

## Data model

Summary only. Alembic migrations are the authority.

- `search_terms`: the terms the scraper watches.
- `scan_runs`: one row per (source, term) scan, with timestamps, status, pages fetched, items returned and `hit_page_cap`.
- `listings`:
  - identity: `UNIQUE (source, external_id)`; Vinted ids are stored without the legacy `v:` prefix
  - current state: title, price, currency, url, `created_at_source`
  - tracking: `first_seen_at`, `last_seen_at`, `gone_at`, rule-based `is_noise`
  - `history_origin` (`legacy_jsonl` | `db`)
- `listing_search_terms`: which terms returned each listing, with first and last seen per term.
- `listing_snapshots`: price and title history, written when a listing is new or its price or title changes. Optional raw JSONB, stripped of seller fields.
- `review_decisions`: `approve` | `discard`, with `origin` (`human` | `legacy_excluded` | `legacy_unknown` | `learned_rule`) and timestamp.
- `exclusions`: `exclude` | `exclude_from_calc`.
- `learned_filter_rules`: the term, the extracted words, an example title and the source listing.
- `notifications`: replaces `seen.json`. Warm-up is derived from `scan_runs`.

**Legacy label trap.** On first use, the prototype auto-initialised `reviewed.json` with every existing id. So "reviewed and not excluded" is not a human approval. Import those rows as `legacy_unknown` and never use them as training labels.

## Commands

The `Makefile` must provide:

| Target | What it does |
|---|---|
| `setup` | Create the Python env and install web dependencies |
| `db-up` | Start Postgres |
| `migrate` | Apply Alembic migrations |
| `import-legacy` | Run the legacy JSONL / state-file import |
| `scraper` | Run the scraper |
| `api` | Run the FastAPI server |
| `web` | Run the Angular dev server |
| `test` | Run all tests |
| `lint` | Run all linters |
| `notebooks` | Convert and execute the analysis notebooks |
| `train` | Train the relevance model |
| `up` | Start the full stack with Compose |

## Engineering conventions

- **Python.**
  - Type hints on public functions; docstrings explain *why*.
  - Pure functions in `rules/`, `catalog/` and `ml/`; I/O at the edges; database access through repositories.
  - Integration tests run against real Postgres via testcontainers, never SQLite, because upserts, `percentile_cont` and JSONB behave differently.
  - `ruff` clean before every commit.
- **API.**
  - REST with plural nouns.
  - Server-side pagination, sorting and filtering.
  - Pydantic response models, OpenAPI at `/docs`, one consistent error shape, `/health`.
- **Angular.**
  - Standalone components, signals for state.
  - Services wrap `HttpClient`.
  - No business rules in components.
- **SQL.**
  - Schema changes only through Alembic.
  - Every analytics view states its grain (one row per …) in a comment.
- **Data science and ML.**
  - The unit of analysis is the listing.
  - Use medians and IQR, with bootstrap CIs that resample listings.
  - Enforce a minimum group size; report a baseline for every model; use time-based splits.
  - Full rules are in `docs/PLAN.md` (Phases 5–6).

## Git and GitHub workflow

Ivan wants the history to show the project growing in real, gradual steps.

- **One branch per phase**, named `phase-N-short-slug`, created from `main`.
- **Small Conventional Commits** (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`, `ci:`):
  - one concern each, ideally under ~300 changed lines excluding lockfiles and generated code;
  - every commit builds and passes tests;
  - when the reason isn't obvious from the diff, the commit body explains why.
- **Commit as you work, and push the branch at least at the end of every session.**
- **At the end of a phase**, open a PR with `gh pr create`. Sections: Summary, Why, How it was tested, Screenshots (UI changes), Follow-ups.
- **Ivan reviews and merges with a merge commit, not a squash**, so the granular history stays visible. Tag `v0.N.0` after each phase merge.
- **Use `git mv`** for moves, so file history follows.
- **Never** force-push `main`, rewrite pushed history, backdate commits, or commit secrets or data.
- If `gh` isn't authenticated or a push fails, stop and tell Ivan.

## DECISIONS.md format

```
### D-007: <short title> (YYYY-MM-DD)
- Context: what forced a choice
- Options: what was considered
- Decision: what we chose
- Why: 2–4 sentences, including why the alternatives lost
- Would change if: the evidence that would reverse it
```

Log every non-trivial choice: schema, libraries, thresholds, definitions, exclusions, sampling.

## Working with Ivan

- He wants mechanisms and tradeoffs, not just results. When you choose something, name the alternative you rejected and why, in 2–4 sentences.
- Prefer simple, defensible solutions over impressive ones he can't explain.
- Save questions for checkpoints, but ask rather than guess when a choice changes behaviour or results.
- Be direct about weaknesses in the data, the code or the results.
