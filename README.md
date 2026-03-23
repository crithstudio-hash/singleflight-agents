# singleflight-agents

Stop paying twice for the same agent work.

`singleflight-agents` collapses duplicate tool calls across parallel agents, retries, and branches into **one real execution**. Everyone else gets a signed copy of the result.

Zero runtime dependencies. Pure Python stdlib.

---

## What this does

When multiple AI agents call the same tool with the same arguments at the same time, only one actually runs. The others wait and share the result. If the same call happens again within the TTL window, it returns the cached result instantly.

Think of it as request deduplication for agent tool calls.

## How it works

```
Agent A ──┐
Agent B ──┤── same tool + same args ──> Fingerprint ──> Lease check
Agent C ──┘
              │
              ├── First caller wins the lease ──> Executes the tool
              │                                        │
              │                                   Signs result as Receipt
              │                                   Stores in SQLite
              │                                        │
              └── Other callers wait ──────────> Get the same Receipt
                                                       │
              Future calls (within TTL) ──────> Cache hit, no execution
```

**Step by step:**

1. **Fingerprint** — Tool name + arguments get hashed (SHA-256) into a unique key.
2. **Lease** — The first caller acquires an exclusive lock on that key. Everyone else waits.
3. **Execute** — The lease holder runs the tool and gets the result.
4. **Receipt** — The result is signed (HMAC-SHA256), timestamped, and stored in SQLite.
5. **Fan out** — All waiting callers get the same signed receipt. Future calls within the TTL reuse it from cache.

If the lease holder crashes, the lock expires and a waiter takes over automatically.

## Quickstart

```bash
pip install -e .[dev]
python -m singleflight_agents demo
```

You will see:

- A **baseline run** where every agent executes its own call (6 executions, ~$0.72, ~1s each)
- A **singleflight run** where duplicates are collapsed (3 executions, ~$0.36, shared results)
- A **summary report** showing avoided calls, dollars saved, and latency saved

## Usage

### Decorator (simplest)

```python
from singleflight_agents import Singleflight

sf = Singleflight()

@sf.tool(
    tool_name="crm.lookup_customer",
    ttl_seconds=300,
    estimated_cost_usd=0.02,
    deterministic=True,
)
def lookup_customer(email: str) -> dict:
    return call_crm_api(email)
```

Every identical in-flight call collapses into one execution. Later calls inside the TTL reuse the signed receipt.

### Direct execution

```python
from singleflight_agents import Singleflight, ToolExecutionOptions

sf = Singleflight()
options = ToolExecutionOptions(
    tool_name="search.web",
    ttl_seconds=120,
    estimated_cost_usd=0.10,
    bounded_read=True,
)

outcome = await sf.execute(my_search_function, "query text", options=options)
print(outcome.value)       # the result
print(outcome.source)      # "executed", "cache_hit", "shared_wait", etc.
print(outcome.receipt)      # signed receipt with metadata
```

## Safety rules

`singleflight-agents` only shares work when you tell it the tool is safe:

| Flag | Meaning | Shared? |
|------|---------|---------|
| `deterministic=True` | Same inputs always produce the same output | Yes |
| `bounded_read=True` | Read-only call with short-lived freshness | Yes |
| `side_effecting=True` | Writes, sends, deletes, or mutates state | **Never** |

If none of these flags are set, the tool is not shared. Side-effecting tools are always executed independently even if inputs match.

**Do not** use this on refund endpoints, message senders, write APIs, or anything that changes state.

## CLI

```bash
python -m singleflight_agents demo            # Run the built-in demo
python -m singleflight_agents summary         # Print receipt summary
python -m singleflight_agents verify          # Run a self-check
python -m singleflight_agents openai-demo     # OpenAI Agents SDK example
python -m singleflight_agents langgraph-demo  # LangGraph example
```

All commands accept `--db path/to/receipts.db` to use a specific database.

## Framework adapters

### OpenAI Agents SDK

```bash
pip install -e .[openai]
```

```python
from singleflight_agents import Singleflight
from singleflight_agents.adapters import function_tool

sf = Singleflight()

@function_tool(
    sf,
    tool_name="account.lookup",
    ttl_seconds=120,
    estimated_cost_usd=0.08,
    bounded_read=True,
)
def lookup_account(email: str) -> str:
    return f"Account for {email}: plan=enterprise"
```

The decorated function works as a standard OpenAI Agents SDK tool with deduplication built in.

### LangGraph

```bash
pip install -e .[langgraph]
```

```python
from singleflight_agents import Singleflight
from singleflight_agents.adapters import wrap_langgraph_node

sf = Singleflight()

def knowledge_lookup(query: str) -> str:
    return expensive_search(query)

deduped = wrap_langgraph_node(
    sf,
    knowledge_lookup,
    tool_name="knowledge.search",
    ttl_seconds=120,
    estimated_cost_usd=0.06,
    bounded_read=True,
)
```

Use `deduped` as a node function in your LangGraph `StateGraph`.

## API reference

| Class / Function | Module | Purpose |
|---|---|---|
| `Singleflight` | `singleflight_agents` | Main engine. Wraps tools, executes with dedup, stores receipts. |
| `ToolExecutionOptions` | `singleflight_agents` | Per-tool config: name, TTL, cost, safety flags. |
| `Receipt` | `singleflight_agents` | Signed execution envelope: fingerprint, output, signature, timing. |
| `ExecutionOutcome` | `singleflight_agents` | Result wrapper: value, receipt, source tag. |
| `make_fingerprint()` | `singleflight_agents.fingerprint` | Generates deterministic cache key from tool name + args. |
| `ReceiptStore` | `singleflight_agents.store` | SQLite backend for receipts, leases, and HMAC signing. |
| `function_tool()` | `singleflight_agents.adapters` | OpenAI Agents SDK decorator with dedup. |
| `wrap_langgraph_node()` | `singleflight_agents.adapters` | LangGraph node wrapper with dedup. |
| `format_summary()` | `singleflight_agents.reporting` | Renders a text summary with per-tool reuse chart. |

See [docs/api.md](docs/api.md) for full parameter documentation.

## FAQ

**Why not just use caching (Redis, functools.lru_cache, etc.)?**

Standard caches don't handle the **in-flight deduplication** case. If 4 agents call the same tool at the same time, a cache misses on all 4 because no result exists yet. Singleflight uses a lease so only 1 executes and the other 3 wait for that result. It also signs every receipt with HMAC-SHA256 to prevent tampering.

**Does this work with async?**

Yes. The `@singleflight.tool()` decorator and `execute()` method handle both sync and async functions automatically. Sync functions run via `asyncio.to_thread`.

**What happens if the executing agent crashes?**

The lease has an expiry (default 30 seconds). When it expires, a waiting agent takes over the lease and executes the tool. There is also a final fallback that executes directly if all else fails.

**What about Redis / distributed leases?**

Not implemented yet. The current store is local SQLite, which is great for single-node use. A Redis-backed `ReceiptStore` is a natural extension.

**Can I use this without any agent framework?**

Yes. The core library has zero dependencies. The OpenAI and LangGraph adapters are optional extras.

## Repo structure

```
src/singleflight_agents/
    __init__.py          # Public API exports
    engine.py            # Singleflight class (core logic)
    models.py            # Receipt, ExecutionOutcome, ToolExecutionOptions
    fingerprint.py       # Deterministic cache key generation
    store.py             # SQLite receipt store + HMAC signing
    reporting.py         # Text summary renderer
    cli.py               # CLI entry point
    adapters/
        openai_agents.py # OpenAI Agents SDK integration
        langgraph.py     # LangGraph integration
examples/
    raw_demo.py          # Baseline vs. singleflight comparison
    openai_demo.py       # OpenAI Agents SDK example
    langgraph_demo.py    # LangGraph example
tests/
    test_singleflight.py # Concurrency, TTL, safety, signing, expiry tests
docs/
    api.md               # Full API reference
    how-it-works.md      # Detailed flow explanation
```

## Limitations

- Local SQLite is the default receipt store. Great for demos and single-node use.
- Redis-backed leases are not implemented yet.
- The framework adapters are intentionally thin wrappers around the core runtime.
- Cached values are stored locally as signed envelopes so they can be replayed consistently.

## Requirements

- Python 3.11+
- No runtime dependencies (stdlib only)
- Optional: `openai-agents` for the OpenAI adapter, `langgraph` for the LangGraph adapter

## License

MIT. See [LICENSE](LICENSE).
