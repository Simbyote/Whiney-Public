# Whiney: every development command in one place. Run from the repo root, in WSL:
#
#     make                  the list of commands
#     make venv             once: the Linux venv with the app, pytest and ruff
#     make check            lint + software tests: run before every commit
#     make test-live        read-only checks against the real Windows install
#
# Options are make variables: make <target> NAME=value.
#     ARGS="..."            passed straight to the command (e.g. ARGS="-k plugins -x")
#     WINPY=py.exe          the Windows Python the live tests run on
# Each target's comment names the guide in docs/guides/ that explains it.
# The maintainer's commands (build.bat, pack_*.bat) stay Windows batch files: docs/guides/build.md.

VENV_DIR ?= .venv
PY       ?= $(if $(wildcard $(VENV_DIR)/bin/python),$(VENV_DIR)/bin/python,python3)
# The live tests need the Windows registry, Steam and Vortex, so they run on
# Windows Python, which WSL can start directly
WINPY    ?= py.exe
ARGS     ?=

.DEFAULT_GOAL := help
.PHONY: help venv live-deps check test test-live lint fix run clean

##@ Start here
help: ## this list
	@awk 'BEGIN {FS = ":.*## "} \
	     /^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5)} \
	     /^[a-z0-9-]+:.*## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Options: make <target> NAME=value, e.g. ARGS=\"-k plugins -x\"  WINPY=python.exe"
	@echo "Python: $(PY)"

venv: ## create .venv with the app (editable), pytest and ruff (make.md)
	python3 -m venv $(VENV_DIR)
	$(VENV_DIR)/bin/pip install --quiet --upgrade pip
	$(VENV_DIR)/bin/pip install --quiet -r requirements-dev.txt
	$(VENV_DIR)/bin/pip install --quiet --no-deps -e .

live-deps: ## install pytest and the app's packages into Windows Python, for test-live
	$(WINPY) -m pip install --quiet --user -r requirements-dev.txt

##@ Every change (pytest.md)
check: lint test ## lint, then the software tests: the gate before a commit

test: ## software tests: fixtures only, any OS, pass/fail
	$(PY) -X warn_default_encoding -m pytest -q $(ARGS)

test-live: ## live tests on Windows Python against the real install; read-only, writes artifacts/
	$(WINPY) -X warn_default_encoding -m pytest --live -q $(ARGS)

lint: ## ruff over src/ and tests/, then mypy over the package (pyproject.toml has both configs)
	$(PY) -m ruff check src tests
	$(PY) -m mypy

fix: ## ruff's safe auto-fixes (import order, upgrades); review the diff after
	$(PY) -m ruff check --fix src tests

##@ The app
run: ## start the GUI from source (WSLg shows the window; Windows-only features stay off)
	$(PY) -m whiney $(ARGS)

clean: ## remove caches, build output and test artifacts (keeps .venv)
	rm -rf build dist artifacts .pytest_cache .ruff_cache .mypy_cache
	find . -name __pycache__ -type d -prune -not -path "./$(VENV_DIR)/*" -exec rm -rf {} +
