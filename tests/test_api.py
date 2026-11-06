"""Integration tests for the FastAPI app.

Uses FastAPI's TestClient. DB and embedding calls are monkeypatched to
hard-coded values so these tests run anywhere, including CI without a
.env file. Coverage:

- /healthz routing, mock DB query path, X-Request-ID middleware, response shape
- /search input validation (empty query, k upper bound)
- /search route with mocked retrieve.search
- /ask returns the AppError JSON envelope when ANTHROPIC_API_KEY is empty
- /ask input validation (empty question)
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from doc_qa.answer import AnswerResult
from doc_qa.api import app
from doc_qa.config import settings
from doc_qa.retrieve import RetrievedChunk


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def mock_db(monkeypatch):
    """Patch doc_qa.api.get_conn so /healthz returns fixed counts."""
    fake_cursor = MagicMock()
    fake_cursor.fetchone.side_effect = [
        (80,),     # select count(*) from sources
        (2193,),   # select count(*) from chunks
        (2193,),   # select count(*) from chunks where embedding is not null
    ]
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor

    @contextmanager
    def fake_get_conn():
        yield fake_conn

    monkeypatch.setattr("doc_qa.api.get_conn", fake_get_conn)
    return fake_cursor


def test_healthz_returns_ok_with_request_id(client, mock_db):
    r = client.get("/healthz")
    assert r.status_code == 200

    headers = {k.lower(): v for k, v in r.headers.items()}
    assert "x-request-id" in headers
    assert len(headers["x-request-id"]) == 12

    body = r.json()
    assert body["status"] == "ok"
    assert body["sources"] == 80
    assert body["chunks"] == 2193
    assert body["chunks_with_embeddings"] == 2193
    assert body["answer_model"]
    assert body["embedding_provider"] in {"voyage", "openai", "none"}


def test_healthz_returns_app_error_when_db_unreachable(client, monkeypatch):
    @contextmanager
    def broken_get_conn():
        raise RuntimeError("simulated db failure")
        yield None  # pragma: no cover

    monkeypatch.setattr("doc_qa.api.get_conn", broken_get_conn)

    r = client.get("/healthz")
    assert r.status_code == 503
    body = r.json()
    assert body["error"] == "retrieval_unavailable"
    assert body["request_id"]


def test_search_validates_empty_query(client):
    r = client.post("/search", json={"query": "", "k": 5})
    assert r.status_code == 422


def test_search_validates_k_upper_bound(client):
    r = client.post("/search", json={"query": "anything", "k": 999})
    assert r.status_code == 422


def test_search_returns_typed_response_on_mocked_retrieval(client, monkeypatch):
    fake_chunk = RetrievedChunk(
        chunk_id=1,
        source_id=42,
        chunk_index=0,
        heading="Heading",
        content="some content here that makes sense",
        source_url="https://example.com/page.md",
        source_title="Page",
        score=0.123,
        fts_rank=1,
        semantic_rank=2,
    )
    monkeypatch.setattr("doc_qa.api.search", lambda *a, **kw: [fake_chunk])

    r = client.post("/search", json={"query": "anything", "k": 5, "mode": "hybrid"})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "anything"
    assert body["mode"] == "hybrid"
    assert len(body["results"]) == 1
    hit = body["results"][0]
    assert hit["chunk_id"] == 1
    assert hit["source_url"] == "https://example.com/page.md"
    assert hit["fts_rank"] == 1
    assert hit["semantic_rank"] == 2


def test_ask_returns_config_error_when_anthropic_key_missing(client, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    r = client.post("/ask", json={"question": "hello", "k": 5})
    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "config_invalid"
    assert "ANTHROPIC_API_KEY" in body["detail"]
    assert body["request_id"]


def test_ask_validates_empty_question(client):
    r = client.post("/ask", json={"question": "", "k": 5})
    assert r.status_code == 422


def _fake_answer(question, *, k, candidates, mode, model):
    return AnswerResult(
        question=question,
        answer="ok",
        citations=[],
        sources=[],
        retrieved_chunks=[],
        model=model or settings.answer_model,
    )


def test_ask_rejects_a_model_outside_the_allowlist(client, monkeypatch):
    called = []
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "allowed_models", "")
    monkeypatch.setattr(
        "doc_qa.api.answer_question", lambda *a, **kw: called.append(kw) or _fake_answer(*a, **kw)
    )
    r = client.post("/ask", json={"question": "hello", "model": "claude-opus-4-1"})
    assert r.status_code == 400
    assert r.json()["error"] == "model_not_allowed"
    assert called == []


def test_ask_accepts_the_answer_model_and_listed_models(client, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "allowed_models", "claude-haiku-4-5, claude-opus-4-1")
    monkeypatch.setattr("doc_qa.api.answer_question", _fake_answer)
    for model in [settings.answer_model, "claude-opus-4-1", None]:
        r = client.post("/ask", json={"question": "hello", "model": model})
        assert r.status_code == 200, r.json()
        assert r.json()["model"] == (model or settings.answer_model)
