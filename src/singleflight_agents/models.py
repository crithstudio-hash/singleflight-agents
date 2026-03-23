from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Receipt:
    """Signed envelope of a single tool execution, stored in the receipt database."""

    fingerprint: str
    tool_name: str
    scope: str
    args_hash: str
    input_json: str
    output_json: str
    output_preview: str
    signature: str
    created_at: float
    expires_at: float
    latency_ms: float
    cost_usd: float
    executor_id: str
    reuse_count: int = 0


@dataclass(slots=True)
class ExecutionOutcome:
    """Result of a tool execution: the value, its receipt, and how it was obtained."""

    value: Any
    receipt: Receipt
    source: str


@dataclass(slots=True)
class ToolExecutionOptions:
    """Per-tool configuration for singleflight deduplication.

    Set ``deterministic=True`` for pure functions, ``bounded_read=True`` for
    read-only calls, or ``side_effecting=True`` to disable sharing entirely.
    """

    tool_name: str
    scope: str = "default"
    namespace: str = "singleflight"
    version: str = "v1"
    ttl_seconds: float = 300.0
    lease_seconds: float = 30.0
    wait_timeout_seconds: float = 35.0
    poll_interval_seconds: float = 0.05
    estimated_cost_usd: float = 0.0
    deterministic: bool = False
    bounded_read: bool = False
    side_effecting: bool = False
    share_failures: bool = False

    @property
    def shareable(self) -> bool:
        if self.side_effecting:
            return False
        return self.deterministic or self.bounded_read
