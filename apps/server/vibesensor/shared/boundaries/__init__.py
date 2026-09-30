"""Boundary serializers and decoders for domain-first core models.

Focused conversion families live in sibling modules and subpackages; import
names from the module that defines them:

- ``analysis_payloads/`` owns ``AnalysisResult`` <-> summary/persisted payloads
  and summary -> ``TestRun`` reconstruction
- ``clients`` owns client API/WS payload projection from runtime snapshots
- ``runs/`` owns persisted run metadata, log, capture, and suitability adapters
- ``reporting/`` owns report preparation and report-facing fact shaping
- ``settings`` owns persisted settings snapshot normalization
- ``summary_fields/`` owns finding, warning, origin, and test-plan payload fragments
- ``sensor_frames/`` owns ``SensorFrame`` JSON codecs

Keep the top level family-oriented; add new boundary helpers to the matching
family instead of as new standalone siblings.
"""
