from __future__ import annotations

from typing import TypedDict

from singleflight_agents import Singleflight
from singleflight_agents.adapters import wrap_langgraph_node


class DemoState(TypedDict):
    query: str
    result: str


def main(db_path: str | None = None) -> int:
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        print("LangGraph is not installed. Run `python -m pip install -e .[langgraph]` first.")
        return 1

    singleflight = Singleflight(db_path=db_path)

    def lookup_knowledge(query: str) -> str:
        return f"Knowledge result for {query}"

    deduped_lookup = wrap_langgraph_node(
        singleflight,
        lookup_knowledge,
        tool_name="langgraph.knowledge_lookup",
        ttl_seconds=120,
        estimated_cost_usd=0.06,
        bounded_read=True,
    )

    def search_node(state: DemoState) -> dict[str, str]:
        return {"result": deduped_lookup(state["query"])}

    graph = StateGraph(DemoState)
    graph.add_node("search", search_node)
    graph.set_entry_point("search")
    graph.add_edge("search", END)
    compiled = graph.compile()

    first = compiled.invoke({"query": "launch checklist", "result": ""})
    second = compiled.invoke({"query": "launch checklist", "result": ""})

    print(first)
    print(second)
    print("")
    print("Run `python -m singleflight_agents summary` to inspect the shared receipts.")
    return 0

