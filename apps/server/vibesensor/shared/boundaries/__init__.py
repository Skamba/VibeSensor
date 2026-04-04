"""Boundary serializers and decoders for domain-first core models.

Focused conversion families live in sibling subpackages:

- ``analysis_payloads/`` owns ``AnalysisResult`` <-> summary/persisted payloads
- ``reporting/`` owns report preparation and report-facing fact shaping
- ``sensor_frames/`` owns ``SensorFrame`` JSON and storage-row adapters

Keep standalone top-level modules for single-purpose codecs and projections only.
"""
