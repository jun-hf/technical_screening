"""
Validates untrusted JSON from an LLM.

Treats LLM output as adversarial input: whitelists known fields,
coerces common LLM type quirks (numeric strings, lossless floats),
and constructs a new trusted object. The original payload is never
passed through.
"""

from __future__ import annotations
from typing import Any, Dict, List, Tuple

VALID_ACTIONS = frozenset({"search", "answer"})
K_MIN, K_MAX, K_DEFAULT = 1, 5, 3
KNOWN_KEYS = frozenset({"action", "q", "k"})

def _trim(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) else None

def _coerce_int(value: Any) -> tuple[int | None, str | None]:
    if isinstance(value, bool):
        return None, "boolean is not a valid integer"
    if isinstance(value, int):
        return value, None
    if isinstance(value, float):
        if value == int(value):
            return int(value), f"coerced float {value} -> {int(value)}"
        return None, f"cannot losslessly coerce {value} to int"
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return int(stripped), "coerced string to int"
        except ValueError:
            try:
                f = float(stripped)
                if f == int(f):
                    return int(f), f"coerced string '{stripped}' -> {int(f)}"
                return None, f"cannot losslessly coerce '{stripped}' to int"
            except ValueError:
                return None, f"cannot coerce '{stripped}' to int"
    return None, f"unexpected type {type(value).__name__}"

def validate_tool_call(
    payload: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    errors: list[str] = []

    if not isinstance(payload, dict):
        return {}, [f"payload must be a dict, got {type(payload).__name__}"]
    
    unknown = set(payload) - KNOWN_KEYS
    if unknown:
        errors.append(f"unknown keys ignored: {sorted(unknown)}")

    action = _trim(payload.get("action"))
    if action is None:
        return {}, errors + ["missing or non-string 'action'"]
    
    action = action.lower()
    if action not in VALID_ACTIONS:
        return {}, errors + [f"invalid action '{action}'"]
    
    if action == "search":
        q = _trim(payload.get("q"))
        if not q:
            return {}, errors + ["missing or empty 'q' for search"]
        
    raw_k = payload.get("k")
    if raw_k is not None:
        k, warn = _coerce_int(raw_k)
        if warn:
            errors.append(f"field 'k': {warn}")
        if k is None:
            k = K_DEFAULT
        elif not (K_MIN <= k <= K_MAX):
            errors.append(f"'k' out of range ({k}), clamped")
            k = max(K_MIN, min(K_MAX, k))
    else:
        k = K_DEFAULT

    clean: dict[str, Any] = {"action": action, "k": k}
    if action == "search":
        clean["q"] = q

    return clean, errors