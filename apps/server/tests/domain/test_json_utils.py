"""Tests for the shared ``json_utils`` module."""

from __future__ import annotations

import json

import numpy as np

from vibesensor.json_utils import (
    safe_json_dumps,
    safe_json_loads,
    sanitize_for_json,
    sanitize_value,
)

# ── sanitize_for_json ────────────────────────────────────────────────────────


class TestSanitizeForJson:
    """Comprehensive tests for :func:`sanitize_for_json`."""

    def test_nan_replaced_with_none(self) -> None:
        cleaned, had = sanitize_for_json({"rpm": float("nan"), "ok": 42})
        assert cleaned["rpm"] is None
        assert cleaned["ok"] == 42
        assert had is True

    def test_inf_replaced_with_none(self) -> None:
        cleaned, had = sanitize_for_json({"val": float("inf")})
        assert cleaned["val"] is None
        assert had is True

    def test_neg_inf_replaced_with_none(self) -> None:
        cleaned, had = sanitize_for_json({"val": float("-inf")})
        assert cleaned["val"] is None
        assert had is True

    def test_normal_floats_preserved(self) -> None:
        data = {"a": 1.5, "b": -3.14, "c": 0.0}
        cleaned, had = sanitize_for_json(data)
        assert cleaned == data
        assert had is False

    def test_nested_nan(self) -> None:
        data = {"outer": {"inner": [1.0, float("nan"), 3.0]}}
        cleaned, had = sanitize_for_json(data)
        assert cleaned == {"outer": {"inner": [1.0, None, 3.0]}}
        assert had is True

    def test_deeply_nested(self) -> None:
        data = {"a": [{"b": [float("inf"), {"c": float("-inf")}]}]}
        cleaned, had = sanitize_for_json(data)
        assert cleaned == {"a": [{"b": [None, {"c": None}]}]}
        assert had is True

    def test_non_float_types_untouched(self) -> None:
        data = {"s": "hello", "i": 42, "b": True, "n": None, "l": [1, 2]}
        cleaned, had = sanitize_for_json(data)
        assert cleaned == data
        assert had is False

    def test_empty_structures(self) -> None:
        cleaned, had = sanitize_for_json({})
        assert cleaned == {}
        assert had is False
        cleaned, had = sanitize_for_json([])
        assert cleaned == []
        assert had is False

    def test_tuple_converted_to_list(self) -> None:
        cleaned, had = sanitize_for_json({"t": (1.0, float("nan"), 3.0)})
        assert cleaned["t"] == [1.0, None, 3.0]
        assert had is True

    def test_output_is_valid_json(self) -> None:
        data = {
            "wheel": {"rpm": float("nan")},
            "spectrum": [float("inf"), 1.0, float("-inf")],
            "speed_mps": 25.5,
        }
        cleaned, had = sanitize_for_json(data)
        assert had is True
        text = json.dumps(cleaned, allow_nan=False)
        parsed = json.loads(text)
        assert parsed["wheel"]["rpm"] is None
        assert parsed["spectrum"] == [None, 1.0, None]
        assert parsed["speed_mps"] == 25.5

    # ── numpy handling ───────────────────────────────────────────────────

    def test_numpy_scalars_converted(self) -> None:
        data = {"a": np.float32(1.5), "b": np.int64(42), "c": np.float64(float("nan"))}
        cleaned, had = sanitize_for_json(data)
        assert cleaned["a"] == 1.5
        assert isinstance(cleaned["a"], float)
        assert cleaned["b"] == 42
        assert isinstance(cleaned["b"], int)
        assert cleaned["c"] is None
        assert had is True

    def test_numpy_arrays_converted(self) -> None:
        data = {"arr": np.array([1.0, float("nan"), 3.0])}
        cleaned, had = sanitize_for_json(data)
        assert cleaned["arr"] == [1.0, None, 3.0]
        assert had is True

    def test_numpy_2d_array(self) -> None:
        arr2d = np.array([[1.0, 2.0], [3.0, 4.0]])
        cleaned, had = sanitize_for_json(arr2d)
        assert cleaned == [[1.0, 2.0], [3.0, 4.0]]
        assert had is False

    def test_numpy_inf_scalar(self) -> None:
        cleaned, _ = sanitize_for_json(np.float32(float("inf")))
        assert cleaned is None


# ── sanitize_value ───────────────────────────────────────────────────────────


class TestSanitizeValue:
    """Tests for the convenience :func:`sanitize_value` wrapper."""

    def test_returns_only_value(self) -> None:
        result = sanitize_value({"a": float("nan"), "b": 1})
        assert result == {"a": None, "b": 1}

    def test_numpy_scalar_converted(self) -> None:
        assert sanitize_value(np.float64(2.5)) == 2.5
        assert isinstance(sanitize_value(np.float64(2.5)), float)

    def test_numpy_nan_scalar_to_none(self) -> None:
        assert sanitize_value(np.float64(float("nan"))) is None

    def test_numpy_array_converted(self) -> None:
        result = sanitize_value(np.array([1.0, 2.0, float("nan")]))
        assert result == [1.0, 2.0, None]


# ── safe_json_dumps ──────────────────────────────────────────────────────────


class TestSafeJsonDumps:
    """Tests for :func:`safe_json_dumps`."""

    def test_plain_dict(self) -> None:
        result = safe_json_dumps({"key": "value", "num": 42})
        parsed = json.loads(result)
        assert parsed == {"key": "value", "num": 42}

    def test_sanitises_nan(self) -> None:
        result = safe_json_dumps({"val": float("nan")})
        parsed = json.loads(result)
        assert parsed["val"] is None

    def test_sanitises_inf(self) -> None:
        result = safe_json_dumps({"val": float("inf")})
        parsed = json.loads(result)
        assert parsed["val"] is None

    def test_numpy_values(self) -> None:
        result = safe_json_dumps({"a": np.float32(1.5), "b": np.int64(42)})
        parsed = json.loads(result)
        assert parsed == {"a": 1.5, "b": 42}

    def test_unicode_preserved(self) -> None:
        result = safe_json_dumps({"text": "Ünïcödé"})
        assert "Ünïcödé" in result

    def test_always_returns_str(self) -> None:
        assert isinstance(safe_json_dumps(None), str)
        assert isinstance(safe_json_dumps([1, 2, 3]), str)


# ── safe_json_loads ──────────────────────────────────────────────────────────


class TestSafeJsonLoads:
    """Tests for :func:`safe_json_loads`."""

    def test_valid_json(self) -> None:
        result = safe_json_loads('{"key": "value"}', context="test")
        assert result == {"key": "value"}

    def test_none_input(self) -> None:
        assert safe_json_loads(None, context="test") is None

    def test_empty_string(self) -> None:
        assert safe_json_loads("", context="test") is None

    def test_invalid_json_returns_none(self) -> None:
        result = safe_json_loads("{invalid json", context="test-field")
        assert result is None

    def test_array_json(self) -> None:
        result = safe_json_loads("[1, 2, 3]", context="test")
        assert result == [1, 2, 3]

    def test_scalar_json(self) -> None:
        result = safe_json_loads("42", context="test")
        assert result == 42
