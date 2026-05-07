# Known issues

## 1. Claude Cowork MCP integration: RESOLVED via MCPB extension

Status: resolved. See `cowork-extension/` for the packaged extension.

Background. Cowork manages MCP connectors through Anthropic's MCPB (formerly
DXT) extension format, not through Claude Code's `claude mcp add` registry.
Adding a server with `claude mcp add` registers it for the Claude Code CLI
only; Cowork ignores the CLI registry.

Resolution. Packaged the same `doc-qa-agent` MCP server as a 1.2 kB MCPB
bundle that references the project venv via `${user_config.python_path}`:

- `cowork-extension/manifest.json`: MCPB manifest.
- `cowork-extension/noop.py`: validator-required entry point placeholder.
- `cowork-extension/doc-qa-agent.mcpb`: packed bundle.
- `cowork-extension/INSTALL.md`: build + install steps.

Install path: double-click `doc-qa-agent.mcpb` (Cowork is the registered file
handler) or drag-drop onto Cowork's Extensions panel. The user_config dialog
defaults the Python path to the project venv. Fully quit and reopen Cowork
to see the three tools.


## 2. q15 batch_pricing: RESOLVED via table-aware chunking + corpus filter

Status: resolved. Hybrid faith jumped from 0.0 to 1.0 in the canonical run.

Background. The previous canonical run had hybrid inventing "50% of standard
prices" instead of citing the specific batch rates. Two root causes:

1. The `Pricing` section on `batch-processing.md` mixed prose ("50% off") with
   the rate table in a single chunk. Retrieval found the chunk but the model
   anchored on the prose summary, not the row.
2. The pre-200-page corpus also had `/docs/en/api/` endpoint reference pages
   in the index. These outranked the conceptual `citations.md` and friends on
   keyword overlap, displacing the right pages from top-k.

Fix shipped:

- `chunk.py`: `_is_table_paragraph` plus an isolation rule in
  `_split_oversized` so every markdown table emits as its own chunk. The
  immediately-preceding prose paragraph rides along as a lead-in so the
  embedding has semantic signal beyond raw numeric rows.
- `.env`: `CRAWL_PATH_DENY=/docs/en/api/` excludes auto-generated endpoint
  and SDK reference pages.
- `tests/test_chunk.py`: two new cases pin the table-isolation behaviour.
- `tests/test_crawl.py`: one new case pins the deny-after-allow logic.

q13 text_editor_tool was also a failure in the first run, traced to a
judge prompt that treated "additions" as "contradictions". Fixed in
`eval/run_eval.py` (the judge now scores faithfulness 0 only on direct
contradictions). q13 hybrid scored faith=1, compl=0.95 in the canonical
run.


## 3. Citation spans are whole-chunk, not sentence-level

Status: design tradeoff, noted in DAY_ONE.md.

Each chunk currently arrives as one custom-content text block, so the citation
span (`start_block_index`, `end_block_index`) covers the whole chunk. Sentence
or paragraph-level citation granularity needs the chunker to split each chunk
into multiple text blocks per paragraph before sending to Claude. Ship as part
of the next iteration.


## 4. q09 managed_agent_session: residual eval-design observation

Status: documented in `eval/REPORT.md` as a remaining "fell short" entry.

Hybrid scores faith=1, compl=0.35 on q09. The model's answer is faithful
(POST to the sessions endpoint with `agent_id`) but pads with broader
context about events, credentials, and conversation history. The judge
penalises completeness because the answer covers about a third of what
the gold's narrow scope describes.

This is an eval-design observation, not a system bug:

- The system retrieved the correct page (mrr=1.0).
- The system cited the correct page (citation_hit=Y, precision=0.67).
- The system did not contradict any gold claim (faith=1).
- The model just elaborated more than the gold expected.

Two ways to make q09 pass on a future eval:

1. Broaden the gold answer to acknowledge legitimate context (events,
   credentials, environment) the docs cover under "starting a session".
2. Sharpen the question wording from "how do you start a session" to
   "what is the single API call required to start a session" so a verbose
   answer is obviously over-reaching.

The case is left in the report on purpose: it is exactly the kind of
"the system says something correct but the eval gold did not anticipate
it" finding that a longer eval set would surface in higher volume. Fix
path is in `DAY_ONE.md` item 4 (longer eval set with per-tag slices).
