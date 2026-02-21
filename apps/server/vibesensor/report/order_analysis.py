# ruff: noqa: E501
"""Order-tracking helpers – wheel/engine/driveshaft Hz, hypotheses, and action plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..analysis_settings import wheel_hz_from_speed_kmh
from ..report_i18n import normalize_lang
from ..runlog import as_float_or_none as _as_float
from .helpers import (
    _effective_engine_rpm,
    _text,
)


def _wheel_hz(sample: dict[str, Any], tire_circumference_m: float | None) -> float | None:
    speed_kmh = _as_float(sample.get("speed_kmh"))
    if speed_kmh is None or speed_kmh <= 0:
        return None
    if tire_circumference_m is None or tire_circumference_m <= 0:
        return None
    return wheel_hz_from_speed_kmh(speed_kmh, tire_circumference_m)


def _driveshaft_hz(
    sample: dict[str, Any],
    metadata: dict[str, Any],
    tire_circumference_m: float | None,
) -> float | None:
    whz = _wheel_hz(sample, tire_circumference_m)
    fd = _as_float(sample.get("final_drive_ratio")) or _as_float(metadata.get("final_drive_ratio"))
    if whz is None or fd is None or fd <= 0:
        return None
    return whz * fd


def _engine_hz(
    sample: dict[str, Any],
    metadata: dict[str, Any],
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    rpm, src = _effective_engine_rpm(sample, metadata, tire_circumference_m)
    if rpm is None or rpm <= 0:
        return None, src
    return rpm / 60.0, src


def _order_label(lang: object, order: int, base: str) -> str:
    if normalize_lang(lang) == "nl":
        names = {"wheel": "wielorde", "engine": "motororde", "driveshaft": "aandrijfasorde"}
    else:
        names = {"wheel": "wheel order", "engine": "engine order", "driveshaft": "driveshaft order"}
    return f"{order}x {names.get(base, base)}"


@dataclass(slots=True)
class _OrderHypothesis:
    key: str
    suspected_source: str
    order_label_base: str
    order: int

    def predicted_hz(
        self,
        sample: dict[str, Any],
        metadata: dict[str, Any],
        tire_circumference_m: float | None,
    ) -> tuple[float | None, str]:
        if self.key.startswith("wheel_"):
            base = _wheel_hz(sample, tire_circumference_m)
            return (base * self.order, "speed+tire") if base is not None else (None, "missing")
        if self.key.startswith("driveshaft_"):
            base = _driveshaft_hz(sample, metadata, tire_circumference_m)
            if base is None:
                return None, "missing"
            return base * self.order, "speed+tire+final_drive"
        if self.key.startswith("engine_"):
            base, src = _engine_hz(sample, metadata, tire_circumference_m)
            return (base * self.order, src) if base is not None else (None, "missing")
        return None, "missing"


def _order_hypotheses() -> list[_OrderHypothesis]:
    return [
        _OrderHypothesis("wheel_1x", "wheel/tire", "wheel", 1),
        _OrderHypothesis("wheel_2x", "wheel/tire", "wheel", 2),
        _OrderHypothesis("driveshaft_1x", "driveline", "driveshaft", 1),
        _OrderHypothesis("engine_1x", "engine", "engine", 1),
        _OrderHypothesis("engine_2x", "engine", "engine", 2),
    ]


def _wheel_focus_from_location(lang: object, location: str) -> str:
    token = location.strip().lower()
    if "front-left wheel" in token:
        return _text(lang, "front-left wheel", "linkervoorwiel")
    if "front-right wheel" in token:
        return _text(lang, "front-right wheel", "rechtervoorwiel")
    if "rear-left wheel" in token:
        return _text(lang, "rear-left wheel", "linkerachterwiel")
    if "rear-right wheel" in token:
        return _text(lang, "rear-right wheel", "rechterachterwiel")
    if "rear" in token or "trunk" in token:
        return _text(lang, "rear wheels", "achterwielen")
    if "front" in token or "engine" in token:
        return _text(lang, "front wheels", "voorwielen")
    return _text(lang, "all wheels", "alle wielen")


def _finding_actions_for_source(
    lang: object,
    source: str,
    *,
    strongest_location: str = "",
    strongest_speed_band: str = "",
    weak_spatial_separation: bool = False,
) -> list[dict[str, str]]:
    location = strongest_location.strip()
    speed_band = strongest_speed_band.strip()
    speed_hint = (
        _text(
            lang,
            f" with focus around {speed_band}",
            f" met focus rond {speed_band}",
        )
        if speed_band
        else ""
    )
    if source == "wheel/tire":
        wheel_focus = _wheel_focus_from_location(lang, location)
        location_hint = (
            _text(
                lang,
                f"Near the strongest location ({location}),",
                f"Nabij de sterkste locatie ({location}),",
            )
            if location
            else _text(lang, "At the wheel/tire corners,", "Bij de wiel/band-hoeken,")
        )
        return [
            {
                "action_id": "wheel_balance_and_runout",
                "what": _text(
                    lang,
                    f"Inspect and balance {wheel_focus}; measure radial/lateral runout on the wheel and tire{speed_hint}.",
                    f"Controleer en balanceer {wheel_focus}; meet radiale/laterale slingering op wiel en band{speed_hint}.",
                ),
                "why": _text(
                    lang,
                    f"{location_hint} wheel-order signatures are most likely caused by imbalance, runout, or tire deformation.",
                    f"{location_hint} wielorde-signaturen komen meestal door onbalans, slingering of banddeformatie.",
                ),
                "confirm": _text(
                    lang,
                    "A clear imbalance or runout is found and corrected, with vibration complaint reduced.",
                    "Er wordt duidelijke onbalans of slingering gevonden en gecorrigeerd, waarna de trillingsklacht afneemt.",
                ),
                "falsify": _text(
                    lang,
                    "Balance and runout are within spec on all checked wheels/tires and complaint remains unchanged.",
                    "Balans en slingering zijn binnen specificatie op alle gecontroleerde wielen/banden en de klacht blijft gelijk.",
                ),
                "eta": "20-45 min",
            },
            {
                "action_id": "wheel_tire_condition",
                "what": _text(
                    lang,
                    f"Inspect {wheel_focus} for tire defects: flat spots, belt shift, uneven wear, pressure mismatch.",
                    f"Controleer {wheel_focus} op banddefecten: vlakke plekken, gordelverschuiving, ongelijk slijtagebeeld, drukverschillen.",
                ),
                "why": _text(
                    lang,
                    "Tire structural issues often create strong 1x/2x wheel-order vibration.",
                    "Structurele bandproblemen veroorzaken vaak sterke 1x/2x wielorde-trillingen.",
                ),
                "confirm": _text(
                    lang,
                    "Visible/measureable tire defect aligns with complaint speed band.",
                    "Zichtbaar/meetbaar banddefect sluit aan op de klachten-snelheidsband.",
                ),
                "falsify": _text(
                    lang,
                    "No tire condition anomaly is found on inspected wheels.",
                    "Er wordt geen bandtoestandsafwijking gevonden op de gecontroleerde wielen.",
                ),
                "eta": "10-20 min",
            },
        ]
    if source == "driveline":
        driveline_focus = (
            _text(
                lang,
                f"near {location}",
                f"nabij {location}",
            )
            if location
            else _text(
                lang,
                "along the tunnel/rear driveline path",
                "langs de tunnel/achterste aandrijflijn",
            )
        )
        return [
            {
                "action_id": "driveline_inspection",
                "what": _text(
                    lang,
                    f"Inspect propshaft runout/balance, center support bearing, CV/guibo joints {driveline_focus}.",
                    f"Controleer cardanas slingering/balans, middenlager, homokineten/hardy-schijf {driveline_focus}.",
                ),
                "why": _text(
                    lang,
                    "Driveline-order vibration is commonly caused by shaft imbalance, joint wear, or support bearing issues.",
                    "Aandrijflijnorde-trillingen komen vaak door onbalans van de as, slijtage van koppelingen of problemen met het middenlager.",
                ),
                "confirm": _text(
                    lang,
                    "Mechanical defect or out-of-spec runout/play is found in driveline components.",
                    "Mechanisch defect of buiten-specificatie slingering/speling wordt gevonden in aandrijflijncomponenten.",
                ),
                "falsify": _text(
                    lang,
                    "No driveline play/runout/balance issue is found.",
                    "Er wordt geen aandrijflijn-issue in speling/slingering/balans gevonden.",
                ),
                "eta": "20-35 min",
            },
            {
                "action_id": "driveline_mounts_and_fasteners",
                "what": _text(
                    lang,
                    "Check driveline mounts and fastening torque (diff mounts, shaft couplings, carrier brackets).",
                    "Controleer aandrijflijnsteunen en aanhaalmomenten (diff-steunen, askoppelingen, draagbeugels).",
                ),
                "why": _text(
                    lang,
                    "Loose or degraded mounts can amplify normal order content into cabin vibration.",
                    "Losse of versleten steunen kunnen normale orde-inhoud versterken tot voelbare trillingen in de auto.",
                ),
                "confirm": _text(
                    lang,
                    "Loose mount/fastener or cracked rubber support is found.",
                    "Losse bevestiging of gescheurde rubbersteun wordt gevonden.",
                ),
                "falsify": _text(
                    lang,
                    "All inspected mounts and fasteners are within condition/torque spec.",
                    "Alle gecontroleerde steunen en bevestigingen zijn binnen conditie-/koppelspecificatie.",
                ),
                "eta": "10-20 min",
            },
        ]
    if source == "engine":
        return [
            {
                "action_id": "engine_mounts_and_accessories",
                "what": _text(
                    lang,
                    "Inspect engine mounts and accessory drive (idler, tensioner, pulleys) for play or resonance.",
                    "Controleer motorsteunen en hulpaandrijving (spanrol, geleiderol, poelies) op speling of resonantie.",
                ),
                "why": _text(
                    lang,
                    "Engine-order vibration often transfers through weakened mounts or accessory imbalance.",
                    "Motororde-trillingen worden vaak doorgegeven via verzwakte steunen of onbalans in hulpaandrijving.",
                ),
                "confirm": _text(
                    lang,
                    "A worn mount or accessory imbalance is identified.",
                    "Een versleten steun of onbalans in hulpaandrijving wordt vastgesteld.",
                ),
                "falsify": _text(
                    lang,
                    "Mounts and accessory drive are within acceptable condition.",
                    "Steunen en hulpaandrijving zijn binnen acceptabele conditie.",
                ),
                "eta": "15-30 min",
            },
            {
                "action_id": "engine_combustion_quality",
                "what": _text(
                    lang,
                    "Check misfire counters and fuel/ignition adaptation for cylinders contributing to roughness.",
                    "Controleer misfire-tellers en brandstof/ontsteking-adaptaties op cilinders die ruwloop veroorzaken.",
                ),
                "why": _text(
                    lang,
                    "Combustion imbalance can create engine-order vibration without obvious mechanical noise.",
                    "Verbrandingsonbalans kan motororde-trillingen geven zonder duidelijk mechanisch geluid.",
                ),
                "confirm": _text(
                    lang,
                    "Cylinder-specific deviation aligns with the vibration complaint.",
                    "Cilinderspecifieke afwijking sluit aan op de trillingsklacht.",
                ),
                "falsify": _text(
                    lang,
                    "Combustion quality indicators are stable and balanced.",
                    "Verbrandingskwaliteits-indicatoren zijn stabiel en gebalanceerd.",
                ),
                "eta": "10-20 min",
            },
        ]
    fallback_why = _text(
        lang,
        "Use direct mechanical checks first because source classification is not specific enough yet.",
        "Gebruik eerst directe mechanische controles omdat de bronclassificatie nog niet specifiek genoeg is.",
    )
    if weak_spatial_separation:
        fallback_why = _text(
            lang,
            "Spatial separation is weak, so prioritize broad underbody and mount checks before part replacement.",
            "Ruimtelijke scheiding is zwak, dus prioriteer brede onderstel- en steuncontroles vóór onderdeelvervanging.",
        )
    return [
        {
            "action_id": "general_mechanical_inspection",
            "what": _text(
                lang,
                "Inspect wheel bearings, suspension bushings, subframe mounts, and loose fasteners in the hotspot area.",
                "Controleer wiellagers, ophangrubbers, subframe-steunen en losse bevestigingen in de hotspot-zone.",
            ),
            "why": fallback_why,
            "confirm": _text(
                lang,
                "A clear mechanical issue is found at or near the hotspot.",
                "Een duidelijke mechanische afwijking wordt bij of nabij de hotspot gevonden.",
            ),
            "falsify": _text(
                lang,
                "No abnormal wear, play, or looseness is found.",
                "Er wordt geen abnormale slijtage, speling of losheid gevonden.",
            ),
            "eta": "20-35 min",
        }
    ]
