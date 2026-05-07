# Sample API responses

Real captured responses from the running FastAPI service against the
99-page Anthropic docs corpus described in the top-level `README.md`.
Reviewers see the system's input / output without standing up a Postgres,
filling in keys, or running uvicorn.

Captured on a live `python -m uvicorn doc_qa.api:app` instance against a
Supabase + pgvector backend with Voyage 3-large embeddings.

## Files

- `healthz_response.json`: `GET /healthz`. Reports source / chunk / embedding
  counts plus the configured embedding provider and answer model. Fast
  liveness probe.

- `search_response.json`: `POST /search` with
  `{"query": "How do prompt caching breakpoints work?", "k": 3, "mode": "hybrid"}`.
  Returns chunk-level results with the FTS rank, the semantic rank, and the
  fused RRF score for every hit. Useful for retrieval ablations and the
  Loom comparison demo. No model call.

- `ask_response.json`: `POST /ask` with
  `{"question": "What pricing applies to batch processing requests in Claude?", "k": 5}`.
  Runs hybrid retrieval, sends the top-5 chunks to Claude Sonnet 4.6 with
  built-in citations enabled, and returns the answer text plus structured
  citations mapped back to source URLs. The grounded answer reports both
  the headline rate ("50% of standard API prices") and the per-model batch
  pricing table from the canonical doc page. This is the same question
  (q15) that failed in the first eval iteration and was resolved by the
  table-aware chunking fix.

The `request_id` field on every response and the `X-Request-ID` header on
every wire response exist to make logs and responses cross-reference cleanly
in production. See `src/doc_qa/api.py`.
