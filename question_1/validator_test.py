"""Tests organised by behaviour — happy path, coercion, conditionals, boundaries, fatal, adversarial."""

import math

import pytest
from validator import validate_tool_call


# --- Happy path ---

class TestHappyPath:
    def test_search_all_fields(self):
        c, e = validate_tool_call({"action": "search", "q": "hello", "k": 2})
        assert c == {"action": "search", "q": "hello", "k": 2}
        assert e == []

    def test_search_default_k(self):
        c, e = validate_tool_call({"action": "search", "q": "hello"})
        assert c == {"action": "search", "q": "hello", "k": 3}
        assert e == []

    def test_answer_minimal(self):
        c, e = validate_tool_call({"action": "answer"})
        assert c == {"action": "answer", "k": 3}
        assert e == []


# --- Coercion (common LLM output quirks) ---

class TestCoercion:
    def test_k_string(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": "2"})
        assert c["k"] == 2
        assert any("coerced" in x for x in e)

    def test_k_lossless_float(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": 3.0})
        assert c["k"] == 3
        assert any("coerced" in x for x in e)

    def test_k_string_float(self):
        """LLM returns k as '3.0' — string of a float."""
        c, e = validate_tool_call({"action": "search", "q": "x", "k": "3.0"})
        assert c["k"] == 3
        assert any("coerced" in x for x in e)

    def test_q_trimmed(self):
        c, e = validate_tool_call({"action": "search", "q": "  hello  "})
        assert c["q"] == "hello"
        assert e == []

    def test_action_case_insensitive(self):
        c, _ = validate_tool_call({"action": "Search", "q": "x"})
        assert c["action"] == "search"

    def test_action_whitespace_trimmed(self):
        c, _ = validate_tool_call({"action": " search ", "q": "x"})
        assert c["action"] == "search"


# --- Conditional q ---

class TestConditionalQ:
    def test_answer_ignores_q(self):
        c, e = validate_tool_call({"action": "answer", "q": "ignored"})
        assert "q" not in c
        assert not any("'q'" in x for x in e)

    def test_search_missing_q_fatal(self):
        c, e = validate_tool_call({"action": "search"})
        assert c == {}
        assert len(e) > 0

    def test_search_whitespace_q_fatal(self):
        c, e = validate_tool_call({"action": "search", "q": "   "})
        assert c == {}
        assert len(e) > 0


# --- k boundary ---

class TestKBoundary:
    def test_k_at_min(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": 1})
        assert c["k"] == 1
        assert e == []

    def test_k_at_max(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": 5})
        assert c["k"] == 5
        assert e == []

    def test_k_below_clamped(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": 0})
        assert c["k"] == 1
        assert any("clamped" in x for x in e)

    def test_k_above_clamped(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": 10})
        assert c["k"] == 5
        assert any("clamped" in x for x in e)

    def test_k_negative_clamped(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": -5})
        assert c["k"] == 1
        assert any("clamped" in x for x in e)


# --- Fatal errors (parametrized) ---

class TestFatal:
    @pytest.mark.parametrize("payload,desc", [
        ({}, "empty payload"),
        ({"q": "hello"}, "missing action"),
        ({"action": "delete"}, "invalid action value"),
        ({"action": ""}, "empty action string"),
        ({"action": ["search"], "q": "x"}, "action wrong type"),
        ({"action": "search", "q": None}, "q is None"),
        ({"action": "search", "q": {"nested": "dict"}}, "q wrong type"),
        ("string", "payload is string"),
        (None, "payload is None"),
    ], ids=lambda x: x if isinstance(x, str) else repr(x))
    def test_fatal_returns_empty_clean(self, payload, desc):
        c, e = validate_tool_call(payload)
        assert c == {}, f"expected empty dict for: {desc}"
        assert len(e) > 0, f"expected errors for: {desc}"


# --- Adversarial / LLM edge cases ---

class TestAdversarial:
    def test_bool_k_rejected(self):
        """bool is a subclass of int in Python — must be explicitly rejected."""
        c, e = validate_tool_call({"action": "search", "q": "x", "k": True})
        assert c["k"] == 3
        assert any("boolean" in x for x in e)

    def test_lossy_float_rejected(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": 3.7})
        assert c["k"] == 3
        assert any("losslessly" in x for x in e)

    def test_k_infinity(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": float("inf")})
        assert c["k"] == 3
        assert len(e) > 0

    def test_k_nan(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": float("nan")})
        assert c["k"] == 3
        assert len(e) > 0

    def test_k_non_numeric_string(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": "abc"})
        assert c["k"] == 3
        assert len(e) > 0

    def test_k_empty_string(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": ""})
        assert c["k"] == 3
        assert len(e) > 0

    def test_k_none_uses_default(self):
        """Explicit None should behave like absent — use default."""
        c, e = validate_tool_call({"action": "search", "q": "x", "k": None})
        assert c["k"] == 3
        assert e == []

    def test_q_as_integer(self):
        """LLM returns q as a number instead of string."""
        c, e = validate_tool_call({"action": "search", "q": 42})
        assert c == {}
        assert len(e) > 0

    def test_unknown_keys_stripped(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "reasoning": "..."})
        assert "reasoning" not in c
        assert any("unknown" in x for x in e)

    def test_unicode_preserved(self):
        c, e = validate_tool_call({"action": "search", "q": "café"})
        assert c["q"] == "café"
        assert e == []

    def test_k_extremely_large(self):
        """LLM hallucinates a huge number."""
        c, e = validate_tool_call({"action": "search", "q": "x", "k": 999999999})
        assert c["k"] == 5
        assert any("clamped" in x for x in e)

    def test_multiple_errors_accumulate(self):
        """Unknown keys AND k clamped — both should appear in errors."""
        c, e = validate_tool_call({"action": "search", "q": "x", "k": 0, "extra": 1})
        assert c["k"] == 1
        assert "extra" not in c
        assert any("unknown" in x for x in e)
        assert any("clamped" in x for x in e)


# --- Structural invariant ---

class TestInvariants:
    @pytest.mark.parametrize("payload", [
        {"action": "search", "q": "test", "k": 2},
        {"action": "search", "q": "x"},
        {"action": "answer"},
        {"action": "answer", "q": "ignored", "k": 4},
        {"action": "Search", "q": "x", "k": "3"},
    ])
    def test_valid_output_shape(self, payload):
        """When validation succeeds, the output must conform to the schema."""
        c, _ = validate_tool_call(payload)
        assert c != {}, "expected non-empty clean dict"
        assert set(c.keys()) <= {"action", "q", "k"}
        assert c["action"] in ("search", "answer")
        if c["action"] == "search":
            assert isinstance(c["q"], str) and len(c["q"]) > 0
            assert isinstance(c["k"], int) and 1 <= c["k"] <= 5
