"""Round-trip and edge-case tests for UpdateJobStatus serialisation.

These tests cover the ``from_dict`` / ``to_dict`` contract of
:class:`~vibesensor.update.models.UpdateJobStatus`, which is exercised at
runtime when the state-store reloads a persisted snapshot.
"""

from __future__ import annotations

from vibesensor.update.models import UpdateIssue, UpdateJobStatus, UpdatePhase, UpdateState


class TestUpdateJobStatusRoundTrip:
    """Serialisation round-trip tests for UpdateJobStatus."""

    def test_to_dict_from_dict_round_trip(self) -> None:
        """A fully populated status must survive a to_dict → from_dict cycle."""
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
            runtime={"version": "1.2.3"},
        )
        restored = UpdateJobStatus.from_dict(original.to_dict())

        assert restored.state == original.state
        assert restored.phase == original.phase
        assert restored.started_at == original.started_at
        assert restored.finished_at == original.finished_at
        assert restored.last_success_at == original.last_success_at
        assert restored.ssid == original.ssid
        assert restored.exit_code == original.exit_code
        assert restored.runtime == {"version": "1.2.3"}
        assert len(restored.issues) == 1
        assert restored.issues[0].phase == "installing"
        assert restored.issues[0].message == "slow pip"
        assert restored.log_tail == ["line1", "line2", "line3"]

    def test_from_dict_empty_yields_idle_defaults(self) -> None:
        """Calling from_dict with an empty dict must produce a blank idle status."""
        status = UpdateJobStatus.from_dict({})

        assert status.state == UpdateState.idle
        assert status.phase == UpdatePhase.idle
        assert status.started_at is None
        assert status.finished_at is None
        assert status.last_success_at is None
        assert status.ssid == ""
        assert status.issues == []
        assert status.log_tail == []
        assert status.exit_code is None
        assert status.runtime == {}

    def test_from_dict_truncates_log_tail_to_50_lines(self) -> None:
        """from_dict must honour the _LOG_TAIL_LIMIT of 50 lines."""
        long_tail = [f"log-line-{i}" for i in range(200)]
        data = {
            "state": "failed",
            "phase": "installing",
            "log_tail": long_tail,
        }
        status = UpdateJobStatus.from_dict(data)

        # Only the last 50 lines should be kept.
        assert len(status.log_tail) == 50
        assert status.log_tail[-1] == "log-line-199"
        assert status.log_tail[0] == "log-line-150"

    def test_from_dict_ignores_malformed_nested_runtime_payloads(self) -> None:
        """Malformed nested fields must fall back to explicit typed defaults."""
        status = UpdateJobStatus.from_dict(
            {
                "issues": ["bad", {"phase": "downloading", "message": "warn", "detail": 99}],
                "log_tail": ["ok", 7, None],
                "runtime": ["not-a-dict"],
            },
        )

        assert status.runtime == {}
        assert status.log_tail == ["ok", "7", "None"]
        assert status.issues == [UpdateIssue(phase="downloading", message="warn", detail="99")]
