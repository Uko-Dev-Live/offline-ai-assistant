#!/usr/bin/env python3
"""Command-line LLM benchmark.

Run from the project root:

    python -m scripts.benchmark                 # default 5 runs, 1 warmup
    python -m scripts.benchmark --runs 10
    python -m scripts.benchmark --prompt "Write a haiku about Linux."
    python -m scripts.benchmark --warmup 0      # skip warmup (will include cold-start cost)

Results are saved to ./benchmarks/benchmark-<timestamp>.{json,csv}.

Tips for fair measurements
--------------------------
  * Always include at least 1 warmup run. The first request after Ollama
    starts (or after the model has been evicted from RAM) pays a one-off
    "load" cost that can dominate everything else.
  * Close other heavy applications. CPU contention skews tokens/sec wildly.
  * Use the same prompt across compared models. Different prompt lengths
    change `prompt_eval_duration` (which doesn't show up in tokens/sec but
    *does* show up in TTFT).
  * Run at least 5 measurements and look at median + p95, not just mean.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

# Make the `app` package importable when running this file directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import benchmark  # noqa: E402
from app.config import settings  # noqa: E402
from app.llm import OllamaError  # noqa: E402


DEFAULT_PROMPTS = [
    "Explain what an operating system kernel does in three short sentences.",
    "Write a Python function that returns the nth Fibonacci number.",
    "Summarize the plot of Romeo and Juliet in roughly 50 words.",
    "List five practical tips for writing maintainable code.",
    "What is the difference between TCP and UDP? Be concise.",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark the offline LLM.")
    p.add_argument("--prompt", help="Single prompt to repeat. Default: rotates 5 prompts.")
    p.add_argument("--runs", type=int, default=5, help="Number of measured runs.")
    p.add_argument("--warmup", type=int, default=1, help="Warmup runs (excluded).")
    p.add_argument("--out-dir", default="benchmarks", help="Where to save results.")
    p.add_argument("--no-save", action="store_true", help="Don't write result files.")
    return p.parse_args()


async def main() -> int:
    args = parse_args()

    if args.prompt:
        prompts = [args.prompt] * args.runs
    else:
        prompts = [DEFAULT_PROMPTS[i % len(DEFAULT_PROMPTS)] for i in range(args.runs)]

    print(f"Model: {settings.model}")
    print(f"Ollama: {settings.ollama_url}")
    print()

    # ---------- Warmup ----------
    for i in range(args.warmup):
        print(f"  warmup {i + 1}/{args.warmup} ...", end=" ", flush=True)
        try:
            r = await benchmark.run_single("Say hi briefly.")
            print(f"ok ({r.tokens_per_second:.1f} tok/s, load={r.load_duration_s:.2f}s)")
        except OllamaError as exc:
            print(f"FAIL: {exc}")
            return 2

    # ---------- Measured runs ----------
    print(f"\nRunning {args.runs} measured run(s):\n")
    print(f"  {'#':<3} {'TTFT (ms)':>11} {'Total (ms)':>12} "
          f"{'Tokens':>8} {'tok/s':>9} {'wall tok/s':>12}")
    print("  " + "-" * 64)

    results: list[benchmark.BenchmarkResult] = []
    for i, prompt in enumerate(prompts, 1):
        try:
            r = await benchmark.run_single(prompt)
        except OllamaError as exc:
            print(f"  {i:<3} ERROR: {exc}")
            continue
        results.append(r)
        print(
            f"  {i:<3} {r.ttft_ms:>11.1f} {r.total_latency_ms:>12.1f} "
            f"{r.tokens_generated:>8} {r.tokens_per_second:>9.1f} "
            f"{r.wall_tokens_per_second:>12.1f}"
        )

    if not results:
        print("\nNo successful runs.", file=sys.stderr)
        return 1

    # ---------- Summary ----------
    agg = benchmark.aggregate(results)
    print("\nAggregate over", len(results), "run(s):")
    print(f"  TTFT (ms)            : median={agg['ttft_ms']['median']:>8.1f}  "
          f"p95={agg['ttft_ms']['p95']:>8.1f}")
    print(f"  Total latency (ms)   : median={agg['total_latency_ms']['median']:>8.1f}  "
          f"p95={agg['total_latency_ms']['p95']:>8.1f}")
    print(f"  Tokens / sec (model) : median={agg['tokens_per_second']['median']:>8.1f}  "
          f"min={agg['tokens_per_second']['min']:>8.1f}")
    print(f"  Tokens / sec (wall)  : median={agg['wall_tokens_per_second']['median']:>8.1f}  "
          f"min={agg['wall_tokens_per_second']['min']:>8.1f}")

    # ---------- Save ----------
    if not args.no_save:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        json_file = out_dir / f"benchmark-{ts}.json"
        csv_file = out_dir / f"benchmark-{ts}.csv"

        with json_file.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "timestamp": ts,
                    "model": results[0].model,
                    "settings": {
                        "temperature": settings.temperature,
                        "num_ctx": settings.num_ctx,
                    },
                    "runs": [asdict(r) for r in results],
                    "aggregate": agg,
                },
                f,
                indent=2,
            )

        with csv_file.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()))
            writer.writeheader()
            for r in results:
                writer.writerow(asdict(r))

        print(f"\nSaved: {json_file}")
        print(f"       {csv_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
