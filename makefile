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

test:
	$(RUN) python -m $(PKG).tests
	$(RUN) pyrefly check -c pyproject.toml

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
	rm -rf .mypy_cache build dist html *.egg-info

distclean: clean
	rm -rf .venv
