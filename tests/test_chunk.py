"""Tests for the heading-aware markdown chunker.

Pure-Python tests, no DB or network required. Cover the three properties the
Loom story leans on: chunks carry their heading, fenced code blocks survive
intact, and tiny adjacent chunks merge into the previous one.
"""

from __future__ import annotations

from doc_qa.chunk import Chunk, chunk_markdown, count_tokens


def test_count_tokens_nonzero_for_real_text():
    assert count_tokens("Hello world") > 0
    assert count_tokens("") == 0


def test_chunker_propagates_heading_per_chunk():
    md = (
        "# Section A\n\n"
        "Content under A. " * 12 + "\n\n"
        "# Section B\n\n"
        "Content under B. " * 12
    )
    chunks = chunk_markdown(md, target_tokens=400, min_tokens=10)
    headings = {c.heading for c in chunks}
    assert "Section A" in headings
    assert "Section B" in headings


def test_chunker_does_not_break_inside_fenced_code():
    md = (
        "# Section\n\n"
        "Pre-code prose. " * 8 + "\n\n"
        "```python\n"
        "def foo():\n"
        "    return 1\n"
        "\n"
        "# this LOOKS like a heading but lives inside a fence\n"
        "def bar():\n"
        "    return 2\n"
        "```\n\n"
        "Post-code prose."
    )
    chunks = chunk_markdown(md, target_tokens=400, min_tokens=10)
    # No chunk should have the in-fence text promoted to a heading
    bogus = [c for c in chunks if c.heading and "lives inside a fence" in c.heading]
    assert not bogus
    # The fenced code block should appear in some chunk's content intact
    assert any("def foo()" in c.content and "def bar()" in c.content for c in chunks)


def test_chunker_keeps_chunks_below_target_when_possible():
    paragraph = "This is a sentence with several words. " * 30
    md = (
        "# Long\n\n" + paragraph + "\n\n"
        "## Sub\n\n" + paragraph + "\n\n"
        "## Another\n\n" + paragraph
    )
    chunks = chunk_markdown(md, target_tokens=400, min_tokens=80)
    assert chunks, "expected at least one chunk"
    # Allow some overrun because long single paragraphs cannot be split below
    # target without breaking sentences. Hard cap is target_tokens * 1.5.
    assert all(c.token_count <= 600 for c in chunks)


def test_chunker_returns_sequential_indices():
    md = "# A\n\nfoo\n\n# B\n\nbar\n\n# C\n\nbaz"
    chunks = chunk_markdown(md, target_tokens=400, min_tokens=2)
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunk_dataclass_shape():
    md = "# Test\n\nSome content here.\n"
    chunks = chunk_markdown(md, target_tokens=400, min_tokens=2)
    assert len(chunks) == 1
    c = chunks[0]
    assert isinstance(c, Chunk)
    assert c.heading == "Test"
    assert "Some content here." in c.content
    assert c.token_count > 0
    assert c.chunk_index == 0


def test_chunker_isolates_markdown_table_into_its_own_chunk():
    # Direct mirror of the q15 batch_pricing failure shape: heading + intro
    # prose + pricing table + closing prose, all small enough to fit in one
    # chunk if we let it. The fix is to force the table into its own chunk
    # so retrieval has a precise target. The lead-in prose paragraph rides
    # along to give the embedding semantic signal beyond raw numeric rows.
    md = (
        "# Pricing\n\n"
        "Batch processing offers a different price tier from standard requests.\n\n"
        "| Model | Batch input | Batch output |\n"
        "| --- | --- | --- |\n"
        "| Claude Opus 4.7 | $2.50 | $12.50 |\n"
        "| Claude Sonnet 4.6 | $1.50 | $7.50 |\n\n"
        "See the API reference for current rates."
    )
    chunks = chunk_markdown(md, target_tokens=400, min_tokens=2)

    table_chunks = [c for c in chunks if "| Model |" in c.content]
    prose_chunks = [c for c in chunks if "| Model |" not in c.content]

    assert len(table_chunks) == 1, "table should land in exactly one chunk"
    table = table_chunks[0]

    # The table chunk has the table itself
    assert "Claude Opus 4.7" in table.content
    assert "$2.50" in table.content

    # The lead-in prose travels WITH the table so the embedding catches
    # natural-language queries like "what pricing applies to batch?".
    # Closing prose stays out because it is not the immediate lead-in.
    assert "Batch processing offers" in table.content
    assert "See the API reference" not in table.content

    # Prose chunks must not carry the table itself
    for c in prose_chunks:
        assert "$2.50" not in c.content
        assert "Claude Opus 4.7" not in c.content


def test_chunker_does_not_treat_pipe_in_prose_as_a_table():
    # A single | character inside prose must NOT trigger table isolation.
    md = (
        "# Notes\n\n"
        "Use the pipe operator | to chain commands together in your shell."
    )
    chunks = chunk_markdown(md, target_tokens=400, min_tokens=2)
    assert len(chunks) == 1
    assert "pipe operator" in chunks[0].content
