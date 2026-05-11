from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pytest
from _paths import SERVER_ROOT

from vibesensor import report_i18n
from vibesensor.adapters.pdf.diagram_layout import canonical_location
from vibesensor.domain import DiagnosisAssessment
from vibesensor.shared.report_confidence_presentation import confidence_reason_text
from vibesensor.shared.report_presentation import (
    display_location,
    display_speed_band,
    order_label_human,
)
from vibesensor.use_cases.history.report_document.pattern_parts import (
    _DEFAULT_PARTS,
    why_parts_listed,
)

_I18N_JSON = SERVER_ROOT / "vibesensor" / "data" / "report_i18n.json"
_SOURCE_ROOT = SERVER_ROOT / "vibesensor"
_UI_NL_JSON = SERVER_ROOT.parent / "ui" / "src" / "i18n" / "catalogs" / "nl.json"


# ---------------------------------------------------------------------------
# Cached data loaders (avoid repeated disk I/O + JSON parsing)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_i18n_data() -> dict[str, dict[str, str]]:
    return json.loads(_I18N_JSON.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_ui_nl() -> dict[str, str]:
    return json.loads(_UI_NL_JSON.read_text(encoding="utf-8"))


def _nl(key: str) -> str:
    """Shortcut: return the Dutch translation for *key* from report_i18n.json."""
    return _load_i18n_data()[key]["nl"]


def test_translation_loads_and_translates() -> None:
    assert report_i18n.tr("nl", "REPORT_DATE") != "REPORT_DATE"


def test_missing_translation_file_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(report_i18n, "_DATA_FILE", Path("/definitely/missing/report_i18n.json"))
    report_i18n._load_translations.cache_clear()
    with pytest.raises(RuntimeError, match="Missing translation file"):
        report_i18n.tr("en", "REPORT_DATE")


def test_corrupt_translation_file_is_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = tmp_path / "report_i18n.json"
    broken.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(report_i18n, "_DATA_FILE", broken)
    report_i18n._load_translations.cache_clear()
    with pytest.raises(RuntimeError, match="Invalid translation file"):
        report_i18n.tr("en", "REPORT_DATE")


def test_all_json_keys_have_en_and_nl() -> None:
    data = _load_i18n_data()
    missing: list[str] = []
    for key, translations in data.items():
        for lang in ("en", "nl"):
            val = translations.get(lang)
            if not isinstance(val, str) or not val.strip():
                missing.append(f"{key}.{lang}")
    assert missing == [], f"Keys with missing or empty translations: {missing}"


def test_all_source_referenced_keys_exist_in_json() -> None:
    data = _load_i18n_data()
    pattern = re.compile(r'(?:_tr\([^,]+,|(?<!\w)tr\()\s*"([A-Z][A-Z_0-9]+)"')
    referenced_keys: set[str] = set()
    for py_file in _SOURCE_ROOT.rglob("*.py"):
        for match in pattern.finditer(py_file.read_text(encoding="utf-8")):
            referenced_keys.add(match.group(1))
    assert referenced_keys, "Sanity: should find at least some keys"
    missing = sorted(referenced_keys - set(data.keys()))
    assert missing == [], f"Keys referenced in source but missing from JSON: {missing}"


def test_variants_returns_both_languages() -> None:
    data = report_i18n._load_translations()
    en_text = data["REPORT_DATE"].get("en", "")
    nl_text = data["REPORT_DATE"].get("nl", "")
    assert isinstance(en_text, str) and en_text.strip()
    assert isinstance(nl_text, str) and nl_text.strip()
    assert en_text != nl_text


def test_dutch_translations_complete() -> None:
    """All Dutch translation assertions consolidated from audit rounds 1-5."""
    # --- Corrections ---
    assert report_i18n.tr("nl", "HEAT_LEGEND_MORE") == "Meer trilling"
    assert report_i18n.tr("nl", "RUN_TRIAGE") == "Meetrun-triage"
    assert (
        report_i18n.tr("nl", "COVERAGE_RISES_ABOVE_THRESHOLD_AND_WHEEL_ORDER_CHECKS")
        == "Dekking stijgt boven de drempel en wielorde-controles komen beschikbaar."
    )
    assert (
        report_i18n.tr("nl", "ENGINE_ORDER_CHECKS_BECOME_AVAILABLE_WITH_ADEQUATE_RPM")
        == "Motororde-controles komen beschikbaar bij voldoende toerentaldekking."
    )

    # --- Round 2 ---
    assert report_i18n.tr("nl", "TOP_ACTIONS") == "Belangrijkste acties"
    assert report_i18n.tr("nl", "TOP_SUSPECTED_CAUSE") == "Meest waarschijnlijke oorzaak"
    assert report_i18n.tr("nl", "WHAT_TO_CHECK_FIRST") == "Wat eerst controleren"
    assert report_i18n.tr("nl", "RUN_CONDITIONS") == "Meetcondities"
    assert report_i18n.tr("nl", "CONFIDENCE_LABEL") == "Betrouwbaarheid"
    assert report_i18n.tr("nl", "FINAL_DRIVE_RATIO_LABEL") == "Eindoverbrenging"
    assert "hogere orden" in report_i18n.tr(
        "nl",
        "CHECK_DRIVESHAFT_RUNOUT_AND_JOINT_CONDITION_FOR_HIGHER",
    )
    assert "ordereferenties" in report_i18n.tr("nl", "SUITABILITY_REFERENCE_COMPLETENESS_PASS")
    assert "ordereferenties" in report_i18n.tr("nl", "SUITABILITY_REFERENCE_COMPLETENESS_WARN")
    assert "locatiegegevens" in report_i18n.tr(
        "nl",
        "NO_USABLE_AMPLITUDE_BY_LOCATION_DATA_WAS_FOUND",
    )
    assert "aanvullende gegevens" in report_i18n.tr("nl", "NO_NEXT_STEPS")
    assert report_i18n.tr("nl", "METRIC_LABEL") == "Meetwaarde"
    assert "Snelheidsgegevens" in report_i18n.tr(
        "nl",
        "SPEED_DATA_MISSING_OR_INSUFFICIENT_SPEED_BINNED_AND",
    )

    # --- Round 3 ---
    assert _nl("TIRE_WIDTH_MM_LABEL") == "Bandenbreedte (mm)"
    assert "gemeten locatie" in _nl("DETECTED_AT_ONE_MONITORED_LOCATION")
    assert "gemeten locaties" in _nl("VIBRATION_SIGNATURE_WAS_DETECTED_AT_ACTIVE_COUNT_OF_DB")
    assert "overeenkomende piekamplitude" in _nl("METRIC_MEAN_MATCHED_PEAK_AMPLITUDE")
    assert "overeenkomende samples" in _nl("METRIC_P95_PEAK_AMPLITUDE")
    assert _nl("MATCHED_SYSTEMS") == "Overeenkomende systemen"
    assert "impulsiviteit" in _nl("EVIDENCE_PEAK_PRESENT")
    assert "flexschijf" in _nl("ACTION_DRIVELINE_INSPECTION_WHAT")
    assert "wiel-/bandposities" in _nl("LOCATION_HINT_AT_WHEEL_CORNERS")
    assert "veroorzaken" in _nl("ACTION_ENGINE_COMBUSTION_WHY")
    assert "orde-trillingen" in _nl("ACTION_DRIVELINE_MOUNTS_WHY")
    assert "amplitudemeetwaarde" in _nl("OUTLIER_SUMMARY_LINE")

    # --- Round 4: Python ---
    assert "versus" in _nl("AMPLITUDE_VS_TIME")
    assert "versus" in _nl("DOMINANT_FREQ_VS_TIME")
    assert _nl("DURATION_DURATION_1F_S") == "Duur: {duration:.1f} s"
    assert "snelheidsgroepering" in _nl("SPEED_DATA_MISSING_OR_INSUFFICIENT_SPEED_BINNED_AND")
    assert "overeenkomende samples" in _nl("ORIGIN_EXPLANATION_FINDING_1")
    assert "toerentalbereik" in _nl("PEAK_DOES_NOT_TRACK_RPM_DURING_STEADY_STATE")
    assert "excitatie" in _nl("CHART_INTERPRETATION_SWEEP")
    assert "Snelheidsbereik" in _nl("SUITABILITY_SPEED_VARIATION_PASS")
    assert "Snelheidsbereik" in _nl("SUITABILITY_SPEED_VARIATION_WARN")
    assert "ordetracking" in _nl("SUITABILITY_SPEED_VARIATION_PASS")
    assert "betrouwbaarheidspunten" in _nl("DATA_TRUST_CAVEATS").lower()
    assert "richtinggevend" in _nl("DATA_TRUST_EFFECT_MEDIUM").lower()
    assert "meer" in _nl("DATA_TRUST_MORE_CAVEATS").lower()
    assert "hoogst gerangschikte" in _nl("NEXT_SENSOR_MOVE_DEFAULT")
    assert "patroonherkenning" in _nl("TIER_A_CAPTURE_WIDER_SPEED")
    assert "de meting" in _nl("RE_RUN_WITH_MEASURED_LOADED_TIRE_CIRCUMFERENCE")
    assert "kwaliteitsmeetwaarde" in _nl("CONSEQUENCE_QUALITY_METRIC_UNAVAILABLE")
    assert "aandrijflijnprobleem" in _nl("ACTION_DRIVELINE_INSPECTION_FALSIFY")
    assert "ordefout" in _nl("FREQUENCY_TRACKS_ENGINE_ORDER_USING_REF_LABEL_BEST")
    assert "ordefout" in _nl("FREQUENCY_TRACKS_WHEEL_ORDER_USING_VEHICLE_SPEED_AND")
    assert "probleemgebieden" in _nl("HOTSPOT_SUMMARY").lower()
    assert "lokale intensiteit" in _nl("HOTSPOT_MARKER_SIZE_HINT").lower()
    assert "ondersteunende meetwaarden" in _nl("DIAGNOSTIC_PEAKS").lower()
    assert "ondersteunende observaties" in _nl("ADDITIONAL_OBSERVATIONS").lower()
    assert _nl("MEANING") == "Betekenis"
    assert "herhaald patroon" in _nl("PEAK_ROW_REPEATED_PATTERN").lower()
    assert "ruisvloer" in _nl("PEAK_ROW_NEAR_NOISE_FLOOR").lower()
    assert "bedrijfsomstandigheid" in _nl(
        "PEAK_FREQUENCY_SHIFTS_RANDOMLY_WITH_NO_REPEATABLE_OPERATING",
    )
    assert "motororde-vergelijking" in _nl("ENGINE_SPEED_REFERENCE_COVERAGE_IS_ENGINE_RPM_NON")
    assert "het resonantiegebied" in _nl("TAP_TEST_NEARBY_PANELS_SEATS_AND_COMPARE_RESONANCE")
    assert "Orde-overeenkomst" in _nl("ORDER_MATCH_DEGRADES_WHEN_USING_MEASURED_TIRE_CIRCUMFERENCE")
    assert "ordevergelijking" in _nl("MEASURED_RPM_BASED_ORDER_MATCHING_DISAGREES_WITH_DERIVED")
    assert _nl("UNKNOWN_SPEED_BAND") == "onbekend snelheidsbereik"
    assert "beschikbaar" in _nl("SPEED_COVERAGE_LINE")
    assert "niet-null" not in _nl("SPEED_COVERAGE_LINE")
    assert "de voertuigsnelheid" in _nl("RECORD_VEHICLE_SPEED_FOR_MOST_SAMPLES_GPS_OR")
    assert "matchpercentage" in _nl("EVIDENCE_ORDER_TRACKED")
    assert _nl("VALIDATE_GEARING_SLIP_ASSUMPTIONS_AGAINST_REAL_RPM_IF").startswith("Controleer")
    assert "brandstof-/ontstekingsadaptaties" in _nl("ACTION_ENGINE_COMBUSTION_WHAT")
    assert "snelheidsmetingen" in _nl("KEEP_TIMESTAMP_BASE_SHARED_WITH_ACCELEROMETER_AND_SPEED")
    assert "snelheids- en versnellingsstromen" in _nl(
        "VERIFY_TIMESTAMP_ALIGNMENT_BETWEEN_SPEED_AND_ACCELERATION_STREAM",
    )
    assert "worden meestal veroorzaakt door" in _nl("ACTION_WHEEL_BALANCE_WHY")
    assert "een patroongebaseerde" in _nl("PATTERN_SUGGESTION_DISCLAIMER")
    assert "motorsnelheidsreferentie" in _nl("ENGINE_SPEED_REFERENCE_COVERAGE_IS_ENGINE_RPM_NON")
    assert "referentiegegevens" in _nl("STATUS_REFERENCE_GAPS")
    assert "definitieve diagnose" in _nl("STATUS_REFERENCE_GAPS")
    assert "ongewijzigd" in _nl("ACTION_WHEEL_BALANCE_FALSIFY")
    assert "snelheidsbereik waarin de klacht optreedt" in _nl("ACTION_TIRE_CONDITION_CONFIRM")
    assert "Verbrandingskwaliteitsindicatoren" in _nl("ACTION_ENGINE_COMBUSTION_FALSIFY")
    assert "de {phase}fase" in _nl("ORIGIN_PHASE_ONSET_NOTE")


def test_dutch_ui_and_recent_translations_complete() -> None:
    """Dutch UI and latest audit assertions stay separate from report-only checks."""
    ui = _load_ui_nl()

    # --- Round 4: UI + Python ---
    assert ui["chart.auto_scale"] == "Automatisch schalen"
    assert ui["location.front_passenger_seat"] == "Bijrijdersstoel"
    assert "eigen merk" in ui["settings.car.or_custom_brand"]
    assert "eigen type" in ui["settings.car.or_custom_type"]
    assert "eigen model" in ui["settings.car.or_custom_model"]
    assert ui["settings.car.use_custom"] == "Eigen invoer gebruiken"
    assert ui["settings.esp_flash.hint"].startswith("Compileer en flash de firmware")
    assert "wachten op" in ui["spectrum.stale"]
    assert "geen snelheid beschikbaar" in ui["dashboard.rotational.reason.speed_unavailable"]
    assert ui["history.loading_preview"] == "Voorbeeld laden..."
    assert "Voorbeeld" in ui["history.preview_unavailable"]
    assert "Voorbeeld" in ui["history.preview_heatmap_title"]
    assert ui["matrix.source.wheel"] == "Wiel/band"
    assert ui["matrix.source.other"] == "Overig / Weg"
    default_nl = [entry[2] for entry in _DEFAULT_PARTS]
    assert any("rubberbus" in label for label in default_nl)

    # --- Round 5: Python ---
    assert _nl("TIRE_ASPECT_PCT_LABEL") == "Zijwanghoogte (%)"
    assert "beste overeenkomst" in _nl("FREQUENCY_TRACKS_ENGINE_ORDER_USING_REF_LABEL_BEST")
    assert "beste overeenkomst" in _nl("FREQUENCY_TRACKS_WHEEL_ORDER_USING_VEHICLE_SPEED_AND")
    assert "ordespecifieke" in _nl("REFERENCE_MISSING_ORDER_SPECIFIC_AMPLITUDE_RANKING_SKIPPED")
    assert "piekherhaalbaarheid" in _nl("REPEAT_RUN_WITH_STABLE_ROUTE_AND_VERIFY_PEAK")
    assert _nl("REFERENCE_COMPLETENESS") == "Referentievolledigheid"
    assert _nl("SUITABILITY_CHECK_REFERENCE_COMPLETENESS") == "Referentievolledigheid"
    assert _nl("DRIVING_PHASE_DECELERATION") == "vertraging"
    assert _nl("DRIVING_PHASE_CRUISE") == "constante snelheid"
    assert "van de sterkste" in _nl("REL_0F_OF_STRONGEST")
    assert _nl("SAMPLE_COUNT_LABEL") == "Aantal metingen"
    assert _nl("NONE_LISTED") == "Niets vermeld"
    assert _nl("RUN_DATE") == "Meetdatum"
    assert _nl("SPEED_BAND") == "Snelheidsbereik"
    assert _nl("REPORT_FALSIFY_COLUMN") == "Als dit niets oplevert"
    assert _nl("REPORT_PAGE1_PARTS_GATE_LABEL") == "Wanneer vervangen"
    assert _nl("REPORT_ACTION_MATRIX_HANDOFF_GATE_TITLE") == "Wanneer vervangen"
    assert "engine-band" not in _nl("REPORT_ACTION_MATRIX_HANDOFF_COMPARE_TEXT")
    assert "gekozen trillingssignaal" in _nl("REPORT_ACTION_MATRIX_HANDOFF_COMPARE_TEXT")
    assert "50-70" not in _nl("REPORT_ACTION_MATRIX_HANDOFF_REPEAT_TEXT")
    assert _nl("REPORT_DOMINANT_CORNER_LABEL") == "Sterkste hoek"
    assert _nl("REPORT_RUNNER_UP_CORNER_LABEL") == "Tweede sterkste hoek"
    assert _nl("REPORT_DOMINANCE_RATIO_LABEL") == "Sterkteverhouding"
    assert _nl("REPORT_LOCATION_CONFIDENCE_LABEL") == "Locatiezekerheid"
    assert _nl("REPORT_COVERAGE_LABEL") == "Sensordekking"
    assert _nl("REPORT_PAGE1_SOURCE_COMPARISON_NOT_INDICATED") == "geen aanwijzing"
    assert _nl("REPORT_PAGE1_PROOF_SUMMARY_TITLE") == "Waarom dit aannemelijk is"
    assert _nl("REPORT_TIMELINE_DETECTIONS_LABEL") == "Signaalvensters"
    assert "motortoerental" in _nl("TIER_A_CAPTURE_REFERENCE_DATA")
    assert "voordat onderdelen worden vervangen" in _nl("WEAK_SPATIAL_SEPARATION_INSPECT_NEARBY")
    assert "ordelabeling" in _nl("THIS_REPORT_IS_GENERATED_FROM_EXPLICIT_REFERENCES_ONLY")
    assert "dominante frequentiepunten" in _nl("PLOT_DOM_FREQ_SKIPPED")
    assert "referentieopmerking" in _nl("INFORMATIONAL_REFERENCE_NOTE")
    assert _nl("DIAGNOSTIC_WORKSHEET") == "VibeSensor-diagnoserapport"
    assert _nl("EVIDENCE_SNAPSHOT") == "Bewijssamenvatting"
    assert _nl("PEAK_DB") == "Piek (dB)"
    assert _nl("SPEED_BINNED_ANALYSIS") == "Analyse per snelheidsband"
    assert "met nadruk op" in _nl("SPEED_HINT_FOCUS")
    assert _nl("RECORD_ADDITIONAL_DATA") == "Verzamel aanvullende gegevens"
    assert "locatievergelijking is minder betrouwbaar" in _nl("SUITABILITY_SENSOR_COVERAGE_WARN")
    assert "te veel slingering/speling" in _nl("ACTION_DRIVELINE_INSPECTION_CONFIRM")

    # --- Round 5: UI + Python ---
    assert ui["dashboard.vibration_count_live"] == "Actuele trillingsteller"
    assert "piek-boven-ruisvloer" in ui["dashboard.matrix_note"]
    assert ui["dashboard.time_window_5min"] == "(afgelopen 5 min)"
    assert "Snelheidsbron:" in ui["dashboard.rotational.basis_source"]
    assert ui["dashboard.rotational.source.fallback_manual"] == "Terugval naar handmatig"
    assert ui["history.refresh"] == "Geschiedenis herladen"
    assert ui["history.pdf_failed"] == "PDF genereren mislukt."
    assert ui["dashboard.logging.run_id"] == "Meetrun-ID: {runId}"
    assert ui["dashboard.logging.last_run_id"] == "Laatste meetrun: {runId}"
    assert ui["history.preview_unavailable"] == ("Voorbeeld is niet beschikbaar voor deze meetrun.")
    assert ui["report.run_id"] == "Meetrun-ID"
    assert ui["settings.update.log_intro"].endswith("meest recente uitvoering.")
    assert ui["settings.update.log_intro_running"].endswith("actieve uitvoering.")
    assert ui["settings.update.health.analysis_run"] == "Actieve analyse"
    assert ui["settings.update.health.analysis_queue_depth"] == "Wachtrij analyses"
    assert ui["settings.tire_aspect"] == "Zijwanghoogte (%)"
    assert ui["settings.wheel_bandwidth"] == "Wielorde-bandbreedte (%)"
    assert ui["settings.driveshaft_bandwidth"] == "Aandrijfasorde-bandbreedte (%)"
    assert ui["settings.engine_bandwidth"] == "Motororde-bandbreedte (%)"
    assert ui["settings.min_half_width"] == "Minimale halve breedte (Hz)"
    assert ui["settings.max_half_width"] == "Maximale halve breedte (%)"
    assert ui["status.running"] == "Lopend"
    assert "Handmatig" in ui["speed.override"]
    assert ui["speed.unit"] == "Eenheid"
    assert ui["ws.connecting"] == "Verbinden"
    assert ui["ws.reconnecting"] == "Opnieuw verbinden"
    assert "herverbinden" in ui["ws.banner.reconnecting"]
    assert "Verbinding maken met server" in ui["ws.banner.connecting"]
    assert "Gecombineerd" in ui["chart.spectrum_title"]
    assert ui["bands.driveshaft_engine_1x"] == "Aandrijfas + Motor 1x"
    assert ui["location.front_subframe"] == "Voorsubframe"
    assert ui["location.rear_subframe"] == "Achtersubframe"
    assert ui["settings.update.runtime_assets_bad"] == "Komt niet overeen"
    assert ui["settings.esp_flash.auto_detect"] == "Automatische detectie"
    assert ui["settings.esp_flash.start"] == "Nieuwste flashen"
    result = why_parts_listed("driveline", "1x", lang="nl")
    assert "cardanasorde" in result
    result = why_parts_listed("driveline", lang="nl")
    assert "aandrijflijntrillingspatronen" in result
    result = why_parts_listed("engine", lang="nl")
    assert "motortrillingspatronen" in result


def test_dutch_location_labels_are_used_for_report_display() -> None:
    def tr_nl(key: str, **kwargs: object) -> str:
        return report_i18n.tr("nl", key, **kwargs)

    assert report_i18n.human_location("Front Left", lang="nl") == "Linksvoor"
    assert report_i18n.human_location("front-right wheel", lang="nl") == "Rechtsvoor"
    assert report_i18n.human_location("Cabine linksvoor", lang="nl") == "Cabine linksvoor"
    assert display_location("rear-left wheel", tr=tr_nl) == "Linksachter"
    assert canonical_location("Linksvoor") == "front-left wheel"
    assert canonical_location("rechterachterwiel") == "rear-right wheel"


def test_dutch_report_presentation_localizes_data_shaped_labels() -> None:
    def tr_nl(key: str, **kwargs: object) -> str:
        return report_i18n.tr("nl", key, **kwargs)

    assert display_speed_band("60-80 km/h", tr=tr_nl) == "60-80 km/u"
    assert order_label_human("nl", "1x wheel, 2x wheel") == "1x wielorde, 2x wielorde"

    fallback = DiagnosisAssessment(
        score_0_to_1=0.42,
        label_key="CONFIDENCE_LOW",
        pct_text="42%",
        tier="A",
        data_basis="summary_only",
        raw_backed_sample_count=0,
        supporting_window_count=None,
        supporting_duration_s=None,
        stable_frequency_min_hz=None,
        stable_frequency_max_hz=None,
        supporting_location_count=0,
        top_support_location=None,
        top_support_share=None,
        mean_relative_error=None,
        snr_db=None,
        alternative_source=None,
        has_reference_gap=True,
        speed_gap_window_count=0,
        rpm_gap_window_count=0,
        car_data_reference_scope=None,
        car_data_confidence=None,
        uses_summary_fallback=True,
        fallback_reason=(
            "Missing reference data may affect accuracy; Speed was not steady during measurement"
        ),
        signal_keys=(),
        caveat_keys=(),
    )
    reason = confidence_reason_text(fallback, tr=tr_nl)
    assert "Referentie ontbreekt" in reason
    assert "snelheid wisselde" in reason
