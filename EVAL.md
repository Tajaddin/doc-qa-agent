# Evaluation methodology

Owen flagged the evaluation as the highest-signal piece of the submission:

> "We care a lot about this. Anyone can wire up RAG, we want to see how you
> think about whether it actually works."

This file explains why the eval looks the way it does, what each metric
catches, and where the methodology has known holes. The latest run is
committed at `eval/REPORT.md`.

## What the eval covers

15 question / answer pairs in `eval/questions.yaml`. Each carries:

- `question`: the user query
- `gold_answer`: a short reference answer the LLM-as-judge step grades against
- `gold_source_urls`: canonical doc page(s) the answer should cite
- `tags`: difficulty and type labels (factual, procedural, comparison,
  edge-case, multi-source)

15 cases is small on purpose. Enough to catch architectural breakage, small
enough to run end-to-end in three minutes for under fifty cents. With more
time the set scales to 100-200 cases per the cookbook recommendation.

## Three metric families, three failure modes

### Retrieval metrics: did the right page reach the model?

| metric          | type     | catches                                              |
|-----------------|----------|------------------------------------------------------|
| **hit@k**       | binary   | retrieval misses outright. Top-k contains zero gold. |
| **recall@k**    | fraction | partial coverage on multi-source questions.          |
| **MRR**         | float    | ranking quality. Two systems both at hit@k=1.00 can  |
|                 |          | still differ on whether gold sits at position 1 vs 5.|

In the canonical run hybrid hit@k = 1.00 (every gold URL pulled into
top-5) and vector hit@k = 0.93 (one miss). MRR splits hybrid (0.92) from
vector (0.82). The retrieval gap is the RRF lift visible in numbers.

### Citation metrics: did Claude cite the right page?

| metric                  | type     | catches                                                |
|-------------------------|----------|--------------------------------------------------------|
| **citation_hit**        | binary   | Claude got the right chunks but cited something else.  |
| **citation_precision**  | fraction | over-citation: model cites every chunk, not the actual |
|                         |          | source it used.                                        |

Distinct from retrieval metrics because the model gets all top-k chunks but
might cite something else, or might not cite at all. A perfect retriever
paired with a hallucinating model would still fail citation_hit. In our run
hybrid hits citation_hit = 1.00 with citation precision 0.90, vs vector
at citation_hit = 0.93 and citation precision = 0.82.

### Answer quality (LLM-as-judge with Haiku 4.5)

| metric            | range    | catches                                          |
|-------------------|----------|--------------------------------------------------|
| **faithfulness**  | 0 or 1   | model answer directly contradicts the gold.      |
| **completeness**  | 0.0-1.0  | answer misses key points the gold answer makes.  |

Important distinction this iteration shipped: faithfulness scores
contradictions against the gold, NOT additions. A model answer that
covers everything in the gold AND adds further doc-supported facts is
faithful (1). Citation precision is the metric that catches grounding
problems separately, since cited URLs are checked against the gold's
canonical source list.

The judge is Haiku 4.5 because Anthropic recommends Haiku as the
fast, cost-effective starting point for grading-style work, and because
keeping the judge cheaper than the answer model lets the eval re-run on
every PR without bill anxiety.

The judge gets a strict JSON system prompt and the parsed JSON drives the
score. Parse failures degrade gracefully to faithfulness=0, completeness=0
with the raw judge text in the `reasoning` field, so reviewers see why a
parse broke.

## Why hybrid mode AND vector mode

Eval runs the same 15 cases twice, once with hybrid retrieval (BM25 FTS +
HNSW vector + RRF) and once with pure vector. Side-by-side numbers expose
where each approach fails. Anyone can wire up hybrid; the value is showing
where it does and does not help.

In the canonical run, hybrid wins on every metric we track and hits
faithfulness 1.00 across all 15 questions. The current numbers are the
output of three eval-driven iterations:

- Table-aware chunking in `chunk.py` so a pricing table emits as its own
  chunk with the lead-in prose attached for embedding signal. Resolved
  q15 batch_pricing, which used to fail on both modes.
- A `CRAWL_PATH_DENY=/docs/en/api/` filter so auto-generated endpoint
  reference pages stop outranking conceptual docs on keyword overlap.
  Resolved q04 (citations + Structured Outputs compatibility) and q11
  (search vs web citation types).
- Judge prompt rewrite. The first version penalised the model for adding
  use cases the gold answer did not enumerate, even when the docs listed
  those use cases. The new version scores faithfulness 0 only on direct
  contradictions, and treats supported additions as faithful. Resolved
  q13 text_editor_tool.

One residual observation in the report: q09 managed_agent_session scores
hybrid faith=1, compl=0.35. The model's answer is faithful (POST to
sessions endpoint with agent_id) but pads with broader context the
narrow gold does not anticipate. The fix is an eval-design choice, not a
system change: either broaden the gold to acknowledge legitimate context
or sharpen the question wording so verbose answers obviously over-reach.
Both are easy and would be the first move on a longer eval pass.

The next iteration (see `DAY_ONE.md`) adds a reranker between RRF and
the LLM and contextual retrieval at ingest. Both would push hit@k closer
to 1.00 on harder corpora and reduce the few remaining cases where the
model picks a less-precise chunk.

## Failure analysis methodology

`run_eval.py` writes a "Where the system fell short" subsection per mode.
A case lands in the subsection if it fails ANY of:

- `hit@k = False`
- `judge_faithfulness = 0`
- `judge_completeness < 0.5`

Each failure entry shows top retrieved URLs, gold URLs, the model answer
truncated to 300 chars, and the judge's one-sentence reasoning. A reviewer
scans the report and reads diagnoses without re-running anything. The
canonical run shows one residual finding, q09 managed_agent_session,
diagnosed in `KNOWN_ISSUES.md` and tracked as future work in `DAY_ONE.md`.

## Reproducibility

```
.venv\Scripts\python.exe -m eval.run_eval
.venv\Scripts\python.exe -m eval.run_eval --modes hybrid
.venv\Scripts\python.exe -m eval.run_eval --filter q01
```

Each run writes both `eval/reports/eval_<UTC ts>.md` and
`eval/reports/eval_<UTC ts>.json`. The JSON dump carries every per-case
field for downstream analysis (per-tag breakdowns, judge-vs-judge agreement,
etc).

## Known limitations of the methodology

Five caveats. Honesty about eval limits is the point of the eval.

1. **15 cases is small.** Confidence intervals on each metric are wide.
   Next iteration scales to 100-200 cases plus per-tag breakdowns.

2. **Single judge model, no inter-rater reliability.** Haiku might disagree
   with itself on borderline cases. A real eval would double-judge or use
   a panel (Haiku + Sonnet + human spot-check).

3. **Gold answers are author-written, not user-sourced.** Real user
   questions have noisier wording. Next iteration adds 5-10 questions from
   real Anthropic forum posts or GitHub issues.

4. **No per-tag breakdown in the report aggregator yet.** Questions carry
   tags (factual, procedural, comparison, etc) but the markdown report does
   not slice by tag. The JSON dump has the data; the slicing is one helper
   function away.

5. **Citation granularity is whole-chunk.** Citation precision counts
   URL-level matches, not span-level. Sentence-level citation alignment
   needs the chunker to split chunks into multiple text blocks per
   paragraph (tracked in `KNOWN_ISSUES.md`).
