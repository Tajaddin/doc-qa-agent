# doc-qa-agent

A documentation Q&A agent on the Anthropic stack. Hybrid retrieval over
Supabase + pgvector, a FastAPI `/ask` endpoint with grounded Claude citations,
and an MCP server so any Claude client connects to the same knowledge base.

Built for the Ovidius AI Senior AI Builder qualification project. Sprint
window 4 to 6 hours.

## What ships

- 99 pages from `https://platform.claude.com/llms.txt` ingested into Supabase
  Postgres + pgvector. 2,633 chunks, 254-token average, 100 percent embedded
  with Voyage 3-large (1024 dim). Auto-generated API endpoint and SDK
  reference pages are excluded via `CRAWL_PATH_DENY=/docs/en/api/` so the
  corpus stays conceptual.
- Hybrid retrieval: BM25-style FTS (GIN over `tsvector`) plus HNSW cosine
  vector search, fused with reciprocal rank fusion in a single SQL function.
- FastAPI service with three routes:
  - `GET /healthz` returns DB stats and the configured embedding provider.
  - `POST /search` runs hybrid or vector retrieval and returns chunk-level
    results with FTS rank, semantic rank, and the fused score.
  - `POST /ask` runs retrieval, sends the chunks to Claude Sonnet 4.6 with
    `citations.enabled=true`, and returns answer text plus structured citations
    plus a deduped sources array, all mapped back to the original URLs.
- 15-question eval set (`eval/questions.yaml`). Side-by-side `hybrid` vs
  `vector` runs. Reports retrieval metrics (hit@k, recall@k, MRR), citation
  precision against gold URLs, and Claude Haiku 4.5 LLM-as-judge for
  faithfulness and completeness. Markdown report plus full JSON dump.
- MCP server (FastMCP, stdio transport) exposing three tools any Claude
  client picks up: `search_docs`, `ask_docs`, `list_sources`.

## Architecture

```
                     https://platform.claude.com/llms.txt
                                  │
                                  ▼  crawl.py (async, .md GET, llms.txt index)
                              chunk.py
                       (heading aware, code-fence safe)
                                  │
                                  ▼
                  ┌─────────────────────────────────┐
                  │  Supabase Postgres + pgvector   │
                  │   sources                       │
                  │   chunks (HNSW + GIN tsvector)  │
                  │   eval_cases                    │
                  │   hybrid_search() RRF fn        │
                  │   vector_search() fn            │
                  └────────┬─────────────┬──────────┘
                           │             │
                           ▼             ▼
                     retrieve.py     embeddings.py
                     (Python wrap)   (Voyage / OpenAI)
                           │
                           ▼
                       answer.py
            (Claude Sonnet 4.6 + built-in citations)
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
       FastAPI /ask   MCP server    eval/run_eval.py
                      stdio tools   hit@k, MRR,
                                    Haiku-as-judge
```

## Stack

- Python 3.10 to 3.12, FastAPI, Pydantic v2, Pydantic Settings.
- Anthropic Messages API with built-in citations. Sonnet 4.6 for `/ask`
  answers, Haiku 4.5 for the eval judge.
- Voyage AI embeddings (`voyage-3-large`, 1024 dim) primary. OpenAI
  `text-embedding-3-small` (shortened to 1024 dim with the `dimensions`
  parameter) as a configurable fallback. Auto-detect by which key is set,
  override with `EMBEDDING_PROVIDER=voyage|openai`.
- Postgres 16 with `pgvector` for semantic search, `tsvector` + GIN for FTS,
  reciprocal rank fusion in SQL.
- Supabase as the managed Postgres host (the production stack the role uses).
  Local Docker Compose works as a drop-in fallback (`docker-compose.yml`
  ships pgvector preloaded).
- MCP Python SDK (FastMCP) over stdio for Claude Desktop, Claude Code, and
  Claude Cowork integration.
- httpx, beautifulsoup4, markdownify, lxml for the crawler.
- tiktoken for chunk token counts.
- tenacity for embedding retry. rich for CLI output. typer / argparse for
  command surfaces.

## Quickstart

You need: Python 3.10 to 3.12, a Supabase project (or local Postgres with
pgvector), an Anthropic API key, and a Voyage or OpenAI key.

One command on Windows:

```
powershell -ExecutionPolicy Bypass -File setup.ps1
```

`setup.ps1` creates the venv, installs deps, copies `.env.example` to
`.env` if missing, and runs the migrations. Edit `.env`, re-run. With Make:

```
make install   # venv + editable install + dev extras
make init-db   # apply sql/*.sql
make all       # install + init-db + ingest + embed
```

Manual path if you prefer:

```
git clone <this repo>
cd doc-qa-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # PowerShell on Windows
pip install -e .[dev]
copy .env.example .env                  # then fill in the keys
```

`.env` keys you need to fill:

- `ANTHROPIC_API_KEY` from console.anthropic.com.
- `VOYAGE_API_KEY` from dash.voyageai.com (free 200M tokens once a payment
  method is on file). Or `OPENAI_API_KEY`. The provider auto-resolves. Force
  one with `EMBEDDING_PROVIDER`.
- `DATABASE_URL`. Either a Supabase connection URI (Session pooler at port
  5432 works on free tier IPv4) or `postgresql://docqa:docqa@localhost:5432/docqa`
  if you run `docker compose up -d`.

Initialise the schema and verify:

```
python -m scripts.init_db
python -m scripts.test_db
python -m scripts.test_hybrid          # 0 rows expected, table is empty
```

Crawl, chunk, ingest:

```
python -m doc_qa.ingest          # uses CRAWL_MAX_PAGES + CRAWL_PATH_DENY from .env
python -m scripts.peek_db
```

The default `.env` settings produce a 99-page conceptual corpus (max 200,
minus the auto-generated SDK / endpoint reference pages under
`/docs/en/api/`). Adjust the env vars to widen or narrow.

Embed every chunk (around a minute on Voyage with billing enabled):

```
python -m doc_qa.embeddings
python -m scripts.peek_db              # chunks_with_embeddings should match chunks
```

## Usage

### FastAPI

```
.\.venv\Scripts\python.exe -m uvicorn doc_qa.api:app --host 127.0.0.1 --port 8000
```

Hit it from a second window:

```
curl.exe http://127.0.0.1:8000/healthz
.\.venv\Scripts\python.exe -m scripts.test_ask "How does prompt caching work?"
```

`POST /ask` returns:

```json
{
  "question": "...",
  "answer": "...",
  "citations": [
    {"cited_text": "...", "source_url": "...", "heading": "...", "document_title": "..."}
  ],
  "sources": [{"url": "...", "title": "..."}],
  "retrieved_chunk_ids": [12, 41, 88, 91, 102],
  "model": "claude-sonnet-4-6",
  "usage": {"input_tokens": 2735, "output_tokens": 115}
}
```

`POST /search` returns the chunk pool with FTS rank, semantic rank, and the
fused RRF score for each hit. Useful for the demo because the ranks expose
which side of the hybrid contributed each result.

OpenAPI lives at `http://127.0.0.1:8000/docs`.

### MCP server

stdio transport. Three tools registered: `search_docs`, `ask_docs`,
`list_sources`.

Direct logic check (no transport):

```
.\.venv\Scripts\python.exe -m scripts.test_mcp_tools
```

Inspector:

```
.\.venv\Scripts\mcp.exe dev src\doc_qa\mcp_server.py
```

In the inspector UI, set Command to your venv Python and Args to
`-m doc_qa.mcp_server` before clicking Connect (the inspector default is
`uv run --with mcp` which builds a fresh env without the project deps).

Claude Code:

```
claude mcp add -s user doc-qa-agent -- "<full path to .venv\Scripts\python.exe>" -m doc_qa.mcp_server
claude mcp list
```

Then start a Claude Code session and ask:

> Use the doc-qa-agent search_docs tool to find docs about prompt caching.

Claude Code calls the tool live and renders results in the session.

Claude Cowork:

```
# Build the MCPB extension once (Node + npm required)
npm install -g @anthropic-ai/mcpb
cd cowork-extension
mcpb pack . doc-qa-agent.mcpb
```

Then double-click `cowork-extension/doc-qa-agent.mcpb`, or drag it into
Cowork's Extensions panel. The user_config prompt defaults the Python path
to the project venv. After install, fully quit and reopen Cowork. See
`cowork-extension/INSTALL.md` for the full walkthrough.

### Ingestion CLI

```
python -m doc_qa.ingest --limit 10 --dry-run --sample
python -m doc_qa.ingest               # default: uses CRAWL_MAX_PAGES + CRAWL_PATH_DENY from .env
python -m doc_qa.ingest --limit 50    # override the page cap explicitly
```

The crawler is idempotent. Re-running with the same corpus reports
`skipped_unchanged=N` for pages whose checksum matches the stored row.

### Embeddings CLI

```
python -m doc_qa.embeddings --limit 50         # smoke test
python -m doc_qa.embeddings                    # all NULL embeddings
python -m doc_qa.embeddings --reembed          # re-embed everything
```

## Evaluation

The methodology, why each metric was picked, and the known limitations all
live in [`EVAL.md`](EVAL.md). The latest run is committed at
[`eval/REPORT.md`](eval/REPORT.md).

```
python -m eval.run_eval                        # 15 cases x 2 modes
python -m eval.run_eval --modes hybrid         # one mode only
python -m eval.run_eval --filter q01           # one case
```

Latest canonical run, committed at `eval/REPORT.md`:

```
mode    n   hit@k  recall@k  MRR    cit_hit  cit_prec  faith  compl  lat_med
hybrid  15  1.00   1.00      0.922  1.00     0.90      1.00   0.90   3.78s
vector  15  0.93   0.93      0.817  0.93     0.82      0.87   0.80   4.06s
```

What the numbers say:

- Hybrid hits faithfulness 1.00 across all 15 questions. Every answer is
  consistent with the gold, no contradictions. Hit@k = 1.00 and citation
  hit = 1.00 confirm retrieval and grounding stay clean.
- Hybrid wins on every metric we track: hit@k, recall@k, MRR, citation
  hit, citation precision, faithfulness, completeness, latency.
- Three iterations the eval drove:
  1. Table-aware chunking in `chunk.py` so the pricing table on
     `batch-processing.md` becomes its own chunk with a prose lead-in.
     Resolved q15 batch_pricing.
  2. `CRAWL_PATH_DENY=/docs/en/api/` filter so auto-generated endpoint
     reference pages stop outranking conceptual docs on keyword overlap.
     Resolved q04 and q11.
  3. Judge prompt tightened so legitimate additions to the gold answer
     count as faithful, not as contradictions. Resolved q13 text_editor_tool.
- One residual finding stays in the report: q09 managed_agent_session.
  Hybrid scores faith=1, compl=0.35. The model's answer is faithful (POST
  to sessions endpoint with agent_id) but pads with extra context the
  narrowly-scoped gold does not anticipate. This is an eval-design
  observation rather than a system bug. The question would benefit from
  either a broader gold or a sharper question wording, both noted in
  `EVAL.md`.

`eval/run_eval.py` writes a markdown report and a structured JSON dump to
`eval/reports/eval_<UTC timestamp>.{md,json}` on every run.

The eval is the section the brief flagged as the highest-signal piece, so the
report calls out failure modes explicitly with judge reasoning, not only
aggregate scores.

## Tests

32 pytest cases. 25 unit tests over pure-Python pieces (chunker including
table isolation, retrieval metric helpers, crawler URL filters with deny
list, markdown cleaner, checksums) and 7 integration tests over the FastAPI
app via TestClient with mocked DB and embedding clients. No DB or network
required to run any of them.

```
make test
# or
.venv\Scripts\python.exe -m pytest tests/ -v
```

The tests caught a real bug: the metrics suite found an order-of-operations
bug in `_normalize` which would have under-scored hit@k on URLs carrying both
a query string and a trailing slash. Fix is in `eval/run_eval.py`. The API
suite exercises the request-id middleware, the AppError exception handler,
and Pydantic input validation.

## Sample API responses

`samples/` contains captured `GET /healthz`, `POST /search`, and `POST /ask`
responses against a live instance, so reviewers see the system's output
shape without running it. See `samples/README.md` for what each file
covers.

## Tradeoffs and limits

- Citations are incompatible with Structured Outputs on the Messages API.
  The FastAPI response is shaped server-side after a normal cited response,
  not asked from Claude as JSON. Documented in `answer.py`.
- Citation spans are whole-chunk, not sentence-level. Each chunk arrives as
  one custom-content text block, so `start_block_index`/`end_block_index`
  cover the whole chunk. Sentence granularity needs the chunker to emit
  multiple text blocks per paragraph. Tracked in `KNOWN_ISSUES.md`.
- Voyage 3-large free tier without a payment method is throttled to 3 RPM /
  10K TPM, too slow for a 99-page corpus. With a payment method on file the
  free 200M tokens still apply, so a 99-page ingest costs $0. The OpenAI
  fallback path is wired and tested if you prefer the OpenAI route.
- Claude Cowork integration ships as an MCPB extension at
  `cowork-extension/doc-qa-agent.mcpb` (1.2 kB, references the venv via
  `${user_config.python_path}` instead of bundling 500 MB of Python deps).
  Two install paths in `cowork-extension/INSTALL.md`. Same retrieval engine,
  third client surface alongside FastAPI and Claude Code.
- Managed Agents were considered for the deeper option. MCP wins on
  signal-to-effort for a 4-6 hour sprint: official Python SDK is mature,
  stdio demos cleanly inside Claude clients, and the same retrieval engine
  composes naturally as both a FastAPI route and an MCP tool surface.

## Layout

```
doc-qa-agent/
  pyproject.toml
  .env.example
  docker-compose.yml
  sql/
    001_init.sql              extension, tables, indexes, fts trigger
    002_hybrid_search.sql     hybrid_search() + vector_search() SQL fns
  src/doc_qa/
    __init__.py
    config.py                 settings via pydantic-settings
    db.py                     psycopg pool with pgvector adapter
    crawl.py                  llms.txt + .md fetch, html fallback
    chunk.py                  heading-aware markdown chunker
    ingest.py                 crawl + chunk + upsert (idempotent)
    embeddings.py             Voyage / OpenAI clients + backfill CLI
    retrieve.py               Python wrapper over the SQL search fns
    answer.py                 Claude Sonnet 4.6 + built-in citations
    api.py                    FastAPI /healthz, /search, /ask
    mcp_server.py             FastMCP stdio: search_docs, ask_docs, list_sources
  scripts/
    init_db.py                applies sql/*.sql
    test_db.py                schema + index + function smoke test
    test_hybrid.py            hybrid_search() function shape test
    peek_db.py                source / chunk / embedding inventory
    test_retrieval.py         CLI retrieval check, hybrid or vector
    test_ask.py               POST /ask client with pretty-printer
    test_mcp_tools.py         direct logic check of MCP tools
  eval/
    questions.yaml            15 Q/A pairs with gold URLs
    run_eval.py               retrieval + citation + judge metrics
    REPORT.md                 canonical run, committed
    reports/                  per-run .md + .json (gitignored)
  cowork-extension/
    manifest.json             MCPB extension manifest
    noop.py                   validator-required placeholder
    doc-qa-agent.mcpb         packed Cowork bundle (1.2 kB)
    INSTALL.md                Cowork install walkthrough
  tests/
    test_chunk.py             chunker behaviour (heading propagation,
                              fenced-code safety, target tokens)
    test_metrics.py           hit@k, recall@k, MRR, citation_metrics
    test_crawl.py             llms.txt parser, URL filter, markdown cleaner
  Makefile                    install / init-db / ingest / embed / eval / api / mcp / test
  setup.ps1                   one-shot Windows setup script
  EVAL.md                     eval methodology, why each metric, known limits
  KNOWN_ISSUES.md             q15 pricing, citation span granularity
  DAY_ONE.md                  what I would build first on day one
  LOOM_OUTLINE.md             5-10 minute demo script
  LICENSE                     MIT
```

## Anthropic stack notes for reviewers

- `answer.py` sends each retrieved chunk as a `type: "document"` block with
  `source.type: "content"` (custom content, one text block per chunk) and
  `citations: { "enabled": true }`. The result is chunk-level citation
  granularity. Citation objects map back to the chunk via `document_index`.
- `title` and `context` on each document carry the heading and source URL
  for grounding without polluting citation spans (the docs explicitly note
  these fields are visible to the model but not citable).
- The system prompt restricts the model to provided documents and asks for
  refusal when a question is not answerable from the corpus. Combined with
  citations the answers are auditable per-claim.
- Eval uses Haiku 4.5 as the judge because Anthropic recommends Haiku as the
  fast, cost-effective starting point for grading-style tasks.

## License

MIT. See `LICENSE`.
