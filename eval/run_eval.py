"""Evaluation harness.

Runs every case in eval/questions.yaml under each requested retrieval mode.
Computes:

  Retrieval (against gold_source_urls)
    - hit@k          : at least one gold URL was retrieved in the top-k pool
    - recall@k       : fraction of gold URLs retrieved in the top-k pool
    - MRR            : reciprocal rank of the first gold URL hit

  Citation (against the citations Claude returned)
    - citation_hit       : Claude cited at least one chunk from a gold URL
    - citation_precision : fraction of cited URLs in the gold set

  Answer quality (LLM-as-judge with claude-haiku-4-5)
    - faithfulness   : 0/1, does the model answer contradict the gold answer
    - completeness   : 0.0 to 1.0, how much of the gold answer is covered

Outputs:
    eval/reports/eval_<UTC timestamp>.md   per-mode tables + failure analysis
    eval/reports/eval_<UTC timestamp>.json full structured payload

CLI:
    python -m eval.run_eval
    python -m eval.run_eval --modes hybrid                   # one mode only
    python -m eval.run_eval --filter q11                     # one case
    python -m eval.run_eval --k 8 --modes hybrid,vector      # different k
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic
import yaml
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from doc_qa.answer import AnswerResult, answer
from doc_qa.config import settings

console = Console()

EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = EVAL_DIR / "questions.yaml"
REPORTS_DIR = EVAL_DIR / "reports"


# ---------- types ----------

@dataclass
class EvalCase:
    id: str
    question: str
    gold_answer: str
    gold_source_urls: list[str]
    tags: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    id: str
    question: str
    gold_answer: str
    gold_source_urls: list[str]
    tags: list[str]
    mode: str
    answer: str
    retrieved_urls: list[str]
    cited_urls: list[str]
    hit_at_k: bool
    recall_at_k: float
    mrr: float
    citation_hit: bool
    citation_precision: float
    judge_faithfulness: int
    judge_completeness: float
    judge_reasoning: str
    latency_s: float
    input_tokens: int
    output_tokens: int


# ---------- metrics ----------

def _normalize(url: str) -> str:
    """Strip fragment, query, then trailing slash. Order matters: a URL with
    both a query and a trailing slash needs the query removed first so the
    trailing slash is exposed for stripping.
    """
    return url.split("#")[0].split("?")[0].rstrip("/")


def _hit_at_k(retrieved: list[str], gold: set[str]) -> bool:
    return any(u in gold for u in retrieved)


def _recall_at_k(retrieved: list[str], gold: set[str]) -> float:
    if not gold:
        return 0.0
    return len(set(retrieved) & gold) / len(gold)


def _reciprocal_rank(retrieved: list[str], gold: set[str]) -> float:
    for i, u in enumerate(retrieved, start=1):
        if u in gold:
            return 1.0 / i
    return 0.0


def _citation_metrics(cited: list[str], gold: set[str]) -> tuple[bool, float]:
    if not cited:
        return False, 0.0
    hit = any(u in gold for u in cited)
    precision = sum(1 for u in cited if u in gold) / len(cited)
    return hit, precision


# ---------- LLM-as-judge ----------

JUDGE_SYSTEM = (
    "You are an evaluation judge for a documentation Q&A system. Given a "
    "question, a gold (reference) answer, and a model answer, return JSON "
    "only with these exact fields:\n"
    '  - "faithfulness": integer, 1 if the model answer does not directly '
    "contradict the gold answer. The model may add information beyond the "
    "gold as long as nothing contradicts it. Score 0 only when a claim in "
    "the model answer directly contradicts the gold or asserts a fact the "
    "gold disputes.\n"
    '  - "completeness": float between 0.0 and 1.0, how much of the gold '
    "answer's key points the model answer covers (1.0 = covers everything, "
    "0.5 = covers roughly half, 0.0 = misses the main point).\n"
    '  - "reasoning": one short sentence justifying both scores.\n'
    "Output strict JSON only. No markdown fences, no commentary."
)


JUDGE_USER_TEMPLATE = (
    "Question:\n{question}\n\n"
    "Gold answer:\n{gold}\n\n"
    "Model answer:\n{model_answer}\n\n"
    "Return JSON only."
)


def _judge(
    client: anthropic.Anthropic,
    question: str,
    gold: str,
    model_answer: str,
) -> dict[str, Any]:
    if not model_answer.strip():
        return {"faithfulness": 0, "completeness": 0.0, "reasoning": "empty answer"}
    response = client.messages.create(
        model=settings.judge_model,
        max_tokens=300,
        temperature=0.0,
        system=JUDGE_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": JUDGE_USER_TEMPLATE.format(
                    question=question, gold=gold, model_answer=model_answer
                ),
            }
        ],
    )
    text = "".join(
        b.text for b in response.content if getattr(b, "type", None) == "text"
    ).strip()
    if text.startswith("```"):
        # Strip optional code fences if Haiku wraps despite instructions.
        parts = text.split("```")
        text = parts[1] if len(parts) >= 2 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
        return {
            "faithfulness": int(data.get("faithfulness", 0)),
            "completeness": float(data.get("completeness", 0.0)),
            "reasoning": str(data.get("reasoning", "")).strip(),
        }
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        return {
            "faithfulness": 0,
            "completeness": 0.0,
            "reasoning": f"judge parse error: {e}; raw={text[:120]!r}",
        }


# ---------- runner ----------

def load_cases(path: Path = QUESTIONS_PATH) -> list[EvalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [EvalCase(**case) for case in raw["cases"]]


def run_one(
    case: EvalCase,
    mode: str,
    k: int,
    candidates: int,
    judge_client: anthropic.Anthropic,
) -> CaseResult:
    gold_set = {_normalize(u) for u in case.gold_source_urls}

    t0 = time.monotonic()
    result: AnswerResult = answer(case.question, k=k, candidates=candidates, mode=mode)
    latency = time.monotonic() - t0

    retrieved_urls = [_normalize(c.source_url) for c in result.retrieved_chunks]
    cited_urls = [_normalize(c.source_url) for c in result.citations]

    hit = _hit_at_k(retrieved_urls, gold_set)
    recall = _recall_at_k(retrieved_urls, gold_set)
    mrr = _reciprocal_rank(retrieved_urls, gold_set)
    cit_hit, cit_prec = _citation_metrics(cited_urls, gold_set)

    judge_result = _judge(judge_client, case.question, case.gold_answer, result.answer)

    return CaseResult(
        id=case.id,
        question=case.question,
        gold_answer=case.gold_answer,
        gold_source_urls=case.gold_source_urls,
        tags=case.tags,
        mode=mode,
        answer=result.answer,
        retrieved_urls=retrieved_urls,
        cited_urls=cited_urls,
        hit_at_k=hit,
        recall_at_k=recall,
        mrr=mrr,
        citation_hit=cit_hit,
        citation_precision=cit_prec,
        judge_faithfulness=judge_result["faithfulness"],
        judge_completeness=judge_result["completeness"],
        judge_reasoning=judge_result["reasoning"],
        latency_s=latency,
        input_tokens=result.usage.get("input_tokens", 0),
        output_tokens=result.usage.get("output_tokens", 0),
    )


def aggregate(results: list[CaseResult]) -> dict[str, float]:
    if not results:
        return {}
    n = len(results)
    return {
        "n": n,
        "hit_at_k": sum(r.hit_at_k for r in results) / n,
        "recall_at_k": sum(r.recall_at_k for r in results) / n,
        "mrr": sum(r.mrr for r in results) / n,
        "citation_hit": sum(r.citation_hit for r in results) / n,
        "citation_precision": sum(r.citation_precision for r in results) / n,
        "judge_faithfulness": sum(r.judge_faithfulness for r in results) / n,
        "judge_completeness": sum(r.judge_completeness for r in results) / n,
        "avg_latency_s": sum(r.latency_s for r in results) / n,
        "median_latency_s": statistics.median(r.latency_s for r in results),
        "total_input_tokens": sum(r.input_tokens for r in results),
        "total_output_tokens": sum(r.output_tokens for r in results),
    }


# ---------- reporting ----------

def _failure_block(r: CaseResult) -> list[str]:
    lines = [
        f"#### {r.id}: {r.question}",
        "",
        f"- gold URLs: {', '.join(r.gold_source_urls)}",
        f"- retrieval: hit={'Y' if r.hit_at_k else 'N'} recall={r.recall_at_k:.2f} mrr={r.mrr:.3f}",
        f"- citation: hit={'Y' if r.citation_hit else 'N'} precision={r.citation_precision:.2f}",
        f"- judge: faithfulness={r.judge_faithfulness} completeness={r.judge_completeness:.2f}",
        f"- judge note: {r.judge_reasoning}",
        f"- top retrieved: {r.retrieved_urls[:3]}",
        f"- model answer: {r.answer[:300]}{'...' if len(r.answer) > 300 else ''}",
        "",
    ]
    return lines


def to_report_md(by_mode: dict[str, list[CaseResult]], k: int, ts: str) -> str:
    lines: list[str] = []
    lines.append("# Evaluation report")
    lines.append("")
    lines.append(f"- Run timestamp (UTC): `{ts}`")
    lines.append(f"- k = {k}")
    lines.append(f"- Answer model: `{settings.answer_model}`")
    lines.append(f"- Judge model: `{settings.judge_model}`")
    lines.append(f"- Embedding provider: `{settings.embedding_provider}`")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| mode | n | hit@k | recall@k | MRR | cit_hit | cit_prec | faith | compl | lat_med |")
    lines.append("|------|---:|------:|---------:|----:|--------:|---------:|------:|------:|--------:|")
    for mode, results in by_mode.items():
        agg = aggregate(results)
        if not agg:
            continue
        lines.append(
            f"| {mode} | {int(agg['n'])} | {agg['hit_at_k']:.2f} | "
            f"{agg['recall_at_k']:.2f} | {agg['mrr']:.3f} | "
            f"{agg['citation_hit']:.2f} | {agg['citation_precision']:.2f} | "
            f"{agg['judge_faithfulness']:.2f} | {agg['judge_completeness']:.2f} | "
            f"{agg['median_latency_s']:.2f}s |"
        )
    lines.append("")

    for mode, results in by_mode.items():
        lines.append(f"## {mode} mode, per-case detail")
        lines.append("")
        lines.append("| id | hit | recall | mrr | cit | faith | compl | lat |")
        lines.append("|----|----:|-------:|----:|----:|------:|------:|----:|")
        for r in results:
            lines.append(
                f"| {r.id} | {'Y' if r.hit_at_k else 'N'} | {r.recall_at_k:.2f} | "
                f"{r.mrr:.3f} | {'Y' if r.citation_hit else 'N'} | "
                f"{r.judge_faithfulness} | {r.judge_completeness:.2f} | {r.latency_s:.2f}s |"
            )
        lines.append("")

        failures = [
            r
            for r in results
            if (not r.hit_at_k) or r.judge_faithfulness == 0 or r.judge_completeness < 0.5
        ]
        if failures:
            lines.append(f"### Where the system fell short ({len(failures)} cases)")
            lines.append("")
            for r in failures:
                lines.extend(_failure_block(r))

    return "\n".join(lines).rstrip() + "\n"


def _print_summary(by_mode: dict[str, list[CaseResult]], k: int) -> None:
    table = Table(title=f"eval summary  (k={k})", header_style="bold")
    table.add_column("mode")
    table.add_column("n", justify="right")
    table.add_column("hit@k", justify="right")
    table.add_column("recall@k", justify="right")
    table.add_column("MRR", justify="right")
    table.add_column("cit hit", justify="right")
    table.add_column("cit prec", justify="right")
    table.add_column("faith", justify="right")
    table.add_column("compl", justify="right")
    table.add_column("lat med", justify="right")
    for mode, results in by_mode.items():
        agg = aggregate(results)
        if not agg:
            continue
        table.add_row(
            mode,
            str(int(agg["n"])),
            f"{agg['hit_at_k']:.2f}",
            f"{agg['recall_at_k']:.2f}",
            f"{agg['mrr']:.3f}",
            f"{agg['citation_hit']:.2f}",
            f"{agg['citation_precision']:.2f}",
            f"{agg['judge_faithfulness']:.2f}",
            f"{agg['judge_completeness']:.2f}",
            f"{agg['median_latency_s']:.2f}s",
        )
    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the doc-qa eval harness.")
    parser.add_argument("--k", type=int, default=5, help="Final chunks per case.")
    parser.add_argument("--candidates", type=int, default=20,
                        help="Initial RRF pool size for hybrid mode.")
    parser.add_argument("--modes", default="hybrid,vector",
                        help="Comma-separated retrieval modes to run.")
    parser.add_argument("--filter", default=None,
                        help="Run only cases whose id contains this substring.")
    parser.add_argument("--out-dir", default=str(REPORTS_DIR),
                        help="Directory to write the .md and .json report.")
    args = parser.parse_args()

    if not settings.anthropic_api_key:
        raise SystemExit("ANTHROPIC_API_KEY missing. Add it to .env.")

    cases = load_cases()
    if args.filter:
        cases = [c for c in cases if args.filter in c.id]
    if not cases:
        raise SystemExit("No cases to run.")

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    judge_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    console.print(
        f"running [bold]{len(cases)}[/] cases x {len(modes)} modes "
        f"(k={args.k}, candidates={args.candidates})"
    )

    by_mode: dict[str, list[CaseResult]] = {m: [] for m in modes}
    columns = [
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    ]
    with Progress(*columns, console=console) as progress:
        task = progress.add_task("eval", total=len(cases) * len(modes))
        for mode in modes:
            for case in cases:
                progress.update(task, description=f"[{mode}] {case.id}")
                try:
                    res = run_one(case, mode, args.k, args.candidates, judge_client)
                    by_mode[mode].append(res)
                except Exception as e:
                    console.print(f"  [red]error[/] {case.id} ({mode}): {e}")
                progress.update(task, advance=1)

    _print_summary(by_mode, args.k)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    md_path = out_dir / f"eval_{ts}.md"
    json_path = out_dir / f"eval_{ts}.json"

    md_path.write_text(to_report_md(by_mode, args.k, ts), encoding="utf-8")
    json_payload = {
        "timestamp": ts,
        "k": args.k,
        "candidates": args.candidates,
        "answer_model": settings.answer_model,
        "judge_model": settings.judge_model,
        "embedding_provider": settings.embedding_provider,
        "by_mode": {
            mode: {"summary": aggregate(results), "cases": [asdict(r) for r in results]}
            for mode, results in by_mode.items()
        },
    }
    json_path.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")

    console.print(f"\nreport: [bold cyan]{md_path}[/]")
    console.print(f"raw:    [bold cyan]{json_path}[/]")


if __name__ == "__main__":
    main()
