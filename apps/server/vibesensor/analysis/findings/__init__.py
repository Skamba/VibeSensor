"""vibesensor.analysis.findings – post-stop vibration findings engine.

Split into focused sub-modules:

- ``builder``            – main ``_build_findings()`` orchestrator
- ``order_findings``     – order-tracking hypothesis matching
- ``persistent_findings``– non-order persistent/transient peak findings
- ``intensity``          – per-location intensity statistics & breakdowns
- ``speed_profile``      – speed-profile extraction & phase helpers
- ``reference_checks``   – reference-missing finding generation
- ``_constants``         – shared constants
"""
