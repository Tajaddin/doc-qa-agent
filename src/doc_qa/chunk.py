"""Heading-aware markdown chunker.

Targets ~400 tokens per chunk for prose, never splits inside fenced code blocks,
isolates markdown tables as their own chunks (so a pricing table never gets cut
in half across two retrieval units), and prepends the nearest heading so each
chunk stands alone in retrieval.

Token counts use cl100k_base. Claude uses a different tokenizer, but cl100k is
within ~10 percent for English + code and is plenty accurate for chunk sizing.

Table-aware splitting was added after the q15 batch_pricing eval failure: the
canonical pricing table on /docs/en/build-with-claude/batch-processing.md was
landing in the same chunk as the surrounding prose, so retrieval found the
chunk but the model anchored on the prose instead of the precise rate row.
Forcing tables into their own chunk gives retrieval a cleaner target.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import tiktoken


@dataclass(slots=True)
class Chunk:
    chunk_index: int
    heading: str | None
    content: str
    token_count: int


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^```")


_ENCODING: tiktoken.Encoding | None = None


def _enc() -> tiktoken.Encoding:
    global _ENCODING
    if _ENCODING is None:
        _ENCODING = tiktoken.get_encoding("cl100k_base")
    return _ENCODING


def count_tokens(text: str) -> int:
    return len(_enc().encode(text))


def _split_segments(md: str) -> list[tuple[str | None, str]]:
    """Walk markdown line by line. Split at H1 to H3 boundaries.
    Headings inside fenced code blocks are ignored. Returns (heading, body) pairs.
    """
    segments: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    in_fence = False

    for raw in md.split("\n"):
        line = raw.rstrip()
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            current_lines.append(line)
            continue
        if not in_fence:
            m = _HEADING_RE.match(line)
            if m and len(m.group(1)) <= 3:
                if current_lines:
                    segments.append((current_heading, current_lines))
                current_heading = m.group(2).strip()
                current_lines = []
                continue
        current_lines.append(line)

    if current_lines:
        segments.append((current_heading, current_lines))

    return [
        (h, "\n".join(body).strip())
        for h, body in segments
        if "\n".join(body).strip()
    ]


def _is_table_paragraph(para: str) -> bool:
    """A paragraph is a markdown table when every non-empty line begins with `|`.

    Catches both the header rows and the body rows of GitHub-flavored markdown
    tables. Pages with mid-paragraph pipe characters (e.g., a ` | ` separator
    inside prose) are NOT tables because their non-pipe lines disqualify them.
    """
    lines = [line.strip() for line in para.splitlines() if line.strip()]
    if not lines:
        return False
    return all(line.startswith("|") and line.count("|") >= 2 for line in lines)


def _split_oversized(body: str, target_tokens: int) -> list[str]:
    """Split a body on paragraph boundaries.

    Three invariants:
    1. Markdown tables emit as their own chunk so retrieval has a clean target
       on pages where the answer is in a table (pricing rows, capability
       matrices, model spec tables).
    2. Each isolated table chunk also carries its lead-in prose paragraph so
       the embedding has semantic signal beyond raw rows. Embeddings of
       pipe-delimited numeric data alone do not retrieve well on natural-
       language pricing queries; the prose lead-in fixes that.
    3. Otherwise, paragraphs concatenate into the current chunk until adding
       the next one would push the running token count past `target_tokens`.

    The lead-in prose appears in two chunks (the prose chunk and the table
    chunk). Slight duplication is the right call: each chunk stays
    self-contained for retrieval, and an LLM seeing the same lead-in twice
    in different contexts costs almost nothing.
    """
    paragraphs = re.split(r"\n\s*\n", body)
    out: list[str] = []
    current = ""

    def _last_non_table(idx: int) -> str | None:
        for prev in reversed(paragraphs[:idx]):
            if prev.strip() and not _is_table_paragraph(prev):
                return prev.strip()
        return None

    for i, para in enumerate(paragraphs):
        if _is_table_paragraph(para):
            if current:
                out.append(current)
                current = ""
            lead = _last_non_table(i)
            # Cap the combined chunk at 2x target to avoid pathological cases.
            if lead and count_tokens(lead + "\n\n" + para) <= target_tokens * 2:
                out.append(lead + "\n\n" + para)
            else:
                out.append(para)
            continue
        candidate = (current + "\n\n" + para).strip() if current else para
        if not current or count_tokens(candidate) <= target_tokens:
            current = candidate
        else:
            out.append(current)
            current = para
    if current:
        out.append(current)
    return out or [body]


def chunk_markdown(
    md: str,
    target_tokens: int = 400,
    min_tokens: int = 80,
) -> list[Chunk]:
    """Chunk markdown into heading-aligned, ~target_tokens-sized chunks.

    Tiny adjacent chunks under the same heading get merged into the previous chunk
    so the retrieval unit is never below `min_tokens`.
    """
    raw = _split_segments(md)
    chunks: list[Chunk] = []
    idx = 0
    for heading, body in raw:
        for piece in _split_oversized(body, target_tokens):
            content = piece if heading is None else f"# {heading}\n\n{piece}"
            chunks.append(
                Chunk(
                    chunk_index=idx,
                    heading=heading,
                    content=content,
                    token_count=count_tokens(content),
                )
            )
            idx += 1

    merged: list[Chunk] = []
    for c in chunks:
        if (
            merged
            and c.token_count < min_tokens
            and merged[-1].heading == c.heading
        ):
            prev = merged[-1]
            stripped = c.content
            if c.heading and stripped.startswith(f"# {c.heading}"):
                stripped = stripped.split("\n\n", 1)[-1]
            new_content = prev.content + "\n\n" + stripped
            merged[-1] = Chunk(
                chunk_index=prev.chunk_index,
                heading=prev.heading,
                content=new_content,
                token_count=count_tokens(new_content),
            )
        else:
            merged.append(c)

    return [
        Chunk(chunk_index=i, heading=c.heading, content=c.content, token_count=c.token_count)
        for i, c in enumerate(merged)
    ]
