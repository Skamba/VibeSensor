"""Exact vehicle-configuration rows used as canonical order-analysis source data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .tire_spec import AxleTireSetup, TireSpec

__all__ = [
    "VehicleConfiguration",
    "VehicleConfigurationConfidence",
    "VehicleConfigurationField",
    "VehicleConfigurationIssue",
    "VehicleConfigurationNote",
    "VehicleConfigurationSourceStatus",
    "VehicleConfigurationTireOption",
    "VehicleCoverageClassification",
    "VehicleDrivetrain",
    "VehicleFieldConfidence",
    "VehicleFieldMetadata",
    "VehicleFuelType",
    "VehicleOrderAnalysisKind",
    "VehicleOrderAnalysisPolicy",
    "VehicleOrderAnalysisPolicyOverride",
    "apply_order_analysis_policy_override",
    "derive_order_analysis_policy",
]

VehicleFuelType = Literal["ICE", "PHEV", "EV"]
VehicleDrivetrain = Literal["FWD", "RWD", "AWD"]
VehicleConfigurationSourceStatus = Literal["exact_row"]
VehicleConfigurationConfidence = Literal[
    "high_confidence",
    "medium_confidence",
    "low_confidence",
    "no_confidence",
    "not_applicable",
]
VehicleFieldConfidence = Literal[
    "official_exact",
    "official_derived",
    "reputable_secondary_crosschecked",
    "family_default",
    "unverified",
    "user_confirmed",
]
VehicleConfigurationField = Literal[
    "final_drive_front",
    "final_drive_rear",
    "top_gear_ratio",
    "gear_ratios",
    "drivetrain",
    "tire_dimensions",
    "transmission_name",
]
VehicleCoverageClassification = Literal["trusted", "approximate", "backlog_unverified"]
VehicleOrderAnalysisKind = Literal["wheel_order", "driveshaft_order", "engine_order"]


def _classify_confidences(
    confidences: tuple[VehicleFieldConfidence, ...],
) -> VehicleCoverageClassification:
    """Map a tuple of field confidences onto a single coverage classification."""

    if any(confidence == "unverified" for confidence in confidences):
        return "backlog_unverified"
    if any(confidence == "family_default" for confidence in confidences):
        return "approximate"
    return "trusted"


@dataclass(frozen=True, slots=True)
class VehicleFieldMetadata:
    """Confidence and evidence metadata for one canonical vehicle field."""

    confidence: VehicleFieldConfidence
    evidence_refs: tuple[str, ...] = ()
    verified_at: str | None = None
    notes: str | None = None

    @property
    def requires_evidence_refs(self) -> bool:
        """Whether this confidence level must resolve to explicit evidence."""

        return self.confidence in {
            "official_exact",
            "official_derived",
            "reputable_secondary_crosschecked",
        }


@dataclass(frozen=True, slots=True)
class VehicleConfigurationNote:
    """A preserved verification note that is not itself runtime truth."""

    note: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VehicleConfigurationIssue:
    """One unresolved research item attached to a canonical configuration row."""

    item: str
    reason: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VehicleOrderAnalysisPolicy:
    """Policy flags derived from canonical car-data confidence."""

    usable_for_engine_order: bool
    usable_for_driveshaft_order: bool
    usable_for_wheel_order: bool
    requires_manual_confirmation: bool


@dataclass(frozen=True, slots=True)
class VehicleOrderAnalysisPolicyOverride:
    """Sparse override applied on top of the derived order-analysis policy.

    Each non-``None`` field replaces the corresponding derived flag. ``reason``
    documents why the row deviates from the derivation.
    """

    reason: str
    usable_for_engine_order: bool | None = None
    usable_for_driveshaft_order: bool | None = None
    usable_for_wheel_order: bool | None = None
    requires_manual_confirmation: bool | None = None


def derive_order_analysis_policy(
    *,
    top_gear_ratio: float | None,
    final_drive_front: float | None,
    final_drive_rear: float | None,
    drivetrain: VehicleDrivetrain | None,
) -> VehicleOrderAnalysisPolicy:
    """Compute the default order-analysis policy from row math inputs.

    A row is *feasible* for an analysis kind when its math inputs are present:

    - ``wheel_order``: tire dimensions (always present on canonical rows).
    - ``driveshaft_order``: driven final-drive ratio.
    - ``engine_order``: driven final-drive ratio + top-gear ratio.

    The derived policy uses feasibility for the ``usable_for_*`` flags and
    sets ``requires_manual_confirmation`` to ``True`` by default. Specific
    rows can override individual flags via
    :class:`VehicleOrderAnalysisPolicyOverride`.
    """

    if drivetrain == "FWD":
        driven_final_drive: float | None = final_drive_front
    elif drivetrain == "RWD":
        driven_final_drive = final_drive_rear
    else:
        driven_final_drive = final_drive_rear or final_drive_front
    has_driven = driven_final_drive is not None
    has_top_gear = top_gear_ratio is not None
    return VehicleOrderAnalysisPolicy(
        usable_for_engine_order=has_top_gear and has_driven,
        usable_for_driveshaft_order=has_driven,
        usable_for_wheel_order=True,
        requires_manual_confirmation=True,
    )


def apply_order_analysis_policy_override(
    derived: VehicleOrderAnalysisPolicy,
    override: VehicleOrderAnalysisPolicyOverride | None,
) -> VehicleOrderAnalysisPolicy:
    """Return a policy with *override* fields replacing matching *derived* fields."""

    if override is None:
        return derived
    return VehicleOrderAnalysisPolicy(
        usable_for_engine_order=(
            derived.usable_for_engine_order
            if override.usable_for_engine_order is None
            else override.usable_for_engine_order
        ),
        usable_for_driveshaft_order=(
            derived.usable_for_driveshaft_order
            if override.usable_for_driveshaft_order is None
            else override.usable_for_driveshaft_order
        ),
        usable_for_wheel_order=(
            derived.usable_for_wheel_order
            if override.usable_for_wheel_order is None
            else override.usable_for_wheel_order
        ),
        requires_manual_confirmation=(
            derived.requires_manual_confirmation
            if override.requires_manual_confirmation is None
            else override.requires_manual_confirmation
        ),
    )


@dataclass(frozen=True, slots=True)
class VehicleConfigurationTireOption:
    """Named tire option attached to one canonical vehicle configuration."""

    name: str
    tire_setup: AxleTireSetup
    metadata: VehicleFieldMetadata | None = None


@dataclass(frozen=True, slots=True)
class VehicleConfiguration:
    """One typed drivetrain configuration row used as order-analysis source data."""

    brand: str
    car_type: str
    model_name: str
    variant_name: str
    drivetrain: VehicleDrivetrain
    transmission_name: str
    top_gear_ratio: float
    default_tire: TireSpec
    tire_options: tuple[VehicleConfigurationTireOption, ...]
    fuel_type: VehicleFuelType = "ICE"
    id: str | None = None
    market: str | None = None
    model_code: str | None = None
    body_code: str | None = None
    production_start_year: int | None = None
    production_end_year: int | None = None
    engine_code: str | None = None
    engine_name: str | None = None
    transmission_code: str | None = None
    gear_ratios: tuple[float, ...] | None = None
    final_drive_front: float | None = None
    final_drive_rear: float | None = None
    transfer_case_ratio: float | None = None
    source_status: VehicleConfigurationSourceStatus = "exact_row"
    drivetrain_metadata: VehicleFieldMetadata | None = None
    transmission_metadata: VehicleFieldMetadata | None = None
    top_gear_ratio_metadata: VehicleFieldMetadata | None = None
    gear_ratios_metadata: VehicleFieldMetadata | None = None
    final_drive_front_metadata: VehicleFieldMetadata | None = None
    final_drive_rear_metadata: VehicleFieldMetadata | None = None
    tire_metadata: VehicleFieldMetadata | None = None
    configuration_confidence: VehicleConfigurationConfidence = "not_applicable"
    order_analysis_policy: VehicleOrderAnalysisPolicy = field(
        default_factory=lambda: VehicleOrderAnalysisPolicy(
            usable_for_engine_order=False,
            usable_for_driveshaft_order=False,
            usable_for_wheel_order=False,
            requires_manual_confirmation=True,
        )
    )
    verification_notes: tuple[VehicleConfigurationNote, ...] = ()
    unresolved: tuple[VehicleConfigurationIssue, ...] = ()

    @property
    def driven_final_drive_ratio(self) -> float | None:
        """Return the most relevant driven final-drive ratio for the configuration."""

        if self.drivetrain == "FWD":
            return self.final_drive_front
        if self.drivetrain == "RWD":
            return self.final_drive_rear
        if self.final_drive_rear is not None:
            return self.final_drive_rear
        return self.final_drive_front

    def metadata_for(
        self,
        field_name: VehicleConfigurationField,
    ) -> VehicleFieldMetadata | None:
        """Return canonical metadata for *field_name* when present."""

        mapping: dict[VehicleConfigurationField, VehicleFieldMetadata | None] = {
            "drivetrain": self.drivetrain_metadata,
            "final_drive_front": self.final_drive_front_metadata,
            "final_drive_rear": self.final_drive_rear_metadata,
            "gear_ratios": self.gear_ratios_metadata,
            "tire_dimensions": self.tire_metadata,
            "top_gear_ratio": self.top_gear_ratio_metadata,
            "transmission_name": self.transmission_metadata,
        }
        return mapping[field_name]

    def order_reference_confidence(
        self,
        field_name: Literal["current_gear_ratio", "final_drive_ratio", "transmission_name"],
    ) -> VehicleFieldConfidence:
        """Return machine-readable confidence for one order-reference field."""

        if field_name == "current_gear_ratio":
            entry = self.metadata_for("top_gear_ratio")
        elif field_name == "transmission_name":
            entry = self.metadata_for("transmission_name")
        elif self.drivetrain == "FWD":
            entry = self.metadata_for("final_drive_front")
        elif self.drivetrain == "RWD":
            entry = self.metadata_for("final_drive_rear")
        else:
            entry = self.metadata_for("final_drive_rear") or self.metadata_for("final_drive_front")
        if entry is not None:
            return entry.confidence
        return "unverified"

    @property
    def coverage_policy_fields(self) -> tuple[VehicleConfigurationField, ...]:
        """Return the broad row research-completeness field set.

        These fields drive :py:attr:`research_completeness`. They include
        non-math fields (``transmission_name``, ``drivetrain``) that document
        the row but are *not* required for order-reference math. For the
        narrower order-analysis trust signal, use
        :py:meth:`order_reference_trust_for` / :py:attr:`order_reference_trust`.
        """

        fields: list[VehicleConfigurationField] = [
            "drivetrain",
            "tire_dimensions",
            "transmission_name",
            "top_gear_ratio",
        ]
        if self.final_drive_front is not None:
            fields.append("final_drive_front")
        if self.final_drive_rear is not None:
            fields.append("final_drive_rear")
        return tuple(fields)

    def coverage_policy_confidence(
        self,
        field_name: VehicleConfigurationField,
    ) -> VehicleFieldConfidence:
        """Return the policy-driving confidence for one order-analysis-critical field."""

        if field_name == "top_gear_ratio":
            return self.order_reference_confidence("current_gear_ratio")
        if field_name == "transmission_name":
            return self.order_reference_confidence("transmission_name")
        if field_name in {"final_drive_front", "final_drive_rear"}:
            entry = self.metadata_for(field_name)
            return entry.confidence if entry is not None else "unverified"
        entry = self.metadata_for(field_name)
        return entry.confidence if entry is not None else "unverified"

    @property
    def research_completeness(self) -> VehicleCoverageClassification:
        """Classify broad row research completeness across all documented fields.

        This signal reflects whether the row is broadly research-complete,
        including non-math labels (e.g. ``transmission_name``). Use
        :py:attr:`order_reference_trust` when the question is whether the
        order-analysis math inputs are trustworthy.
        """

        confidences = tuple(
            self.coverage_policy_confidence(field_name)
            for field_name in self.coverage_policy_fields
        )
        return _classify_confidences(confidences)

    def _order_reference_trust_fields(
        self, kind: VehicleOrderAnalysisKind
    ) -> tuple[VehicleConfigurationField, ...]:
        """Return the order-math input fields that drive trust for *kind*."""

        fields: list[VehicleConfigurationField] = ["tire_dimensions"]
        if kind in ("driveshaft_order", "engine_order"):
            if self.drivetrain == "FWD":
                if self.final_drive_front is not None:
                    fields.append("final_drive_front")
            elif self.drivetrain == "RWD":
                if self.final_drive_rear is not None:
                    fields.append("final_drive_rear")
            else:
                if self.final_drive_rear is not None:
                    fields.append("final_drive_rear")
                elif self.final_drive_front is not None:
                    fields.append("final_drive_front")
        if kind == "engine_order":
            fields.append("top_gear_ratio")
        return tuple(fields)

    def _order_reference_kind_feasible(self, kind: VehicleOrderAnalysisKind) -> bool:
        if kind == "wheel_order":
            return True
        if self.driven_final_drive_ratio is None:
            return False
        if kind == "engine_order":
            return self.top_gear_ratio is not None
        return True

    def order_reference_trust_for(
        self, kind: VehicleOrderAnalysisKind
    ) -> VehicleCoverageClassification:
        """Classify trust in the math inputs for one order-analysis kind.

        Trust is computed strictly from the runtime math inputs:

        - ``wheel_order``  → tire dimensions
        - ``driveshaft_order``  → tire dimensions + selected final-drive ratio
        - ``engine_order``  → tire dimensions + selected final-drive ratio +
          top-gear ratio

        Non-math metadata such as ``transmission_name`` does not influence the
        trust signal. When the row is not feasible for *kind* (e.g. EV with no
        gear ratio for engine order), the classifier returns
        ``"backlog_unverified"`` because no reliable math output is possible.
        """

        if not self._order_reference_kind_feasible(kind):
            return "backlog_unverified"
        confidences: list[VehicleFieldConfidence] = []
        for field_name in self._order_reference_trust_fields(kind):
            entry = self.metadata_for(field_name)
            confidences.append(entry.confidence if entry is not None else "unverified")
        return _classify_confidences(tuple(confidences))

    @property
    def order_reference_trust(self) -> VehicleCoverageClassification:
        """Return the worst trust classification across feasible analysis kinds."""

        all_kinds: tuple[VehicleOrderAnalysisKind, ...] = (
            "wheel_order",
            "driveshaft_order",
            "engine_order",
        )
        feasible = [kind for kind in all_kinds if self._order_reference_kind_feasible(kind)]
        if not feasible:
            return "backlog_unverified"
        ranks = {"trusted": 0, "approximate": 1, "backlog_unverified": 2}
        worst = max(
            (self.order_reference_trust_for(kind) for kind in feasible),
            key=lambda c: ranks[c],
        )
        return worst

    @property
    def requires_manual_drivetrain_confirmation(self) -> bool:
        """Whether selected drivetrain ratios should be treated as approximate."""

        return self.order_analysis_policy.requires_manual_confirmation
