from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass

from singleflight_agents import Singleflight, ToolExecutionOptions
from singleflight_agents.reporting import format_summary


@dataclass
class DemoMetrics:
    actual_calls: int = 0
    actual_cost_usd: float = 0.0


async def run_demo(db_path: str | None = None) -> None:
    metrics = DemoMetrics()
    singleflight = Singleflight(db_path=db_path)

    async def expensive_search(query: str) -> dict[str, str | float]:
        metrics.actual_calls += 1
        metrics.actual_cost_usd += 0.12
        await asyncio.sleep(1.0)
        return {
            "query": query,
            "answer": f"Result for {query}",
            "fetched_at": round(time.time(), 3),
        }

    duplicate_queries = [
        "pricing page churn",
        "pricing page churn",
        "pricing page churn",
        "error budget policy",
        "error budget policy",
        "launch checklist",
    ]

    print("Baseline: every agent executes its own tool call.")
    started = time.perf_counter()
    baseline_results = await asyncio.gather(*(expensive_search(query) for query in duplicate_queries))
    baseline_latency = time.perf_counter() - started
    print(f"  Actual executions: {metrics.actual_calls}")
    print(f"  Actual cost: ${metrics.actual_cost_usd:.2f}")
    print(f"  Wall-clock latency: {baseline_latency:.2f}s")
    print(f"  Distinct answers: {len({result['query'] for result in baseline_results})}")
    print("")

    metrics.actual_calls = 0
    metrics.actual_cost_usd = 0.0
    options = ToolExecutionOptions(
        tool_name="demo.search",
        ttl_seconds=120,
        lease_seconds=10,
        wait_timeout_seconds=12,
        estimated_cost_usd=0.12,
        bounded_read=True,
    )

    async def wrapped(query: str):
        return await singleflight.execute(expensive_search, query, options=options)

    print("Singleflight: one execution per unique in-flight query.")
    started = time.perf_counter()
    outcomes = await asyncio.gather(*(wrapped(query) for query in duplicate_queries))
    deduped_latency = time.perf_counter() - started
    source_counts = Counter(outcome.source for outcome in outcomes)
    print(f"  Actual executions: {metrics.actual_calls}")
    print(f"  Actual cost: ${metrics.actual_cost_usd:.2f}")
    print(f"  Wall-clock latency: {deduped_latency:.2f}s")
    print(f"  Execution sources: {dict(source_counts)}")
    print("")

    print(format_summary(singleflight.summary()))


async def verify_runtime(db_path: str | None = None) -> bool:
    singleflight = Singleflight(db_path=db_path)
    call_count = 0

    async def deterministic_lookup(key: str) -> dict[str, str]:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return {"key": key, "value": key.upper()}

    options = ToolExecutionOptions(
        tool_name="verify.lookup",
        ttl_seconds=60,
        lease_seconds=5,
        wait_timeout_seconds=5,
        estimated_cost_usd=0.01,
        deterministic=True,
    )
    outcomes = await asyncio.gather(
        *(singleflight.execute(deterministic_lookup, "agent", options=options) for _ in range(4))
    )
    ok = (
        call_count == 1
        and len({outcome.value["value"] for outcome in outcomes}) == 1
        and singleflight.verify_receipt(outcomes[0].receipt)
    )
    print("verify:", "pass" if ok else "fail")
    return ok
