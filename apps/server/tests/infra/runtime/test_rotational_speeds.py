from __future__ import annotations

from vibesensor.infra.runtime.rotational_speeds import rotational_basis_speed_source


def test_rotational_basis_speed_source_prefers_explicit_resolution_source() -> None:
    assert (
        rotational_basis_speed_source(
            "gps",
            gps_enabled=True,
            resolution_source="fallback_manual",
        )
        == "fallback_manual"
    )


def test_rotational_basis_speed_source_uses_fallback_flag_without_resolution_source() -> None:
    assert (
        rotational_basis_speed_source(
            "gps",
            gps_enabled=True,
            fallback_active=True,
        )
        == "fallback_manual"
    )


def test_rotational_basis_speed_source_handles_disabled_gps() -> None:
    assert (
        rotational_basis_speed_source("gps", gps_enabled=False, resolution_source="none")
        == "unknown"
    )


def test_rotational_basis_speed_source_preserves_manual_selection() -> None:
    assert (
        rotational_basis_speed_source("manual", gps_enabled=True, resolution_source="gps")
        == "manual"
    )
