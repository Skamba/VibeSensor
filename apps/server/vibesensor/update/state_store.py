"""Persistent state store for update job status.

Writes are atomic (write-to-temp + ``os.replace``) so a crash mid-write
never corrupts the file.  Reads tolerate missing or malformed JSON and
return ``None`` with a logged warning.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from .models import UpdateJobStatus

LOGGER = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "/var/lib/vibesensor/update/update_status.json"


class UpdateStateStore:
    """Load / save :class:`UpdateJobStatus` to a JSON file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(
            path or os.environ.get("VIBESENSOR_UPDATE_STATE_PATH", DEFAULT_STATE_PATH)
        )

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> UpdateJobStatus | None:
        """Load persisted status.  Returns ``None`` if missing or corrupt."""
        if not self._path.is_file():
            return None
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return UpdateJobStatus.from_dict(data)
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            LOGGER.warning("Corrupt update state file %s: %s", self._path, exc)
            return None
        except OSError as exc:
            LOGGER.warning("Cannot read update state file %s: %s", self._path, exc)
            return None

    def save(self, status: UpdateJobStatus) -> None:
        """Persist *status* atomically (temp-file + ``os.replace``)."""
        data = status.to_dict()
        payload = json.dumps(data, indent=2, default=str) + "\n"
        tmp: str | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent),
                prefix=".update_status_",
                suffix=".tmp",
            )
            try:
                os.write(fd, payload.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, str(self._path))
        except OSError as exc:
            LOGGER.warning("Failed to persist update state to %s: %s", self._path, exc)
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
