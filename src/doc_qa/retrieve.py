"""Retrieval API. Thin Python wrapper around the hybrid_search() and vector_search() SQL functions.

Decoupling retrieval from the answer step lets the FastAPI `/search` endpoint
return raw results without a model call, and lets the eval harness ablate
hybrid vs. vector-only without touching answer code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

import numpy as np

from doc_qa.db import get_conn
from doc_qa.embeddings import EmbeddingClient, get_embedding_client

SearchMode = Literal["hybrid", "vector"]

# Most chunks any caller (HTTP or MCP) may pull into one search or answer.
MAX_K = 20


@dataclass(slots=True)
class RetrievedChunk:
    chunk_id: int
    source_id: int
    chunk_index: int
    heading: str | None
    content: str
    source_url: str
    source_title: str | None
    score: float
    fts_rank: int | None = None
    semantic_rank: int | None = None
    metadata: dict = field(default_factory=dict)


@lru_cache(maxsize=1)
def _client() -> EmbeddingClient:
    return get_embedding_client()


def embed_query(query: str) -> np.ndarray:
    vec = _client().embed([query], input_type="query")[0]
    return np.array(vec, dtype=np.float32)


def hybrid_search(query: str, k: int = 5, candidates: int = 20) -> list[RetrievedChunk]:
    """Run RRF over FTS and vector search, return top-k. `candidates` controls the
    initial pool the SQL function pulls from each side before fusion.
    """
    qvec = embed_query(query)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select * from hybrid_search(%s, %s::vector(1024), %s::int)",
                (query, qvec, candidates),
            )
            rows = cur.fetchall()
    return [
        RetrievedChunk(
            chunk_id=r[0],
            source_id=r[1],
            chunk_index=r[2],
            heading=r[3],
            content=r[4],
            metadata=r[5] or {},
            source_url=r[6],
            source_title=r[7],
            fts_rank=r[8],
            semantic_rank=r[9],
            score=float(r[10]),
        )
        for r in rows[:k]
    ]


def vector_search(query: str, k: int = 5) -> list[RetrievedChunk]:
    qvec = embed_query(query)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select * from vector_search(%s::vector(1024), %s::int)",
                (qvec, k),
            )
            rows = cur.fetchall()
    return [
        RetrievedChunk(
            chunk_id=r[0],
            source_id=r[1],
            chunk_index=r[2],
            heading=r[3],
            content=r[4],
            metadata=r[5] or {},
            source_url=r[6],
            source_title=r[7],
            score=-float(r[8]),
            semantic_rank=i + 1,
        )
        for i, r in enumerate(rows)
    ]


def search(query: str, k: int = 5, mode: SearchMode = "hybrid", candidates: int = 20) -> list[RetrievedChunk]:
    if mode == "hybrid":
        return hybrid_search(query, k=k, candidates=candidates)
    return vector_search(query, k=k)
