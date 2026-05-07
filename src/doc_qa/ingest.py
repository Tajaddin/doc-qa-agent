"""Ingestion pipeline: crawl -> chunk -> upsert sources -> replace chunks.

Idempotent. Re-running with the same corpus is fast: pages whose checksum matches
the stored value are skipped, so chunks for unchanged pages stay in place.

CLI:
    python -m doc_qa.ingest --limit 10 --dry-run --sample
    python -m doc_qa.ingest --limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from doc_qa.chunk import Chunk, chunk_markdown
from doc_qa.crawl import FetchedPage, crawl
from doc_qa.db import get_conn

console = Console()


def _upsert_source(cur, page: FetchedPage) -> tuple[int, bool]:
    """Insert or update a source row. Returns (source_id, content_changed)."""
    cur.execute(
        "select id, checksum from sources where source_url = %s",
        (page.url,),
    )
    row = cur.fetchone()
    now = datetime.now(timezone.utc)
    meta = json.dumps({})
    if row:
        source_id, prev_checksum = row
        if prev_checksum == page.checksum:
            return source_id, False
        cur.execute(
            "update sources set title = %s, checksum = %s, fetched_at = %s, metadata = %s "
            "where id = %s",
            (page.title, page.checksum, now, meta, source_id),
        )
        return source_id, True
    cur.execute(
        "insert into sources (source_url, title, checksum, fetched_at, metadata) "
        "values (%s, %s, %s, %s, %s::jsonb) returning id",
        (page.url, page.title, page.checksum, now, meta),
    )
    return cur.fetchone()[0], True


def _replace_chunks(cur, source_id: int, chunks: list[Chunk]) -> None:
    cur.execute("delete from chunks where source_id = %s", (source_id,))
    if not chunks:
        return
    cur.executemany(
        "insert into chunks (source_id, chunk_index, heading, content, token_count, metadata) "
        "values (%s, %s, %s, %s, %s, %s::jsonb)",
        [
            (source_id, c.chunk_index, c.heading, c.content, c.token_count, json.dumps({}))
            for c in chunks
        ],
    )


def _summary_table(pages: list[FetchedPage], chunks_per_page: list[list[Chunk]]) -> Table:
    total_chunks = sum(len(cs) for cs in chunks_per_page)
    total_tokens = sum(c.token_count for cs in chunks_per_page for c in cs)
    avg = total_tokens / max(1, total_chunks)
    over = sum(1 for cs in chunks_per_page for c in cs if c.token_count > 800)
    under = sum(1 for cs in chunks_per_page for c in cs if c.token_count < 60)

    t = Table(title="Ingest summary", show_header=True, header_style="bold")
    t.add_column("metric")
    t.add_column("value", justify="right")
    t.add_row("pages fetched",       str(len(pages)))
    t.add_row("chunks built",        str(total_chunks))
    t.add_row("total tokens",        f"{total_tokens:,}")
    t.add_row("avg tokens / chunk",  f"{avg:.1f}")
    t.add_row("chunks > 800 tokens", str(over))
    t.add_row("chunks < 60 tokens",  str(under))
    return t


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl, chunk, and ingest into Postgres.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max pages to fetch. Defaults to CRAWL_MAX_PAGES from .env.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Crawl + chunk and print stats. No DB writes.")
    parser.add_argument("--sample", action="store_true",
                        help="Print one example chunk after the summary.")
    args = parser.parse_args()

    pages = asyncio.run(crawl(limit=args.limit))
    chunks_per_page = [chunk_markdown(p.markdown) for p in pages]

    console.print(_summary_table(pages, chunks_per_page))

    if args.sample and pages:
        first_idx = next((i for i, cs in enumerate(chunks_per_page) if cs), None)
        if first_idx is not None:
            p = pages[first_idx]
            cs = chunks_per_page[first_idx]
            console.print(f"\n[bold]Sample chunk from[/] {p.url}")
            console.print(f"[dim]heading:[/] {cs[0].heading}    [dim]tokens:[/] {cs[0].token_count}\n")
            preview = cs[0].content if len(cs[0].content) <= 700 else cs[0].content[:700] + " ..."
            console.print(preview)

    if args.dry_run:
        console.print("\n[yellow]dry-run, no DB writes performed.[/]")
        return

    written_sources = 0
    written_chunks = 0
    skipped = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for page, chunks in zip(pages, chunks_per_page, strict=True):
                src_id, changed = _upsert_source(cur, page)
                if not changed:
                    skipped += 1
                    continue
                _replace_chunks(cur, src_id, chunks)
                written_sources += 1
                written_chunks += len(chunks)
        conn.commit()

    console.print(
        f"[bold green]wrote[/] sources={written_sources}, chunks={written_chunks}, "
        f"skipped_unchanged={skipped}"
    )


if __name__ == "__main__":
    main()
