from __future__ import annotations

from vibesensor.adapters.simulator.scripted_targeting import matches_scripted_target


def test_matches_scripted_target_supports_group_aliases_and_named_slots() -> None:
    assert matches_scripted_target("front-left", "all")
    assert matches_scripted_target("front-left", "front-axle")
    assert matches_scripted_target("rear-left", "left-side")
    assert matches_scripted_target("trunk", "body")
    assert matches_scripted_target("front_left", "front-left")
    assert not matches_scripted_target("trunk", "front-axle")
    assert not matches_scripted_target("front-right", "rear-right")
