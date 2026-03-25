"""GPS-related adapters.

Sub-modules
-----------
- :mod:`~vibesensor.adapters.gps.gps_transport` — GPSD connection loop and TPV ingestion.
- :mod:`~vibesensor.adapters.gps.speed_validation` — GPS speed plausibility policy.
- :mod:`~vibesensor.adapters.gps.speed_resolution` — manual override and stale-fallback policy.
- :mod:`~vibesensor.adapters.gps.speed_status` — JSON-style status presentation helpers.
- :mod:`~vibesensor.adapters.gps.gps_speed` — thin runtime-facing monitor facade.
"""
