.PHONY: sync lint fmt mypy test vtest cov build

sync:
	uv sync

lint: mypy
	uv run ruff check
	uv run ruff format --check

fmt:
	uv run ruff check --fix
	uv run ruff format

mypy:
	uv run mypy

test: lint
	uv run pytest tests

vtest: lint
	uv run pytest -v tests

cov: lint
	uv run pytest --cov=janus --cov=tests --cov-report=term --cov-report=html
	@echo "open file://`pwd`/coverage/index.html"

build:
	uv build
