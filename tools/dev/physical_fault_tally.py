#!/usr/bin/env python3
"""Tally the diagnosis accuracy benchmark with physically sized faults.

A developer tool, not a CI gate. CI runs the benchmark with tuned fault
amplitudes; this runs it with the faults sized as forces in grams and newtons
(``VIBESENSOR_BENCH_FAULT_AMPLITUDES=physical``, see "Fault amplitudes" in
docs/simulator_realism.md) and reports how much of it the analysis meets:

    .venv/bin/python tools/dev/physical_fault_tally.py cases
    .venv/bin/python tools/dev/physical_fault_tally.py limits
    .venv/bin/python tools/dev/physical_fault_tally.py cases --match front-left --workers 2

``cases`` runs every case and car over seeds 1-6 on the case's own floor, as
CI does, and prints per area (wheel/tire, driveline, engine, brakes, healthy)
how many case and car runs pass CI's rule: seed 1 and 4 of seeds 2-6.
``limits`` drives each fault source at fixed speeds and sizes on both floors
and prints the smallest size found on 4 of 5 seeds per sensor layout. Both can
write every run as a JSON line (``--out``) to compare two analysis versions.
Each run takes a few seconds of CPU: ``cases`` about 1300 runs, ``limits``
about 1500.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import tempfile
import traceback
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path

os.environ["VIBESENSOR_BENCH_FAULT_AMPLITUDES"] = "physical"
_SERVER = Path(__file__).resolve().parents[2] / "apps" / "server"
sys.path[:0] = [str(_SERVER / "tests"), str(_SERVER / "tests" / "integration")]

import test_diagnosis_accuracy_benchmark as bench  # noqa: E402

from vibesensor.simulator.profiles import PROFILE_LIBRARY  # noqa: E402
from vibesensor.simulator.road_surface import generated_road  # noqa: E402

CI_SEEDS = (bench.CI_SEED, *bench.MATRIX_SEEDS)
LIMIT_SEEDS = (1, 2, 3, 4, 5)
LIMIT_SPEEDS_KMH = (50, 80, 100, 130)
# Found on this many of the limit seeds counts as found.
LIMIT_MIN_FOUND = 4
AREAS = ("wheel/tire", "driveline", "engine", "brakes", "healthy")


@dataclass(frozen=True)
class Source:
    """A fault source driven at a size, read by a sensor layout."""

    name: str
    unit: str
    sizes: tuple[float, ...]
    layout: tuple[bench.BenchSensor, ...]
    fault: Callable[[float], tuple[bench.PhaseOverride, ...]]
    # (diagnosed source, zone it must name; ``None``: any zone)
    expected: tuple[str, str | None]


def _forces_at(
    name: str, size: float, forces: Iterable[bench.OrderForce], reference: float
):
    return bench._car(
        f"limit_{name}_{size:g}", *(f.scaled(size / reference) for f in forces)
    )


SOURCES = {
    source.name: source
    for source in (
        Source(
            "wheel-at-its-knuckle",
            "g",
            (2, 5, 10, 15, 20, 30, 40, 60),
            bench.SENSORS,
            lambda g: bench._imbalance("front-left", g),
            ("wheel/tire", "front_left_wheel"),
        ),
        Source(
            "wheel-cabin-only",
            "g",
            (10, 20, 40, 60, 100, 200),
            bench.CABIN_ONLY,
            lambda g: bench._imbalance("front-left", g),
            ("wheel/tire", None),
        ),
        Source(
            "propshaft",
            "g",
            (5, 15, 30, 60, 120, 240),
            bench.SENSORS,
            lambda g: _forces_at(
                "propshaft", g, bench._PROPSHAFT_IMBALANCE_FORCES, 15.0
            ),
            ("driveline", None),
        ),
        Source(
            "inline-4-e2",
            "g",
            (20, 50, 100, 150, 300),
            bench.SENSORS,
            lambda g: _forces_at("i4", g, bench._I4_SECOND_ORDER_FORCES, 150.0),
            ("engine", None),
        ),
        Source(
            "inline-4-e2-engine-bay-sensor",
            "g",
            (20, 50, 100, 150, 300),
            bench.WITH_ENGINE_BAY,
            lambda g: _forces_at("i4", g, bench._I4_SECOND_ORDER_FORCES, 150.0),
            ("engine", None),
        ),
    )
}


def _register_profiles() -> None:
    """Build every limit drive's profile, then register all the benchmark's (before forking)."""
    for source in SOURCES.values():
        for size in source.sizes:
            source.fault(size)
    PROFILE_LIBRARY.update(bench.bench_profiles())


def _area(case: bench.Case, car: str) -> str:
    return case.by_car.get(car, case.expected).source or "healthy"


def _run_case(job: tuple[str, str, int]) -> dict[str, object]:
    case_id, car, seed = job
    case = next(case for case in bench.CASES if case.case_id == case_id)
    error = None
    with tempfile.TemporaryDirectory() as tmp:
        try:
            bench._run_case(case, car, seed, Path(tmp))
        except AssertionError as exc:
            error = (str(exc).splitlines() or ["AssertionError"])[0][:300]
        except Exception as exc:  # noqa: BLE001 - a crash is a failed run, reported
            error = (
                "error: " + "".join(traceback.format_exception_only(exc)).strip()[:300]
            )
    return {
        "case": case_id,
        "car": car,
        "seed": seed,
        "area": _area(case, car),
        "road": case.idealised_floor is None,
        "ok": error is None,
        "error": error,
    }


def _limit_phases(kmh: float, fault: tuple[bench.PhaseOverride, ...]):
    return (
        bench._phase("ramp", 14.0, kmh - 8.0, kmh + 8.0, *fault),
        *bench._wobbly_cruise(kmh, 15.0, *fault),
    )


def _run_limit(job: tuple[str, float, int, bool, int]) -> dict[str, object]:
    name, size, kmh, road, seed = job
    source = SOURCES[name]
    row: dict[str, object] = {
        "source": name,
        "size": size,
        "kmh": kmh,
        "road": road,
        "seed": seed,
    }
    with tempfile.TemporaryDirectory() as tmp:
        try:
            result = bench.run_sim_pipeline(
                Path(tmp),
                car=bench.DEFAULT_CAR,
                sensors=source.layout,
                scenario_name=f"limit-{name}",
                phases=_limit_phases(kmh, source.fault(size)),
                client_seed=seed,
                road=generated_road(seed) if road else None,
            )
            diagnosis = result.diagnosis
            result.history_db.close()
        except Exception as exc:  # noqa: BLE001 - a crash is a miss, reported
            row["error"] = "".join(traceback.format_exception_only(exc)).strip()[:300]
            row["found"] = row["fault"] = False
            return row
    want_source, want_zone = source.expected
    found = (
        diagnosis["verdict"] in ("fault", "weak_evidence")
        and diagnosis["source"] == want_source
        and (want_zone is None or diagnosis["zone"] == want_zone)
    )
    row.update(found=found, fault=found and diagnosis["verdict"] == "fault")
    row.update(
        verdict=diagnosis["verdict"],
        diagnosed=diagnosis["source"],
        zone=diagnosis["zone"],
        order_code=diagnosis["order_code"],
    )
    return row


def _run(
    jobs: list, run: Callable, workers: int, out: Path | None
) -> list[dict[str, object]]:
    rows = []
    with get_context("fork").Pool(workers, maxtasksperchild=20) as pool:
        for row in pool.imap_unordered(run, jobs, chunksize=1):
            rows.append(row)
            print(
                f"\r{len(rows)}/{len(jobs)} runs", end="", file=sys.stderr, flush=True
            )
    print(file=sys.stderr)
    if out is not None:
        out.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return rows


def _passes(by_seed: dict[int, bool]) -> bool:
    """CI's rule over the seeds run: seed 1, and 4 of seeds 2-6 (all, with fewer)."""
    matrix = [by_seed[seed] for seed in bench.MATRIX_SEEDS if seed in by_seed]
    needed = (
        bench.MATRIX_MIN_PASSES
        if len(matrix) == len(bench.MATRIX_SEEDS)
        else len(matrix)
    )
    return by_seed.get(bench.CI_SEED, True) and sum(matrix) >= needed


def tally_cases(args: argparse.Namespace) -> None:
    cases = [case for case in bench.CASES if args.match in case.case_id]
    jobs = [
        (case.case_id, car, seed)
        for case in cases
        for car in case.cars
        for seed in args.seeds
    ]
    rows = _run(jobs, _run_case, args.workers, args.out)
    runs: dict[tuple[str, str], dict[int, bool]] = collections.defaultdict(dict)
    meta = {}
    for row in rows:
        runs[row["case"], row["car"]][row["seed"]] = row["ok"]
        meta[row["case"], row["car"]] = (row["area"], row["road"])
        if row["seed"] == min(args.seeds) and not row["ok"]:
            meta[row["case"], row["car"], "error"] = row["error"]
    table = collections.Counter()
    failed = []
    for key, by_seed in sorted(runs.items()):
        area, road = meta[key]
        ok = _passes(by_seed)
        table[area, road, ok] += 1
        if not ok:
            failed.append(
                (
                    area,
                    key,
                    sum(by_seed.values()),
                    len(by_seed),
                    meta.get((*key, "error")),
                )
            )
    print(
        f"Physical fault amplitudes: case and car runs passing CI's rule (seeds {args.seeds})"
    )
    print(f"{'area':12} {'on the road':>14} {'idealised floor':>17} {'all':>10}")
    for area in AREAS:
        cells = []
        for floor in (True, False, None):
            ok = sum(
                table[area, road, True]
                for road in (True, False)
                if floor in (None, road)
            )
            n = ok + sum(
                table[area, road, False]
                for road in (True, False)
                if floor in (None, road)
            )
            cells.append(f"{ok}/{n}")
        print(f"{area:12} {cells[0]:>14} {cells[1]:>17} {cells[2]:>10}")
    total_ok = sum(count for (_, _, ok), count in table.items() if ok)
    print(f"{'total':12} {'':>14} {'':>17} {f'{total_ok}/{sum(table.values())}':>10}")
    if args.verbose:
        print("\nFailing (area, case, car, seeds passed, first failing seed's reason):")
        for area, (case_id, car), passed, n, error in failed:
            print(f"  {area:10} {case_id} [{car}] {passed}/{n}: {error or ''}")


def tally_limits(args: argparse.Namespace) -> None:
    names = list(SOURCES) if args.source == "all" else [args.source]
    jobs = [
        (name, size, kmh, road, seed)
        for name in names
        for size in SOURCES[name].sizes
        for kmh in args.speeds
        for road in (True, False)
        for seed in args.seeds
    ]
    rows = _run(jobs, _run_limit, args.workers, args.out)
    found = collections.Counter()
    faults = collections.Counter()
    for row in rows:
        key = (row["source"], row["road"], row["kmh"], row["size"])
        found[key] += row["found"]
        faults[key] += row["fault"]
    need = min(LIMIT_MIN_FOUND, len(args.seeds))
    print(f"Smallest fault found on {need} of {len(args.seeds)} seeds, by speed")
    print("(in brackets: the smallest a fault verdict, not weak evidence, names there;")
    print(" none / -: not even the largest size tried)")
    header = "".join(f"{kmh:>11} km/h" for kmh in args.speeds)
    print(f"{'source':32} {'floor':9}" + header)
    for name in names:
        source = SOURCES[name]
        for road in (True, False):
            cells = []
            for kmh in args.speeds:
                smallest = _smallest(source, found, (name, road, kmh), need)
                verdict = _smallest(source, faults, (name, road, kmh), need)
                text = "none" if smallest is None else f"{smallest:g} {source.unit}"
                if smallest is not None and verdict != smallest:
                    text += f" ({'-' if verdict is None else f'{verdict:g}'})"
                cells.append(text)
            floor = "road" if road else "idealised"
            print(f"{name:32} {floor:9}" + "".join(f"{cell:>16}" for cell in cells))
    print(
        "sizes tried: "
        + "; ".join(
            f"{name} {SOURCES[name].sizes[0]:g}-{SOURCES[name].sizes[-1]:g} {SOURCES[name].unit}"
            for name in names
        )
    )


def _smallest(
    source: Source, counts: collections.Counter, key: tuple, need: int
) -> float | None:
    """The smallest size from which every larger one is found too."""
    smallest = None
    for size in reversed(source.sizes):
        if counts[(*key, size)] < need:
            break
        smallest = size
    return smallest


def _ints(text: str) -> tuple[int, ...]:
    if "-" in text:
        low, high = text.split("-")
        return tuple(range(int(low), int(high) + 1))
    return tuple(int(part) for part in text.split(","))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, seeds in (("cases", CI_SEEDS), ("limits", LIMIT_SEEDS)):
        command = sub.add_parser(name)
        command.add_argument(
            "--seeds", type=_ints, default=seeds, help="e.g. 1-6 or 1,3"
        )
        command.add_argument(
            "--workers",
            type=int,
            default=int(os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS", "4")),
            help="parallel runs (default: PYTEST_XDIST_AUTO_NUM_WORKERS, else 4)",
        )
        command.add_argument("--out", type=Path, help="write every run as a JSON line")
    sub.choices["cases"].add_argument(
        "--match", default="", help="only case ids containing this"
    )
    sub.choices["cases"].add_argument("-v", "--verbose", action="store_true")
    sub.choices["limits"].add_argument(
        "--source", choices=["all", *SOURCES], default="all"
    )
    sub.choices["limits"].add_argument("--speeds", type=_ints, default=LIMIT_SPEEDS_KMH)
    args = parser.parse_args()
    _register_profiles()
    (tally_cases if args.command == "cases" else tally_limits)(args)


if __name__ == "__main__":
    main()
