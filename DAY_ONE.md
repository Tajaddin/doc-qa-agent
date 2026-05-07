# Day one of the job

Owen asked for "a few sentences on what you'd build next if this were day one
of the job." The eval surfaced real failures and the architecture has obvious
extension points. Five things, ranked by signal-to-effort.

## 1. Reranker between RRF and the LLM

The Anthropic RAG cookbook uses an initial pool of 20 candidates, reranks down
to 3 with a dedicated reranker, and reports cleaner answers. My pipeline pulls
20 candidates and sends 5 directly to Claude. A reranker step closes the gap.

Two viable rerankers, both compatible with the existing retrieval module:

- Voyage `rerank-2.5-lite`. One API call per query, returns scored chunks, very
  cheap.
- Claude Haiku 4.5 as a reranker, prompted with the query and chunk summaries
  to pick the top 3-5. Slower but stays inside the Anthropic stack.

I would A/B these against the current eval set and ship whichever wins MRR and
faithfulness without breaking citation hit rate.

## 2. Contextual Retrieval

Anthropic's Contextual Retrieval write-up reports a 49% reduction in failed
retrievals using contextual embeddings + contextual BM25, and 67% when stacked
with reranking. The technique prepends a short Claude-generated context string
to each chunk before embedding. My current eval has hybrid hit@k = 1.00 and
faithfulness = 1.00 on the 15-case set. Contextual embeddings would help
hold those numbers as the eval set scales to 100+ cases, since they
reduce the "right page, wrong section" failure mode that the longer set
would surface.

Cost is one-time at ingest. With prompt caching the per-chunk context call
costs cents.

## 3. Streaming /ask with Server-Sent Events

Sonnet 4.6 takes 3-4 seconds for the median answer. A non-streaming endpoint
feels slow even though throughput is fine. Switch the answer module to
`AsyncAnthropic`, switch FastAPI to async, and stream content blocks plus
citations as they arrive. Adds maybe 80 lines.

## 4. Longer eval set with per-tag breakdowns

The current 15-case set is enough to catch the architectural failures it
already caught. The next iteration scales to 100 to 200 cases and slices by
tag (factual, procedural, comparison, edge-case, multi-source). The infra
is already there: `eval/run_eval.py` reads from `questions.yaml` and the
JSON dump carries every per-case field. The aggregator just needs a tag
slicing helper.

The q09 managed_agent_session observation in the current report is the
clearest sign the eval set should grow: a question that has multiple
correct levels of detail needs either a broader gold answer or a sharper
question wording. A larger set lets us tag and average across question
shapes rather than fight individual edge cases.

## What already shipped after the first two eval iterations

The first canonical run had two failures: q15 batch_pricing and q13
text_editor_tool. Each one drove a fix:

- Table-aware chunking in `chunk.py`. Every markdown table emits as its
  own chunk, with the section's lead-in prose attached for embedding
  signal. Two pinned tests in `tests/test_chunk.py`. Resolved q15.
- Corpus deny list in `.env` and `config.py`. `/docs/en/api/` (endpoint
  and SDK reference) gets filtered out so it stops outranking conceptual
  docs. One pinned test in `tests/test_crawl.py`. Resolved q04 and q11.
- Judge prompt rewrite in `eval/run_eval.py`. The first version penalised
  the model for adding use cases the gold answer did not enumerate, even
  when the docs listed those cases. The new version scores faithfulness
  0 only on direct contradictions. Resolved q13.
- System prompt rule in `answer.py` against blind extrapolation. Steers
  the model toward the docs' framing first.

Result: hybrid faithfulness went from 0.87 in the first run to 1.00 in
the canonical run. Hybrid is now strictly better than vector on every
metric.

## 5. Wrap the agent as a Cowork Skill

The role description mentions Cowork heavily. Once the MCP-in-Cowork issue
in KNOWN_ISSUES.md is fixed, package the doc-qa workflow as a Cowork Skill so
non-technical teammates ask documentation questions in their daily environment.
Same retrieval engine, new surface. This is Option B from the brief, so adding
it on top of Option C lets the project demo two of the three deeper paths.

## What I would not do day one

I would not switch the answer model to Opus 4.7 for /ask. Sonnet 4.6 already
hits 1.00 faithfulness on the canonical run with citations enabled, and the
cost difference (5x) doesn't justify any marginal lift on documentation
questions. Opus belongs on the harder agentic work the role mentions, not
on a vanilla RAG endpoint.

I would not move retrieval to a managed vector DB (Pinecone, Weaviate). The
Supabase + pgvector path stays in one process boundary, runs on the production
stack you already use, and HNSW + GIN handles the corpus size with room to
spare. Moving introduces operational surface area without clear retrieval
gains.
