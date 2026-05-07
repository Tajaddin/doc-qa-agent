"""POST a question to the running FastAPI /ask endpoint and pretty-print the answer.

Usage:
    python -m scripts.test_ask "How does prompt caching work?"
    python -m scripts.test_ask "Sonnet 4.6 pricing" --k 8 --port 8000
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--mode", choices=("hybrid", "vector"), default="hybrid")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--raw", action="store_true", help="Print the full JSON payload.")
    args = parser.parse_args()

    base = f"http://{args.host}:{args.port}"

    try:
        h = httpx.get(f"{base}/healthz", timeout=10).json()
    except httpx.HTTPError as e:
        console.print(f"[red]/healthz unreachable at {base}: {e}[/]")
        sys.exit(2)
    console.print(
        f"[dim]server ok  sources={h['sources']}  chunks={h['chunks']}  "
        f"embedded={h['chunks_with_embeddings']}  provider={h['embedding_provider']}  "
        f"model={h['answer_model']}[/]"
    )

    payload = {"question": args.question, "k": args.k, "mode": args.mode}
    r = httpx.post(f"{base}/ask", json=payload, timeout=60)
    if r.status_code != 200:
        console.print(f"[red]HTTP {r.status_code}: {r.text}[/]")
        sys.exit(1)
    data = r.json()

    if args.raw:
        console.print(json.dumps(data, indent=2))
        return

    console.print(Panel(data["answer"] or "(empty)", title=f"Answer for: {args.question!r}",
                        border_style="green"))

    if data["citations"]:
        t = Table(title=f"{len(data['citations'])} citations", show_lines=True, header_style="bold")
        t.add_column("#", justify="right", style="dim")
        t.add_column("source", overflow="fold")
        t.add_column("heading")
        t.add_column("cited span", overflow="fold")
        for i, c in enumerate(data["citations"], start=1):
            span = (c["cited_text"] or "").replace("\n", " ")
            if len(span) > 220:
                span = span[:220] + " ..."
            t.add_row(str(i), c["source_url"], c.get("heading") or "-", span)
        console.print(t)
    else:
        console.print("[yellow]no citations returned[/]")

    if data["sources"]:
        s = Table(title=f"{len(data['sources'])} unique sources", header_style="bold")
        s.add_column("url", overflow="fold")
        s.add_column("title")
        for src in data["sources"]:
            s.add_row(src["url"], src.get("title") or "-")
        console.print(s)

    usage = data.get("usage", {})
    console.print(
        f"[dim]model={data['model']}  input={usage.get('input_tokens', '-')}  "
        f"output={usage.get('output_tokens', '-')}  "
        f"retrieved={len(data['retrieved_chunk_ids'])}[/]"
    )


if __name__ == "__main__":
    main()
