# API Reference

## Core

### `Singleflight`

**Module**: `singleflight_agents`

The main engine. Manages tool execution, deduplication, and receipt storage.

```python
from singleflight_agents import Singleflight

sf = Singleflight(db_path=None)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `db_path` | `str \| None` | `None` | Path to SQLite database. Defaults to `.singleflight/receipts.db` in the current directory. |

**Methods:**

#### `tool(**kwargs) -> decorator`

Returns a decorator that wraps a sync or async function with singleflight deduplication. Keyword arguments are forwarded to `ToolExecutionOptions`.

```python
@sf.tool(tool_name="search", ttl_seconds=300, deterministic=True)
def search(query: str) -> dict:
    ...
```

#### `execute(func, *args, options, **kwargs) -> ExecutionOutcome`

Async. Execute a tool call with deduplication. Returns an `ExecutionOutcome`.

```python
outcome = await sf.execute(my_func, "arg1", options=options)
```

#### `execute_sync(func, *args, options, **kwargs) -> ExecutionOutcome`

Synchronous wrapper around `execute()`. Creates a new event loop with `asyncio.run()`.

#### `summary() -> dict`

Returns aggregate receipt statistics:

```python
{
    "unique_executions": 3,
    "avoided_calls": 7,
    "dollars_saved": 0.84,
    "latency_saved_ms": 7000.0,
    "tools": [...],
    "db_path": ".singleflight/receipts.db"
}
```

#### `verify_receipt(receipt) -> bool`

Verify the HMAC-SHA256 signature on a receipt. Returns `True` if the receipt has not been tampered with.

---

### `ToolExecutionOptions`

**Module**: `singleflight_agents`

Per-tool configuration for deduplication behavior.

```python
from singleflight_agents import ToolExecutionOptions

options = ToolExecutionOptions(
    tool_name="crm.lookup",
    ttl_seconds=300,
    estimated_cost_usd=0.02,
    deterministic=True,
)
```

**Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tool_name` | `str` | *required* | Identifier for the tool (used in fingerprinting and reporting). |
| `scope` | `str` | `"default"` | Logical scope for partitioning receipts. |
| `namespace` | `str` | `"singleflight"` | Namespace prefix in the fingerprint key. |
| `version` | `str` | `"v1"` | Version string included in fingerprinting. |
| `ttl_seconds` | `float` | `300.0` | How long a receipt remains valid (seconds). |
| `lease_seconds` | `float` | `30.0` | How long a lease is held before expiring. |
| `wait_timeout_seconds` | `float` | `35.0` | How long waiters poll for a receipt before giving up. |
| `poll_interval_seconds` | `float` | `0.05` | Polling interval for waiters (seconds). |
| `estimated_cost_usd` | `float` | `0.0` | Estimated cost per execution (used in summary reporting). |
| `deterministic` | `bool` | `False` | True if same inputs always produce the same output. Enables sharing. |
| `bounded_read` | `bool` | `False` | True if the tool is read-only with short-lived freshness. Enables sharing. |
| `side_effecting` | `bool` | `False` | True if the tool writes, sends, or mutates state. **Disables sharing.** |
| `share_failures` | `bool` | `False` | Whether to cache and share failed executions. |

**Property:**

- `shareable -> bool`: Returns `True` if `not side_effecting and (deterministic or bounded_read)`.

---

### `Receipt`

**Module**: `singleflight_agents`

Signed envelope of a single tool execution.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `fingerprint` | `str` | Unique key for this tool+args combination. |
| `tool_name` | `str` | Name of the tool that was executed. |
| `scope` | `str` | Scope partition. |
| `args_hash` | `str` | SHA-256 hex digest of the normalized arguments. |
| `input_json` | `str` | Canonical JSON of the fingerprint payload. |
| `output_json` | `str` | Serialized output value (JSON or base64 pickle). |
| `output_preview` | `str` | Truncated `repr()` of the output (max 120 chars). |
| `signature` | `str` | HMAC-SHA256 hex digest for tamper detection. |
| `created_at` | `float` | Unix timestamp when the receipt was created. |
| `expires_at` | `float` | Unix timestamp when the receipt expires. |
| `latency_ms` | `float` | Execution time in milliseconds. |
| `cost_usd` | `float` | Estimated cost of the execution. |
| `executor_id` | `str` | UUID of the lease holder that executed. |
| `reuse_count` | `int` | Number of times this receipt was reused. |

---

### `ExecutionOutcome`

**Module**: `singleflight_agents`

Result wrapper returned by `execute()` and `execute_sync()`.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `value` | `Any` | The deserialized return value of the tool. |
| `receipt` | `Receipt` | The signed receipt for this execution. |
| `source` | `str` | How the result was obtained (see below). |

**Source values:**

| Source | Meaning |
|--------|---------|
| `"executed"` | This caller won the lease and ran the tool. |
| `"cache_hit"` | A valid receipt already existed in the store. |
| `"shared_wait"` | Another caller was executing; this caller waited and got the shared result. |
| `"executed_unshared"` | Tool is side-effecting; executed without dedup. |
| `"executed_fallback"` | All dedup paths failed; executed directly as a last resort. |

---

## Fingerprinting

### `make_fingerprint(**kwargs) -> Fingerprint`

**Module**: `singleflight_agents.fingerprint`

Generates a deterministic cache key from tool name, arguments, scope, namespace, and version. Arguments are recursively normalized (dicts sorted by key, sets sorted) before SHA-256 hashing.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `tool_name` | `str` | Tool identifier. |
| `args` | `tuple` | Positional arguments. |
| `kwargs` | `dict` | Keyword arguments. |
| `scope` | `str` | Scope partition. |
| `namespace` | `str` | Namespace prefix. |
| `version` | `str` | Version string. |

**Returns:** `Fingerprint` with fields `key`, `payload_json`, `args_hash`.

---

## Store

### `ReceiptStore`

**Module**: `singleflight_agents.store`

SQLite-backed store for receipts and leases. Handles HMAC signing, lease acquisition, and aggregate queries. You normally don't interact with this directly — `Singleflight` manages it internally.

---

## Adapters

### `function_tool(singleflight, **kwargs) -> decorator`

**Module**: `singleflight_agents.adapters`

Decorator for OpenAI Agents SDK. Wraps a function with singleflight dedup and registers it as an OpenAI tool. Requires `pip install -e .[openai]`.

### `wrap_langgraph_node(singleflight, func, **kwargs) -> Callable`

**Module**: `singleflight_agents.adapters`

Wraps a sync function with singleflight dedup for use as a LangGraph node. Requires `pip install -e .[langgraph]`.

---

## Reporting

### `format_summary(summary) -> str`

**Module**: `singleflight_agents.reporting`

Renders a plain-text summary report from the dict returned by `Singleflight.summary()`. Includes a bar chart of per-tool reuse counts.
