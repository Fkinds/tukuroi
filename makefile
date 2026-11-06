SRC:=src/fixit/ scripts/
PKG:=fixit
EXTRAS:=dev,docs,lsp,pretty

UV:=$(shell uv --version)
ifdef UV
	VENV:=uv venv
	PIP:=uv pip
else
	VENV:=python -m venv
	PIP:=python -m pip
endif

all: venv test lint html

install:
	$(PIP) install -Ue .[$(EXTRAS)]

.venv:
	$(VENV) --prompt fixit .venv

venv: .venv
	source .venv/bin/activate && make install
	echo 'run `source .venv/bin/activate` to activate virtualenv'

test:
	python -m $(PKG).tests
	pyrefly check -c pyproject.toml

lint:
	python -m ruff check $(SRC)
	python -m ruff format --check $(SRC)
	python -m fixit lint $(SRC)
	python scripts/check_copyright.py

html: docs/*
	python scripts/document_rules.py
	sphinx-build -ab html docs html

format:
	python -m ruff check --select I --fix $(SRC)
	python -m ruff format $(SRC)

clean:
	rm -rf .mypy_cache build dist html *.egg-info

distclean: clean
	rm -rf .venv
