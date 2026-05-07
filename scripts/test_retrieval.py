"""End-to-end retrieval check: embed a query, hit hybrid_search(), pretty-print top-k.

Usage:
    python -m scripts.test_retrieval "How does prompt caching work?"
    python -m scripts.test_retrieval "claude citations" --k 5 --vector-only
"""

from __future__ import annotations

import argparse

import numpy as np
from rich.console import Console
from rich.table import Table

from doc_qa.db import get_conn
from doc_qa.embeddings import get_embedding_client

console = Console()


def _show_results(query: str, rows: list[tuple], mode: str) -> None:
    table = Table(title=f"Top {len(rows)} via {mode} for: {query!r}", show_lines=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("score", justify="right")
    table.add_column("ranks", justify="right")
    table.add_column("source", overflow="fold")
    table.add_column("heading")
    table.add_column("preview", overflow="fold")

    for i, row in enumerate(rows, start=1):
        if mode == "hybrid":
            (_id, _src_id, _ci, heading, content, _meta, url, _title,
             fts_rank, sem_rank, score) = row
            ranks = f"fts={fts_rank or '-'} sem={sem_rank or '-'}"
        else:
            (_id, _src_id, _ci, heading, content, _meta, url, _title, distance) = row
            score = -distance
            ranks = f"d={distance:.4f}"
        preview = content.replace("\n", " ")
        if len(preview) > 220:
            preview = preview[:220] + " ..."
        table.add_row(str(i), f"{score:.4f}", ranks, url, heading or "-", preview)

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="Question or phrase to retrieve against.")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--vector-only", action="store_true")
    args = parser.parse_args()

    client = get_embedding_client()
    console.print(
        f"[dim]embed provider:[/] {client.name}  model={client.model}  dim={client.dim}"
    )
    qvec = np.array(client.embed([args.query], input_type="query")[0], dtype=np.float32)

    with get_conn() as conn:
        with conn.cursor() as cur:
            if args.vector_only:
                cur.execute(
                    "select * from vector_search(%s::vector(1024), %s::int)",
                    (qvec, args.k),
                )
                rows = cur.fetchall()
                _show_results(args.query, rows, "vector_search")
            else:
                cur.execute(
                    "select * from hybrid_search(%s, %s::vector(1024), %s::int)",
                    (args.query, qvec, args.k),
                )
                rows = cur.fetchall()
                _show_results(args.query, rows, "hybrid")


if __name__ == "__main__":
    main()
