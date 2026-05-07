"""Answer generation with Claude Messages API + built-in citations.

Each retrieved chunk becomes a custom-content document block, which gives us
chunk-level citation granularity: a citation's start_block_index/end_block_index
points back to the chunk we sent. Citations cannot be combined with Structured
Outputs on Claude, so the FastAPI response is shaped server-side after the call.

CLI:
    python -m doc_qa.answer "What does the citations API return?"
    python -m doc_qa.answer "Sonnet 4.6 pricing" --k 8 --mode hybrid
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Any

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from doc_qa.config import settings
from doc_qa.retrieve import RetrievedChunk, SearchMode, search

console = Console()


SYSTEM_PROMPT = """You are a documentation Q&A assistant for the Anthropic developer docs.

Rules:
- Use only the provided documents. Do not draw on outside knowledge.
- Cite the documents for every substantive claim. Cite the exact span you used.
- If the documents do not contain the answer, say so plainly. Do not guess.
- Prefer direct quotes for API names, model IDs, prices, and exact field names.
- When asked what a tool or feature does, name the fundamental capabilities
  the documents describe. Do not enumerate specific applications,
  sub-tasks, or use cases unless the documents themselves enumerate them.
- Keep answers concise. 2 to 5 sentences for most questions.""".strip()


@dataclass(slots=True)
class Citation:
    cited_text: str
    document_index: int
    document_title: str | None
    source_url: str
    heading: str | None
    start_block_index: int | None = None
    end_block_index: int | None = None


@dataclass(slots=True)
class AnswerResult:
    question: str
    answer: str
    citations: list[Citation]
    sources: list[dict[str, Any]]
    retrieved_chunks: list[RetrievedChunk]
    model: str
    usage: dict[str, int] = field(default_factory=dict)


def _document_block(chunk: RetrievedChunk) -> dict[str, Any]:
    """Wrap one chunk as a Claude custom-content document block."""
    title = chunk.source_title or "Documentation"
    if chunk.heading:
        title = f"{title}: {chunk.heading}"
    return {
        "type": "document",
        "source": {
            "type": "content",
            "content": [{"type": "text", "text": chunk.content}],
        },
        "title": title[:200],
        "context": f"URL: {chunk.source_url}",
        "citations": {"enabled": True},
    }


def _empty_corpus_response(question: str, model: str) -> AnswerResult:
    return AnswerResult(
        question=question,
        answer="No relevant content found in the indexed corpus for this question.",
        citations=[],
        sources=[],
        retrieved_chunks=[],
        model=model,
    )


def _parse_response(
    response: anthropic.types.Message,
    chunks: list[RetrievedChunk],
) -> tuple[str, list[Citation]]:
    answer_parts: list[str] = []
    citations: list[Citation] = []
    for block in response.content:
        if getattr(block, "type", None) != "text":
            continue
        answer_parts.append(block.text)
        for cite in (getattr(block, "citations", None) or []):
            doc_idx = getattr(cite, "document_index", -1)
            if not (0 <= doc_idx < len(chunks)):
                continue
            chunk = chunks[doc_idx]
            citations.append(
                Citation(
                    cited_text=getattr(cite, "cited_text", ""),
                    document_index=doc_idx,
                    document_title=getattr(cite, "document_title", None),
                    source_url=chunk.source_url,
                    heading=chunk.heading,
                    start_block_index=getattr(cite, "start_block_index", None),
                    end_block_index=getattr(cite, "end_block_index", None),
                )
            )
    return "".join(answer_parts).strip(), citations


def _unique_sources(citations: list[Citation], chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for c in citations:
        if c.source_url in seen:
            continue
        seen.add(c.source_url)
        chunk = chunks[c.document_index]
        out.append({"url": c.source_url, "title": chunk.source_title})
    return out


def answer(
    question: str,
    k: int = 5,
    candidates: int = 20,
    mode: SearchMode = "hybrid",
    model: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.0,
) -> AnswerResult:
    chosen_model = model or settings.answer_model
    chunks = search(question, k=k, mode=mode, candidates=candidates)
    if not chunks:
        return _empty_corpus_response(question, chosen_model)

    documents = [_document_block(c) for c in chunks]
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=chosen_model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    *documents,
                    {"type": "text", "text": question},
                ],
            }
        ],
    )

    answer_text, citations = _parse_response(response, chunks)
    sources = _unique_sources(citations, chunks)
    return AnswerResult(
        question=question,
        answer=answer_text,
        citations=citations,
        sources=sources,
        retrieved_chunks=chunks,
        model=response.model,
        usage={
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    )


# ---------- CLI ----------

def _print_result(result: AnswerResult) -> None:
    console.print(Panel(result.answer or "(empty answer)", title="Answer", border_style="green"))

    if result.citations:
        t = Table(title="Citations", show_lines=True, header_style="bold")
        t.add_column("#", justify="right", style="dim")
        t.add_column("source", overflow="fold")
        t.add_column("heading")
        t.add_column("cited span", overflow="fold")
        for i, c in enumerate(result.citations, start=1):
            span = c.cited_text.replace("\n", " ")
            if len(span) > 200:
                span = span[:200] + " ..."
            t.add_row(str(i), c.source_url, c.heading or "-", span)
        console.print(t)
    else:
        console.print("[yellow]no citations returned[/]")

    if result.sources:
        s = Table(title="Sources", show_header=True, header_style="bold")
        s.add_column("url", overflow="fold")
        s.add_column("title")
        for src in result.sources:
            s.add_row(src["url"], src.get("title") or "-")
        console.print(s)

    usage = result.usage or {}
    console.print(
        f"[dim]model={result.model}  input={usage.get('input_tokens', '-')}  "
        f"output={usage.get('output_tokens', '-')}  "
        f"retrieved={len(result.retrieved_chunks)}[/]"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the corpus a question via Claude.")
    parser.add_argument("question")
    parser.add_argument("--k", type=int, default=5, help="Final chunks sent to the model.")
    parser.add_argument("--candidates", type=int, default=20, help="Initial RRF pool size.")
    parser.add_argument("--mode", choices=("hybrid", "vector"), default="hybrid")
    parser.add_argument("--model", default=None, help="Override ANSWER_MODEL.")
    args = parser.parse_args()

    if not settings.anthropic_api_key:
        raise SystemExit("ANTHROPIC_API_KEY missing. Add it to .env.")

    result = answer(
        args.question,
        k=args.k,
        candidates=args.candidates,
        mode=args.mode,
        model=args.model,
    )
    _print_result(result)


if __name__ == "__main__":
    main()
