"""The road a simulated drive runs on: ISO 8608 roughness sections and impacts.

Positions are metres along the road. Every sensor of a drive shares one
``RoadSurface``; each wheel meets it at its own axle (the rear axle one
wheelbase later), so a joint hits the front wheels first and the rear ones
``wheelbase / speed`` later. Sources and the reasoning behind each number are
in ``docs/simulator_realism.md``.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

import numpy as np

__all__ = [
    "ISO8608_GD_N0_M3",
    "ISO8608_N0_CYCLES_PER_M",
    "RoadImpact",
    "RoadSection",
    "RoadSurface",
    "generated_road",
    "uniform_road",
]

ISO8608_N0_CYCLES_PER_M = 0.1
"""ISO 8608 reference spatial frequency (cycles/m)."""

ISO8608_GD_N0_M3: dict[str, float] = {
    "A": 16e-6,
    "B": 64e-6,
    "C": 256e-6,
    "D": 1024e-6,
}
"""Displacement PSD ``Gd(n0)`` (m^3) at the geometric mean of each ISO 8608 class.

``Gd(n) = Gd(n0) * (n / n0) ** -2``: every class is four times the power of
the one before it, so twice the amplitude.
"""


@dataclass(frozen=True, slots=True)
class RoadSection:
    """From *start_m* on, the road is ISO 8608 class *iso_class*."""

    start_m: float
    iso_class: str


@dataclass(frozen=True, slots=True)
class RoadImpact:
    """A short dip in the road at *at_m*: an expansion joint, a pothole, a manhole.

    The wheel drops *depth_m* over *length_m* and climbs out again (a
    half-cosine dip); the tyre's contact patch smooths it further.
    """

    at_m: float
    depth_m: float
    length_m: float

    def displacement_m(self, position_m: np.ndarray) -> np.ndarray:
        """Road height (m, negative into the dip) under a wheel at *position_m*."""
        x = (position_m - self.at_m) / self.length_m
        inside = (x > 0.0) & (x < 1.0)
        return np.where(inside, -0.5 * self.depth_m * (1.0 - np.cos(2.0 * np.pi * x)), 0.0)


@dataclass(frozen=True, slots=True)
class RoadSurface:
    """Roughness sections (sorted by start) and impacts (sorted by position)."""

    sections: tuple[RoadSection, ...]
    impacts: tuple[RoadImpact, ...] = ()

    def __post_init__(self) -> None:
        if not self.sections or self.sections[0].start_m > 0.0:
            raise ValueError("a road needs a section starting at 0 m")
        starts = [section.start_m for section in self.sections]
        if starts != sorted(starts):
            raise ValueError("road sections must be sorted by start")
        for section in self.sections:
            if section.iso_class not in ISO8608_GD_N0_M3:
                raise ValueError(f"unknown ISO 8608 class {section.iso_class!r}")

    def gd_n0_m3(self, position_m: float) -> float:
        """ISO 8608 ``Gd(n0)`` (m^3) of the road at *position_m* (0 before the start)."""
        if position_m < 0.0:
            return 0.0
        starts = [section.start_m for section in self.sections]
        section = self.sections[bisect_right(starts, position_m) - 1]
        return ISO8608_GD_N0_M3[section.iso_class]

    def impacts_between(self, start_m: float, end_m: float) -> tuple[RoadImpact, ...]:
        """The impacts a wheel touches while it rolls from *start_m* to *end_m*."""
        return tuple(
            impact
            for impact in self.impacts
            if impact.at_m < end_m and impact.at_m + impact.length_m > start_m
        )


def uniform_road(iso_class: str) -> RoadSurface:
    """One ISO 8608 class all the way, no impacts."""
    return RoadSurface(sections=(RoadSection(0.0, iso_class),))


# A section of road keeps its surface for a few hundred metres.
_SECTION_LENGTH_M = (200.0, 800.0)


@dataclass(frozen=True, slots=True)
class _ImpactKind:
    rate_per_km: dict[str, float]
    depth_m: tuple[float, float]
    length_m: tuple[float, float]


_IMPACT_KINDS = (
    # Expansion joints: a few mm, about a contact patch long; bridges come
    # every kilometre or so whatever the surface.
    _ImpactKind(
        rate_per_km={"A": 1.5, "B": 1.5, "C": 1.5, "D": 1.5},
        depth_m=(0.003, 0.008),
        length_m=(0.05, 0.15),
    ),
    # Potholes, sunken manholes and patches: a few cm deep, up to half a metre
    # long; none on a smooth road, several per kilometre on a poor one.
    _ImpactKind(
        rate_per_km={"A": 0.0, "B": 0.3, "C": 2.0, "D": 5.0},
        depth_m=(0.01, 0.04),
        length_m=(0.2, 0.6),
    ),
)


def generated_road(
    seed: int,
    *,
    length_m: float = 20_000.0,
    class_weights: dict[str, float] | None = None,
) -> RoadSurface:
    """A road of changing ISO 8608 sections with joints and potholes, from *seed*.

    *class_weights* (default: mostly A, some B, a little C, as surveys of
    paved roads find) picks each section's class.
    """
    weights = class_weights or {"A": 0.6, "B": 0.3, "C": 0.1}
    classes = sorted(weights)
    probabilities = np.asarray([weights[name] for name in classes], dtype=np.float64)
    probabilities /= probabilities.sum()
    rng = np.random.default_rng((seed, 0x8608))
    sections: list[RoadSection] = []
    impacts: list[RoadImpact] = []
    position_m = 0.0
    while position_m < length_m:
        iso_class = classes[int(rng.choice(len(classes), p=probabilities))]
        section_m = float(rng.uniform(*_SECTION_LENGTH_M))
        sections.append(RoadSection(position_m, iso_class))
        for kind in _IMPACT_KINDS:
            count = int(rng.poisson(kind.rate_per_km[iso_class] * section_m / 1000.0))
            for at_m in np.sort(rng.uniform(position_m, position_m + section_m, size=count)):
                impacts.append(
                    RoadImpact(
                        at_m=float(at_m),
                        depth_m=float(rng.uniform(*kind.depth_m)),
                        length_m=float(rng.uniform(*kind.length_m)),
                    )
                )
        position_m += section_m
    impacts.sort(key=lambda impact: impact.at_m)
    return RoadSurface(sections=tuple(sections), impacts=tuple(impacts))
