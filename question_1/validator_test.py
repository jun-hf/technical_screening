"""Tests organised by behaviour"""

import pytest
from validator import validate_tool_call


# --- Happy path ---

class TestHappyPath:
    def test_search_all_fields(self):
        c, e = validate_tool_call({"action": "search", "q": "hello", "k": 2})
        assert c == {"action": "search", "q": "hello", "k": 2} and e == []

    def test_search_default_k(self):
        c, e = validate_tool_call({"action": "search", "q": "hello"})
        assert c == {"action": "search", "q": "hello", "k": 3} and e == []

    def test_answer_minimal(self):
        c, e = validate_tool_call({"action": "answer"})
        assert c == {"action": "answer", "k": 3} and e == []


# --- Coercion (common LLM output quirks) ---

class TestCoercion:
    def test_k_string(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": "2"})
        assert c["k"] == 2

    def test_k_lossless_float(self):
        c, _ = validate_tool_call({"action": "search", "q": "x", "k": 3.0})
        assert c["k"] == 3

    def test_q_trimmed(self):
        c, _ = validate_tool_call({"action": "search", "q": "  hello  "})
        assert c["q"] == "hello"

    def test_action_case_insensitive(self):
        c, _ = validate_tool_call({"action": "Search", "q": "x"})
        assert c["action"] == "search"


# --- Conditional q ---

class TestConditionalQ:
    def test_answer_ignores_q(self):
        c, e = validate_tool_call({"action": "answer", "q": "ignored"})
        assert "q" not in c and not any("'q'" in x for x in e)

    def test_search_missing_q_fatal(self):
        c, _ = validate_tool_call({"action": "search"})
        assert c == {}

    def test_search_whitespace_q_fatal(self):
        c, _ = validate_tool_call({"action": "search", "q": "   "})
        assert c == {}


# --- k boundary ---

class TestKBoundary:
    def test_k_below_clamped(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": 0})
        assert c["k"] == 1 and any("clamped" in x for x in e)

    def test_k_above_clamped(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": 10})
        assert c["k"] == 5


# --- Fatal errors ---

class TestFatal:
    def test_missing_action(self):
        assert validate_tool_call({"q": "hello"})[0] == {}

    def test_invalid_action(self):
        assert validate_tool_call({"action": "delete"})[0] == {}

    def test_empty_payload(self):
        assert validate_tool_call({})[0] == {}


# --- Adversarial / LLM edge cases ---

class TestAdversarial:
    def test_not_a_dict(self):
        assert validate_tool_call("string")[0] == {}

    def test_none_payload(self):
        assert validate_tool_call(None)[0] == {}

    def test_bool_k_rejected(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "k": True})
        assert c["k"] == 3 and any("boolean" in x for x in e)

    def test_lossy_float_rejected(self):
        c, _ = validate_tool_call({"action": "search", "q": "x", "k": 3.7})
        assert c["k"] == 3

    def test_unknown_keys_stripped(self):
        c, e = validate_tool_call({"action": "search", "q": "x", "reasoning": "..."})
        assert "reasoning" not in c and any("unknown" in x for x in e)

    def test_q_none_fatal(self):
        assert validate_tool_call({"action": "search", "q": None})[0] == {}

    def test_unicode_preserved(self):
        c, e = validate_tool_call({"action": "search", "q": "café"})
        assert c["q"] == "café" and e == []

    def test_empty_action(self):
        assert validate_tool_call({"action": ""})[0] == {}

    def test_action_wrong_type(self):
        """LLM wraps action in a list."""
        assert validate_tool_call({"action": ["search"], "q": "x"})[0] == {}

    def test_q_wrong_type(self):
        """LLM returns a dict instead of a string."""
        assert validate_tool_call({"action": "search", "q": {"nested": "dict"}})[0] == {}

    def test_k_extremely_large(self):
        """LLM hallucinates a huge number."""
        c, e = validate_tool_call({"action": "search", "q": "x", "k": 999999999})
        assert c["k"] == 5 and any("clamped" in x for x in e)