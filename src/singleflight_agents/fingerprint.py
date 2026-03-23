from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, set):
        return sorted(_normalize(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


@dataclass(frozen=True)
class Fingerprint:
    key: str
    payload_json: str
    args_hash: str


def make_fingerprint(
    *,
    tool_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    scope: str,
    namespace: str,
    version: str,
) -> Fingerprint:
    """Generate a deterministic cache key from tool name, args, and metadata.

    Arguments are recursively normalized (dicts sorted, sets sorted) before
    being JSON-serialized and SHA-256 hashed.
    """
    payload = {
        "tool_name": tool_name,
        "scope": scope,
        "namespace": namespace,
        "version": version,
        "args": _normalize(args),
        "kwargs": _normalize(kwargs),
    }
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return Fingerprint(
        key=f"{namespace}:{tool_name}:{digest}",
        payload_json=payload_json,
        args_hash=digest,
    )

