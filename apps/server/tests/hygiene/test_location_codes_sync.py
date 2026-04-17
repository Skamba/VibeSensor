"""Guard: backend location codes stay in sync with generated UI constants."""

from __future__ import annotations

import json
import re
import subprocess
import sys

from tests._paths import REPO_ROOT
from vibesensor.domain.sensor import _LOCATION_CODES as DOMAIN_LOCATION_CODES
from vibesensor.shared.locations import LOCATION_CODES

_GENERATOR = REPO_ROOT / "tools" / "config" / "generate_ui_shared_constants.py"


def _generated_constants_ts() -> str:
    result = subprocess.run(
        [sys.executable, str(_GENERATOR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _extract_export_json(module_text: str, export_name: str) -> object:
    match = re.search(
        rf"export const {re.escape(export_name)} = (?P<value>\{{.*?\}}|\[.*?\]) as const;",
        module_text,
        re.DOTALL,
    )
    assert match is not None, f"Missing generated export {export_name}"
    return json.loads(match.group("value"))


def test_generated_ui_constants_encode_backend_locations() -> None:
    """The shared constants generator must reflect backend location literals only."""
    generated = _generated_constants_ts()
    assert "export const METRIC_FIELDS" not in generated
    assert "export const LOCATION_CODES" not in generated
    assert _extract_export_json(generated, "defaultLocationCodes") == list(LOCATION_CODES.keys())


def test_domain_location_codes_match_shared() -> None:
    """Domain-internal _LOCATION_CODES must stay in sync with shared/locations."""
    assert DOMAIN_LOCATION_CODES == LOCATION_CODES, (
        "domain/sensor.py _LOCATION_CODES drifted from shared/locations.py LOCATION_CODES"
    )
