# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-23

### Added

- Core `Singleflight` engine with async/sync execution, fingerprinting, leasing, and receipt fan-out.
- `ToolExecutionOptions` with safety flags: `deterministic`, `bounded_read`, `side_effecting`.
- `ReceiptStore` backed by SQLite with HMAC-SHA256 signed receipts.
- `make_fingerprint()` for deterministic cache key generation from tool name and arguments.
- `@singleflight.tool()` decorator for wrapping any sync or async function.
- Lease-based deduplication: one execution per unique in-flight call, waiters share the result.
- TTL-based receipt expiry with configurable `ttl_seconds`.
- Fallback execution when lease owner crashes or times out.
- Summary reporting with per-tool reuse counts, dollars saved, and latency saved.
- OpenAI Agents SDK adapter (`function_tool`).
- LangGraph adapter (`wrap_langgraph_node`).
- CLI with `demo`, `summary`, `verify`, `openai-demo`, `langgraph-demo` subcommands.
- Built-in demo comparing baseline vs. deduplicated execution.
- 5 tests covering concurrency, TTL, safety flags, signatures, and expiry.
- Zero runtime dependencies — stdlib only.
