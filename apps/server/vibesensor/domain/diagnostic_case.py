"""Case-level aggregate for one diagnostic problem over one investigation episode."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from vibesensor.domain.car import Car
from vibesensor.domain.test_plan import TestPlan
from vibesensor.domain.test_run import TestRun

__all__ = ["DiagnosticCase", "Symptom"]


# ── Symptom ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Symptom:
    """The complaint or observed problem motivating diagnosis."""

    description: str
    onset: str = ""
    context: str = ""

    @classmethod
    def unspecified(cls) -> Symptom:
        return cls(description="unspecified complaint")

    @property
    def is_unspecified(self) -> bool:
        return self.description.strip().lower() == "unspecified complaint"

    @property
    def is_speed_dependent(self) -> bool:
        text = f"{self.description} {self.context}".lower()
        return any(token in text for token in ("speed", "km/h", "cruise", "driving"))

    @property
    def is_transient(self) -> bool:
        text = f"{self.description} {self.context} {self.onset}".lower()
        return any(token in text for token in ("intermittent", "transient", "sometimes"))


# ── DiagnosticCase ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DiagnosticCase:
    """Top-level aggregate for the diagnostic problem under investigation."""

    case_id: str
    car: Car | None = None
    symptoms: tuple[Symptom, ...] = ()
    test_plan: TestPlan = TestPlan()
    test_runs: tuple[TestRun, ...] = ()

    _EMPTY_TEST_PLAN = TestPlan()

    @classmethod
    def start(
        cls,
        *,
        car: Car | None = None,
        symptoms: tuple[Symptom, ...] = (),
        test_plan: TestPlan | None = None,
    ) -> DiagnosticCase:
        return cls(
            case_id=uuid4().hex,
            car=car,
            symptoms=symptoms or (Symptom.unspecified(),),
            test_plan=test_plan or cls._EMPTY_TEST_PLAN,
        )

    def add_run(self, test_run: TestRun) -> DiagnosticCase:
        return replace(
            self,
            test_runs=(*self.test_runs, test_run),
        )

    @property
    def primary_run(self) -> TestRun | None:
        return self.test_runs[-1] if self.test_runs else None
