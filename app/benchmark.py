"""Benchmark the LLM: time-to-first-token, tokens/sec, total latency.

Two views of speed are reported:

  * `tokens_per_second`        — generated tokens divided by the time the model
                                 reported it spent generating (from Ollama's
                                 `eval_duration`). This is the "pure" model speed.

  * `wall_tokens_per_second`   — generated tokens divided by wall-clock time
                                 *after* the first token. This is what a user
                                 perceives once streaming has started.

  * `ttft_ms`                  — time from sending the request until the first
                                 token of content arrives. Includes prompt
                                 processing and (on a cold start) model load.

  * `total_latency_ms`         — full wall-clock time from request to last token.

Run via the FastAPI endpoint or as a CLI: `python -m scripts.benchmark`.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass

from . import llm
from .config import settings


@dataclass
class BenchmarkResult:
    prompt: str
    model: str
    ttft_ms: float
    total_latency_ms: float
    tokens_generated: int
    prompt_tokens: int
    tokens_per_second: float          # eval-duration based (model-reported)
    wall_tokens_per_second: float     # wall-clock based (user-perceived)
    load_duration_s: float            # > 0 only on a cold start


async def run_single(prompt: str) -> BenchmarkResult:
    """Run one timed request against the configured model."""
    messages = [
        {"role": "system", "content": settings.system_prompt},
        {"role": "user", "content": prompt},
    ]
    m = await llm.stream_chat_with_metrics(messages)

    eval_count = m["eval_count"]
    # Guard against zero-division when the run is unusually short.
    eval_dur = max(m["eval_duration_s"], 1e-6)
    wall_after_ttft = max(m["total_s"] - m["ttft_s"], 1e-6)

    return BenchmarkResult(
        prompt=prompt,
        model=settings.model,
        ttft_ms=round(m["ttft_s"] * 1000, 2),
        total_latency_ms=round(m["total_s"] * 1000, 2),
        tokens_generated=eval_count,
        prompt_tokens=m["prompt_eval_count"],
        tokens_per_second=round(eval_count / eval_dur, 2),
        wall_tokens_per_second=round(eval_count / wall_after_ttft, 2),
        load_duration_s=round(m["load_duration_s"], 3),
    )


def _stats(values: list[float]) -> dict:
    if not values:
        return {}
    sv = sorted(values)

    def pct(p: float) -> float:
        # Nearest-rank percentile, clamped to the last index.
        idx = max(0, min(len(sv) - 1, int(round(p / 100 * (len(sv) - 1)))))
        return sv[idx]

    return {
        "mean": round(statistics.fmean(values), 2),
        "median": round(statistics.median(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "p95": round(pct(95), 2),
        "stdev": round(statistics.pstdev(values), 2) if len(values) > 1 else 0.0,
    }


def aggregate(results: list[BenchmarkResult]) -> dict:
    """Summarise a list of runs into mean/median/p95/etc."""
    if not results:
        return {"runs": 0}
    return {
        "runs": len(results),
        "model": results[0].model,
        "ttft_ms": _stats([r.ttft_ms for r in results]),
        "total_latency_ms": _stats([r.total_latency_ms for r in results]),
        "tokens_per_second": _stats([r.tokens_per_second for r in results]),
        "wall_tokens_per_second": _stats([r.wall_tokens_per_second for r in results]),
        "tokens_generated": _stats([float(r.tokens_generated) for r in results]),
    }


def to_dicts(results: list[BenchmarkResult]) -> list[dict]:
    return [asdict(r) for r in results]
