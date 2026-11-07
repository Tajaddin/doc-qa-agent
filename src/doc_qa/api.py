"""FastAPI app exposing /healthz, /search, /ask.

/search runs hybrid or vector retrieval and returns chunks with FTS rank,
semantic rank, and the fused RRF score. Useful for retrieval ablations and
the Loom comparison demo. No model call.

/ask runs retrieval, sends the chunks to Claude with built-in citations,
and returns the answer text plus structured citations mapped back to source
URLs. Citations and Structured Outputs are mutually exclusive on the
Messages API, so the response shape is assembled in Python after the model
call rather than asked from Claude as JSON.

Production touches:
- request-id middleware that tags every request with a 12-char id and
  echoes it back via the X-Request-ID response header.
- AppError exception hierarchy with structured 4xx/5xx JSON responses.
- Standard Python logging so errors surface in stderr without leaking
  secrets.
- Pydantic v2 schemas with Field constraints on every input.

Run:
    uvicorn doc_qa.api:app --reload --host 127.0.0.1 --port 8000
or:
    python -m doc_qa.api
"""

from __future__ import annotations

import logging
import uuid

import anthropic
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from doc_qa.answer import AnswerResult
from doc_qa.answer import answer as answer_question
from doc_qa.config import settings
from doc_qa.db import get_conn
from doc_qa.retrieve import MAX_K, RetrievedChunk, SearchMode, search

logger = logging.getLogger("doc_qa.api")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ---------- exceptions ----------

class AppError(Exception):
    """Base class for app-level errors that map to JSON responses."""

    status_code = 500
    code = "internal_error"


class ConfigError(AppError):
    status_code = 500
    code = "config_invalid"


class RetrievalError(AppError):
    status_code = 503
    code = "retrieval_unavailable"


class AnswerError(AppError):
    status_code = 502
    code = "answer_failed"


class ModelNotAllowedError(AppError):
    status_code = 400
    code = "model_not_allowed"


# ---------- schemas ----------

class HealthResponse(BaseModel):
    status: str
    sources: int
    chunks: int
    chunks_with_embeddings: int
    embedding_provider: str
    answer_model: str


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=MAX_K)
    mode: SearchMode = "hybrid"
    candidates: int = Field(default=20, ge=1, le=50)


class SearchHit(BaseModel):
    chunk_id: int
    source_url: str
    source_title: str | None
    heading: str | None
    score: float
    fts_rank: int | None = None
    semantic_rank: int | None = None
    preview: str


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode
    results: list[SearchHit]


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=MAX_K)
    mode: SearchMode = "hybrid"
    candidates: int = Field(default=20, ge=1, le=50)
    model: str | None = None


class CitationOut(BaseModel):
    cited_text: str
    source_url: str
    heading: str | None
    document_title: str | None
    start_block_index: int | None = None
    end_block_index: int | None = None


class SourceOut(BaseModel):
    url: str
    title: str | None


class AskResponse(BaseModel):
    question: str
    answer: str
    citations: list[CitationOut]
    sources: list[SourceOut]
    retrieved_chunk_ids: list[int]
    model: str
    usage: dict[str, int]
    request_id: str


# ---------- helpers ----------

def _hit_from_chunk(c: RetrievedChunk) -> SearchHit:
    preview = c.content.replace("\n", " ")
    if len(preview) > 280:
        preview = preview[:280] + " ..."
    return SearchHit(
        chunk_id=c.chunk_id,
        source_url=c.source_url,
        source_title=c.source_title,
        heading=c.heading,
        score=c.score,
        fts_rank=c.fts_rank,
        semantic_rank=c.semantic_rank,
        preview=preview,
    )


# ---------- app + middleware + exception handlers ----------

app = FastAPI(
    title="doc-qa-agent",
    version="0.1.0",
    description="Documentation Q&A over Anthropic docs with hybrid retrieval and Claude citations.",
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Tag every request with a short id. Helps cross-reference logs and responses."""
    request.state.request_id = uuid.uuid4().hex[:12]
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "unhandled exception", extra={"request_id": request.state.request_id}
        )
        raise
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    rid = getattr(request.state, "request_id", None)
    logger.warning(
        "%s: %s", exc.code, exc, extra={"request_id": rid}
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.code,
            "detail": str(exc),
            "request_id": rid,
        },
    )


# ---------- routes ----------

@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) from sources")
                n_sources = cur.fetchone()[0]
                cur.execute("select count(*) from chunks")
                n_chunks = cur.fetchone()[0]
                cur.execute("select count(*) from chunks where embedding is not null")
                n_embedded = cur.fetchone()[0]
    except Exception as e:
        raise RetrievalError(f"database unreachable: {e}") from e

    return HealthResponse(
        status="ok",
        sources=n_sources,
        chunks=n_chunks,
        chunks_with_embeddings=n_embedded,
        embedding_provider=settings.embedding_provider,
        answer_model=settings.answer_model,
    )


@app.post("/search", response_model=SearchResponse)
def search_route(req: SearchRequest) -> SearchResponse:
    try:
        chunks = search(req.query, k=req.k, mode=req.mode, candidates=req.candidates)
    except Exception as e:
        raise RetrievalError(f"search failed: {e}") from e
    return SearchResponse(
        query=req.query,
        mode=req.mode,
        results=[_hit_from_chunk(c) for c in chunks],
    )


@app.post("/ask", response_model=AskResponse)
def ask_route(req: AskRequest, request: Request) -> AskResponse:
    if req.model is not None and req.model not in settings.allowed_model_ids:
        raise ModelNotAllowedError(
            f"model {req.model!r} is not allowed; set ALLOWED_MODELS to permit it"
        )
    if not settings.anthropic_api_key:
        raise ConfigError("ANTHROPIC_API_KEY not set")

    try:
        result: AnswerResult = answer_question(
            req.question,
            k=req.k,
            candidates=req.candidates,
            mode=req.mode,
            model=req.model,
        )
    except anthropic.AnthropicError as e:
        raise AnswerError(f"Anthropic call failed: {e}") from e
    except Exception as e:
        raise RetrievalError(f"answer pipeline failed: {e}") from e

    rid = getattr(request.state, "request_id", "unknown")
    logger.info(
        "ask ok q_len=%d k=%d mode=%s in=%d out=%d cites=%d",
        len(req.question),
        req.k,
        req.mode,
        result.usage.get("input_tokens", 0),
        result.usage.get("output_tokens", 0),
        len(result.citations),
        extra={"request_id": rid},
    )

    return AskResponse(
        question=req.question,
        answer=result.answer,
        citations=[
            CitationOut(
                cited_text=c.cited_text,
                source_url=c.source_url,
                heading=c.heading,
                document_title=c.document_title,
                start_block_index=c.start_block_index,
                end_block_index=c.end_block_index,
            )
            for c in result.citations
        ],
        sources=[SourceOut(url=s["url"], title=s.get("title")) for s in result.sources],
        retrieved_chunk_ids=[c.chunk_id for c in result.retrieved_chunks],
        model=result.model,
        usage=result.usage,
        request_id=rid,
    )


def main() -> None:
    import uvicorn

    uvicorn.run("doc_qa.api:app", host=settings.api_host, port=settings.api_port, reload=False)


if __name__ == "__main__":
    main()
