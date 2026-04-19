"""Explicit pytest-benchmark suite for updater-status codec hot path."""

from __future__ import annotations

import pytest

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
            UpdateIssue(phase="checking", message="Network slow", detail="retry budget 2"),
            UpdateIssue(phase="downloading", message="Wheel cached", detail="cache hit"),
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


@pytest.mark.benchmark(group="update-status-codec")
def test_update_status_encode_benchmark(benchmark) -> None:
    status = _representative_status()
    encoded = benchmark(lambda: update_status_to_json(status, now_s=_NOW_S))

    assert len(encoded) > 0


@pytest.mark.benchmark(group="update-status-codec")
def test_update_status_decode_benchmark(benchmark) -> None:
    encoded = update_status_to_json(_representative_status(), now_s=_NOW_S)
    decoded = benchmark(lambda: update_status_from_json(encoded))

    assert decoded.phase == UpdatePhase.installing
    assert decoded.transport == UpdateTransport.usb_internet
    assert decoded.runtime == UpdateRuntimeDetails(
        version="2026.4.19",
        commit="08915691",
        ui_source_hash="ui-source-hash",
        static_assets_hash="static-assets-hash",
        static_build_source_hash="build-source-hash",
        static_build_commit="build-commit",
        assets_verified=True,
        has_packaged_static=True,
    )
