"""vibesensor.report – renderer-only PDF/report modules.

This package contains **only** rendering code (PDF builder, car diagram,
theme, i18n).  All analysis logic (findings, ranking, phase segmentation,
strength classification, etc.) lives in ``vibesensor.analysis``.

Import analysis symbols from ``vibesensor.analysis`` directly.

Module topology
---------------
- **Data layer**: ``report_data.py`` (dataclasses, ``from_dict()``), ``theme.py``.
- **Engine**: ``pdf_engine.py`` (public entry, page orchestration, pagination).
- **Pages**: ``pdf_page1.py``, ``pdf_page1_sections.py``, ``pdf_page2.py``,
  ``pdf_page2_sections.py``.
- **Diagrams**: ``pdf_diagram_layout.py`` (planning), ``pdf_diagram_models.py``
  (geometry), ``pdf_diagram_render.py`` (drawing).
- **Primitives**: ``pdf_drawing.py``, ``pdf_text.py``, ``pdf_style.py``,
  ``pdf_layout.py``, ``pdf_page_layouts.py``, ``pdf_helpers.py``,
  ``pdf_render_context.py``.

Dependency rule: pages → primitives → data; diagrams → primitives → data.
Modules must not import from ``vibesensor.analysis`` sub-modules.
"""
