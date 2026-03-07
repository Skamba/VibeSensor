"""PDF report helper functions – color utilities."""

from __future__ import annotations

from .theme import (
    FINDING_SOURCE_COLORS,
)

# ── Module-level constants ────────────────────────────────────────────────

_FL_COMPACTS: frozenset[str] = frozenset({"frontleft", "frontleftwheel", "fl", "flwheel"})
_FR_COMPACTS: frozenset[str] = frozenset({"frontright", "frontrightwheel", "fr", "frwheel"})
_RL_COMPACTS: frozenset[str] = frozenset({"rearleft", "rearleftwheel", "rl", "rlwheel"})
_RR_COMPACTS: frozenset[str] = frozenset({"rearright", "rearrightwheel", "rr", "rrwheel"})


# ── Pure helpers (no external deps) ──────────────────────────────────────


def _canonical_location(raw: object) -> str:
    token = str(raw or "").strip().lower().replace("_", "-")
    compact = "".join(ch for ch in token if ch.isalnum())
    if ("front" in token and "left" in token and "wheel" in token) or compact in _FL_COMPACTS:
        return "front-left wheel"
    if ("front" in token and "right" in token and "wheel" in token) or compact in _FR_COMPACTS:
        return "front-right wheel"
    if ("rear" in token and "left" in token and "wheel" in token) or compact in _RL_COMPACTS:
        return "rear-left wheel"
    if ("rear" in token and "right" in token and "wheel" in token) or compact in _RR_COMPACTS:
        return "rear-right wheel"
    if "trunk" in token:
        return "trunk"
    if "driveshaft" in token or "tunnel" in token:
        return "driveshaft tunnel"
    if "engine" in token:
        return "engine bay"
    if "driver" in token:
        return "driver seat"
    return token


def _source_color(source: object) -> str:
    src = str(source or "unknown").strip().lower()
    return FINDING_SOURCE_COLORS.get(src, FINDING_SOURCE_COLORS["unknown"])
