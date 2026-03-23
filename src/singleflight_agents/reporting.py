from __future__ import annotations

from typing import Any


def format_summary(summary: dict[str, Any]) -> str:
    lines = [
        "Singleflight Summary",
        "--------------------",
        f"Receipt store: {summary['db_path']}",
        f"Unique executions: {summary['unique_executions']}",
        f"Duplicate calls avoided: {summary['avoided_calls']}",
        f"Dollars saved (estimated): ${summary['dollars_saved']:.2f}",
        f"Latency saved (estimated): {summary['latency_saved_ms'] / 1000:.2f}s",
        "",
        "Tool hit graph:",
    ]
    tools = summary["tools"]
    if not tools:
        lines.append("  (no receipts yet)")
        return "\n".join(lines)

    max_reuse = max(tool["reuse_count"] for tool in tools) or 1
    for tool in tools:
        bars = "#" * max(1, int((tool["reuse_count"] / max_reuse) * 20)) if tool["reuse_count"] else ""
        lines.append(
            f"  {tool['tool_name']:<28} avoided={tool['reuse_count']:<3} {bars}"
        )
    return "\n".join(lines)

