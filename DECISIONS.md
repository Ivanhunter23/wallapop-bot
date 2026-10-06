# Decisions

Every non-trivial choice, with the alternative that lost. D-001 to D-006
were made before the rebuild started and are recorded here in Phase 0.

### D-001: PostgreSQL over MySQL (2026-10-06)
- Context: the JSONL files cannot answer "when was this listing last seen", and the dashboard reparses the whole file on every request. The project needs a real database.
- Options: PostgreSQL, MySQL, SQLite.
- Decision: PostgreSQL.
- Why: medians are central to this project, and Postgres has `percentile_cont` as an aggregate, while MySQL has no built-in median or percentile aggregate. Postgres also has JSONB for raw payloads, partial indexes and `INSERT … ON CONFLICT` upserts, and Ivan already uses it in his Spring Boot projects. SQLite was ruled out because the scraper and the API write concurrently.
- Would change if: a deployment target only offered MySQL, in which case medians would move into Python.

### D-002: FastAPI over Spring Boot (2026-10-06)
- Context: the stdlib `market_server.py` needs replacing with a real API.
- Options: FastAPI, Spring Boot.
- Decision: FastAPI.
- Why: the scraper, rules, analytics and ML are all Python. A Python backend keeps one copy of the noise rules and serves the ML model in-process. Ivan's other portfolio projects already cover Spring Boot. Accepted tradeoff: Spring Boot appears in more Spanish junior backend offers overall.
- Would change if: the rules and model moved to a separate service anyway, which would remove the shared-code advantage.

### D-003: Angular over React (2026-10-06)
- Context: the React dashboard must be rebuilt to consume the new API.
- Options: keep React, Angular.
- Decision: Angular (standalone components, signals).
- Why: Angular is Ivan's preferred frontend for the offers he targets. The rewrite is needed anyway, because business rules have to move out of the frontend.
- Would change if: target offers shifted clearly towards React.

### D-004: pandas over polars for analysis (2026-10-06)
- Context: Phase 5 notebooks need a dataframe library.
- Options: pandas, polars.
- Decision: pandas.
- Why: the data is small (tens of thousands of listings), so polars' speed does not matter, and pandas is the library Spanish job offers name.
- Would change if: data grew to a size where pandas became a bottleneck.

### D-005: No Power BI (2026-10-06)
- Context: BI dashboards are common in junior data offers.
- Options: Power BI report, notebooks plus SQL marts.
- Decision: no Power BI for now.
- Why: its desktop authoring tool is Windows-only and Ivan works on Linux. The SQL marts in the `analytics` schema make a BI report easy to add later.
- Would change if: a target role required a Power BI sample.

### D-006: Track disappearance in the database (2026-10-06)
- Context: since late June the prototype writes a JSONL line only when an item is new or its price changes, so "last seen" cannot be reconstructed.
- Options: go back to one row per scan, or keep current state in the database.
- Decision: the database records `last_seen_at` on every scan, plus a `scan_runs` table with page caps and status.
- Why: one row per scan grew the file to 640 MB in three days. Upserting `last_seen_at` keeps storage flat, and `scan_runs` says which absences are evidence (complete scans) and which are not (capped or failed scans). Time-on-market analysis is possible from the migration date onward.
- Would change if: the marketplaces exposed sold or removed status directly.

### D-007: Keep the prototype byte-identical under `wallabot.legacy` (2026-10-06)
- Context: Phase 0 moves the Python code under `backend/`, and the scraper must keep running.
- Options: (a) move with `git mv` and run from the data directory via the Makefile; (b) root-level shim scripts; (c) fix the cwd-relative paths in the move.
- Decision: (a). The files are pure renames; `make scraper` and `make legacy-server` `cd` into `data/` first. Ruff excludes `src/wallabot/legacy`.
- Why: pure renames keep `git log --follow` and `git blame` intact, and the characterisation tests run against exactly the code that ran in production. Shims add files that Phase 2 deletes anyway. Fixing paths or lint now would change the prototype before Phase 2 replaces it, with no test covering file I/O.
- Would change if: the scraper had to run for a long time from a location other than `data/` before Phase 2.

### D-008: Python 3.12 managed by uv (2026-10-06)
- Context: the host Python is 3.14 and the old venv was built on it; the stack specifies 3.12.
- Options: use the host 3.14, or pin 3.12 through uv.
- Decision: `backend/.python-version` pins 3.12, and `requires-python = ">=3.12,<3.13"`.
- Why: uv downloads the interpreter, so local, CI and Docker run the same minor version regardless of the host. 3.12 also has the widest wheel coverage for the data stack (lifelines, statsmodels, mlflow).
- Would change if: a required library dropped 3.12.

### D-009: Port price outliers to Python, proven by a parity test against the JS (2026-10-06)
- Context: outlier detection lives only in `priceOutliers.js`. Ground rule 5 moves business rules to Python.
- Options: port by reading the code, or port and compare outputs with the original.
- Decision: `wallabot.rules.outliers` plus a test that runs the original JS under Node on 500 seeded random categories and requires identical output.
- Why: subtle details decide results, for example cheap listings still count towards the median and MAD after the low-price rule flags them. A mutation check showed the parity test catches that exact mistake, and a hand-written golden case pins it as well.
- Would change if: the JS were deleted (Phase 4). The parity test then becomes a fixed golden file.

### D-010: The data audit is generated by a script (2026-10-06)
- Context: ground rule 3 forbids numbers not produced by code in the repo.
- Options: one-off notebook, or a script that rewrites a marked block of the audit doc.
- Decision: `wallabot.importers.legacy_audit`, run by `make audit`, rewrites only the block between the `GENERATED` markers in `docs/data_audit.md`.
- Why: anyone with the files can regenerate the numbers, and the hand-written findings stay in the same document. A notebook would mix output and code, and is harder to diff.
- Would change if: the audit needed plots, which belong in Phase 5 notebooks.

### D-011: Do not adopt the abandoned `marketwatch/` package (2026-10-06)
- Context: an earlier, unfinished refactor left an untracked `marketwatch/` package (about 500 lines) whose docstring describes modules that do not exist.
- Options: commit it into `backend/`, or ignore it.
- Decision: ignore it (listed in `.gitignore`); the target package is `wallabot`.
- Why: it would add a third copy of the noise and learned-filter logic with no tests and no callers. Its useful ideas are covered by the Phase 2 plan.
- Would change if: Ivan wants a specific piece of it, which would then be ported with tests.
