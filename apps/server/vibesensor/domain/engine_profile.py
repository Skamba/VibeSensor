"""The car's engine profile and the engine orders it is expected to excite.

An engine order ``E<m>`` is a vibration at *m* times the crankshaft (for a
rotary, the eccentric shaft) speed. Which orders an engine excites follows
from two facts, its layout and its cylinder count (rotors for a rotary), so
the profile holds just those, plus the bank angle of a V or W engine when it
is known. The car library reads the profile from its engine text
(``engine_profile_from_engine_text``); the owner can give it for a custom car.

``ENGINE_ORDER_RULES`` is the one table that maps a profile to its orders.
Each rule adds one order with one role:

* ``rotating``: E1, the crank's own rotation (unbalanced rotating parts,
  a bent or out-of-round crank pulley or flywheel). Every engine has it.
* ``firing``: the firing rhythm. A four-stroke piston engine fires every
  cylinder once per two crank turns, so an evenly firing engine with *n*
  cylinders fires at E(n/2): E1 for a twin, E1.5 for an inline-3, E2 for a
  four, E2.5 for a five, E3 for a six, E4 for a V8, E5 for a V10 and E6 for a
  V12/W12. A rotary fires each rotor once per eccentric-shaft turn (three
  faces, the rotor turning at a third of the shaft speed): E1 per rotor.
* ``imbalance``: a free force or rocking couple the layout leaves unbalanced
  by design (only well-established cases): an inline-3's primary rocking
  couple (E1), an inline-4's secondary force (E2), a 90° V6's primary couple
  (E1, cancelled where a balance shaft is fitted) and a flat-4's secondary
  rocking couple (E2). Inline-6, flat-6, V12 and cross-plane V8 engines are
  inherently balanced and add nothing.

Adding an engine type, or an order such as the half-order misfire (E0.5,
``EngineOrderRule("misfire", PISTON_LAYOUTS, multiple=0.5)``), is a new row,
not new code. Without a profile (not given, or an EV) the analysis keeps the
orders it always tested, E1 and E2, without claiming what E2 is.
docs/order_tracking.md "Engine orders" lists the sources.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal, NotRequired, TypedDict, get_args

__all__ = [
    "ENGINE_ORDER_RULES",
    "EngineLayout",
    "EngineOrder",
    "EngineOrderRole",
    "EngineOrderRule",
    "EngineProfile",
    "EngineProfilePayload",
    "UNKNOWN_ENGINE_ORDERS",
    "engine_orders",
    "engine_profile_payload",
    "engine_profile_from_engine_text",
]

EngineLayout = Literal["inline", "v", "flat", "w", "rotary"]
EngineOrderRole = Literal["rotating", "firing", "imbalance"]

ENGINE_LAYOUTS: Final[tuple[EngineLayout, ...]] = get_args(EngineLayout)
PISTON_LAYOUTS: Final[frozenset[EngineLayout]] = frozenset({"inline", "v", "flat", "w"})
ALL_LAYOUTS: Final[frozenset[EngineLayout]] = frozenset(ENGINE_LAYOUTS)
_MAX_CYLINDERS: Final[dict[EngineLayout, int]] = {
    "inline": 16,
    "v": 16,
    "flat": 16,
    "w": 16,
    "rotary": 4,
}
_BANKED_LAYOUTS: Final[frozenset[EngineLayout]] = frozenset({"v", "w"})


@dataclass(frozen=True, slots=True)
class EngineOrder:
    """One crank order the engine is expected to excite, and why."""

    multiple: float
    """Times the crank speed, e.g. 3.0 for E3, 1.5 for E1.5."""
    roles: tuple[EngineOrderRole, ...]
    """Why the engine excites it; empty when the engine is not known."""

    @property
    def code(self) -> str:
        """Workshop order label: ``"E3"``, ``"E1.5"``."""
        return f"E{_multiple_text(self.multiple, '.')}"

    @property
    def key(self) -> str:
        """Hypothesis and finding key: ``"engine_3x"``, ``"engine_1_5x"``."""
        return f"engine_{_multiple_text(self.multiple, '_')}x"


def _multiple_text(multiple: float, separator: str) -> str:
    whole, fraction = divmod(round(multiple * 10), 10)
    return str(whole) if fraction == 0 else f"{whole}{separator}{fraction}"


@dataclass(frozen=True, slots=True)
class EngineProfile:
    """An engine's layout and cylinder count (rotors for a rotary)."""

    layout: EngineLayout
    cylinders: int
    bank_angle_deg: int | None = None
    """The angle between a V or W engine's banks, when known."""

    def __post_init__(self) -> None:
        if self.layout not in ENGINE_LAYOUTS:
            raise ValueError(f"unknown engine layout {self.layout!r}")
        if not 1 <= self.cylinders <= _MAX_CYLINDERS[self.layout]:
            raise ValueError(f"{self.cylinders} cylinders is not a {self.layout} engine")
        if self.bank_angle_deg is not None and (
            self.layout not in _BANKED_LAYOUTS or not 0 < self.bank_angle_deg < 180
        ):
            raise ValueError(f"a {self.layout} engine has no bank angle {self.bank_angle_deg}")

    @property
    def orders(self) -> tuple[EngineOrder, ...]:
        return engine_orders(self)

    @property
    def firing_order(self) -> EngineOrder:
        """The order of the engine's firing rhythm."""
        return next(order for order in self.orders if "firing" in order.roles)


class EngineProfilePayload(TypedDict):
    """The engine's layout and cylinder count (rotors for a rotary)."""

    layout: EngineLayout
    cylinders: int
    bank_angle_deg: NotRequired[int | None]
    """The angle between a V or W engine's banks; absent when not known."""


def engine_profile_payload(profile: EngineProfile) -> EngineProfilePayload:
    """*profile* as its stored and served JSON shape."""
    payload: EngineProfilePayload = {"layout": profile.layout, "cylinders": profile.cylinders}
    if profile.bank_angle_deg is not None:
        payload["bank_angle_deg"] = profile.bank_angle_deg
    return payload


@dataclass(frozen=True, slots=True)
class EngineOrderRule:
    """One row of the rules table: an order the matching engines excite.

    The order is ``multiple + per_cylinder * cylinders`` times the crank speed,
    for engines of one of ``layouts`` (and, when given, that cylinder count
    and bank angle).
    """

    role: EngineOrderRole
    layouts: frozenset[EngineLayout]
    multiple: float = 0.0
    per_cylinder: float = 0.0
    cylinders: int | None = None
    bank_angle_deg: int | None = None

    def order_multiple(self, profile: EngineProfile) -> float | None:
        """The order this rule gives *profile*; ``None`` when it does not apply."""
        if (
            profile.layout not in self.layouts
            or (self.cylinders is not None and profile.cylinders != self.cylinders)
            or (self.bank_angle_deg is not None and profile.bank_angle_deg != self.bank_angle_deg)
        ):
            return None
        return self.multiple + self.per_cylinder * profile.cylinders


ENGINE_ORDER_RULES: Final[tuple[EngineOrderRule, ...]] = (
    EngineOrderRule("rotating", ALL_LAYOUTS, multiple=1.0),
    EngineOrderRule("firing", PISTON_LAYOUTS, per_cylinder=0.5),
    EngineOrderRule("firing", frozenset({"rotary"}), per_cylinder=1.0),
    EngineOrderRule("imbalance", frozenset({"inline"}), multiple=1.0, cylinders=3),
    EngineOrderRule("imbalance", frozenset({"inline"}), multiple=2.0, cylinders=4),
    EngineOrderRule("imbalance", frozenset({"v"}), multiple=1.0, cylinders=6, bank_angle_deg=90),
    EngineOrderRule("imbalance", frozenset({"flat"}), multiple=2.0, cylinders=4),
)

UNKNOWN_ENGINE_ORDERS: Final[tuple[EngineOrder, ...]] = (
    EngineOrder(1.0, ("rotating",)),
    EngineOrder(2.0, ()),
)


def engine_orders(profile: EngineProfile | None) -> tuple[EngineOrder, ...]:
    """The engine orders *profile* excites, lowest first, each with its roles.

    Without a profile: E1 and E2, the orders tested before engines had one.
    """
    if profile is None:
        return UNKNOWN_ENGINE_ORDERS
    roles: dict[float, list[EngineOrderRole]] = {}
    for rule in ENGINE_ORDER_RULES:
        multiple = rule.order_multiple(profile)
        if multiple is not None and rule.role not in roles.setdefault(multiple, []):
            roles[multiple].append(rule.role)
    return tuple(EngineOrder(multiple, tuple(roles[multiple])) for multiple in sorted(roles))


# The layout token of the car library's engine text (docs/car_library_architecture.md
# "Engine text"): ``B58 3.0L I6 Turbo`` is an inline-6.
_ENGINE_TEXT_LAYOUT = re.compile(r"(?:^|\s)(?P<layout>[IVW])(?P<cylinders>\d{1,2})(?=\s|$)")
_LAYOUT_TOKENS: Final[dict[str, EngineLayout]] = {"I": "inline", "V": "v", "W": "w"}


def engine_profile_from_engine_text(text: str | None) -> EngineProfile | None:
    """The profile the library's engine text names; ``None`` for an EV or no text."""
    match = _ENGINE_TEXT_LAYOUT.search(text or "")
    if match is None:
        return None
    return EngineProfile(_LAYOUT_TOKENS[match["layout"]], int(match["cylinders"]))
