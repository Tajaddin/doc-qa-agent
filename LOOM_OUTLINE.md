# Loom outline

Target length: 7 minutes. Trim aggressively if the run goes over 8.

Watch out for: long pauses while a window loads, reading prompts off screen
instead of speaking them. Pre-position every window before recording.

## 0:00 to 0:30, intro and framing

Speak (don't read):

> Hi Owen, I'm Tajaddin. The brief asked for a doc-QA agent over a public docs
> site, with grounded citations, FastAPI exposure, an evaluation, and one
> deeper path. I picked Option C, an MCP server, and used the Anthropic
> developer docs as the corpus because the role lives in that ecosystem. Here
> is what I built and what the eval found.

## 0:30 to 1:30, architecture in one slide

Open `README.md` and show the architecture section. Talk through the flow.

Three points to land:

- Used Mintlify's `llms.txt` manifest plus `.md` URLs instead of HTML scraping.
  The docs site is JS-rendered and the markdown endpoints are stable.
- Each chunk goes to Claude as a custom-content document block with
  `citations.enabled=true`. That gives chunk-level citation granularity,
  the start/end block index points back to the chunk we sent.
- Hybrid retrieval is RRF fusion of FTS (GIN over `tsvector`) and HNSW vector
  search. Same SQL function the eval ablation calls.

## 1:30 to 3:30, FastAPI /ask demo

Pre-position:

- PowerShell A: server already running on `:8000`.
- PowerShell B: cd to repo, ready to type `python -m scripts.test_ask "..."`.

Run two questions back to back. Read the answer. Point at the citations
table: each row has a `cited_text` span, a `source_url`, and the heading the
chunk came from. Click one URL to confirm the page is real.

Suggested questions:

1. "What does Claude's citations API return? List the fields."
2. "How does prompt caching work in Claude?"

The first answer cites two pages (citations.md, search-results.md). Use that
to point out the model picked across pages on its own.

## 3:30 to 5:00, MCP server demo: two clients, one server

The MCP segment shows the same retrieval engine answering through two
different Claude clients. Strongest signal in the whole demo because the role
description names both Claude Code AND Cowork as primary surfaces.

Pre-position before recording:

- PowerShell C: cd to repo, type `claude` and Enter so the session is loaded.
- Cowork: open the app, start a fresh chat, do not pre-type anything.

### Step 1, Claude Code CLI (3:30 to 4:15)

Inside the Claude Code session, type:

> Use the doc-qa-agent search_docs tool to find documentation about citations.

Claude Code shows the tool call, the JSON response from `search_docs`, then
a grounded summary. Point at the URLs in the response.

### Step 2, Claude Cowork (4:15 to 5:00)

Switch to Cowork. In the fresh chat, type:

> Use the Doc QA Agent search_docs tool to find documentation about prompt
> caching breakpoints.

Cowork invokes the tool through the MCPB extension you installed earlier.
Show Settings, Extensions, "Doc QA Agent" listed and enabled.

Mention out loud: "Same MCP server, two different clients. Claude Code
reaches the server through its project-scoped CLI registry. Cowork reaches
the server through the MCPB extension I packaged at
`cowork-extension/doc-qa-agent.mcpb`. One retrieval engine, three surfaces if
you count the FastAPI route from earlier."

## 5:00 to 6:15, the eval, the part Owen flagged hardest

Open `eval/REPORT.md` (the canonical run, committed in-repo). Re-runs land in `eval/reports/` which is gitignored.

Read the summary table. Three stats to land:

- Hybrid hits faithfulness 1.00 across all 15 questions. Every answer is
  consistent with the gold, no contradictions.
- Hybrid wins on every metric: MRR 0.92 vs 0.82, faith 1.00 vs 0.87,
  completeness 0.90 vs 0.80, citation precision 0.90 vs 0.82.
- The current numbers are the output of three eval-driven iterations: the
  first run flagged q15 batch_pricing as a failure on both modes, the
  second run flagged q13 text_editor_tool, and each round drove a real
  fix (table-aware chunking, an /api/ deny filter, and a judge prompt
  rewrite for the additions-vs-contradictions distinction). The eval did
  what Owen asked of it: it told us where the system breaks, and we
  shipped the fixes.

Scroll to "Where the system fell short". Read this line out loud first:

> I left this failure visible on purpose. The eval is supposed to tell us
> where the system breaks. Hiding a known failure would defeat the point.

Then walk through the remaining residual finding (q09):

- q09 managed_agent_session. Hybrid scores faith=1, compl=0.35. The
  model's answer is faithful (POST to sessions endpoint with agent_id)
  but pads with broader context the gold did not anticipate.
- Diagnosis: eval-design observation, not a system bug. The fix is to
  broaden the gold or tighten the question wording. Both noted in
  EVAL.md.

Mention the iteration story:

> The first canonical run had two failures: q15 batch_pricing and q13
> text_editor_tool. Each one drove a real fix. q15 needed table-aware
> chunking plus a deny filter for /docs/en/api/. q13 turned out to be a
> judge prompt issue: my first version penalised the model for adding
> use cases the gold did not enumerate, even when the docs listed those
> cases. The new version scores faithfulness 0 only on direct
> contradictions. Hybrid faithfulness went from 0.87 to 1.00 across the
> three iterations.

Closing line for the eval section, ties straight into day-one:

> Day-one would be a reranker between RRF and the model, contextual
> retrieval per Anthropic's blog, and a longer eval set with per-tag
> breakdowns. All in DAY_ONE.md.

## 6:15 to 6:50, day one of the job

Open `DAY_ONE.md`. Pick three to mention out loud, in this order:

1. Add a reranker between RRF and the LLM. Voyage rerank-2.5-lite or
   Haiku-as-reranker per the cookbook.
2. Contextual Retrieval (Anthropic's blog reports 49 to 67 percent reduction
   in failed retrievals).
3. Stream /ask with SSE so the answer renders as it arrives.

Mention briefly that I would not move to Pinecone, the Supabase + pgvector
path is the production stack listed in the JD already.

## 6:50 to 7:15, wrap

> Repo is github.com/Tajaddin/doc-qa-agent, README has setup, the eval report
> is at `eval/REPORT.md`. KNOWN_ISSUES.md tracks the Cowork integration item I
> deferred. Happy to dig into anything you want to go deeper on. Thanks.

## What NOT to say

Five phrases to avoid because they undercut signal:

- "Quick demo" or "just a quick demo". Owen knows the demo is short; the
  qualifier reads as low-confidence.
- "Hopefully this works". Pre-test before recording. Either it works or you
  cut and re-record.
- "I didn't have time to...". The brief named 4-6 hours. Naming what you
  cut INTO the brief is fine; naming what you "didn't have time for" reads
  as missing the spec.
- "This is just a toy / hack". Owen explicitly wants signal, not polish.
  Calling your work a toy disrespects the signal.
- "I think this works". Either run it, or cut. No guesses on tape.

## Fallback if a tool call hangs during recording

If `/ask` or the MCP tool call stalls during the live demo:

1. Pause for max five seconds. Most calls finish under four.
2. If still hanging, switch to the prebuilt result. Open
   `eval/REPORT.md` and read one of the 1.00-faithfulness rows out loud.
   Phrasing: "While that runs, here is what the same question scored on the
   eval, judged by Haiku 4.5."
3. After the recording, retake the section if cleanly recoverable.

The fallback turns a hiccup into another data point about the eval, which is
the part Owen flagged hardest. Net positive.

## Pre-record checklist

- [ ] `python -m scripts.peek_db` shows 99 sources, 2633 chunks, 2633 with
      embeddings. If not, run `python -m doc_qa.embeddings`.
- [ ] `python -m pytest tests/ -v` shows 32 / 32 passing.
- [ ] FastAPI server running on port 8000. Curl `/healthz` and confirm
      200 with the X-Request-ID header.
- [ ] Claude Code session in repo dir, ready to accept prompts.
- [ ] Cowork open, fresh chat, doc-qa-agent extension enabled in Settings.
- [ ] Latest eval report visible on disk at `eval/REPORT.md`.
- [ ] Browser tab open to the GitHub repo.
- [ ] Notifications silenced (Windows Focus Assist on Priority Only).
- [ ] One bottle of water.
