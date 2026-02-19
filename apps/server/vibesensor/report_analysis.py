"""Backward-compat shim – real code lives in vibesensor.report.*"""

# Re-export the public API from the new sub-package.
# Names that tests also pull from here (originally imported at top of file).
from .analysis.vibration_strength import _percentile  # noqa: F401
from .report.findings import (  # noqa: F401
    _build_findings,
    _build_order_findings,
    _finding_actions_for_source,
    _location_speedbin_summary,
    _merge_test_plan,
    _reference_missing_finding,
    _sensor_intensity_by_location,
    _speed_breakdown,
    _wheel_hz,
)
from .report.helpers import (  # noqa: F401
    CONSTANT_SPEED_STDDEV_KMH,
    ORDER_CONSTANT_SPEED_MIN_MATCH_RATE,
    ORDER_MIN_CONFIDENCE,
    ORDER_MIN_COVERAGE_POINTS,
    ORDER_MIN_MATCH_POINTS,
    ORDER_TOLERANCE_MIN_HZ,
    ORDER_TOLERANCE_REL,
    SPEED_BIN_WIDTH_KMH,
    SPEED_COVERAGE_MIN_PCT,
    SPEED_MIN_POINTS,
    STEADY_SPEED_RANGE_KMH,
    STEADY_SPEED_STDDEV_KMH,
    _corr_abs,
    _effective_engine_rpm,
    _format_duration,
    _load_run,
    _location_label,
    _locations_connected_throughout_run,
    _mean_variance,
    _normalize_lang,
    _outlier_summary,
    _percent_missing,
    _primary_vibration_strength_db,
    _required_text,
    _sample_top_peaks,
    _sensor_limit_g,
    _speed_bin_label,
    _speed_bin_sort_key,
    _speed_stats,
    _text,
    _tire_reference_from_metadata,
    _validate_required_strength_metrics,
)
from .report.summary import (  # noqa: F401
    build_findings_for_samples,
    confidence_label,
    select_top_causes,
    summarize_log,
    summarize_run_data,
)
from .runlog import as_float_or_none as _as_float  # noqa: F401

__all__ = [
    "build_findings_for_samples",
    "confidence_label",
    "select_top_causes",
    "summarize_log",
    "summarize_run_data",
]
