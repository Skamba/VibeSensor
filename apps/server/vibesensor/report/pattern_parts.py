"""Centralized pattern-to-parts mapping for diagnostic reports.

Maps detected vibration patterns (system + location + order/frequency bucket)
to commonly associated parts.  This is the single place to adjust the mapping
when domain knowledge evolves — end users do not configure these rules.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Static mapping tables
# ---------------------------------------------------------------------------

# Keys: (system_lower, order_bucket)
# order_bucket: "1x", "2x", "higher", or "*" (wildcard).
# Values: list of (part_key, en_label, nl_label).

_SYSTEM_PARTS: dict[tuple[str, str], list[tuple[str, str, str]]] = {
    # Wheel / Tire
    ("wheel/tire", "1x"): [
        ("flat_spot", "Tire flat spot / out-of-round", "Band platte plek / uit-rond"),
        ("wheel_balance", "Wheel balance weights", "Wielbalanseringsgewichten"),
        ("hub_bearing", "Wheel hub bearing", "Wielnaaf-lager"),
    ],
    ("wheel/tire", "2x"): [
        ("hub_bearing", "Wheel hub bearing", "Wielnaaf-lager"),
        ("brake_disc", "Brake disc runout / warping", "Remschijf-slingering / vervorming"),
        ("cv_joint", "CV joint / drive shaft", "Homokineet / aandrijfas"),
    ],
    ("wheel/tire", "higher"): [
        (
            "hub_bearing",
            "Wheel hub bearing (advanced wear)",
            "Wielnaaf-lager (gevorderde slijtage)",
        ),
        ("brake_caliper", "Brake caliper / pad contact", "Remklauw / blokcontact"),
    ],
    ("wheel/tire", "*"): [
        ("flat_spot", "Tire flat spot / out-of-round", "Band platte plek / uit-rond"),
        ("wheel_balance", "Wheel balance weights", "Wielbalanseringsgewichten"),
        ("hub_bearing", "Wheel hub bearing", "Wielnaaf-lager"),
    ],
    # Driveline
    ("driveline", "1x"): [
        ("center_bearing", "Center support bearing", "Middensteunlager"),
        ("u_joint", "Universal joint / flex disc", "Kruiskoppeling / flexschijf"),
        ("prop_shaft", "Propshaft imbalance", "Cardanas-onbalans"),
    ],
    ("driveline", "2x"): [
        ("u_joint", "Universal joint / flex disc", "Kruiskoppeling / flexschijf"),
        ("diff_mount", "Differential mount", "Differentieelophanging"),
    ],
    ("driveline", "higher"): [
        ("spline_wear", "Spline wear / slip joint", "Slijtage van tandkoppeling"),
        ("diff_gear", "Differential gear wear", "Slijtage differentieel-tandwiel"),
    ],
    ("driveline", "*"): [
        ("center_bearing", "Center support bearing", "Middensteunlager"),
        ("u_joint", "Universal joint / flex disc", "Kruiskoppeling / flexschijf"),
        ("prop_shaft", "Propshaft imbalance", "Cardanas-onbalans"),
    ],
    # Engine
    ("engine", "1x"): [
        ("engine_mount", "Engine / transmission mount", "Motor- / versnellingsbaksteun"),
        ("accessory_belt", "Accessory belt / tensioner", "Hulpaandrijfriem / spanrol"),
    ],
    ("engine", "2x"): [
        ("engine_mount", "Engine / transmission mount", "Motor- / versnellingsbaksteun"),
        ("misfire", "Cylinder misfire / injector", "Cilinderontsteking / injector"),
        ("exhaust_mount", "Exhaust mount / heat shield", "Uitlaatophanging / hitteschild"),
    ],
    ("engine", "higher"): [
        ("accessory_belt", "Accessory belt / tensioner", "Hulpaandrijfriem / spanrol"),
        ("valve_train", "Valve train / timing chain", "Kleppentrein / distributieketting"),
    ],
    ("engine", "*"): [
        ("engine_mount", "Engine / transmission mount", "Motor- / versnellingsbaksteun"),
        ("accessory_belt", "Accessory belt / tensioner", "Hulpaandrijfriem / spanrol"),
    ],
}

# Fallback for unknown systems
_DEFAULT_PARTS: list[tuple[str, str, str]] = [
    ("mount_general", "Mounting / rubber bushing", "Ophanging / rubberbushing"),
    ("resonance", "Structural resonance path", "Structureel resonantiepad"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _order_bucket(order_text: str) -> str:
    """Normalise an order label like '1x wheel order' → '1x', '2x', 'higher'."""
    text = str(order_text or "").strip().lower()
    if "1x" in text or "1×" in text:
        return "1x"
    if "2x" in text or "2×" in text:
        return "2x"
    # Any numeric > 2 or general "higher"
    for token in text.split():
        if token.endswith("x") and token[:-1].isdigit():
            n = int(token[:-1])
            if n > 2:
                return "higher"
    return "*"


def parts_for_pattern(
    system: str,
    order_label: str | None = None,
    *,
    lang: str = "en",
) -> list[str]:
    """Return human-readable part names for a (system, order) pattern.

    Parameters
    ----------
    system:
        Suspected source, e.g. ``"wheel/tire"``, ``"driveline"``, ``"engine"``.
    order_label:
        Optional order string, e.g. ``"1x wheel order"``.  When *None* or
        unrecognised the wildcard bucket ``"*"`` is used.
    lang:
        ``"en"`` or ``"nl"``.

    Returns
    -------
    list[str]
        Part descriptions in the requested language.
    """
    src = str(system or "").strip().lower()
    bucket = _order_bucket(order_label or "")
    key = (src, bucket)
    entries = _SYSTEM_PARTS.get(key) or _SYSTEM_PARTS.get((src, "*")) or _DEFAULT_PARTS
    idx = 2 if lang == "nl" else 1
    return [entry[idx] for entry in entries]


def why_parts_listed(
    system: str,
    order_label: str | None = None,
    *,
    lang: str = "en",
) -> str:
    """Return a short explanation of why these parts were listed.

    The wording is deterministic and drawn from a controlled set.
    """
    src = str(system or "").strip().lower()
    bucket = _order_bucket(order_label or "")

    base_en = "These parts are commonly associated with"
    base_nl = "Deze onderdelen worden vaak geassocieerd met"

    if src == "wheel/tire":
        if bucket in ("1x", "2x"):
            return (
                f"{base_en} a {bucket} wheel-order vibration pattern."
                if lang != "nl"
                else f"{base_nl} een {bucket} wielorde-trillingspatroon."
            )
        return (
            f"{base_en} wheel/tire vibration patterns."
            if lang != "nl"
            else f"{base_nl} wiel-/bandtrillingspatronen."
        )
    if src == "driveline":
        if bucket in ("1x", "2x"):
            return (
                f"{base_en} a {bucket} driveshaft-order vibration pattern."
                if lang != "nl"
                else f"{base_nl} een {bucket} cardanas-orde trillingspatroon."
            )
        return (
            f"{base_en} driveline vibration patterns."
            if lang != "nl"
            else f"{base_nl} aandrijflijn-trillingspatronen."
        )
    if src == "engine":
        if bucket in ("1x", "2x"):
            return (
                f"{base_en} a {bucket} engine-order vibration pattern."
                if lang != "nl"
                else f"{base_nl} een {bucket} motororde-trillingspatroon."
            )
        return (
            f"{base_en} engine vibration patterns."
            if lang != "nl"
            else f"{base_nl} motor-trillingspatronen."
        )

    return (
        f"{base_en} the detected vibration pattern."
        if lang != "nl"
        else f"{base_nl} het gedetecteerde trillingspatroon."
    )
