"""Rollback candidate selection and execution for updater-managed server wheels."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.artifact_validation import WheelArtifactValidator
from vibesensor.use_cases.updates.rollback_snapshot import (
    RollbackSnapshotMetadata,
    RollbackSnapshotStore,
)
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wheel_installation import WheelInstallExecutor


def _rollback_wheel_version(wheel_path: Path) -> str:
    """Extract the version token from a rollback wheel filename when present."""

    wheel_parts = wheel_path.stem.split("-")
    return wheel_parts[1] if len(wheel_parts) >= 2 else ""


@dataclass(frozen=True, slots=True)
class RollbackCandidate:
    wheel_path: Path
    expected_version: str
    expected_sha256: str | None
    primary: bool


class RollbackExecutor:
    """Select a rollback candidate and reinstall it after update failure."""

    __slots__ = (
        "_rollback_dir",
        "_rollback_snapshots",
        "_tracker",
        "_wheel_install_executor",
        "_wheel_validator",
    )

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        rollback_dir: Path,
        rollback_snapshots: RollbackSnapshotStore,
        wheel_validator: WheelArtifactValidator,
        wheel_install_executor: WheelInstallExecutor,
    ) -> None:
        self._tracker = tracker
        self._rollback_dir = rollback_dir
        self._rollback_snapshots = rollback_snapshots
        self._wheel_validator = wheel_validator
        self._wheel_install_executor = wheel_install_executor

    async def rollback(self) -> bool:
        self._tracker.log("Rolling back to previous version...")
        candidate = self._select_candidate()
        if candidate is None:
            return False
        return await self._wheel_install_executor.install_rollback_wheel(
            candidate.wheel_path,
            expected_version=candidate.expected_version,
        )

    def _select_candidate(self) -> RollbackCandidate | None:
        candidates = self._candidate_list()
        for index, candidate in enumerate(candidates):
            if not candidate.wheel_path.is_file():
                if index == 0 and candidate.primary:
                    self._tracker.add_issue(
                        "installing",
                        "Rollback snapshot wheel is missing",
                        f"metadata expected {candidate.wheel_path}",
                    )
                continue
            context = "Rollback wheel" if candidate.primary else "Fallback rollback wheel"
            if not self._wheel_validator.validate_wheel(
                candidate.wheel_path,
                phase="installing",
                context=context,
                fatal=False,
                expected_sha256=candidate.expected_sha256,
            ):
                if candidate.primary and len(candidates) > 1:
                    self._tracker.log(
                        "Primary rollback snapshot could not be used; trying older rollback wheel",
                    )
                continue
            if not candidate.primary:
                self._tracker.log(f"Using fallback rollback wheel {candidate.wheel_path.name}")
            return candidate
        return None

    def _candidate_list(self) -> list[RollbackCandidate]:
        metadata = self._rollback_snapshots.load_metadata()
        rollback_wheels = self._rollback_snapshots.rollback_wheels()
        if not rollback_wheels:
            self._tracker.add_issue("installing", "No rollback wheel available")
            return []

        candidates: list[RollbackCandidate] = []
        if metadata is not None:
            candidates.extend(self._metadata_candidates(metadata, rollback_wheels=rollback_wheels))
            return candidates

        self._tracker.log(
            "Rollback metadata missing; falling back to newest rollback wheel without checksum pin",
        )
        for fallback_wheel in rollback_wheels:
            candidates.append(
                RollbackCandidate(
                    wheel_path=fallback_wheel,
                    expected_version=_rollback_wheel_version(fallback_wheel),
                    expected_sha256=None,
                    primary=False,
                ),
            )
        return candidates

    def _metadata_candidates(
        self,
        metadata: RollbackSnapshotMetadata,
        *,
        rollback_wheels: list[Path],
    ) -> list[RollbackCandidate]:
        candidates = [
            RollbackCandidate(
                wheel_path=self._rollback_dir / metadata.wheel_name,
                expected_version=metadata.version,
                expected_sha256=metadata.sha256,
                primary=True,
            ),
        ]
        for fallback_wheel in rollback_wheels:
            if fallback_wheel.name == metadata.wheel_name:
                continue
            candidates.append(
                RollbackCandidate(
                    wheel_path=fallback_wheel,
                    expected_version=_rollback_wheel_version(fallback_wheel),
                    expected_sha256=None,
                    primary=False,
                ),
            )
        return candidates
