"""Exercise the MCP tools by calling them directly (no transport layer).

This is the fastest way to confirm tool wiring before plugging the server into
Claude Desktop or Claude Code. If this script prints sensible output, the
underlying tool functions are healthy and any client-side problem is transport
or configuration, not logic.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from doc_qa.mcp_server import ask_docs, list_sources, search_docs

console = Console()


def main() -> None:
    # 1. list_sources
    console.rule("[bold]list_sources(limit=5)[/]")
    rows = list_sources(limit=5)
    t = Table(show_header=True, header_style="bold")
    t.add_column("chunks", justify="right")
    t.add_column("title")
    t.add_column("url", overflow="fold")
    for r in rows:
        t.add_row(str(r.chunks), r.title or "-", r.url)
    console.print(t)

    # 2. search_docs
    console.rule("[bold]search_docs(query=..., k=3, mode='hybrid')[/]")
    hits = search_docs("How do prompt caching breakpoints work?", k=3, mode="hybrid")
    t = Table(show_header=True, header_style="bold", show_lines=True)
    t.add_column("score", justify="right")
    t.add_column("ranks", justify="right")
    t.add_column("source", overflow="fold")
    t.add_column("heading")
    t.add_column("preview", overflow="fold")
    for h in hits:
        ranks = f"fts={h.fts_rank or '-'} sem={h.semantic_rank or '-'}"
        preview = h.content.replace("\n", " ")
        if len(preview) > 200:
            preview = preview[:200] + " ..."
        t.add_row(f"{h.score:.4f}", ranks, h.source_url, h.heading or "-", preview)
    console.print(t)

    # 3. ask_docs
    console.rule("[bold]ask_docs(question=..., k=5)[/]")
    answer = ask_docs("What citation type does Claude return for custom-content documents?", k=5)
    console.print(Panel(answer.answer, title="answer", border_style="green"))
    console.print(
        f"[dim]model={answer.model}  input={answer.input_tokens}  "
        f"output={answer.output_tokens}  citations={len(answer.citations)}  "
        f"sources={len(answer.sources)}[/]"
    )
    if answer.sources:
        s = Table(show_header=True, header_style="bold")
        s.add_column("url", overflow="fold")
        s.add_column("title")
        for src in answer.sources:
            s.add_row(src.url, src.title or "-")
        console.print(s)


if __name__ == "__main__":
    main()
