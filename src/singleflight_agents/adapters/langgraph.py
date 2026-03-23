from __future__ import annotations

from typing import Any, Callable

from ..engine import Singleflight
from ..models import ToolExecutionOptions


def wrap_langgraph_node(
    singleflight: Singleflight,
    func: Callable[..., Any],
    **kwargs: Any,
) -> Callable[..., Any]:
    """Wrap a sync function with singleflight dedup for use as a LangGraph node.

    Keyword arguments are forwarded to ``ToolExecutionOptions``.
    Requires the ``langgraph`` package (install with ``pip install -e .[langgraph]``).
    """
    options = ToolExecutionOptions(**kwargs)

    def wrapped(*args: Any, **inner_kwargs: Any) -> Any:
        outcome = singleflight.execute_sync(func, *args, options=options, **inner_kwargs)
        return outcome.value

    wrapped.__name__ = getattr(func, "__name__", "wrapped_node")
    wrapped.__doc__ = getattr(func, "__doc__", None)
    return wrapped

