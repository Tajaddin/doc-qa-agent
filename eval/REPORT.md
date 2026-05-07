# Evaluation report

- Run timestamp (UTC): `20260507_073839Z`
- k = 5
- Answer model: `claude-sonnet-4-6`
- Judge model: `claude-haiku-4-5`
- Embedding provider: `voyage`

## Summary

| mode | n | hit@k | recall@k | MRR | cit_hit | cit_prec | faith | compl | lat_med |
|------|---:|------:|---------:|----:|--------:|---------:|------:|------:|--------:|
| hybrid | 15 | 1.00 | 1.00 | 0.922 | 1.00 | 0.90 | 1.00 | 0.90 | 3.78s |
| vector | 15 | 0.93 | 0.93 | 0.817 | 0.93 | 0.82 | 0.87 | 0.80 | 4.06s |

## hybrid mode, per-case detail

| id | hit | recall | mrr | cit | faith | compl | lat |
|----|----:|-------:|----:|----:|------:|------:|----:|
| q01_voyage_dim | Y | 1.00 | 1.000 | Y | 1 | 1.00 | 4.94s |
| q02_cache_breakpoints | Y | 1.00 | 1.000 | Y | 1 | 1.00 | 2.20s |
| q03_citations_enable | Y | 1.00 | 0.333 | Y | 1 | 0.85 | 3.78s |
| q04_citations_structured_outputs | Y | 1.00 | 1.000 | Y | 1 | 0.95 | 2.89s |
| q05_custom_content_citation_type | Y | 1.00 | 1.000 | Y | 1 | 1.00 | 3.31s |
| q06_lookback_window | Y | 1.00 | 1.000 | Y | 1 | 1.00 | 2.64s |
| q07_compaction_caching | Y | 1.00 | 1.000 | Y | 1 | 0.85 | 3.52s |
| q08_voyage_context | Y | 1.00 | 1.000 | Y | 1 | 1.00 | 2.44s |
| q09_managed_agent_session | Y | 1.00 | 1.000 | Y | 1 | 0.35 | 5.17s |
| q10_agent_skills | Y | 1.00 | 1.000 | Y | 1 | 0.95 | 4.61s |
| q11_search_vs_web_citations | Y | 1.00 | 1.000 | Y | 1 | 0.95 | 11.08s |
| q12_adaptive_thinking_caching | Y | 1.00 | 0.500 | Y | 1 | 0.85 | 3.42s |
| q13_text_editor_tool | Y | 1.00 | 1.000 | Y | 1 | 0.95 | 7.08s |
| q14_bash_tool | Y | 1.00 | 1.000 | Y | 1 | 0.85 | 5.76s |
| q15_batch_pricing | Y | 1.00 | 1.000 | Y | 1 | 0.95 | 4.39s |

### Where the system fell short (1 cases)

#### q09_managed_agent_session: How do you start a session with a Managed Agent?

- gold URLs: https://platform.claude.com/docs/en/managed-agents/sessions.md
- retrieval: hit=Y recall=1.00 mrr=1.000
- citation: hit=Y precision=0.67
- judge: faithfulness=1 completeness=0.35
- judge note: The model answer does not contradict the gold answer's core instruction (POST to sessions endpoint with agent_id), but it provides extensive additional context about sessions, events, and credentials rather than directly answering the specific question about how to start a session, covering only a portion of what would constitute a complete answer to the narrowly-scoped question.
- top retrieved: ['https://platform.claude.com/docs/en/managed-agents/sessions.md', 'https://platform.claude.com/docs/en/managed-agents/sessions.md', 'https://platform.claude.com/docs/en/managed-agents/quickstart.md']
- model answer: Based on the documentation, here's how to start a session with a Managed Agent:

**1. Create the Session**

A session is a running agent instance within an environment. Each session references an agent and an environment (both created separately), and maintains conversation history across multiple i...

## vector mode, per-case detail

| id | hit | recall | mrr | cit | faith | compl | lat |
|----|----:|-------:|----:|----:|------:|------:|----:|
| q01_voyage_dim | N | 0.00 | 0.000 | N | 0 | 0.00 | 3.22s |
| q02_cache_breakpoints | Y | 1.00 | 1.000 | Y | 1 | 1.00 | 2.12s |
| q03_citations_enable | Y | 1.00 | 0.500 | Y | 1 | 0.85 | 3.26s |
| q04_citations_structured_outputs | Y | 1.00 | 1.000 | Y | 1 | 0.95 | 2.72s |
| q05_custom_content_citation_type | Y | 1.00 | 1.000 | Y | 1 | 1.00 | 3.56s |
| q06_lookback_window | Y | 1.00 | 1.000 | Y | 1 | 1.00 | 2.34s |
| q07_compaction_caching | Y | 1.00 | 1.000 | Y | 1 | 0.85 | 4.06s |
| q08_voyage_context | Y | 1.00 | 1.000 | Y | 1 | 1.00 | 2.00s |
| q09_managed_agent_session | Y | 1.00 | 1.000 | Y | 1 | 0.85 | 9.45s |
| q10_agent_skills | Y | 1.00 | 0.250 | Y | 1 | 0.85 | 4.52s |
| q11_search_vs_web_citations | Y | 1.00 | 1.000 | Y | 1 | 0.95 | 9.19s |
| q12_adaptive_thinking_caching | Y | 1.00 | 1.000 | Y | 1 | 0.85 | 4.26s |
| q13_text_editor_tool | Y | 1.00 | 1.000 | Y | 1 | 0.75 | 4.88s |
| q14_bash_tool | Y | 1.00 | 1.000 | Y | 1 | 0.85 | 6.14s |
| q15_batch_pricing | Y | 1.00 | 0.500 | Y | 0 | 0.30 | 4.44s |

### Where the system fell short (2 cases)

#### q01_voyage_dim: What is the default embedding dimension for voyage-3-large?

- gold URLs: https://platform.claude.com/docs/en/build-with-claude/embeddings.md
- retrieval: hit=N recall=0.00 mrr=0.000
- citation: hit=N precision=0.00
- judge: faithfulness=0 completeness=0.00
- judge note: The model answer claims the information is not available in the documentation, directly contradicting the gold answer of 1024, which indicates the information should be present in the provided documentation.
- top retrieved: ['https://platform.claude.com/docs/en/build-with-claude/skills-guide.md', 'https://platform.claude.com/docs/en/build-with-claude/prompt-caching.md', 'https://platform.claude.com/docs/en/build-with-claude/pdf-support.md']
- model answer: The documents provided don't contain any information about Voyage embeddings or their embedding dimensions. This question cannot be answered based on the available documentation.

For accurate information about `voyage-3-large` embedding dimensions, I'd recommend checking the [Voyage AI documentatio...

#### q15_batch_pricing: What pricing applies to batch processing requests in Claude?

- gold URLs: https://platform.claude.com/docs/en/build-with-claude/batch-processing.md
- retrieval: hit=Y recall=1.00 mrr=0.500
- citation: hit=Y precision=0.25
- judge: faithfulness=0 completeness=0.30
- judge note: The model answer contradicts the gold answer by claiming batch pricing is 50% of standard rates and providing different prices for Claude Opus (e.g., $7.50/$37.50 vs. the gold's $2.50/$12.50), while only partially addressing the core concept that batch processing has lower pricing.
- top retrieved: ['https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool.md', 'https://platform.claude.com/docs/en/build-with-claude/batch-processing.md', 'https://platform.claude.com/docs/en/build-with-claude/batch-processing.md']
- model answer: The Batches API offers significant cost savings — all usage is charged at **50% of the standard API prices**. For example, some key batch pricing rates are:

- **Claude Sonnet 4.5/4/3.7**: $1.50 / MTok (input), $7.50 / MTok (output)
- **Claude Haiku 3.5**: $0.40 / MTok (input), $2.00 / MTok (output)...
