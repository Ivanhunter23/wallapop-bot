# Targets are added phase by phase; see the Commands table in AGENTS.md.
UV ?= uv
DATA_DIR ?= $(CURDIR)/data
BACKEND := $(CURDIR)/backend

.PHONY: setup scraper legacy-server audit test lint

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

# Read-only audit of the legacy files; rewrites the generated block of docs/data_audit.md.
LEGACY_SNAPSHOT ?= $(CURDIR)/../wallabotdata
audit:
	cd backend && $(UV) run python -m wallabot.importers.legacy_audit \
		--out $(CURDIR)/docs/data_audit.md \
		--jsonl snapshot-0621=$(LEGACY_SNAPSHOT)/wallapop_data.jsonl \
		--jsonl full-backup-0627=$(DATA_DIR)/backups/wallapop_data.jsonl.bak \
		--jsonl compaction-1=$(DATA_DIR)/backups/wallapop_data.jsonl.bak-20260628-153851 \
		--jsonl compaction-2=$(DATA_DIR)/backups/wallapop_data.jsonl.bak-20260628-154618 \
		--jsonl compaction-3=$(DATA_DIR)/backups/wallapop_data.jsonl.bak-20260628-155256 \
		--jsonl current=$(DATA_DIR)/wallapop_data.jsonl \
		--summary-only compaction-1 --summary-only compaction-2 --summary-only compaction-3 \
		--chain full-backup-0627,compaction-1,compaction-2,compaction-3,current \
		--state snapshot-0621=$(LEGACY_SNAPSHOT) \
		--state current=$(DATA_DIR)

test:
	cd backend && $(UV) run pytest

lint:
	cd backend && $(UV) run ruff check . && $(UV) run ruff format --check .
