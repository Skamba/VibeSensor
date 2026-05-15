from __future__ import annotations

import pytest

from vibesensor.adapters.simulator.scripted_targeting import matches_scripted_target


@pytest.mark.parametrize(
    ("client_name", "target", "expected"),
    [
        ("front-left", "all", True),
        ("front-left", "front-axle", True),
        ("rear-left", "left-side", True),
        ("trunk", "body", True),
        ("front_left", "front-left", True),
        ("trunk", "front-axle", False),
        ("front-right", "rear-right", False),
    ],
)
def test_matches_scripted_target_supports_aliases_and_named_slots(
    client_name: str,
    target: str,
    expected: bool,
) -> None:
    assert matches_scripted_target(client_name, target) is expected
