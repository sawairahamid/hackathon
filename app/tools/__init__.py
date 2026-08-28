from __future__ import annotations

import inspect
import json
from typing import Any, Callable, get_args, get_origin, get_type_hints

from app.models import ToolResult

_REGISTRY: dict[str, dict[str, Any]] = {}


def _annotation_to_schema(ann: Any) -> dict[str, Any]:
    origin = get_origin(ann)
    args = get_args(ann)
    if ann is inspect.Parameter.empty or ann is Any:
        return {"type": "object"}
    if origin is list or ann is list:
        item = _annotation_to_schema(args[0]) if args else {"type": "object"}
        return {"type": "array", "items": item}
    if origin is dict or ann is dict:
        return {"type": "object"}
    if origin is type(None):
        return {"type": "null"}
    mapping = {str: "string", int: "integer", float: "number", bool: "boolean"}
    if ann in mapping:
        return {"type": mapping[ann]}
    if origin is not None and type(origin) is type(type(int | str)):  # union
        return {"anyOf": [_annotation_to_schema(a) for a in args]}
    name = getattr(ann, "__name__", str(ann))
    if "Union" in str(origin) or "Union" in str(ann) or "Optional" in str(ann) or " | " in str(ann):
        return {"anyOf": [_annotation_to_schema(a) for a in args] or [{"type": "object"}]}
    if name in mapping:
        return {"type": mapping[name]}  # type: ignore[index]
    return {"type": "object", "description": name}


def _schema_from_fn(fn: Callable) -> dict[str, Any]:
    hints = {}
    try:
        hints = get_type_hints(fn)
    except Exception:
        hints = dict(getattr(fn, "__annotations__", {}))
    sig = inspect.signature(fn)
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        props[name] = _annotation_to_schema(hints.get(name, param.annotation))
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": True,
    }


def tool(name: str | None = None, description: str = "") -> Callable:
    """Register a function as an invocable agent tool. Schema is derived from type hints."""

    def deco(fn: Callable) -> Callable:
        n = name or fn.__name__
        _REGISTRY[n] = {
            "name": n,
            "description": description or (fn.__doc__ or "").strip(),
            "fn": fn,
            "schema": _schema_from_fn(fn),
        }
        return fn

    return deco


def registered() -> dict[str, dict[str, Any]]:
    return {
        k: {"name": v["name"], "description": v["description"], "schema": v["schema"]}
        for k, v in _REGISTRY.items()
    }


def invoke(name: str, inputs: dict[str, Any] | None = None) -> ToolResult:
    import time

    spec = _REGISTRY.get(name)
    if not spec:
        return ToolResult(ok=False, tool=name, error=f"Unknown tool '{name}'. Known: {list(_REGISTRY)}")
    inputs = dict(inputs or {})
    fn = spec["fn"]
    sig = inspect.signature(fn)
    # Drop unexpected keys so LLM-planned extra fields don't crash calls.
    accepted = {p for p in sig.parameters}
    filtered = {k: v for k, v in inputs.items() if k in accepted}
    t0 = time.perf_counter()
    try:
        result = fn(**filtered)
        latency = int((time.perf_counter() - t0) * 1000)
        if isinstance(result, ToolResult):
            result.latency_ms = result.latency_ms or latency
            return result
        return ToolResult(ok=True, tool=name, data=result, latency_ms=latency, source="local")
    except TypeError as exc:
        latency = int((time.perf_counter() - t0) * 1000)
        return ToolResult(ok=False, tool=name, error=f"Bad inputs for {name}: {exc}", latency_ms=latency)
    except Exception as exc:  # noqa: BLE001 — tools must not crash the executor
        latency = int((time.perf_counter() - t0) * 1000)
        return ToolResult(ok=False, tool=name, error=str(exc), latency_ms=latency)


def dump_manifest() -> str:
    return json.dumps(registered(), indent=2)


def load_all() -> None:
    """Import tool modules so the @tool decorator fills the registry."""
    from app.tools import approvals, documents, scoring, suppliers  # noqa: F401
    from app import validator  # noqa: F401
