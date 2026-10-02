# Video Factory agent shortcuts. All read-only except where noted.
# `make check` == `./scripts/vf check`: lint + type/syntax + tests + doctor.
#
# Python: prefer this checkout's worker venv, fall back to the daily-routine
# checkout's venv (read-only use — never install anything into it), else python3.

WENV := $(CURDIR)/apps/worker/.venv/bin/python
MENV := $(HOME)/Projects/video-factory/apps/worker/.venv/bin/python
VENV_PY := $(shell if [ -x "$(WENV)" ]; then echo "$(WENV)"; elif [ -x "$(MENV)" ]; then echo "$(MENV)"; else echo python3; fi)

LINT_SCOPE := scripts/vf scripts/migrate_ledger.py \
  apps/worker/src/services/error_codes.py apps/worker/src/services/checkpoint.py \
  apps/worker/src/services/series_registry.py apps/worker/src/services/funnel.py \
  apps/worker/src/services/cli_runner.py

.PHONY: check test lint doctor status drift help

check: ## One gate: lint + type/syntax + tests + doctor (read-only, ~1 min)
	$(VENV_PY) ./scripts/vf check --json

test: ## Fast test suite (apps/worker, ~45s, coverage gate 60%)
	cd apps/worker && $(VENV_PY) -m pytest -p no:cacheprovider -q

lint: ## Ruff on the agent-facing surface (must stay clean)
	$(VENV_PY) -m ruff check $(LINT_SCOPE)

doctor: ## Env health (disk/mem/ffmpeg/whisper/creds-booleans/proxy)
	$(VENV_PY) ./scripts/vf doctor --json

status: ## Ledger status
	$(VENV_PY) ./scripts/vf status --json

drift: ## New ledger vs old read-only ledgers
	$(VENV_PY) ./scripts/vf status --check-drift --json

help: ## This list
	@grep -E '^[a-z-]+: ## ' $(MAKEFILE_LIST) | sort
