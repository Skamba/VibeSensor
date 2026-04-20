"""Guard: car-library JSON, ratio ledger, and variant-source docs stay aligned."""

from __future__ import annotations

import json

from vibesensor.adapters.persistence.car_library import _DATA_FILE, load_car_library

_RATIO_SOURCES_FILE = _DATA_FILE.with_name("car_library_ratio_sources.json")
_VARIANT_SOURCES_FILE = _DATA_FILE.with_name("CAR_VARIANT_SOURCES.md")


def _car_key(entry: dict[str, object]) -> str:
    return f"{entry['brand']}|{entry['model']}"


def _variant_rows_from_docs() -> dict[str, list[tuple[str, str, str]]]:
    rows: dict[str, list[tuple[str, str, str]]] = {}
    current_brand: str | None = None
    lines = _VARIANT_SOURCES_FILE.read_text().splitlines()
    index = 0

    while index < len(lines):
        line = lines[index]
        if line.startswith("## "):
            heading = line[3:].strip()
            if heading in {"BMW", "Audi"}:
                current_brand = heading
            index += 1
            continue

        if not line.startswith("### "):
            index += 1
            continue

        assert current_brand is not None, f"Model heading {line!r} missing brand section"
        model = line[4:].strip()
        index += 1

        while index < len(lines) and not lines[index].startswith("| Variant |"):
            if lines[index].startswith("### ") or lines[index].startswith("## "):
                break
            index += 1

        if index >= len(lines) or not lines[index].startswith("| Variant |"):
            raise AssertionError(f"{current_brand}|{model} missing variant table")

        index += 2
        variants: list[tuple[str, str, str]] = []
        while index < len(lines) and lines[index].startswith("|"):
            cells = [cell.strip() for cell in lines[index].split("|")[1:-1]]
            if len(cells) >= 3 and cells[0]:
                variants.append((cells[0], cells[1], cells[2]))
            index += 1

        rows[f"{current_brand}|{model}"] = variants

    return rows


def _variant_rows_from_library() -> dict[str, list[tuple[str, str, str]]]:
    rows: dict[str, list[tuple[str, str, str]]] = {}
    for entry in load_car_library():
        rows[_car_key(entry)] = [
            (variant["name"], variant["engine"], variant["drivetrain"])
            for variant in entry["variants"]
        ]
    return rows


def test_car_library_artifact_model_sets_match() -> None:
    with _RATIO_SOURCES_FILE.open() as fh:
        ratio_source_rows = json.load(fh)["cars"]

    library_rows = _variant_rows_from_library()
    doc_rows = _variant_rows_from_docs()

    assert set(library_rows) == set(ratio_source_rows) == set(doc_rows)


def test_variant_source_docs_match_car_library_variants() -> None:
    doc_rows = _variant_rows_from_docs()
    library_rows = _variant_rows_from_library()

    for car_key, library_variants in library_rows.items():
        library_variant_set = set(library_variants)
        missing = [variant for variant in doc_rows[car_key] if variant not in library_variant_set]
        assert missing == [], (
            f"{car_key} documents variants not present in car_library.json: {missing}"
        )
