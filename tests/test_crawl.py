"""Tests for crawler helpers: URL filtering, llms.txt parsing, markdown cleaning.

Pure functions, no network. The crawler's network-bound parts (sitemap fetch,
async page fetch) get exercised through the live ingest CLI; these tests
target the deterministic transformations.
"""

from __future__ import annotations

import pytest

from doc_qa.crawl import (
    _parse_llms_txt,
    checksum_of,
    clean_markdown,
    filter_urls,
)


def test_parse_llms_txt_extracts_link_targets():
    text = (
        "# Index\n"
        "- [Page A](https://example.com/a.md)\n"
        "- [Page B](https://example.com/b.md)\n"
        "Some prose with [Inline](https://example.com/c.md) link.\n"
    )
    targets = _parse_llms_txt(text)
    assert "https://example.com/a.md" in targets
    assert "https://example.com/b.md" in targets
    assert "https://example.com/c.md" in targets


def test_parse_llms_txt_returns_empty_on_no_links():
    assert _parse_llms_txt("") == []
    assert _parse_llms_txt("# Header\n\nNo links here.\n") == []


def test_filter_urls_respects_base_and_path_allow(monkeypatch):
    from doc_qa.config import settings

    monkeypatch.setattr(settings, "crawl_base_url", "https://platform.claude.com")
    monkeypatch.setattr(settings, "crawl_path_allow", "/docs/en/")
    # Clear deny so this test exercises allow-only logic in isolation.
    monkeypatch.setattr(settings, "crawl_path_deny", "")

    urls = [
        "https://platform.claude.com/docs/en/intro.md",
        "https://platform.claude.com/docs/de/intro.md",  # wrong language
        "https://other.com/docs/en/intro.md",            # wrong host
        "https://platform.claude.com/docs/en/intro.md",  # duplicate
    ]
    out = filter_urls(urls)
    assert out == ["https://platform.claude.com/docs/en/intro.md"]


def test_filter_urls_multiple_allow_prefixes(monkeypatch):
    from doc_qa.config import settings

    monkeypatch.setattr(settings, "crawl_base_url", "https://platform.claude.com")
    monkeypatch.setattr(settings, "crawl_path_allow", "/docs/en/build,/docs/en/api")
    monkeypatch.setattr(settings, "crawl_path_deny", "")

    urls = [
        "https://platform.claude.com/docs/en/build/x.md",
        "https://platform.claude.com/docs/en/api/y.md",
        "https://platform.claude.com/docs/en/marketing/z.md",
    ]
    out = filter_urls(urls)
    assert "https://platform.claude.com/docs/en/build/x.md" in out
    assert "https://platform.claude.com/docs/en/api/y.md" in out
    assert all("marketing" not in u for u in out)


def test_filter_urls_applies_deny_after_allow(monkeypatch):
    """The new deny list excludes /docs/en/api/* even when allow includes it."""
    from doc_qa.config import settings

    monkeypatch.setattr(settings, "crawl_base_url", "https://platform.claude.com")
    monkeypatch.setattr(settings, "crawl_path_allow", "/docs/en/")
    monkeypatch.setattr(settings, "crawl_path_deny", "/docs/en/api/")

    urls = [
        "https://platform.claude.com/docs/en/build-with-claude/citations.md",
        "https://platform.claude.com/docs/en/api/messages/create.md",
        "https://platform.claude.com/docs/en/api/beta.md",
    ]
    out = filter_urls(urls)
    assert "https://platform.claude.com/docs/en/build-with-claude/citations.md" in out
    assert all("/api/" not in u for u in out)


def test_clean_markdown_strips_mintlify_wrapper_tags():
    md = (
        "# Heading\n\n"
        "<Tip>Useful tip text.</Tip>\n\n"
        "<Warning>Be careful</Warning>\n\n"
        "Plain prose.\n"
    )
    cleaned = clean_markdown(md)
    assert "<Tip>" not in cleaned
    assert "</Tip>" not in cleaned
    assert "<Warning>" not in cleaned
    assert "Useful tip text." in cleaned
    assert "Plain prose." in cleaned


def test_clean_markdown_strips_yaml_frontmatter():
    md = "---\ntitle: Some Page\nlayout: docs\n---\n\n# Heading\n\nBody.\n"
    cleaned = clean_markdown(md)
    assert "title: Some Page" not in cleaned
    assert "layout: docs" not in cleaned
    assert cleaned.startswith("# Heading")


def test_clean_markdown_collapses_excess_blank_lines():
    md = "Para one.\n\n\n\n\nPara two.\n"
    cleaned = clean_markdown(md)
    assert "\n\n\n" not in cleaned
    assert "Para one." in cleaned
    assert "Para two." in cleaned


def test_checksum_is_deterministic_and_truncated():
    assert checksum_of("abc") == checksum_of("abc")
    assert checksum_of("abc") != checksum_of("abd")
    assert len(checksum_of("anything")) == 16


@pytest.mark.parametrize(
    "text",
    ["short", "a much longer string with many words", "unicode: 日本語"],
)
def test_checksum_handles_unicode_and_lengths(text: str):
    digest = checksum_of(text)
    assert isinstance(digest, str)
    assert len(digest) == 16
