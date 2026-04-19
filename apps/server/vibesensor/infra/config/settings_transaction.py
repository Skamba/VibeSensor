"""Reusable settings update-with-rollback transaction helper.

Owns the generic snapshot → apply → persist → audit → restore-on-failure
sequencing used by all settings update paths.
"""

from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from threading import RLock

from vibesensor.shared.exceptions import PersistenceError
from vibesensor.shared.structured_logging import log_extra


def log_settings_change(
    logger: Logger,
    *,
    action: str,
    before: object,
    after: object,
    **fields: object,
) -> None:
    """Emit a structured settings-change audit record for the supplied logger."""

    logger.info(
        "settings_change",
        extra=log_extra(
            event="settings_change",
            settings_action=action,
            before=before,
            after=after,
            **fields,
        ),
    )


def update_with_rollback[SnapshotT, ResultT](
    *,
    lock: RLock,
    persist: Callable[[], None],
    snapshot: Callable[[], SnapshotT],
    apply: Callable[[SnapshotT], bool],
    restore: Callable[[SnapshotT], None],
    audit_log: Callable[[SnapshotT], None] | None = None,
    after_persist: Callable[[], None] | None = None,
    result: Callable[[], ResultT],
) -> ResultT:
    """Execute an atomic settings update with rollback on persistence failure.

    1. Acquire *lock*.
    2. Take a *snapshot* of the current state.
    3. *apply* the change; if it returns ``False`` (no-op), return *result*
       immediately.
    4. *persist* the updated state.
    5. On ``PersistenceError``, *restore* the previous snapshot and re-raise.
    6. Call *audit_log* (if supplied) after successful persistence.
    7. Call *after_persist* (if supplied) for post-commit side effects.
    8. Return *result*.
    """
    with lock:
        previous = snapshot()
        changed = apply(previous)
        if not changed:
            return result()
        try:
            persist()
        except (PersistenceError, TypeError, AttributeError, KeyError):
            restore(previous)
            raise
        if audit_log is not None:
            audit_log(previous)
        if after_persist is not None:
            after_persist()
        return result()
