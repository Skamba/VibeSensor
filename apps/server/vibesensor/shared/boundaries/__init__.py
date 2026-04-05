"""Boundary serializers and decoders for domain-first core models.

Focused conversion families live in sibling subpackages:

- ``analysis_payloads/`` owns ``AnalysisResult`` <-> summary/persisted payloads
- ``runs/`` owns persisted run metadata, log, capture, and suitability adapters
- ``reporting/`` owns report preparation and report-facing fact shaping
- ``settings/`` owns persisted settings-snapshot normalization
- ``summary_fields/`` owns finding, warning, origin, and test-plan payload fragments
- ``sensor_frames/`` owns ``SensorFrame`` JSON and storage-row adapters

Keep the top level family-oriented; add new boundary helpers under the matching
subsystem package instead of as new standalone siblings.
"""
