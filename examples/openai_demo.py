from __future__ import annotations

import os

from singleflight_agents import Singleflight
from singleflight_agents.adapters import function_tool


def main(db_path: str | None = None) -> int:
    try:
        from agents import Agent, Runner
    except ImportError:
        print("OpenAI Agents SDK is not installed. Run `python -m pip install -e .[openai]` first.")
        return 1

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set.")
        return 1

    singleflight = Singleflight(db_path=db_path)

    @function_tool(
        singleflight,
        tool_name="openai.account_lookup",
        ttl_seconds=120,
        estimated_cost_usd=0.08,
        bounded_read=True,
    )
    def lookup_account(email: str) -> str:
        return f"Account record for {email}: plan=enterprise, health=green"

    agent = Agent(
        name="account-ops",
        instructions="Use the tool if you need account details. Be concise.",
        tools=[lookup_account],
    )

    result = Runner.run_sync(
        agent,
        "Look up jordan@example.com twice, then summarize the customer state in one sentence.",
    )
    final_output = getattr(result, "final_output", result)
    print(final_output)
    print("")
    print("Run `python -m singleflight_agents summary` to inspect the dedupe receipts.")
    return 0

