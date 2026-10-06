"""The engine profile and the engine orders its rules table gives it."""

from __future__ import annotations

import pytest

from vibesensor.domain.engine_profile import (
    EngineProfile,
    engine_orders,
    engine_profile_from_engine_text,
)
from vibesensor.settings.vehicle_configurations import load_vehicle_configurations


def _orders(profile: EngineProfile | None) -> list[tuple[str, tuple[str, ...]]]:
    return [(order.code, order.roles) for order in engine_orders(profile)]


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        pytest.param(None, [("E1", ("rotating",)), ("E2", ())], id="unknown-keeps-e1-e2"),
        pytest.param(
            EngineProfile("inline", 2), [("E1", ("rotating", "firing"))], id="inline-2-fires-e1"
        ),
        pytest.param(
            EngineProfile("inline", 3),
            [("E1", ("rotating", "imbalance")), ("E1.5", ("firing",))],
            id="inline-3-rocking-couple",
        ),
        pytest.param(
            EngineProfile("inline", 4),
            [("E1", ("rotating",)), ("E2", ("firing", "imbalance"))],
            id="inline-4-secondary",
        ),
        pytest.param(
            EngineProfile("inline", 5), [("E1", ("rotating",)), ("E2.5", ("firing",))], id="i5"
        ),
        pytest.param(
            EngineProfile("inline", 6), [("E1", ("rotating",)), ("E3", ("firing",))], id="i6"
        ),
        pytest.param(
            EngineProfile("v", 6, bank_angle_deg=90),
            [("E1", ("rotating", "imbalance")), ("E3", ("firing",))],
            id="v6-90-primary-couple",
        ),
        pytest.param(
            EngineProfile("v", 6),
            [("E1", ("rotating",)), ("E3", ("firing",))],
            id="v6-bank-unknown",
        ),
        pytest.param(
            EngineProfile("v", 6, bank_angle_deg=60),
            [("E1", ("rotating",)), ("E3", ("firing",))],
            id="v6-60",
        ),
        pytest.param(EngineProfile("v", 8), [("E1", ("rotating",)), ("E4", ("firing",))], id="v8"),
        pytest.param(
            EngineProfile("v", 10), [("E1", ("rotating",)), ("E5", ("firing",))], id="v10"
        ),
        pytest.param(
            EngineProfile("v", 12), [("E1", ("rotating",)), ("E6", ("firing",))], id="v12"
        ),
        pytest.param(
            EngineProfile("w", 12), [("E1", ("rotating",)), ("E6", ("firing",))], id="w12"
        ),
        pytest.param(
            EngineProfile("flat", 4),
            [("E1", ("rotating",)), ("E2", ("firing", "imbalance"))],
            id="flat-4-secondary-couple",
        ),
        pytest.param(
            EngineProfile("flat", 6), [("E1", ("rotating",)), ("E3", ("firing",))], id="flat-6"
        ),
        pytest.param(
            EngineProfile("rotary", 2),
            [("E1", ("rotating",)), ("E2", ("firing",))],
            id="rotary-fires-once-per-rotor-per-shaft-turn",
        ),
    ],
)
def test_engine_orders_follow_the_rules_table(
    profile: EngineProfile | None, expected: list[tuple[str, tuple[str, ...]]]
) -> None:
    assert _orders(profile) == expected


def test_a_half_order_has_a_code_key_and_label_of_its_own() -> None:
    firing = engine_orders(EngineProfile("inline", 3))[1]

    assert (firing.multiple, firing.code, firing.key) == (1.5, "E1.5", "engine_1_5x")
    assert [order.key for order in engine_orders(EngineProfile("inline", 6))] == [
        "engine_1x",
        "engine_3x",
    ]
    assert EngineProfile("inline", 6).firing_order.code == "E3"
    assert EngineProfile("inline", 2).firing_order.roles == ("rotating", "firing")


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        pytest.param(dict(layout="inline", cylinders=0), "cylinders", id="no-cylinders"),
        pytest.param(dict(layout="inline", cylinders=17), "cylinders", id="too-many"),
        pytest.param(dict(layout="rotary", cylinders=5), "cylinders", id="too-many-rotors"),
        pytest.param(dict(layout="inline", cylinders=4, bank_angle_deg=90), "bank", id="inline"),
        pytest.param(dict(layout="v", cylinders=8, bank_angle_deg=0), "bank", id="flat-bank"),
        pytest.param(dict(layout="hemi", cylinders=8), "layout", id="unknown-layout"),
    ],
)
def test_an_impossible_profile_is_rejected(fields: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        EngineProfile(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("B58 3.0L I6 Turbo", EngineProfile("inline", 6)),
        ("B38 1.5L I3 Turbo PHEV", EngineProfile("inline", 3)),
        ("B47 2.0L I4 Turbo Diesel", EngineProfile("inline", 4)),
        ("2.5L I5 Turbo", EngineProfile("inline", 5)),
        ("3.0L V6 Supercharged", EngineProfile("v", 6)),
        ("N63 4.4L V8 Turbo", EngineProfile("v", 8)),
        ("6.6L V12 Turbo", EngineProfile("v", 12)),
        ("Electric Dual Motor", None),
        ("", None),
        (None, None),
    ],
)
def test_the_profile_is_read_from_the_library_engine_text(
    text: str | None, expected: EngineProfile | None
) -> None:
    assert engine_profile_from_engine_text(text) == expected


# Engine families pinned to their cylinder counts (BMW technical data).
_BMW_FAMILIES = {
    "B37": 3,
    "B38": 3,
    "B47": 4,
    "B48": 4,
    "N20": 4,
    "B57": 6,
    "B58": 6,
    "N55": 6,
    "N57": 6,
    "S55": 6,
    "S58": 6,
    "N63": 8,
    "S63": 8,
    "S68": 8,
}


def test_every_combustion_row_of_the_library_has_a_profile_and_no_ev_has_one() -> None:
    families: dict[str, set[tuple[str, int]]] = {}
    for config in load_vehicle_configurations():
        profile = config.engine_profile
        if config.fuel_type == "EV":
            assert profile is None, config.id
            continue
        assert profile is not None, config.id
        assert profile.bank_angle_deg is None, config.id
        if config.brand == "BMW" and config.engine_code in _BMW_FAMILIES:
            families.setdefault(config.engine_code, set()).add((profile.layout, profile.cylinders))
    assert families == {
        code: {("v" if count == 8 else "inline", count)} for code, count in _BMW_FAMILIES.items()
    }
