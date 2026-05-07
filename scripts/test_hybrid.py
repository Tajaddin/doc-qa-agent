"""Verify hybrid_search() compiles, accepts a vector arg, and returns the right shape.

Runs against an empty chunks table, so 0 rows is the expected pass condition.
"""

from __future__ import annotations

import numpy as np
from rich.console import Console

from doc_qa.db import get_conn

console = Console()


def main() -> None:
    emb = np.zeros(1024, dtype=np.float32)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select * from hybrid_search(%s, %s, 5)",
                ("claude api", emb),
            )
            rows = cur.fetchall()
            cur.execute(
                "select * from vector_search(%s, 5)",
                (emb,),
            )
            v_rows = cur.fetchall()

    console.print(f"hybrid_search rows: [bold]{len(rows)}[/]  (0 expected, no chunks ingested yet)")
    console.print(f"vector_search rows: [bold]{len(v_rows)}[/]  (0 expected, no chunks ingested yet)")
    if len(rows) == 0 and len(v_rows) == 0:
        console.print("[bold green]Both functions callable with a vector(1024) argument.[/]")
    else:
        raise SystemExit("Unexpected rows returned. Check the chunks table state.")


if __name__ == "__main__":
    main()
