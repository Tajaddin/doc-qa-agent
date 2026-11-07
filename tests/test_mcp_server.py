"""Bounds on the MCP tool arguments.

The tools are called directly with retrieval, answering and the DB patched out,
so these run without a database or API key. A client (or a prompt-injected
model) can pass any integer, so k and limit are clamped to the same caps the
HTTP API enforces.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from doc_qa import mcp_server
from doc_qa.answer import AnswerResult


@pytest.fixture
def search_calls(monkeypatch):
    calls: list[dict] = []

    def fake_search(query, *, k, mode):
        calls.append({"k": k, "mode": mode})
        return []

    monkeypatch.setattr(mcp_server, "search", fake_search)
    return calls


@pytest.fixture
def answer_calls(monkeypatch):
    calls: list[dict] = []

    def fake_answer(question, *, k, mode):
        calls.append({"k": k})
        return AnswerResult(
            question=question,
            answer="",
            citations=[],
            sources=[],
            retrieved_chunks=[],
            model="m",
        )

    monkeypatch.setattr(mcp_server, "answer_question", fake_answer)
    return calls


@pytest.fixture
def limit_args(monkeypatch):
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def fake_get_conn():
        yield conn

    monkeypatch.setattr(mcp_server, "get_conn", fake_get_conn)
    return cursor.execute


@pytest.mark.parametrize(("k", "sent"), [(500, 20), (20, 20), (3, 3), (0, 1), (-7, 1)])
def test_search_docs_clamps_k(search_calls, k, sent):
    mcp_server.search_docs("q", k=k)
    assert search_calls == [{"k": sent, "mode": "hybrid"}]


@pytest.mark.parametrize(("k", "sent"), [(500, 20), (5, 5), (0, 1)])
def test_ask_docs_clamps_k(answer_calls, k, sent):
    mcp_server.ask_docs("q", k=k)
    assert answer_calls == [{"k": sent}]


@pytest.mark.parametrize(("limit", "sent"), [(10**9, 200), (20, 20), (-1, 1)])
def test_list_sources_clamps_limit(limit_args, limit, sent):
    mcp_server.list_sources(limit=limit)
    (_sql, params), _ = limit_args.call_args
    assert params == (sent,)
