# doc-qa-agent Makefile.
#
# Targets are designed to run from a fresh clone end to end:
#   make install   -> venv + editable install
#   make init-db   -> apply SQL migrations against $DATABASE_URL
#   make ingest    -> crawl + chunk 80 pages from llms.txt
#   make embed     -> backfill embeddings via Voyage / OpenAI
#   make eval      -> 15 cases x 2 modes, writes eval/reports/eval_*.md
#   make api       -> uvicorn doc_qa.api:app on 127.0.0.1:8000
#   make mcp       -> stdio MCP server (Claude Code / Cowork attach to this)
#   make test      -> pytest over tests/
#   make lint      -> ruff over src/ scripts/ eval/ tests/
#   make all       -> install + init-db + ingest + embed (one shot)
#
# Windows note: paths use forward slashes which work in Git Bash, mingw, and
# WSL. On bare PowerShell prefer `setup.ps1` instead.

PY := .venv/Scripts/python.exe
RUFF := .venv/Scripts/ruff.exe

.PHONY: help install init-db ingest embed eval api mcp test lint all clean

help:
	@echo "Targets: install init-db ingest embed eval api mcp test lint all clean"
	@echo "Run 'make all' for end-to-end setup (after editing .env)."

install:
	python -m venv .venv
	$(PY) -m pip install --upgrade pip --quiet
	$(PY) -m pip install -e .[dev]
	@if [ ! -f .env ]; then cp .env.example .env; echo "Edit .env with your keys."; fi

init-db:
	$(PY) -m scripts.init_db
	$(PY) -m scripts.test_db

ingest:
	$(PY) -m doc_qa.ingest --limit 80

embed:
	$(PY) -m doc_qa.embeddings

eval:
	$(PY) -m eval.run_eval

api:
	$(PY) -m uvicorn doc_qa.api:app --host 127.0.0.1 --port 8000

mcp:
	$(PY) -m doc_qa.mcp_server

test:
	$(PY) -m pytest tests/ -v

lint:
	$(RUFF) check src/ scripts/ eval/ tests/

all: install init-db ingest embed
	@echo "==> setup complete. 'make api' or 'make mcp' next."

clean:
	rm -rf src/doc_qa.egg-info build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
