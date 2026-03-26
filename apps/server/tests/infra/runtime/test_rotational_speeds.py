"""Guard rotational-basis speed-source selection across fallback and GPS states."""

from __future__ import annotations

import pytest

from vibesensor.infra.runtime.rotational_speeds import rotational_basis_speed_source


@pytest.mark.parametrize(
    ("selected_source", "kwargs", "expected"),
    [
        (
            "gps",
            {"gps_enabled": True, "resolution_source": "fallback_manual"},
            "fallback_manual",
        ),
        (
            "gps",
            {"gps_enabled": True, "fallback_active": True},
            "fallback_manual",
        ),
        (
            "gps",
            {"gps_enabled": False, "resolution_source": "none"},
            "unknown",
        ),
        (
            "manual",
            {"gps_enabled": True, "resolution_source": "gps"},
            "manual",
        ),
    ],
)
def test_rotational_basis_speed_source_cases(
    selected_source: str,
    kwargs: dict[str, object],
    expected: str,
) -> None:
    assert rotational_basis_speed_source(selected_source, **kwargs) == expected
