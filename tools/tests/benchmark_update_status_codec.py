#!/usr/bin/env python3
"""Benchmark the updater status msgspec codec with a representative payload.

Usage::

    python tools/tests/benchmark_update_status_codec.py
    python tools/tests/benchmark_update_status_codec.py --iterations 5000 --rounds 20

Run this on a Raspberry Pi or similar low-power Linux host before copying the
pattern to larger payload boundaries. Output reports payload bytes plus encode
and decode latency in microseconds per operation.
"""

from __future__ import annotations

import argparse
import statistics
import time

from vibesensor.use_cases.updates.models import (
    UpdateIssue,
    UpdateJobStatus,
    UpdatePhase,
    UpdateRuntimeDetails,
    UpdateState,
    UpdateTransport,
)
from vibesensor.use_cases.updates.status import (
    update_status_from_json,
    update_status_to_json,
)

_NOW_S = 1_700_000_120.0


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return ordered[idx]


def _representative_status() -> UpdateJobStatus:
    return UpdateJobStatus(
        state=UpdateState.running,
        phase=UpdatePhase.installing,
        transport=UpdateTransport.usb_internet,
        started_at=1_700_000_000.0,
        last_success_at=1_699_999_500.0,
        phase_started_at=1_700_000_090.0,
        updated_at=1_700_000_110.0,
        uplink_interface="usb0",
        issues=[
            UpdateIssue(
                phase="checking", message="Network slow", detail="retry budget 2"
            ),
            UpdateIssue(
                phase="downloading", message="Wheel cached", detail="cache hit"
            ),
            UpdateIssue(phase="installing", message="Service restart pending"),
        ],
        log_tail=[f"log line {idx:02d}" for idx in range(32)],
        runtime=UpdateRuntimeDetails(
            version="2026.4.19",
            commit="08915691",
            ui_source_hash="ui-source-hash",
            static_assets_hash="static-assets-hash",
            static_build_source_hash="build-source-hash",
            static_build_commit="build-commit",
            assets_verified=True,
            has_packaged_static=True,
        ),
    )


def run_benchmark(*, iterations: int, rounds: int) -> dict[str, float | int]:
    status = _representative_status()
    encode_us: list[float] = []
    decode_us: list[float] = []
    payload_size_bytes = 0

    for _ in range(rounds):
        started = time.perf_counter()
        encoded = b""
        for _iteration in range(iterations):
            encoded = update_status_to_json(status, now_s=_NOW_S)
        encode_us.append((time.perf_counter() - started) * 1_000_000 / iterations)
        payload_size_bytes = len(encoded)

        started = time.perf_counter()
        decoded = status
        for _iteration in range(iterations):
            decoded = update_status_from_json(encoded)
        decode_us.append((time.perf_counter() - started) * 1_000_000 / iterations)

        assert decoded.phase == status.phase
        assert decoded.transport == status.transport
        assert decoded.runtime == status.runtime

    return {
        "payload_size_bytes": payload_size_bytes,
        "encode_median_us": round(statistics.median(encode_us), 2),
        "encode_p95_us": round(_p95(encode_us), 2),
        "decode_median_us": round(statistics.median(decode_us), 2),
        "decode_p95_us": round(_p95(decode_us), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark updater status msgspec codec"
    )
    parser.add_argument(
        "--iterations", type=int, default=5000, help="Ops per timing round"
    )
    parser.add_argument(
        "--rounds", type=int, default=20, help="Number of timing rounds"
    )
    args = parser.parse_args()

    results = run_benchmark(iterations=args.iterations, rounds=args.rounds)
    print(f"payload_size_bytes={results['payload_size_bytes']}")
    print(
        "encode_us_per_op median={encode_median_us:.2f} p95={encode_p95_us:.2f}".format(
            **results
        )
    )
    print(
        "decode_us_per_op median={decode_median_us:.2f} p95={decode_p95_us:.2f}".format(
            **results
        )
    )


if __name__ == "__main__":
    main()
