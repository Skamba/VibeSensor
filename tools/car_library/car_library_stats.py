#!/usr/bin/env python3
"""Print coverage statistics for the bundled car library (read-only).

Usage: python tools/car_library/car_library_stats.py

The numbers feed the coverage table in ``docs/user_journeys.md`` §4. Run it
before and after a library data change and update that table.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from vibesensor.domain.vehicle_configuration import VehicleConfigurationTireOption
from vibesensor.settings.car_library import load_car_library
from vibesensor.settings.vehicle_configurations import load_vehicle_configurations

_WEAK = frozenset({"family_default", "unverified"})


def _line(label: str, value: object) -> None:
    print(f"{label}: {value}")


def _tire_size(option: VehicleConfigurationTireOption) -> tuple[object, ...]:
    front, rear = option.tire_setup.front, option.tire_setup.rear
    return (
        option.name,
        front.width_mm,
        front.aspect_pct,
        front.rim_in,
        rear.width_mm,
        rear.aspect_pct,
        rear.rim_in,
    )


def _counts(counter: Counter[str]) -> str:
    return " · ".join(f"{key} {count}" for key, count in counter.most_common())


def main() -> int:
    rows = load_vehicle_configurations()
    total = len(rows)
    _line("Brands", dict(Counter(row.brand for row in rows)))
    _line("Rows / fuel", f"{total} ({_counts(Counter(row.fuel_type for row in rows))})")
    _line("Generation codes", len({(row.brand, row.model_code) for row in rows}))
    starts = [row.production_start_year for row in rows if row.production_start_year]
    ends = [row.production_end_year for row in rows if row.production_end_year]
    _line("Production years", f"{min(starts)}–{max(ends or starts)}")
    _line("Rows with tire options", sum(1 for row in rows if row.tire_options))
    with_fd = [row for row in rows if row.driven_final_drive_ratio is not None]
    _line("Rows with driven final drive", len(with_fd))
    _line(
        "Rows without driven final drive",
        dict(
            Counter(
                f"{row.brand} {row.model_code}" for row in rows if row not in with_fd
            )
        ),
    )
    _line(
        "Rows with top gear", sum(1 for row in rows if row.top_gear_ratio is not None)
    )
    _line("Rows with full gear sets", sum(1 for row in rows if row.gear_ratios))
    tire_conf = Counter(
        row.tire_metadata.confidence if row.tire_metadata else "none" for row in rows
    )
    fd_conf = Counter(
        row.order_reference_confidence("final_drive_ratio")
        if row in with_fd
        else "none"
        for row in rows
    )
    gear_conf = Counter(
        row.order_reference_confidence("current_gear_ratio") for row in rows
    )
    _line("Tire confidence", _counts(tire_conf))
    _line("Driven final-drive confidence", _counts(fd_conf))
    _line("Top-gear confidence", _counts(gear_conf))
    weak = {
        name: sum(n for key, n in conf.items() if key in _WEAK)
        for name, conf in (
            ("final drive", fd_conf),
            ("top gear", gear_conf),
            ("tire", tire_conf),
        )
    }
    _line(
        "Weak (family_default or unverified)",
        ", ".join(f"{k} {v}/{total}" for k, v in weak.items()),
    )
    _line(
        "order_reference_trust",
        _counts(Counter(row.order_reference_trust for row in rows)),
    )
    _line(
        "requires_manual_confirmation",
        _counts(
            Counter(str(row.requires_manual_drivetrain_confirmation) for row in rows)
        ),
    )

    library = load_car_library()
    variants = [variant for entry in library for variant in entry["variants"]]
    _line("Picker models / variants", f"{len(library)} / {len(variants)}")
    _line(
        "Picker variants without any gearbox",
        sum(1 for v in variants if not v["gearboxes"]),
    )
    tire_sets: defaultdict[tuple[str, ...], set[tuple[object, ...]]] = defaultdict(set)
    for row in rows:
        key = (row.brand, row.car_type, row.model_name, row.variant_name)
        tire_sets[key].add(
            tuple(sorted(_tire_size(option) for option in row.tire_options))
        )
    _line(
        "Variants whose rows differ in tire options",
        sum(1 for sets in tire_sets.values() if len(sets) > 1),
    )
    labels: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in library:
        labels[(entry["brand"], entry["model"].split(",")[0])].add(entry["model"])
    _line(
        "Model families split into several picker entries",
        sum(1 for names in labels.values() if len(names) > 1),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
