"""Guard normalization and duplicate-assignment behavior in location assignment validation."""

from __future__ import annotations

import pytest

from vibesensor.infra.location_assignment_validator import (
    AssignedLocation,
    LocationAssignmentValidator,
)


def test_normalize_strips_whitespace() -> None:
    validator = LocationAssignmentValidator()

    assert validator.normalize("  front-left  ") == "front-left"


def test_normalize_caps_utf8_bytes_without_splitting_codepoints() -> None:
    validator = LocationAssignmentValidator(max_utf8_bytes=64)

    normalized = validator.normalize("€" * 25)

    assert len(normalized.encode("utf-8")) <= 64
    assert normalized.encode("utf-8").decode("utf-8") == normalized
    assert normalized == "€" * 21


def test_validate_assignment_rejects_duplicate_location() -> None:
    validator = LocationAssignmentValidator()

    with pytest.raises(ValueError, match="Location 'front_left' already assigned to Rear Left"):
        validator.validate_assignment(
            owner_id="aabbccddeeff",
            location_code="front_left",
            assigned_locations=[
                AssignedLocation(
                    owner_id="112233445566",
                    owner_name="Rear Left",
                    location_code="front_left",
                ),
            ],
        )


def test_validate_assignment_allows_reassigning_same_owner() -> None:
    validator = LocationAssignmentValidator()

    validator.validate_assignment(
        owner_id="aabbccddeeff",
        location_code="front_left",
        assigned_locations=[
            AssignedLocation(
                owner_id="aabbccddeeff",
                owner_name="Front Left",
                location_code="front_left",
            ),
        ],
    )
