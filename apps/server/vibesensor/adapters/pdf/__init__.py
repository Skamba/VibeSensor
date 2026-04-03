"""vibesensor.adapters.pdf – PDF rendering over assembled report documents.

This package contains **only** rendering code (PDF builder, car diagram,
style, i18n). All analysis logic (findings, ranking, phase segmentation,
strength classification, etc.) lives in ``vibesensor.use_cases.diagnostics``.

Import analysis symbols from ``vibesensor.use_cases.diagnostics`` directly.

Module topology
---------------
- **Models**: ``models/`` (document, panel, section, and appendix dataclasses).
- **Assembly**: ``assembly/`` plus ``report_context.py`` (prepared report input
  -> ``ReportTemplateData`` document assembly).
- **Context helpers**: ``_candidate_resolver.py`` (primary candidate),
  ``_card_builder.py`` (system cards and signature humanization).
- **Assembly helpers**: ``peak_table.py``, ``report_sections.py``,
  ``presentation.py``, ``pattern_parts.py``.
- **Engine**: ``pdf_engine.py`` (public entry, page orchestration, pagination).
- **Pages**: ``pdf_page1.py``, ``pdf_page2.py`` (thin page composers over the
  panel renderers in ``panels/_panel_*.py``).
- **Panels**: ``panels/_panel_*.py`` (page-section renderers grouped by visual
  block responsibility).
- **Diagrams**: ``pdf_diagram_render.py`` (layout planning, drawing).
- **Primitives**: ``pdf_drawing.py``, ``pdf_text.py``, ``pdf_style.py``
  (theme, constants, page geometry, render context).

Dependency rule: pages -> primitives -> data; diagrams -> primitives -> data.
Modules must not import from ``vibesensor.use_cases.diagnostics`` sub-modules.
``assembly`` may consume the prepared report-input contract from
``vibesensor.use_cases.history.report_preparation`` but must not call back into
history-layer interpretation or diagnostics helpers directly.
"""
