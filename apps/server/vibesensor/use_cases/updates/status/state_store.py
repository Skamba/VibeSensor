"""Persistent JSON state store for update job status."""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path

import msgspec

from vibesensor.use_cases.updates.models import UpdateJobStatus
from vibesensor.use_cases.updates.status.payload_codec import (
    update_status_from_json,
    update_status_to_json,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "/var/lib/vibesensor/update/update_status.json"


class UpdateStateStore:
    """Load / save :class:`UpdateJobStatus` to a JSON file.

    Writes are atomic (write-to-temp + ``os.replace``) so a crash mid-write
    never corrupts the file. Reads tolerate missing or malformed JSON and
    return ``None`` with a logged warning.
    """

    __slots__ = ("_path",)

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(
            path or os.environ.get("VIBESENSOR_UPDATE_STATE_PATH", DEFAULT_STATE_PATH),
        )

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> UpdateJobStatus | None:
        """Load persisted status. Returns ``None`` if missing or corrupt."""
        if not self._path.is_file():
            return None
        try:
            return update_status_from_json(self._path.read_bytes())
        except (msgspec.DecodeError, msgspec.ValidationError, ValueError, TypeError) as exc:
            LOGGER.warning("Corrupt update state file %s: %s", self._path, exc)
            return None
        except OSError as exc:
            LOGGER.warning("Cannot read update state file %s: %s", self._path, exc)
            return None

    def save(self, status: UpdateJobStatus) -> None:
        """Persist *status* atomically (temp-file + ``os.replace``)."""
        payload = update_status_to_json(status)
        tmp: str | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent),
                prefix=".update_status_",
                suffix=".tmp",
            )
            try:
                os.write(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            Path(tmp).replace(self._path)
        except OSError as exc:
            LOGGER.warning("Failed to persist update state to %s: %s", self._path, exc)
            if tmp is not None:
                with contextlib.suppress(OSError):
                    Path(tmp).unlink()
