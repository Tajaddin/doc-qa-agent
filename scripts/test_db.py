"""Smoke test the schema, indexes, and helper functions."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from doc_qa.db import get_conn

console = Console()


CHECKS_SQL = [
    ("vector extension",     "select 1 from pg_extension where extname = 'vector'"),
    ("sources table",        "select 1 from information_schema.tables where table_name = 'sources'"),
    ("chunks table",         "select 1 from information_schema.tables where table_name = 'chunks'"),
    ("eval_cases table",     "select 1 from information_schema.tables where table_name = 'eval_cases'"),
    ("HNSW index",           "select 1 from pg_indexes where indexname = 'chunks_embedding_hnsw'"),
    ("GIN fts index",        "select 1 from pg_indexes where indexname = 'chunks_fts_gin'"),
    ("hybrid_search fn",     "select 1 from pg_proc where proname = 'hybrid_search'"),
    ("vector_search fn",     "select 1 from pg_proc where proname = 'vector_search'"),
    ("fts trigger",          "select 1 from pg_trigger where tgname = 'chunks_fts_trigger'"),
]


def main() -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("check")
    table.add_column("result")

    failures = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for label, sql in CHECKS_SQL:
                cur.execute(sql)
                ok = cur.fetchone() is not None
                table.add_row(label, "[green]OK[/]" if ok else "[red]MISSING[/]")
                if not ok:
                    failures += 1

    console.print(table)
    if failures:
        raise SystemExit(f"{failures} check(s) failed")
    console.print("[bold green]All schema checks passed.[/]")


if __name__ == "__main__":
    main()
