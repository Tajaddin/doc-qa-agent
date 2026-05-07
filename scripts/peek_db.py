"""Print a small snapshot of what is in `sources` and `chunks` after ingestion."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from doc_qa.db import get_conn

console = Console()


def main() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from sources")
            n_sources = cur.fetchone()[0]
            cur.execute("select count(*) from chunks")
            n_chunks = cur.fetchone()[0]
            cur.execute("select count(*) from chunks where embedding is not null")
            n_embedded = cur.fetchone()[0]
            cur.execute("select avg(token_count)::int, min(token_count), max(token_count) from chunks")
            avg_tok, min_tok, max_tok = cur.fetchone() or (None, None, None)

            cur.execute(
                "select source_url, title, "
                "(select count(*) from chunks where source_id = s.id) as nchunks "
                "from sources s order by id desc limit 5"
            )
            recent = cur.fetchall()

    summary = Table(title="DB snapshot", show_header=True, header_style="bold")
    summary.add_column("metric")
    summary.add_column("value", justify="right")
    summary.add_row("sources", str(n_sources))
    summary.add_row("chunks", str(n_chunks))
    summary.add_row("chunks with embeddings", str(n_embedded))
    summary.add_row("avg tokens / chunk", str(avg_tok) if avg_tok is not None else "-")
    summary.add_row("min tokens", str(min_tok) if min_tok is not None else "-")
    summary.add_row("max tokens", str(max_tok) if max_tok is not None else "-")
    console.print(summary)

    if recent:
        recents = Table(title="5 most recent sources", show_header=True, header_style="bold")
        recents.add_column("url")
        recents.add_column("title")
        recents.add_column("chunks", justify="right")
        for url, title, n in recent:
            recents.add_row(url, title or "-", str(n))
        console.print(recents)


if __name__ == "__main__":
    main()
