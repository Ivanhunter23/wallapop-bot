# Targets are added phase by phase; see the Commands table in AGENTS.md.
UV ?= uv
DATA_DIR ?= $(CURDIR)/data
BACKEND := $(CURDIR)/backend

.PHONY: setup scraper legacy-server test lint

setup:
	cd backend && $(UV) sync
	cd backend && $(UV) run playwright install chromium

# The prototype scripts read and write their state files relative to the
# working directory, so they run from the data directory.
scraper:
	cd $(DATA_DIR) && $(UV) run --project $(BACKEND) python -m wallabot.legacy.wallapop_watcher

# Temporary: the stdlib dashboard server, until the FastAPI API and Angular app replace it.
legacy-server:
	cd $(DATA_DIR) && DASHBOARD_DIST=$(CURDIR)/market_dashboard/dist \
		$(UV) run --project $(BACKEND) python -m wallabot.legacy.market_server

test:
	cd backend && $(UV) run pytest

lint:
	cd backend && $(UV) run ruff check . && $(UV) run ruff format --check .
