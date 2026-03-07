"""Composed run-history persistence mixins for HistoryDB."""

from __future__ import annotations

from ._run_common import ANALYSIS_SCHEMA_VERSION as ANALYSIS_SCHEMA_VERSION
from ._run_common import RunStatus as RunStatus
from ._run_reads import HistoryRunReadMixin
from ._run_writes import HistoryRunWriteMixin


class HistoryRunStoreMixin(HistoryRunWriteMixin, HistoryRunReadMixin):
    """Combined run-history API: writes plus reads under the old public surface."""

    __slots__ = ()
