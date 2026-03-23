from __future__ import annotations

import asyncio
import time
from dataclasses import asdict

from singleflight_agents import Singleflight, ToolExecutionOptions
from singleflight_agents.models import Receipt


def test_parallel_calls_deduplicate(tmp_path):
    db_path = tmp_path / "receipts.db"
    singleflight = Singleflight(db_path=str(db_path))
    call_count = 0

    async def lookup(key: str) -> dict[str, str]:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return {"key": key, "value": key.upper()}

    options = ToolExecutionOptions(
        tool_name="tests.lookup",
        ttl_seconds=30,
        lease_seconds=5,
        wait_timeout_seconds=5,
        deterministic=True,
        estimated_cost_usd=0.01,
    )

    async def run():
        return await asyncio.gather(
            *(singleflight.execute(lookup, "alpha", options=options) for _ in range(4))
        )

    outcomes = asyncio.run(run())
    assert call_count == 1
    assert {outcome.value["value"] for outcome in outcomes} == {"ALPHA"}
    assert {outcome.source for outcome in outcomes} == {"executed", "shared_wait"}
    summary = singleflight.summary()
    assert summary["unique_executions"] == 1
    assert summary["avoided_calls"] == 3


def test_receipt_reused_inside_ttl(tmp_path):
    db_path = tmp_path / "receipts.db"
    singleflight = Singleflight(db_path=str(db_path))
    call_count = 0

    def lookup(key: str) -> dict[str, str]:
        nonlocal call_count
        call_count += 1
        return {"key": key, "value": key.upper()}

    options = ToolExecutionOptions(
        tool_name="tests.lookup_ttl",
        ttl_seconds=30,
        lease_seconds=5,
        wait_timeout_seconds=5,
        deterministic=True,
    )

    first = singleflight.execute_sync(lookup, "beta", options=options)
    second = singleflight.execute_sync(lookup, "beta", options=options)
    assert call_count == 1
    assert first.value == second.value
    assert second.source == "cache_hit"


def test_side_effecting_tools_are_not_shared(tmp_path):
    db_path = tmp_path / "receipts.db"
    singleflight = Singleflight(db_path=str(db_path))
    call_count = 0

    def mutate(counter: int) -> dict[str, int]:
        nonlocal call_count
        call_count += 1
        return {"counter": counter}

    options = ToolExecutionOptions(
        tool_name="tests.mutate",
        ttl_seconds=30,
        lease_seconds=5,
        wait_timeout_seconds=5,
        side_effecting=True,
    )

    first = singleflight.execute_sync(mutate, 1, options=options)
    second = singleflight.execute_sync(mutate, 1, options=options)
    assert call_count == 2
    assert first.source == "executed_unshared"
    assert second.source == "executed_unshared"


def test_receipts_are_signed(tmp_path):
    db_path = tmp_path / "receipts.db"
    singleflight = Singleflight(db_path=str(db_path))

    def lookup(key: str) -> dict[str, str]:
        return {"key": key, "value": key.upper()}

    options = ToolExecutionOptions(
        tool_name="tests.signed",
        ttl_seconds=30,
        lease_seconds=5,
        wait_timeout_seconds=5,
        deterministic=True,
    )

    outcome = singleflight.execute_sync(lookup, "gamma", options=options)
    assert singleflight.verify_receipt(outcome.receipt)
    tampered = Receipt(**{**asdict(outcome.receipt), "output_json": '{"value":"tampered"}'})
    assert not singleflight.verify_receipt(tampered)


def test_expired_receipts_do_not_reuse(tmp_path):
    db_path = tmp_path / "receipts.db"
    singleflight = Singleflight(db_path=str(db_path))
    call_count = 0

    def lookup(key: str) -> dict[str, float]:
        nonlocal call_count
        call_count += 1
        return {"key": key, "time": time.time()}

    options = ToolExecutionOptions(
        tool_name="tests.expiry",
        ttl_seconds=0.1,
        lease_seconds=5,
        wait_timeout_seconds=5,
        bounded_read=True,
    )

    first = singleflight.execute_sync(lookup, "delta", options=options)
    time.sleep(0.15)
    second = singleflight.execute_sync(lookup, "delta", options=options)
    assert call_count == 2
    assert first.value != second.value
