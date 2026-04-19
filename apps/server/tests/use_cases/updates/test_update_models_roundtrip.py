"""Round-trip and edge-case tests for the updater status msgspec codec."""

from __future__ import annotations

import msgspec
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
    update_status_from_builtins,
    update_status_to_builtins,
)


class TestUpdateJobStatusRoundTrip:
    """Payload round-trip tests for the updater status codec."""

    def test_to_builtins_from_builtins_round_trip(self) -> None:
        """A fully populated status must survive a msgspec builtins round trip."""
        original = UpdateJobStatus(
            state=UpdateState.success,
            phase=UpdatePhase.done,
            started_at=1_700_000_000.0,
            finished_at=1_700_000_060.0,
            last_success_at=1_700_000_060.0,
            ssid="CorpNet",
            issues=[UpdateIssue(phase="installing", message="slow pip", detail="took 90s")],
            log_tail=["line1", "line2", "line3"],
            exit_code=0,
            runtime=UpdateRuntimeDetails(version="1.2.3"),
        )
        restored = update_status_from_builtins(update_status_to_builtins(original))

        assert restored.state == original.state
        assert restored.phase == original.phase
        assert restored.started_at == original.started_at
        assert restored.finished_at == original.finished_at
        assert restored.last_success_at == original.last_success_at
        assert restored.ssid == original.ssid
        assert restored.exit_code == original.exit_code
        assert restored.runtime == UpdateRuntimeDetails(version="1.2.3")
        assert len(restored.issues) == 1
        assert restored.issues[0].phase == "installing"
        assert restored.issues[0].message == "slow pip"
        assert restored.log_tail == ["line1", "line2", "line3"]

    def test_from_payload_empty_yields_idle_defaults(self) -> None:
        """Decoding an empty payload must produce a blank idle status."""
        status = update_status_from_builtins({})

        assert status.state == UpdateState.idle
        assert status.phase == UpdatePhase.idle
        assert status.started_at is None
        assert status.finished_at is None
        assert status.last_success_at is None
        assert status.transport == UpdateTransport.wifi
        assert status.ssid is None
        assert status.issues == []
        assert status.log_tail == []
        assert status.exit_code is None
        assert status.runtime == UpdateRuntimeDetails()

    def test_from_payload_truncates_log_tail_to_50_lines(self) -> None:
        """Decoding must honour the updater log-tail limit of 50 lines."""
        long_tail = [f"log-line-{i}" for i in range(200)]
        data = {
            "state": "failed",
            "phase": "installing",
            "log_tail": long_tail,
        }
        status = update_status_from_builtins(data)

        # Only the last 50 lines should be kept.
        assert len(status.log_tail) == 50
        assert status.log_tail[-1] == "log-line-199"
        assert status.log_tail[0] == "log-line-150"

    def test_to_payload_truncates_log_tail_to_last_50_lines(self) -> None:
        status = UpdateJobStatus(log_tail=[f"log-line-{i}" for i in range(80)])

        payload = update_status_to_builtins(status)

        assert payload["log_tail"] == [f"log-line-{i}" for i in range(30, 80)]

    @pytest.mark.parametrize(
        ("payload", "expected_message"),
        [
            pytest.param({"state": "broken"}, "Invalid enum value 'broken'", id="bad-state"),
            pytest.param({"phase": "broken"}, "Invalid enum value 'broken'", id="bad-phase"),
            pytest.param(
                {"transport": "broken"},
                "Invalid enum value 'broken'",
                id="bad-transport",
            ),
            pytest.param({"state": 7}, r"Expected `str`, got `int`", id="non-string-state"),
        ],
    )
    def test_from_payload_rejects_invalid_enum_values(
        self,
        payload: dict[str, object],
        expected_message: str,
    ) -> None:
        with pytest.raises(msgspec.ValidationError, match=expected_message):
            update_status_from_builtins(payload)

    def test_finished_at_must_not_precede_started_at(self) -> None:
        with pytest.raises(
            ValueError,
            match="finished_at must be greater than or equal to started_at",
        ):
            UpdateJobStatus(
                state=UpdateState.success,
                phase=UpdatePhase.done,
                started_at=20.0,
                finished_at=10.0,
            )

    def test_from_payload_preserves_partial_valid_fields(self) -> None:
        """Malformed nested fields must drop cleanly while valid pieces survive."""
        status = update_status_from_builtins(
            {
                "state": "failed",
                "phase": "installing",
                "transport": "usb_internet",
                "started_at": "10.5",
                "finished_at": "20.5",
                "last_success_at": "7",
                "phase_started_at": "12.25",
                "updated_at": "18",
                "ssid": 123,
                "uplink_interface": ["usb0"],
                "issues": [
                    "bad",
                    {"phase": "downloading", "message": "warn", "detail": 99},
                    {"phase": "installing", "message": "retry"},
                ],
                "log_tail": ["ok", 7, None],
                "exit_code": "5",
                "runtime": {
                    "version": 9,
                    "commit": None,
                    "assets_verified": 1,
                    "has_packaged_static": "true",
                },
            },
        )

        assert status.state == UpdateState.failed
        assert status.phase == UpdatePhase.installing
        assert status.transport == UpdateTransport.usb_internet
        assert status.started_at == 10.5
        assert status.finished_at == 20.5
        assert status.last_success_at == 7.0
        assert status.phase_started_at == 12.25
        assert status.updated_at == 18.0
        assert status.ssid is None
        assert status.uplink_interface is None
        assert status.log_tail == ["ok", "7", "None"]
        assert status.exit_code == 5
        assert status.issues == [
            UpdateIssue(phase="downloading", message="warn", detail="99"),
            UpdateIssue(phase="installing", message="retry", detail=""),
        ]
        assert status.runtime == UpdateRuntimeDetails(
            version="9",
            commit="",
            assets_verified=True,
            has_packaged_static=True,
        )

    def test_from_payload_coerces_legacy_boolish_runtime_flags(self) -> None:
        status = update_status_from_builtins(
            {
                "runtime": {
                    "assets_verified": 1,
                    "has_packaged_static": "true",
                },
            },
        )

        assert status.runtime == UpdateRuntimeDetails(
            assets_verified=True,
            has_packaged_static=True,
        )
