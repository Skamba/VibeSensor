from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from vibesensor import report_i18n

_I18N_JSON = Path(__file__).resolve().parent.parent / "data" / "report_i18n.json"
_SOURCE_ROOT = Path(__file__).resolve().parent.parent / "vibesensor"


def test_translation_loads_and_translates() -> None:
    assert report_i18n.tr("nl", "REPORT_DATE") != "REPORT_DATE"


def test_missing_translation_file_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(report_i18n, "_DATA_FILE", Path("/definitely/missing/report_i18n.json"))
    report_i18n._load_translations.cache_clear()
    with pytest.raises(RuntimeError, match="Missing translation file"):
        report_i18n.tr("en", "REPORT_DATE")


def test_corrupt_translation_file_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "report_i18n.json"
    broken.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(report_i18n, "_DATA_FILE", broken)
    report_i18n._load_translations.cache_clear()
    with pytest.raises(RuntimeError, match="Invalid translation file"):
        report_i18n.tr("en", "REPORT_DATE")


def test_all_json_keys_have_en_and_nl() -> None:
    data = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    missing: list[str] = []
    for key, translations in data.items():
        for lang in ("en", "nl"):
            val = translations.get(lang)
            if not isinstance(val, str) or not val.strip():
                missing.append(f"{key}.{lang}")
    assert missing == [], f"Keys with missing or empty translations: {missing}"


def test_all_source_referenced_keys_exist_in_json() -> None:
    data = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    # Match _tr(lang, "KEY") and tr("KEY") calls – the two i18n call patterns used.
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


def test_dutch_translation_corrections() -> None:
    assert report_i18n.tr("nl", "HEAT_LEGEND_MORE") == "Meer trilling"
    assert report_i18n.tr("nl", "RUN_TRIAGE") == "Run triage"
    assert (
        report_i18n.tr("nl", "COVERAGE_RISES_ABOVE_THRESHOLD_AND_WHEEL_ORDER_CHECKS")
        == "Dekking stijgt boven de drempel en wielorde-controles komen beschikbaar."
    )
    assert (
        report_i18n.tr("nl", "ENGINE_ORDER_CHECKS_BECOME_AVAILABLE_WITH_ADEQUATE_RPM")
        == "Motororde-controles komen beschikbaar bij voldoende toerentaldekking."
    )


def test_dutch_translation_audit_round_2() -> None:
    """Verify Dutch translation improvements from the second audit round."""
    # Anglicism fixes: "Top" → natural Dutch
    assert report_i18n.tr("nl", "TOP_ACTIONS") == "Belangrijkste acties"
    assert report_i18n.tr("nl", "TOP_SUSPECTED_CAUSE") == "Meest waarschijnlijke oorzaak"
    # Natural phrasing
    assert report_i18n.tr("nl", "WHAT_TO_CHECK_FIRST") == "Wat eerst controleren"
    assert report_i18n.tr("nl", "RUN_CONDITIONS") == "Meetcondities"
    # Accurate translation of "Confidence"
    assert report_i18n.tr("nl", "CONFIDENCE_LABEL") == "Betrouwbaarheid"
    # Consistency with UI term
    assert report_i18n.tr("nl", "FINAL_DRIVE_RATIO_LABEL") == "Eindoverbrenging"
    # Correct plural "orden" (not "ordes")
    assert "hogere orden" in report_i18n.tr(
        "nl", "CHECK_DRIVESHAFT_RUNOUT_AND_JOINT_CONDITION_FOR_HIGHER"
    )
    # Correct compound "ordereferenties" (not "ordesreferenties")
    assert "ordereferenties" in report_i18n.tr("nl", "SUITABILITY_REFERENCE_COMPLETENESS_PASS")
    assert "ordereferenties" in report_i18n.tr("nl", "SUITABILITY_REFERENCE_COMPLETENESS_WARN")
    # Consistent "data" terminology (not mixed "gegevens")
    assert "locatiedata" in report_i18n.tr("nl", "NO_USABLE_AMPLITUDE_BY_LOCATION_DATA_WAS_FOUND")
    assert "aanvullende data" in report_i18n.tr("nl", "NO_NEXT_STEPS")
    assert report_i18n.tr("nl", "METRIC_LABEL") == "Meetwaarde"
    assert "Snelheidsdata" in report_i18n.tr(
        "nl", "SPEED_DATA_MISSING_OR_INSUFFICIENT_SPEED_BINNED_AND"
    )


def test_dutch_translation_audit_round_3() -> None:
    """Verify Dutch translation improvements from the third audit round (22 changes)."""
    data = json.loads(_I18N_JSON.read_text(encoding="utf-8"))

    def nl(key: str) -> str:
        return data[key]["nl"]

    # --- report_i18n.json improvements ---

    # Consistency: "Bandbreedte" → "Bandenbreedte" matching UI term
    assert nl("TIRE_WIDTH_MM_LABEL") == "Bandenbreedte (mm)"

    # Accuracy: "bewaakte" → "gemonitorde" for "monitored"
    assert "gemonitorde locatie" in nl("DETECTED_AT_ONE_MONITORED_LOCATION")
    assert "gemonitorde locaties" in nl("VIBRATION_SIGNATURE_WAS_DETECTED_AT_ACTIVE_COUNT_OF_DB")

    # Anglicism removal: "gematchte" → "overeenkomende"
    assert "overeenkomende piekamplitude" in nl("METRIC_MEAN_MATCHED_PEAK_AMPLITUDE")
    assert "overeenkomende samples" in nl("METRIC_P95_PEAK_AMPLITUDE")
    assert nl("MATCHED_SYSTEMS") == "Overeenkomende systemen"

    # Natural Dutch: "burstigheid" → "impulsiviteit"
    assert "impulsiviteit" in nl("EVIDENCE_PEAK_PRESENT")

    # Consistency: "hardy-schijf" → "flexschijf" matching pattern_parts.py
    assert "flexschijf" in nl("ACTION_DRIVELINE_INSPECTION_WHAT")

    # Natural Dutch: "wiel/band-hoeken" → "wiel-/bandposities"
    assert "wiel-/bandposities" in nl("LOCATION_HINT_AT_WHEEL_CORNERS")

    # Precise verb: "geven" → "veroorzaken"
    assert "veroorzaken" in nl("ACTION_ENGINE_COMBUSTION_WHY")

    # Clearer Dutch: "orde-inhoud" → "orde-trillingen"
    assert "orde-trillingen" in nl("ACTION_DRIVELINE_MOUNTS_WHY")

    # Consistency: "amplitudemetriek" → "amplitudemeetwaarde" matching METRIC_LABEL
    assert "amplitudemeetwaarde" in nl("OUTLIER_SUMMARY_LINE")


def test_dutch_translation_audit_round_4() -> None:
    """Verify Dutch translation improvements from the fourth audit round (50+ changes)."""
    data = json.loads(_I18N_JSON.read_text(encoding="utf-8"))

    def nl(key: str) -> str:
        return data[key]["nl"]

    # --- report_i18n.json improvements ---

    # Formal Dutch: "vs" → "versus"
    assert "versus" in nl("AMPLITUDE_VS_TIME")
    assert "versus" in nl("DOMINANT_FREQ_VS_TIME")

    # SI spacing: space before unit symbol
    assert nl("DURATION_DURATION_1F_S") == "Duur: {duration:.1f} s"

    # Anglicism removal: "snelheids-binning" → "snelheidsgroepering"
    assert "snelheidsgroepering" in nl("SPEED_DATA_MISSING_OR_INSUFFICIENT_SPEED_BINNED_AND")

    # Anglicism removal: "gematchte" → "overeenkomende" in origin explanation
    assert "overeenkomende samples" in nl("ORIGIN_EXPLANATION_FINDING_1")

    # Anglicism removal: "sweep" → "toerentalbereik"
    assert "toerentalbereik" in nl("PEAK_DOES_NOT_TRACK_RPM_DURING_STEADY_STATE")

    # Technical Dutch: "aanstoting" → "excitatie"
    assert "excitatie" in nl("CHART_INTERPRETATION_SWEEP")

    # Anglicism removal: "Snelheidssweep" → "Snelheidsbereik"
    assert "Snelheidsbereik" in nl("SUITABILITY_SPEED_VARIATION_PASS")
    assert "Snelheidsbereik" in nl("SUITABILITY_SPEED_VARIATION_WARN")

    # Compound: "orde-tracking" → "ordetracking"
    assert "ordetracking" in nl("SUITABILITY_SPEED_VARIATION_PASS")

    # Natural Dutch: remove "hotspot-pad"
    assert "piekwaarde" in nl("NEXT_SENSOR_MOVE_DEFAULT")

    # Anglicism removal: "patroontracking" → "patroonherkenning"
    assert "patroonherkenning" in nl("TIER_A_CAPTURE_WIDER_SPEED")

    # Natural Dutch: add article for completeness
    assert "de meting" in nl("RE_RUN_WITH_MEASURED_LOADED_TIRE_CIRCUMFERENCE")

    # Consistency: "kwaliteitsmeting" → "kwaliteitsmeetwaarde" matching METRIC_LABEL
    assert "kwaliteitsmeetwaarde" in nl("CONSEQUENCE_QUALITY_METRIC_UNAVAILABLE")

    # Anglicism removal: "issue" → "probleem"
    assert "aandrijflijnprobleem" in nl("ACTION_DRIVELINE_INSPECTION_FALSIFY")

    # Compound: "orde-fout" → "ordefout"
    assert "ordefout" in nl("FREQUENCY_TRACKS_ENGINE_ORDER_USING_REF_LABEL_BEST")
    assert "ordefout" in nl("FREQUENCY_TRACKS_WHEEL_ORDER_USING_VEHICLE_SPEED_AND")

    # Natural Dutch: "bedrijfsconditie" → "bedrijfsomstandigheid"
    assert "bedrijfsomstandigheid" in nl(
        "PEAK_FREQUENCY_SHIFTS_RANDOMLY_WITH_NO_REPEATABLE_OPERATING"
    )

    # Anglicism removal: "motororde-matching" → "motororde-vergelijking"
    assert "motororde-vergelijking" in nl("ENGINE_SPEED_REFERENCE_COVERAGE_IS_ENGINE_RPM_NON")

    # Grammar: article before "resonantiegebied"
    assert "het resonantiegebied" in nl("TAP_TEST_NEARBY_PANELS_SEATS_AND_COMPARE_RESONANCE")

    # Anglicism removal: "Orde-match" → "Orde-overeenkomst"
    assert "Orde-overeenkomst" in nl("ORDER_MATCH_DEGRADES_WHEN_USING_MEASURED_TIRE_CIRCUMFERENCE")

    # Anglicism removal: "orde-matching" → "ordevergelijking"
    assert "ordevergelijking" in nl("MEASURED_RPM_BASED_ORDER_MATCHING_DISAGREES_WITH_DERIVED")

    # Clarity: "onbekende band" → "onbekend snelheidsbereik"
    assert nl("UNKNOWN_SPEED_BAND") == "onbekend snelheidsbereik"

    # Natural Dutch: "niet-null" → "beschikbaar"
    assert "beschikbaar" in nl("SPEED_COVERAGE_LINE")
    assert "niet-null" not in nl("SPEED_COVERAGE_LINE")

    # Grammar: add article "de"
    assert "de voertuigsnelheid" in nl("RECORD_VEHICLE_SPEED_FOR_MOST_SAMPLES_GPS_OR")

    # Anglicism removal: "trefferratio" → "trefkans"
    assert "trefkans" in nl("EVIDENCE_ORDER_TRACKED")

    # Natural Dutch: "Valideer" → "Controleer"
    assert nl("VALIDATE_GEARING_SLIP_ASSUMPTIONS_AGAINST_REAL_RPM_IF").startswith("Controleer")

    # Compound correction: "brandstof/ontsteking-adaptaties" → proper Dutch compound
    assert "brandstof-/ontstekingsadaptaties" in nl("ACTION_ENGINE_COMBUSTION_WHAT")

    # Natural Dutch: "snelheidsrecords" → "snelheidsmetingen"
    assert "snelheidsmetingen" in nl("KEEP_TIMESTAMP_BASE_SHARED_WITH_ACCELEROMETER_AND_SPEED")

    # Interfixed s: "snelheid-" → "snelheids-"
    assert "snelheids- en versnellingsstromen" in nl(
        "VERIFY_TIMESTAMP_ALIGNMENT_BETWEEN_SPEED_AND_ACCELERATION_STREAM"
    )

    # Passive construction: "komen door" → "worden veroorzaakt door"
    assert "worden meestal veroorzaakt door" in nl("ACTION_WHEEL_BALANCE_WHY")

    # Grammar: add "een" article
    assert "een patroongebaseerde" in nl("PATTERN_SUGGESTION_DISCLAIMER")

    # Compound: "motor-snelheidsreferentie" → "motorsnelheidsreferentie"
    assert "motorsnelheidsreferentie" in nl("ENGINE_SPEED_REFERENCE_COVERAGE_IS_ENGINE_RPM_NON")

    # Terminology: "referentiegegevens" → "referentiedata"
    assert "referentiedata" in nl("STATUS_REFERENCE_GAPS")

    # Natural Dutch: "einddiagnose" → "definitieve diagnose"
    assert "definitieve diagnose" in nl("STATUS_REFERENCE_GAPS")

    # Precision: "blijft gelijk" → "blijft ongewijzigd"
    assert "ongewijzigd" in nl("ACTION_WHEEL_BALANCE_FALSIFY")

    # Compound: "klachten-snelheidsband" → "klachtsnelheidsband"
    assert "klachtsnelheidsband" in nl("ACTION_TIRE_CONDITION_CONFIRM")

    # Compound: "Verbrandingskwaliteits-indicatoren" → "Verbrandingskwaliteitsindicatoren"
    assert "Verbrandingskwaliteitsindicatoren" in nl("ACTION_ENGINE_COMBUSTION_FALSIFY")

    # Grammar: article before phase
    assert "de {phase}fase" in nl("ORIGIN_PHASE_ONSET_NOTE")


def test_dutch_translation_audit_round_4_ui_and_python() -> None:
    """Verify Dutch translation improvements in nl.json (UI) and Python files."""
    # --- nl.json UI translations ---
    ui_json = (
        Path(__file__).resolve().parent.parent.parent
        / "ui"
        / "src"
        / "i18n"
        / "catalogs"
        / "nl.json"
    )
    ui = json.loads(ui_json.read_text(encoding="utf-8"))

    # Natural Dutch: "Autoschaal" → "Automatisch schalen"
    assert ui["chart.auto_scale"] == "Automatisch schalen"

    # Standard Dutch term: "Voorpassagiersstoel" → "Bijrijdersstoel"
    assert ui["location.front_passenger_seat"] == "Bijrijdersstoel"

    # Natural Dutch: "aangepast" → "eigen"
    assert "eigen merk" in ui["settings.car.or_custom_brand"]
    assert "eigen type" in ui["settings.car.or_custom_type"]
    assert "eigen model" in ui["settings.car.or_custom_model"]
    assert ui["settings.car.use_custom"] == "Eigen invoer gebruiken"

    # Technical Dutch: "Bouw en flash" → "Compileer en flash de"
    assert ui["settings.esp_flash.hint"].startswith("Compileer en flash de firmware")

    # Infinitive form: "wacht" → "wachten"
    assert "wachten op" in ui["spectrum.stale"]

    # Avoid repeating "niet beschikbaar"
    assert "geen snelheid beschikbaar" in ui["dashboard.rotational.reason.speed_unavailable"]

    # Anglicism removal: "Preview" → "Voorvertoning"
    assert ui["history.loading_preview"] == "Voorvertoning laden..."
    assert "Voorvertoning" in ui["history.preview_unavailable"]
    assert "Voorvertoning" in ui["history.preview_heatmap_title"]

    # Consistent slash spacing matching report style
    assert ui["matrix.source.wheel"] == "Wiel / Band"
    assert ui["matrix.source.other"] == "Overig / Weg"

    # --- Python file improvements ---
    from vibesensor.analysis.pattern_parts import _DEFAULT_PARTS
    from vibesensor.analysis.strength_labels import _CERTAINTY_REASONS

    # Anglicism removal: "match" → "overeenkomst"
    assert "overeenkomst" in _CERTAINTY_REASONS["strong_order_match"]["nl"]
    assert "overeenkomst" in _CERTAINTY_REASONS["moderate_order_match"]["nl"]

    # Anglicism removal: "patroonmatching" → "patroonvergelijking"
    assert "patroonvergelijking" in _CERTAINTY_REASONS["reference_gaps"]["nl"]

    # Dutch terminology: "rubberbushing" → "rubberbus"
    default_nl = [entry[2] for entry in _DEFAULT_PARTS]
    assert any("rubberbus" in label for label in default_nl)


def test_dutch_translation_audit_round_5() -> None:
    """Verify Dutch translation improvements from the fifth audit round."""
    data = json.loads(_I18N_JSON.read_text(encoding="utf-8"))

    def nl(key: str) -> str:
        return data[key]["nl"]

    # --- report_i18n.json improvements ---

    # Consistency with UI: "Bandprofiel" → "Bandenprofiel"
    assert nl("TIRE_ASPECT_PCT_LABEL") == "Bandenprofiel (%)"

    # Anglicism removal: "beste match" → "beste overeenkomst"
    assert "beste overeenkomst" in nl("FREQUENCY_TRACKS_ENGINE_ORDER_USING_REF_LABEL_BEST")
    assert "beste overeenkomst" in nl("FREQUENCY_TRACKS_WHEEL_ORDER_USING_VEHICLE_SPEED_AND")

    # Compound correction: "orde-specifieke" → "ordespecifieke"
    assert "ordespecifieke" in nl("REFERENCE_MISSING_ORDER_SPECIFIC_AMPLITUDE_RANKING_SKIPPED")

    # Compound correction: "piek-herhaalbaarheid" → "piekherhaalbaarheid"
    assert "piekherhaalbaarheid" in nl("REPEAT_RUN_WITH_STABLE_ROUTE_AND_VERIFY_PEAK")

    # Natural Dutch: "Referentiecompleetheid" → "Referentievolledigheid"
    assert nl("REFERENCE_COMPLETENESS") == "Referentievolledigheid"
    assert nl("SUITABILITY_CHECK_REFERENCE_COMPLETENESS") == "Referentievolledigheid"

    # Natural Dutch: "deceleratie" → "vertraging"
    assert nl("DRIVING_PHASE_DECELERATION") == "vertraging"

    # Grammar: add article "de" before "sterkste"
    assert "van de sterkste" in nl("REL_0F_OF_STRONGEST")

    # Consistency: "Aantal samples" → "Aantal metingen" matching SAMPLES key
    assert nl("SAMPLE_COUNT_LABEL") == "Aantal metingen"

    # Closer to English: "Geen items" → "Niets vermeld"
    assert nl("NONE_LISTED") == "Niets vermeld"

    # Consistency: "motor-RPM" → "motortoerental"
    assert "motortoerental" in nl("TIER_A_CAPTURE_REFERENCE_DATA")

    # Formal register: remove informal "je" → passive
    assert "voordat onderdelen worden vervangen" in nl("WEAK_SPATIAL_SEPARATION_INSPECT_NEARBY")

    # Compound: "orde-labeling" → "ordelabeling"
    assert "ordelabeling" in nl("THIS_REPORT_IS_GENERATED_FROM_EXPLICIT_REFERENCES_ONLY")

    # Hyphen removal: "dominante-frequentiepunten" → "dominante frequentiepunten"
    assert "dominante frequentiepunten" in nl("PLOT_DOM_FREQ_SKIPPED")

    # Compound: "referentie-opmerking" → "referentieopmerking"
    assert "referentieopmerking" in nl("INFORMATIONAL_REFERENCE_NOTE")

    # More precise: "werkblad" → "werkformulier"
    assert nl("DIAGNOSTIC_WORKSHEET") == "Diagnostisch werkformulier"

    # "Bewijsoverzicht" → "Bewijssamenvatting"
    assert nl("EVIDENCE_SNAPSHOT") == "Bewijssamenvatting"

    assert nl("PEAK_DB") == "Piek (dB)"

    # Natural Dutch: "Analyse per snelheidsband"
    assert nl("SPEED_BINNED_ANALYSIS") == "Analyse per snelheidsband"

    # More natural: "met nadruk op" instead of "met focus rond"
    assert "met nadruk op" in nl("SPEED_HINT_FOCUS")

    # Consistency: "Verzamel aanvullende data"
    assert nl("RECORD_ADDITIONAL_DATA") == "Verzamel aanvullende data"

    # Clearer: "locatievergelijking is minder betrouwbaar"
    assert "locatievergelijking is minder betrouwbaar" in nl("SUITABILITY_SENSOR_COVERAGE_WARN")

    # "buiten-specificatie" → "buiten specificatie"
    assert "buiten specificatie" in nl("ACTION_DRIVELINE_INSPECTION_CONFIRM")


def test_dutch_translation_audit_round_5_ui_and_python() -> None:
    """Verify Dutch translation improvements in nl.json and Python files (round 5)."""
    # --- nl.json UI translations ---
    ui_json = (
        Path(__file__).resolve().parent.parent.parent
        / "ui"
        / "src"
        / "i18n"
        / "catalogs"
        / "nl.json"
    )
    ui = json.loads(ui_json.read_text(encoding="utf-8"))

    # Natural Dutch: "Live trillingsteller" → "Actuele trillingsteller"
    assert ui["dashboard.vibration_count_live"] == "Actuele trillingsteller"

    # More accurate: "piek-boven-ruisvloer" in matrix note
    assert "piek-boven-ruisvloer" in ui["dashboard.matrix_note"]

    # Natural Dutch: "(laatste 5 min)" → "(afgelopen 5 min)"
    assert ui["dashboard.time_window_5min"] == "(afgelopen 5 min)"

    # Consistency: "Snelheidsbasis" → "Snelheidsbron" matching settings.speed.title
    assert "Snelheidsbron:" in ui["dashboard.rotational.basis_source"]

    # Natural Dutch: "Handmatige terugval" → "Terugval naar handmatig"
    assert ui["dashboard.rotational.source.fallback_manual"] == "Terugval naar handmatig"

    # More natural: "verversen" → "herladen"
    assert ui["history.refresh"] == "Geschiedenis herladen"

    # More concise: "PDF genereren mislukt."
    assert ui["history.pdf_failed"] == "PDF genereren mislukt."

    # More accurate: "Verlies Δ" → "Verloren Δ"
    assert ui["history.table.dropped_delta"] == "Verloren Δ"

    # Dutch for overflow: "Overflow Δ" → "Overloop Δ"
    assert ui["history.table.overflow_delta"] == "Overloop Δ"

    # Better word order for bandwidth labels
    assert ui["settings.wheel_bandwidth"] == "Wielorde-bandbreedte (%)"
    assert ui["settings.driveshaft_bandwidth"] == "Aandrijfasorde-bandbreedte (%)"
    assert ui["settings.engine_bandwidth"] == "Motororde-bandbreedte (%)"

    # Avoid abbreviations: "Min" → "Minimale", "Max" → "Maximale"
    assert ui["settings.min_half_width"] == "Minimale halve breedte (Hz)"
    assert ui["settings.max_half_width"] == "Maximale halve breedte (%)"

    # More accurate: "Actief" → "Lopend" for "Running"
    assert ui["status.running"] == "Lopend"

    # Dutch override term: "Geforceerd" → "Handmatig"
    assert "Handmatig" in ui["speed.override"]

    # Concise: "Snelheidseenheid" → "Eenheid"
    assert ui["speed.unit"] == "Eenheid"

    # Natural Dutch: "verbinden" → "verbinding maken"
    assert "verbinding maken" in ui["ws.connecting"]

    # Consistency: "herverbinden"
    assert "herverbinden" in ui["ws.reconnecting"]
    assert "herverbinden" in ui["ws.banner.reconnecting"]

    # Better Dutch: "Verbinding maken met server"
    assert "Verbinding maken met server" in ui["ws.banner.connecting"]

    # More precise: "Gemengd" → "Gecombineerd"
    assert "Gecombineerd" in ui["chart.spectrum_title"]

    # Consistent spacing: "Aandrijfas+Motor" → "Aandrijfas + Motor"
    assert ui["bands.driveshaft_engine_1x"] == "Aandrijfas + Motor 1x"

    # Compound: "Voorste subframe" → "Voorsubframe"
    assert ui["location.front_subframe"] == "Voorsubframe"
    assert ui["location.rear_subframe"] == "Achtersubframe"

    # More natural: "Niet overeenkomend" → "Komt niet overeen"
    assert ui["settings.update.runtime_assets_bad"] == "Komt niet overeen"

    # Anglicism: "Auto-detectie" → "Automatische detectie"
    assert ui["settings.esp_flash.auto_detect"] == "Automatische detectie"

    # Dutch word order: "Flash nieuwste" → "Nieuwste flashen"
    assert ui["settings.esp_flash.start"] == "Nieuwste flashen"

    # --- Python source file improvements ---
    from vibesensor.analysis.pattern_parts import why_parts_listed
    from vibesensor.analysis.strength_labels import _CERTAINTY_REASONS

    # Compound fix: "tracking-betrouwbaarheid" → "trackingbetrouwbaarheid"
    assert "trackingbetrouwbaarheid" in _CERTAINTY_REASONS["narrow_speed_range"]["nl"]

    # Compound fix in pattern_parts: "cardanas-orde" → "cardanasorde"
    result = why_parts_listed("driveline", "1x", lang="nl")
    assert "cardanasorde" in result

    # Compound fix: "aandrijflijn-trillingspatronen" → "aandrijflijntrillingspatronen"
    result = why_parts_listed("driveline", lang="nl")
    assert "aandrijflijntrillingspatronen" in result

    # Compound fix: "motor-trillingspatronen" → "motortrillingspatronen"
    result = why_parts_listed("engine", lang="nl")
    assert "motortrillingspatronen" in result
