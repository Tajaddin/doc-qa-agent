"""Tests for the retrieval / citation metric helpers in eval.run_eval.

Exercises the helpers with hand-crafted inputs so the eval numbers in the
report are auditable. Pure functions, no API or DB required.
"""

from __future__ import annotations

from eval.run_eval import (
    _citation_metrics,
    _hit_at_k,
    _normalize,
    _recall_at_k,
    _reciprocal_rank,
)


def test_normalize_strips_trailing_slash_fragment_query():
    assert _normalize("https://x.com/foo/") == "https://x.com/foo"
    assert _normalize("https://x.com/foo#bar") == "https://x.com/foo"
    assert _normalize("https://x.com/foo?baz=1") == "https://x.com/foo"
    assert _normalize("https://x.com/foo/?baz=1#frag") == "https://x.com/foo"


def test_hit_at_k_true_when_any_gold_in_retrieved():
    assert _hit_at_k(["a", "b", "c"], {"b"}) is True
    assert _hit_at_k(["a", "b", "c"], {"z"}) is False
    assert _hit_at_k([], {"a"}) is False
    assert _hit_at_k(["a"], set()) is False


def test_recall_at_k_computes_fraction_of_gold_retrieved():
    assert _recall_at_k(["a", "b"], {"a", "b"}) == 1.0
    assert _recall_at_k(["a"], {"a", "b"}) == 0.5
    assert _recall_at_k(["c"], {"a", "b"}) == 0.0
    assert _recall_at_k([], set()) == 0.0
    # Duplicates in retrieved do not double-count
    assert _recall_at_k(["a", "a", "b"], {"a", "b"}) == 1.0


def test_reciprocal_rank_uses_first_match():
    assert _reciprocal_rank(["a", "b", "c"], {"a"}) == 1.0
    assert _reciprocal_rank(["a", "b", "c"], {"b"}) == 0.5
    assert _reciprocal_rank(["a", "b", "c"], {"c"}) == 1.0 / 3
    assert _reciprocal_rank(["a", "b", "c"], {"z"}) == 0.0
    # Multiple golds: pick the earliest-ranked one
    assert _reciprocal_rank(["a", "b", "c"], {"b", "c"}) == 0.5


def test_citation_metrics_handles_empty_full_partial():
    hit, prec = _citation_metrics([], {"a"})
    assert hit is False and prec == 0.0
    hit, prec = _citation_metrics(["a", "b"], {"a"})
    assert hit is True and prec == 0.5
    hit, prec = _citation_metrics(["a", "a"], {"a"})
    assert hit is True and prec == 1.0
    hit, prec = _citation_metrics(["a", "b", "c"], {"a", "b"})
    assert hit is True
    assert abs(prec - 2 / 3) < 1e-9
