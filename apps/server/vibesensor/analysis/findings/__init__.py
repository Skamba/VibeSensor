"""vibesensor.analysis.findings – post-stop vibration findings engine.

Previously a single 1,600-line module, now split into focused sub-modules:

- ``builder``            – main ``_build_findings()`` orchestrator
- ``order_findings``     – order-tracking hypothesis matching
- ``persistent_findings``– non-order persistent/transient peak findings
- ``intensity``          – per-location intensity statistics & breakdowns
- ``speed_profile``      – speed-profile extraction & phase helpers
- ``reference_checks``   – reference-missing finding generation
- ``_constants``         – shared constants

All public symbols are re-exported here so that existing imports of the form
``from vibesensor.analysis.findings import X`` continue to work unchanged.
"""

from ..helpers import _speed_bin_label, _weighted_percentile  # noqa: F401 – re-exports
from .builder import _build_findings  # noqa: F401
from .intensity import (  # noqa: F401
    _phase_speed_breakdown,
    _sensor_intensity_by_location,
    _speed_breakdown,
)
from .order_findings import (  # noqa: F401
    _build_order_findings,
    _compute_effective_match_rate,
    _compute_order_confidence,
    _detect_diffuse_excitation,
    _suppress_engine_aliases,
)
from .persistent_findings import (  # noqa: F401
    BASELINE_NOISE_SNR_THRESHOLD,
    PERSISTENT_PEAK_MAX_FINDINGS,
    PERSISTENT_PEAK_MIN_PRESENCE,
    TRANSIENT_BURSTINESS_THRESHOLD,
    _build_persistent_peak_findings,
    _classify_peak_type,
)
from .reference_checks import _reference_missing_finding  # noqa: F401
from .speed_profile import _phase_to_str, _speed_profile_from_points  # noqa: F401

__all__ = [
    "BASELINE_NOISE_SNR_THRESHOLD",
    "PERSISTENT_PEAK_MAX_FINDINGS",
    "PERSISTENT_PEAK_MIN_PRESENCE",
    "TRANSIENT_BURSTINESS_THRESHOLD",
    "_build_findings",
    "_build_order_findings",
    "_build_persistent_peak_findings",
    "_classify_peak_type",
    "_compute_effective_match_rate",
    "_compute_order_confidence",
    "_detect_diffuse_excitation",
    "_phase_speed_breakdown",
    "_phase_to_str",
    "_reference_missing_finding",
    "_sensor_intensity_by_location",
    "_speed_bin_label",
    "_speed_breakdown",
    "_speed_profile_from_points",
    "_suppress_engine_aliases",
    "_weighted_percentile",
]
