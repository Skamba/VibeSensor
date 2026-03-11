"""vibesensor.report – renderer-only PDF/report modules.

This package contains **only** rendering code (PDF builder, car diagram,
style, i18n).  All analysis logic (findings, ranking, phase segmentation,
strength classification, etc.) lives in ``vibesensor.analysis``.

Import analysis symbols from ``vibesensor.analysis`` directly.

Module topology
---------------
- **Data layer**: ``report_data.py`` (dataclasses).
- **Engine**: ``pdf_engine.py`` (public entry, page orchestration, pagination).
- **Pages**: ``pdf_page1.py``, ``pdf_page2.py``.
- **Diagrams**: ``pdf_diagram_render.py`` (layout planning, drawing).
- **Primitives**: ``pdf_drawing.py``, ``pdf_text.py``,
  ``pdf_style.py`` (theme, constants, page geometry, render context).

Dependency rule: pages → primitives → data; diagrams → primitives → data.
Modules must not import from ``vibesensor.analysis`` sub-modules.
"""
