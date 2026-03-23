from __future__ import annotations

import asyncio
import base64
import functools
import inspect
import json
import pickle
import time
import uuid
from typing import Any, Awaitable, Callable, TypeVar, cast

from .fingerprint import make_fingerprint
from .models import ExecutionOutcome, Receipt, ToolExecutionOptions
from .store import ReceiptStore

F = TypeVar("F", bound=Callable[..., Any])


class Singleflight:
    """Collapses duplicate in-flight tool calls into a single execution.

    Wraps tool functions so that concurrent identical calls are deduplicated
    via fingerprint-based leasing. Results are stored as HMAC-signed receipts
    in a local SQLite database and shared with all waiters.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.store = ReceiptStore(db_path)

    def tool(self, **kwargs: Any) -> Callable[[F], F]:
        """Decorator that wraps a sync or async function with singleflight deduplication.

        Keyword arguments are forwarded to ``ToolExecutionOptions``.
        """
        options = ToolExecutionOptions(**kwargs)

        def decorator(func: F) -> F:
            if inspect.iscoroutinefunction(func):

                @functools.wraps(func)
                async def async_wrapper(*args: Any, **inner_kwargs: Any) -> Any:
                    outcome = await self.execute(func, *args, options=options, **inner_kwargs)
                    return outcome.value

                return cast(F, async_wrapper)

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **inner_kwargs: Any) -> Any:
                outcome = self.execute_sync(func, *args, options=options, **inner_kwargs)
                return outcome.value

            return cast(F, sync_wrapper)

        return decorator

    async def execute(
        self,
        func: Callable[..., Any],
        *args: Any,
        options: ToolExecutionOptions,
        **kwargs: Any,
    ) -> ExecutionOutcome:
        """Execute a tool call with singleflight deduplication (async).

        Returns an ``ExecutionOutcome`` whose ``source`` field indicates how
        the result was obtained: ``"executed"``, ``"cache_hit"``,
        ``"shared_wait"``, ``"executed_unshared"``, or ``"executed_fallback"``.
        """
        if not options.shareable:
            return await self._execute_direct(func, args, kwargs, options, source="executed_unshared")

        fingerprint = make_fingerprint(
            tool_name=options.tool_name,
            args=args,
            kwargs=kwargs,
            scope=options.scope,
            namespace=options.namespace,
            version=options.version,
        )
        cached = self.store.fetch_valid_receipt(fingerprint.key)
        if cached is not None:
            self.store.record_reuse(fingerprint.key)
            latest = self.store.fetch_valid_receipt(fingerprint.key) or cached
            return ExecutionOutcome(
                value=self._load_value(latest.output_json),
                receipt=latest,
                source="cache_hit",
            )

        owner_id = uuid.uuid4().hex
        acquired = self.store.try_acquire_lease(
            fingerprint=fingerprint.key,
            owner_id=owner_id,
            lease_seconds=options.lease_seconds,
        )
        if acquired:
            try:
                return await self._execute_shared(
                    func,
                    args,
                    kwargs,
                    options,
                    fingerprint.key,
                    fingerprint.args_hash,
                    fingerprint.payload_json,
                    owner_id,
                )
            finally:
                self.store.release_lease(fingerprint.key, owner_id)

        waited = await asyncio.to_thread(
            self.store.wait_for_receipt,
            fingerprint.key,
            timeout_seconds=options.wait_timeout_seconds,
            poll_interval_seconds=options.poll_interval_seconds,
        )
        if waited is not None:
            self.store.record_reuse(fingerprint.key)
            latest = self.store.fetch_valid_receipt(fingerprint.key) or waited
            return ExecutionOutcome(
                value=self._load_value(latest.output_json),
                receipt=latest,
                source="shared_wait",
            )

        acquired_after_wait = self.store.try_acquire_lease(
            fingerprint=fingerprint.key,
            owner_id=owner_id,
            lease_seconds=options.lease_seconds,
        )
        if acquired_after_wait:
            try:
                return await self._execute_shared(
                    func,
                    args,
                    kwargs,
                    options,
                    fingerprint.key,
                    fingerprint.args_hash,
                    fingerprint.payload_json,
                    owner_id,
                )
            finally:
                self.store.release_lease(fingerprint.key, owner_id)

        refreshed = self.store.fetch_valid_receipt(fingerprint.key)
        if refreshed is not None:
            self.store.record_reuse(fingerprint.key)
            latest = self.store.fetch_valid_receipt(fingerprint.key) or refreshed
            return ExecutionOutcome(
                value=self._load_value(latest.output_json),
                receipt=latest,
                source="shared_wait",
            )

        return await self._execute_direct(func, args, kwargs, options, source="executed_fallback")

    def execute_sync(
        self,
        func: Callable[..., Any],
        *args: Any,
        options: ToolExecutionOptions,
        **kwargs: Any,
    ) -> ExecutionOutcome:
        """Synchronous wrapper around ``execute()``. Creates a new event loop."""
        return asyncio.run(self.execute(func, *args, options=options, **kwargs))

    async def _execute_direct(
        self,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        options: ToolExecutionOptions,
        *,
        source: str,
    ) -> ExecutionOutcome:
        started = time.perf_counter()
        value = await self._invoke(func, *args, **kwargs)
        latency_ms = (time.perf_counter() - started) * 1000
        output_json = self._dump_value(value)
        created_at = time.time()
        expires_at = created_at + options.ttl_seconds
        receipt = Receipt(
            fingerprint=f"unshared:{uuid.uuid4().hex}",
            tool_name=options.tool_name,
            scope=options.scope,
            args_hash="unshared",
            input_json="{}",
            output_json=output_json,
            output_preview=self._preview(value),
            signature="unshared",
            created_at=created_at,
            expires_at=expires_at,
            latency_ms=latency_ms,
            cost_usd=options.estimated_cost_usd,
            executor_id="direct",
            reuse_count=0,
        )
        return ExecutionOutcome(value=value, receipt=receipt, source=source)

    async def _execute_shared(
        self,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        options: ToolExecutionOptions,
        fingerprint: str,
        args_hash: str,
        input_json: str,
        owner_id: str,
    ) -> ExecutionOutcome:
        started = time.perf_counter()
        value = await self._invoke(func, *args, **kwargs)
        latency_ms = (time.perf_counter() - started) * 1000
        output_json = self._dump_value(value)
        created_at = time.time()
        expires_at = created_at + options.ttl_seconds
        signature = self.store.sign(
            fingerprint=fingerprint,
            args_hash=args_hash,
            output_json=output_json,
            created_at=created_at,
            expires_at=expires_at,
            latency_ms=latency_ms,
            cost_usd=options.estimated_cost_usd,
        )
        receipt = Receipt(
            fingerprint=fingerprint,
            tool_name=options.tool_name,
            scope=options.scope,
            args_hash=args_hash,
            input_json=input_json,
            output_json=output_json,
            output_preview=self._preview(value),
            signature=signature,
            created_at=created_at,
            expires_at=expires_at,
            latency_ms=latency_ms,
            cost_usd=options.estimated_cost_usd,
            executor_id=owner_id,
            reuse_count=0,
        )
        self.store.save_receipt(receipt)
        saved = self.store.fetch_valid_receipt(fingerprint)
        assert saved is not None
        return ExecutionOutcome(value=value, receipt=saved, source="executed")

    async def _invoke(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if inspect.iscoroutinefunction(func):
            return await cast(Callable[..., Awaitable[Any]], func)(*args, **kwargs)
        return await asyncio.to_thread(func, *args, **kwargs)

    def summary(self) -> dict[str, Any]:
        """Return aggregate receipt statistics: unique executions, avoided calls, savings."""
        return self.store.summary()

    def verify_receipt(self, receipt: Receipt) -> bool:
        """Verify the HMAC-SHA256 signature on a receipt. Returns True if valid."""
        return self.store.verify(receipt)

    @staticmethod
    def _dump_value(value: Any) -> str:
        try:
            payload = {"encoding": "json", "value": value}
            return json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except TypeError:
            payload = {
                "encoding": "pickle",
                "value_b64": base64.b64encode(pickle.dumps(value)).decode("ascii"),
            }
            return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _load_value(payload_json: str) -> Any:
        payload = json.loads(payload_json)
        if not isinstance(payload, dict) or "encoding" not in payload:
            return payload
        if payload["encoding"] == "json":
            return payload["value"]
        if payload["encoding"] == "pickle":
            return pickle.loads(base64.b64decode(payload["value_b64"].encode("ascii")))
        return payload

    @staticmethod
    def _preview(value: Any) -> str:
        preview = repr(value)
        if len(preview) > 120:
            return preview[:117] + "..."
        return preview
