"""Guard: backend and frontend LOCATION_CODES stay in sync."""

from __future__ import annotations

import subprocess
import sys

from tests._paths import REPO_ROOT
from vibesensor.domain.sensor import _LOCATION_CODES as DOMAIN_LOCATION_CODES
from vibesensor.shared.locations import LOCATION_CODES

_CONSTANTS_TS = REPO_ROOT / "apps" / "ui" / "src" / "constants.ts"
_GENERATOR = REPO_ROOT / "tools" / "config" / "generate_ui_shared_constants.py"


def _generated_constants_ts() -> str:
    result = subprocess.run(
        [sys.executable, str(_GENERATOR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_generated_ui_constants_are_current() -> None:
    """Generated apps/ui/src/constants.ts must stay in sync with backend sources."""
    expected = _generated_constants_ts()
    actual = _CONSTANTS_TS.read_text()
    assert actual == expected, (
        "apps/ui/src/constants.ts is stale.\n"
        "Run `npm run sync:contracts` to regenerate the shared UI constants."
    )


def test_domain_location_codes_match_shared() -> None:
    """Domain-internal _LOCATION_CODES must stay in sync with shared/locations."""
    assert DOMAIN_LOCATION_CODES == LOCATION_CODES, (
        "domain/sensor.py _LOCATION_CODES drifted from shared/locations.py LOCATION_CODES"
    )
