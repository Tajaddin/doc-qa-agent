"""Apply every SQL file in ./sql in lexical order against $DATABASE_URL."""

from __future__ import annotations

from pathlib import Path

import psycopg
from rich.console import Console

from doc_qa.config import settings

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
console = Console()


def main() -> None:
    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        raise SystemExit(f"No SQL files found in {SQL_DIR}")

    safe_dsn = settings.database_url.split("@")[-1]
    console.print(f"[bold]Applying {len(files)} migrations to[/] {safe_dsn}")

    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            for f in files:
                console.print(f"  [cyan]{f.name}[/] ...", end=" ")
                cur.execute(f.read_text(encoding="utf-8"))
                console.print("[green]ok[/]")

    console.print("[bold green]Migrations complete.[/]")


if __name__ == "__main__":
    main()
