"""Shared lightweight typing aliases for the analysis package."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeAlias

from .phase_segmentation import DrivingPhase

Sample: TypeAlias = dict[str, Any]
Finding: TypeAlias = dict[str, Any]
SummaryData: TypeAlias = dict[str, Any]
PhaseLabel: TypeAlias = DrivingPhase | str
PhaseLabels: TypeAlias = Sequence[PhaseLabel]
Translator: TypeAlias = Callable[[str], str]