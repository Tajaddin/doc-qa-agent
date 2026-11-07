"""MCP server exposing the doc-qa retrieval engine to Claude clients.

Three tools are registered:

  search_docs   Hybrid (FTS + vector via RRF) or pure vector retrieval. Returns the
                top-k matching chunks with content, URL, heading, and rank info.
  ask_docs      Full RAG pipeline. Sends retrieved chunks to Claude with built-in
                citations enabled, returns the grounded answer plus citation list.
  list_sources  Inventory of indexed pages by chunk count.

Transport is stdio, the default Claude Desktop and Claude Code expect.

Run for manual testing through the MCP inspector:
    mcp dev src\\doc_qa\\mcp_server.py

Run as the configured server (Claude Desktop launches the server the same way):
    python -m doc_qa.mcp_server

Note on annotations: `from __future__ import annotations` is intentionally NOT used here.
FastMCP's StrictJsonSchema generator resolves Pydantic field types eagerly at tool
registration time, and forward-string references to nested models (AskCitation inside
AskAnswer) trigger PydanticUserError unless model_rebuild() is called. Eager evaluation
is simpler than wiring rebuilds for every model.
"""

from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from doc_qa.answer import answer as answer_question
from doc_qa.db import get_conn
from doc_qa.retrieve import MAX_K, search

mcp = FastMCP("doc-qa-agent")

MAX_SOURCES = 200


def _clamp(value: int, high: int) -> int:
    return max(1, min(value, high))


# ---------- output schemas ----------

class SearchHit(BaseModel):
    chunk_id: int
    source_url: str
    source_title: str | None
    heading: str | None
    score: float
    fts_rank: int | None = None
    semantic_rank: int | None = None
    content: str


class AskCitation(BaseModel):
    cited_text: str
    source_url: str
    heading: str | None
    document_title: str | None


class AskSource(BaseModel):
    url: str
    title: str | None


class AskAnswer(BaseModel):
    answer: str
    citations: list[AskCitation]
    sources: list[AskSource]
    retrieved_chunk_ids: list[int]
    model: str
    input_tokens: int
    output_tokens: int


class SourceRow(BaseModel):
    url: str
    title: str | None
    chunks: int


# ---------- tools ----------

@mcp.tool()
def search_docs(
    query: str,
    k: int = 5,
    mode: Literal["hybrid", "vector"] = "hybrid",
) -> list[SearchHit]:
    """Search the indexed documentation for passages matching the query.

    Returns the top-k matching chunks with their full content and source URL.
    Mode "hybrid" combines BM25-style full-text search with vector similarity via
    reciprocal rank fusion. Mode "vector" runs pure semantic search.

    Use this when you want raw passages without an LLM-generated answer.
    k is capped at 20.
    """
    chunks = search(query, k=_clamp(k, MAX_K), mode=mode)
    return [
        SearchHit(
            chunk_id=c.chunk_id,
            source_url=c.source_url,
            source_title=c.source_title,
            heading=c.heading,
            score=c.score,
            fts_rank=c.fts_rank,
            semantic_rank=c.semantic_rank,
            content=c.content,
        )
        for c in chunks
    ]


@mcp.tool()
def ask_docs(question: str, k: int = 5) -> AskAnswer:
    """Answer a natural-language question against the indexed documentation.

    Runs hybrid retrieval, sends the top-k chunks to Claude as document blocks
    with built-in citations enabled, and returns the grounded answer plus a
    structured citation list mapped back to source URLs.

    Use this when you want a concise answer with provenance, not raw chunks.
    k is capped at 20.
    """
    result = answer_question(question, k=_clamp(k, MAX_K), mode="hybrid")
    return AskAnswer(
        answer=result.answer,
        citations=[
            AskCitation(
                cited_text=c.cited_text,
                source_url=c.source_url,
                heading=c.heading,
                document_title=c.document_title,
            )
            for c in result.citations
        ],
        sources=[AskSource(url=s["url"], title=s.get("title")) for s in result.sources],
        retrieved_chunk_ids=[c.chunk_id for c in result.retrieved_chunks],
        model=result.model,
        input_tokens=result.usage.get("input_tokens", 0),
        output_tokens=result.usage.get("output_tokens", 0),
    )


@mcp.tool()
def list_sources(limit: int = 20) -> list[SourceRow]:
    """List indexed source pages ordered by chunk count, descending.

    Use this to inspect what documentation is in the corpus before searching.
    limit is capped at 200.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select s.source_url, s.title, "
                "(select count(*) from chunks where source_id = s.id) as nchunks "
                "from sources s order by nchunks desc limit %s",
                (_clamp(limit, MAX_SOURCES),),
            )
            rows = cur.fetchall()
    return [SourceRow(url=r[0], title=r[1], chunks=r[2]) for r in rows]


# ---------- entry point ----------

def main() -> None:
    """Run the server over stdio. Default transport for Claude Desktop / Claude Code."""
    mcp.run()


if __name__ == "__main__":
    main()
