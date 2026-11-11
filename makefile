SRC:=src/fixit/ scripts/
PKG:=fixit

# What uv installs from uv.lock before it runs a command: every extra and group
# by default. A CI job narrows it to what it needs (#8).
SYNC?=--all-extras --all-groups
RUN=uv run $(SYNC)

all: install test lint html

install:
	uv sync $(SYNC)

venv: install

# uv.lock, and the build backend with hashes for the release build (#18). Both
# keep the versions they have: pass --upgrade to `uv lock` and to
# `uv pip compile` to take newer ones. Renovate runs the command of the header
# of build-constraints.txt (#7): it takes `--option=value` only.
lock:
	uv lock
	uv pip compile --quiet --python-version=3.14 --generate-hashes \
		build-constraints.in --output-file=build-constraints.txt

test:
	$(RUN) python -m $(PKG).tests
	$(RUN) pyrefly check -c pyproject.toml

# The tests change the current directory, and so do the processes that they
# start: the data goes to one place, by its absolute path (#10).
coverage: export COVERAGE_FILE=$(CURDIR)/.coverage
coverage:
	rm -f .coverage .coverage.*
	$(RUN) coverage run -m $(PKG).tests
	$(RUN) coverage combine -q
	$(RUN) coverage report

lint:
	$(RUN) ruff check $(SRC)
	$(RUN) ruff format --check $(SRC)
	$(RUN) python -m fixit lint $(SRC)
	$(RUN) python scripts/check_copyright.py

html: docs/*
	$(RUN) python scripts/document_rules.py
	$(RUN) sphinx-build -ab html docs html

format:
	$(RUN) ruff check --select I --fix $(SRC)
	$(RUN) ruff format $(SRC)

clean:
	rm -rf .mypy_cache build dist html *.egg-info .coverage .coverage.*

distclean: clean
	rm -rf .venv
