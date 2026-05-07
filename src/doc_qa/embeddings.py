"""Embedding client abstraction with Voyage as primary and OpenAI as fallback.

The interface keeps document vs query input distinct because Voyage's encoder is
asymmetric. OpenAI's encoder ignores the flag.

CLI:
    python -m doc_qa.embeddings --limit 50
    python -m doc_qa.embeddings              # all NULL embeddings
    python -m doc_qa.embeddings --reembed    # rebuild every embedding
"""

from __future__ import annotations

import argparse
import time
from abc import ABC, abstractmethod
from typing import Literal

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from doc_qa.config import settings
from doc_qa.db import get_conn

console = Console()
InputType = Literal["document", "query"]


# ---------- client abstraction ----------

class EmbeddingClient(ABC):
    name: str
    model: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str], input_type: InputType = "document") -> list[list[float]]:
        """Return one vector per input text. Order is preserved."""


class VoyageClient(EmbeddingClient):
    def __init__(self, api_key: str, model: str, dim: int) -> None:
        import voyageai

        self._client = voyageai.Client(api_key=api_key)
        self.model = model
        self.dim = dim
        self.name = "voyage"

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def embed(self, texts: list[str], input_type: InputType = "document") -> list[list[float]]:
        result = self._client.embed(
            texts=texts,
            model=self.model,
            input_type=input_type,
            output_dimension=self.dim,
            truncation=True,
        )
        return result.embeddings


class OpenAIClient(EmbeddingClient):
    def __init__(self, api_key: str, model: str, dim: int) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.model = model
        self.dim = dim
        self.name = "openai"

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def embed(self, texts: list[str], input_type: InputType = "document") -> list[list[float]]:
        # OpenAI does not distinguish document vs query input types.
        result = self._client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dim,
        )
        return [item.embedding for item in result.data]


def get_embedding_client() -> EmbeddingClient:
    provider = settings.embedding_provider
    if provider == "voyage":
        return VoyageClient(
            api_key=settings.voyage_api_key,
            model=settings.voyage_model,
            dim=settings.embedding_dim,
        )
    if provider == "openai":
        return OpenAIClient(
            api_key=settings.openai_api_key,
            model=settings.openai_embed_model,
            dim=settings.openai_embed_dimensions,
        )
    raise RuntimeError(
        "No embedding provider configured. Set VOYAGE_API_KEY or OPENAI_API_KEY in .env."
    )


# ---------- backfill ----------

def _select_pending(cur, limit: int | None, reembed: bool) -> list[tuple[int, str]]:
    where = "" if reembed else "where embedding is null"
    sql = f"select id, content from chunks {where} order by id"
    if limit:
        sql += f" limit {int(limit)}"
    cur.execute(sql)
    return cur.fetchall()


def _update_embeddings(cur, ids: list[int], vectors: list[list[float]]) -> None:
    cur.executemany(
        "update chunks set embedding = %s where id = %s",
        list(zip(vectors, ids, strict=True)),
    )


def backfill(batch_size: int = 100, limit: int | None = None, reembed: bool = False) -> None:
    client = get_embedding_client()
    console.print(
        f"embedding provider: [bold]{client.name}[/]  "
        f"model={client.model}  dim={client.dim}  batch={batch_size}"
    )

    with get_conn() as conn:
        with conn.cursor() as cur:
            rows = _select_pending(cur, limit, reembed)

        if not rows:
            console.print("[yellow]No chunks need embedding.[/]")
            return

        total = len(rows)
        console.print(f"target: [bold]{total}[/] chunks")

        columns = [
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("[bold]{task.fields[rate]:.0f}[/] chunks/s"),
            TimeElapsedColumn(),
        ]
        start = time.monotonic()
        embedded = 0

        with Progress(*columns, console=console) as progress:
            task = progress.add_task("embedding", total=total, rate=0.0)
            for i in range(0, total, batch_size):
                batch = rows[i : i + batch_size]
                ids = [r[0] for r in batch]
                texts = [r[1] for r in batch]
                vectors = client.embed(texts, input_type="document")
                with conn.cursor() as cur:
                    _update_embeddings(cur, ids, vectors)
                conn.commit()
                embedded += len(batch)
                elapsed = max(time.monotonic() - start, 1e-6)
                progress.update(task, advance=len(batch), rate=embedded / elapsed)

    console.print(f"[bold green]done[/] embedded {embedded}/{total}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill embeddings into chunks.embedding.")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Texts per embedding API call. Default 100.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap the number of chunks processed. Default: all pending.")
    parser.add_argument("--reembed", action="store_true",
                        help="Re-embed every chunk, including ones that already have a vector.")
    args = parser.parse_args()
    backfill(batch_size=args.batch_size, limit=args.limit, reembed=args.reembed)


if __name__ == "__main__":
    main()
