"""vibesensor.adapters.pdf – renderer-only PDF/report modules.

This package contains **only** rendering code (PDF builder, car diagram,
style, i18n).  All analysis logic (findings, ranking, phase segmentation,
strength classification, etc.) lives in ``vibesensor.use_cases.diagnostics``.

Import analysis symbols from ``vibesensor.use_cases.diagnostics`` directly.

Module topology
---------------
- **Data layer**: ``report_data.py`` (report metadata and renderer dataclasses).
- **Context assembly**: ``report_context.py`` (``ReportMappingContext`` and
  summary/data-prep bridge to adapter rendering).
- **Context helpers**: ``_candidate_resolver.py`` (primary candidate),
  ``_card_builder.py`` (system cards and signature humanization).
- **Mapping**: ``mapping.py`` (thin mapper: context → ``ReportTemplateData``).
- **Mapping helpers**: ``peak_table.py`` (peak rows), ``report_sections.py`` (report sections), ``presentation.py`` (render-only labels), ``pattern_parts.py`` (parts suggestions).
- **Engine**: ``pdf_engine.py`` (public entry, page orchestration, pagination).
- **Pages**: ``pdf_page1.py``, ``pdf_page2.py`` (thin page composers over ``_panel_*.py`` modules).
- **Diagrams**: ``pdf_diagram_render.py`` (layout planning, drawing).
- **Primitives**: ``pdf_drawing.py``, ``pdf_text.py``,
  ``pdf_style.py`` (theme, constants, page geometry, render context).

Dependency rule: pages → primitives → data; diagrams → primitives → data.
Modules must not import from ``vibesensor.use_cases.diagnostics`` sub-modules.
``mapping.py`` must not import from ``vibesensor.use_cases`` —
``report_context.py`` handles that bridge.
"""
