"""vibesensor.analysis.findings – post-stop vibration findings engine.

Module topology
---------------
- **Orchestration**: ``builder.py`` (main ``_build_findings()``),
  ``builder_support.py`` (helper functions for the builder).
- **Domain finders**: ``order_findings.py`` (order-tracking hypothesis),
  ``persistent_findings.py`` (non-order persistent/transient peaks),
  ``reference_checks.py`` (reference-missing findings).
- **Support**: ``intensity.py`` (per-location intensity stats & breakdowns),
  ``speed_profile.py`` (speed-profile extraction & phase helpers).
- **Order internals**: ``order_assembly.py`` (assembly), ``order_matching.py``
  (frequency matching), ``order_scoring.py`` (confidence scoring),
  ``order_support.py`` (helper utilities), ``order_models.py`` (data models).
- **Constants**: ``_constants.py`` (re-exports from ``vibesensor.constants``).

Dependency rule: builder → domain finders → support/order internals → constants.
The ``order_*`` modules form a cohesive sub-layer for rotational-order analysis.
All constants originate from ``vibesensor.constants`` (single source of truth).
"""
