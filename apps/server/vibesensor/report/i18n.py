"""Report internationalisation – re-export from canonical module.

The implementation stays in ``vibesensor.report_i18n`` so that existing
tests which monkeypatch module-level state (e.g. ``_DATA_FILE``) keep
working.  Report-internal code should import from this module
(``vibesensor.report.i18n``) to express the correct dependency direction.
"""

from ..report_i18n import (
    _load_translations,
    normalize_lang,
    tr,
    variants,
)
