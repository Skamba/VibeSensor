"""Tests for the shared ``json_utils`` module."""

from __future__ import annotations

import json
import logging

import numpy as np
import pytest

from vibesensor.shared.json_utils import (
    deep_merge,
    json_text_dumps,
    payload_object_from_json,
    payload_objects_from_json,
    payload_value_from_json,
    safe_json_dumps,
    safe_json_loads,
    sanitize_for_json,
    sanitize_value,
)


class TestDeepMerge:
    """Tests for the shared ``deep_merge`` helper."""

    @pytest.mark.parametrize(
        ("base", "override", "expected"),
        [
            pytest.param({"a": 1, "b": 2}, {"a": 10}, {"a": 10, "b": 2}, id="scalar"),
            pytest.param(
                {"top": {"a": 1, "b": 2}},
                {"top": {"b": 3}},
                {"top": {"a": 1, "b": 3}},
                id="nested-object",
            ),
            pytest.param({"a": 1}, {"b": 2}, {"a": 1, "b": 2}, id="new-key"),
            pytest.param({"items": [1, 2]}, {"items": [3]}, {"items": [3]}, id="list-replace"),
        ],
    )
    def test_merges_nested_objects_and_replaces_scalars(
        self,
        base: dict[str, object],
        override: dict[str, object],
        expected: dict[str, object],
    ) -> None:
        assert deep_merge(base, override) == expected

    def test_null_dict_section_keeps_existing_section_and_logs_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        result = deep_merge({"ap": {"self_heal": {"enabled": True}}}, {"ap": None})

        assert result == {"ap": {"self_heal": {"enabled": True}}}
        assert "keeping default section" in caplog.text


# ── sanitize_for_json ────────────────────────────────────────────────────────


class TestSanitizeForJson:
    """Comprehensive tests for :func:`sanitize_for_json`."""

    @pytest.mark.parametrize(
        ("value", "label"),
        [(float("nan"), "nan"), (float("inf"), "inf"), (float("-inf"), "-inf")],
    )
    def test_non_finite_replaced_with_none(self, value: float, label: str) -> None:
        cleaned, had = sanitize_for_json({"val": value})
        assert cleaned["val"] is None, f"{label} should become None"
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

    def test_depth_limit_truncates_to_none(self) -> None:
        """Objects beyond _max_depth are replaced with None."""
        # Build a chain 4 deep with a sentinel float value at the bottom.
        nested: dict = {}
        innermost = nested
        for _ in range(3):
            child: dict = {}
            innermost["child"] = child
            innermost = child
        innermost["val"] = 1.5

        # Default limit is 128, so this trivially passes at depth 4.
        cleaned, had = sanitize_for_json(nested)
        # All data is within depth limit; sentinel value should survive.
        assert had is False

        # With _max_depth=2 the deeply nested value is truncated.
        # Depth 0 → nested, depth 1 → child1, depth 2 → child2 (still ok),
        # depth 3 → child3 exceeds limit and becomes None.
        cleaned_limited, _ = sanitize_for_json(nested, _max_depth=2)
        # Use .get() chaining to avoid KeyError if truncation produces a different structure.
        level1 = cleaned_limited.get("child")
        assert isinstance(level1, dict), "level1 should still be a dict (within depth limit)"
        level2 = level1.get("child")
        assert isinstance(level2, dict), "level2 should still be a dict (within depth limit)"
        # The third level exceeds the depth limit and should be None.
        assert level2.get("child") is None, "level3 should be truncated to None"

    def test_depth_limit_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Exceeding _max_depth emits a warning log."""
        import logging

        nested = {"a": {"b": {"c": "deep"}}}
        with caplog.at_level(logging.WARNING, logger="vibesensor.shared.json_utils"):
            sanitize_for_json(nested, _max_depth=1)
        assert any("nesting depth" in r.message for r in caplog.records)


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

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param({"key": "value", "num": 42}, {"key": "value", "num": 42}, id="plain"),
            pytest.param({"val": float("nan")}, {"val": None}, id="nan"),
            pytest.param({"val": float("inf")}, {"val": None}, id="inf"),
            pytest.param(
                {"a": np.float32(1.5), "b": np.int64(42)},
                {"a": 1.5, "b": 42},
                id="numpy-scalars",
            ),
        ],
    )
    def test_projects_supported_values(self, value: object, expected: object) -> None:
        parsed = json.loads(safe_json_dumps(value))
        assert parsed == expected

    def test_nested_numpy_payload_round_trip(self) -> None:
        result = safe_json_dumps(
            {
                "matrix": np.array([[1.0, float("nan")], [3.0, 4.0]]),
                "meta": {
                    "sensor": np.int64(2),
                    "levels": (np.float32(1.5), float("-inf")),
                },
            }
        )
        parsed = safe_json_loads(result, context="nested-payload")
        assert parsed == {
            "matrix": [[1.0, None], [3.0, 4.0]],
            "meta": {"sensor": 2, "levels": [1.5, None]},
        }

    def test_unicode_preserved(self) -> None:
        result = safe_json_dumps({"text": "Ünïcödé"})
        assert "Ünïcödé" in result

    def test_always_returns_str(self) -> None:
        assert isinstance(safe_json_dumps(None), str)
        assert isinstance(safe_json_dumps([1, 2, 3]), str)


class TestJsonTextDumps:
    """Tests for :func:`json_text_dumps`."""

    def test_supports_sorted_pretty_text(self) -> None:
        result = json_text_dumps({"b": 2, "a": {"z": 1}}, sort_keys=True, indent=2)

        assert isinstance(result, str)
        assert result.splitlines()[1].strip() == '"a": {'
        assert json.loads(result) == {"a": {"z": 1}, "b": 2}

    def test_rejects_unsupported_indent(self) -> None:
        with pytest.raises(ValueError, match="indent=None or indent=2"):
            json_text_dumps({"a": 1}, indent=4)


# ── safe_json_loads ──────────────────────────────────────────────────────────


class TestSafeJsonLoads:
    """Tests for :func:`safe_json_loads`."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param('{"key": "value"}', {"key": "value"}, id="object"),
            pytest.param("[1, 2, 3]", [1, 2, 3], id="array"),
            pytest.param("42", 42, id="scalar"),
            pytest.param(None, None, id="none"),
            pytest.param("", None, id="empty"),
        ],
    )
    def test_loads_expected_values(self, value: str | None, expected: object) -> None:
        assert safe_json_loads(value, context="test") == expected

    def test_invalid_json_returns_none_and_logs_context(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="vibesensor.shared.json_utils"):
            result = safe_json_loads("{invalid json", context="test-field")
        assert result is None
        assert any(
            record.message == "Skipping invalid JSON payload while reading test-field"
            for record in caplog.records
        )


def test_depth_limited_value_still_round_trips_through_json() -> None:
    nested = {"a": {"b": {"c": {"d": "deep"}}}}
    cleaned, had = sanitize_for_json(nested, _max_depth=2)
    assert had is False
    assert json.loads(json.dumps(cleaned, allow_nan=False)) == {"a": {"b": {"c": None}}}


def test_payload_helpers_project_nested_json_objects() -> None:
    value = {
        "_i18n_key": "SUMMARY_LABEL",
        "params": {"severity": "warn"},
        "bands": [1, {"name": "cruise"}],
    }
    values = [
        {"code": "speed_gap", "state": "warn"},
        {"title": value},
    ]

    assert payload_value_from_json(value) == value
    assert payload_object_from_json(values[1]) == values[1]
    assert payload_objects_from_json(values) == values
