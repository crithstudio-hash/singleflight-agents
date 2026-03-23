from __future__ import annotations

from typing import Any, Callable

from ..engine import Singleflight
from ..models import ToolExecutionOptions


def function_tool(singleflight: Singleflight, **kwargs: Any) -> Callable[[Callable[..., Any]], Any]:
    """Decorator that wraps a function with singleflight dedup and registers it as an OpenAI Agents SDK tool.

    Keyword arguments are forwarded to ``ToolExecutionOptions``.
    Requires the ``openai-agents`` package (install with ``pip install -e .[openai]``).
    """
    try:
        from agents import function_tool as openai_function_tool
    except ImportError as exc:
        raise RuntimeError(
            "OpenAI Agents SDK is not installed. Install with `python -m pip install -e .[openai]`."
        ) from exc

    options = ToolExecutionOptions(**kwargs)

    def decorator(func: Callable[..., Any]) -> Any:
        async def wrapped(*args: Any, **inner_kwargs: Any) -> Any:
            outcome = await singleflight.execute(func, *args, options=options, **inner_kwargs)
            return outcome.value

        wrapped.__name__ = getattr(func, "__name__", "wrapped_tool")
        wrapped.__doc__ = getattr(func, "__doc__", None)
        return openai_function_tool(wrapped)

    return decorator

