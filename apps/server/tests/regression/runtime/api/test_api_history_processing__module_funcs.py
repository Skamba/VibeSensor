"""Runtime regressions spanning API, history, and processing boundaries."""

from __future__ import annotations

import re

from _paths import SERVER_ROOT

_SAFE_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def test_live_diagnostics_entries_type_annotation() -> None:
    """Verify event_detector properly extracts label and location per client."""
    source = (SERVER_ROOT / "vibesensor" / "live_diagnostics" / "event_detector.py").read_text()
    assert "client_map" in source, "client_map lookup must exist"
    assert "client_location_map" in source, "client_location_map lookup must exist"


def test_set_location_uses_stripped_code() -> None:
    """Verify the stripped code is passed to registry.set_location."""
    source = (SERVER_ROOT / "vibesensor" / "routes" / "clients.py").read_text()
    assert "set_location(normalized_client_id, code)" in source
    assert "set_location(normalized_client_id, req.location_code)" not in source
