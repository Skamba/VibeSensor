"""Backward-compatibility wrapper – delegates to :mod:`vibesensor.routes`.

All route logic now lives in domain-specific modules under ``routes/``.
This file re-exports the public symbols that existing tests and call-sites
import so that ``from vibesensor.api import create_router`` (and friends)
keeps working without changes.
"""

from __future__ import annotations

# Re-export api_models symbols that tests import through this module.
from .api_models import ActiveCarRequest as ActiveCarRequest  # noqa: F401
from .api_models import AnalysisSettingsRequest as AnalysisSettingsRequest  # noqa: F401
from .api_models import AnalysisSettingsResponse as AnalysisSettingsResponse  # noqa: F401
from .api_models import CarLibraryModelsResponse as CarLibraryModelsResponse  # noqa: F401
from .api_models import CarUpsertRequest as CarUpsertRequest  # noqa: F401
from .api_models import SetLocationRequest as SetLocationRequest  # noqa: F401
from .api_models import UpdateStartRequest as UpdateStartRequest  # noqa: F401
from .routes import create_router as create_router  # noqa: F401
from .routes._helpers import safe_filename as _safe_filename  # noqa: F401
from .routes.history import EXPORT_CSV_COLUMNS as _EXPORT_CSV_COLUMNS  # noqa: F401
from .routes.history import build_report_pdf as build_report_pdf  # noqa: F401
from .routes.history import flatten_for_csv as _flatten_for_csv  # noqa: F401
from .runlog import bounded_sample as _bounded_sample  # noqa: F401  # re-exported for tests
