"""Guard: backend and frontend LOCATION_CODES stay in sync."""

from __future__ import annotations

import re

from tests._paths import REPO_ROOT
from vibesensor.domain.sensor import _LOCATION_CODES as DOMAIN_LOCATION_CODES
from vibesensor.shared.locations import LOCATION_CODES

_CONSTANTS_TS = REPO_ROOT / "apps" / "ui" / "src" / "constants.ts"


def test_frontend_location_codes_match_backend() -> None:
    """Frontend constants.ts LOCATION_CODES must match backend keys."""
    text = _CONSTANTS_TS.read_text()
    frontend_codes = re.findall(r'"([a-z_]+)"', text.split("LOCATION_CODES")[1].split("]")[0])
    backend_codes = list(LOCATION_CODES.keys())
    assert frontend_codes == backend_codes, (
        f"Frontend/backend location code mismatch.\n"
        f"  Backend:  {backend_codes}\n"
        f"  Frontend: {frontend_codes}"
    )


def test_domain_location_codes_match_shared() -> None:
    """Domain-internal _LOCATION_CODES must stay in sync with shared/locations."""
    assert DOMAIN_LOCATION_CODES == LOCATION_CODES, (
        "domain/sensor.py _LOCATION_CODES drifted from shared/locations.py LOCATION_CODES"
    )
