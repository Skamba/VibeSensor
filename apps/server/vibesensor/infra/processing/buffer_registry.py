from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from threading import RLock

import numpy as np

from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.models import FloatArray, ProcessorConfig


class ClientBufferRegistry:
    """Own per-client buffer objects, epochs, and lock acquisition protocol."""

    def __init__(self, config: ProcessorConfig) -> None:
        self._initial_capacity = config.max_samples
        self.buffers: dict[str, ClientBuffer] = {}
        self._client_locks: dict[str, RLock] = {}
        self._next_buffer_epoch = 0
        self.lock = RLock()

    def _get_or_create_unlocked(self, client_id: str) -> ClientBuffer:
        buf = self.buffers.get(client_id)
        if buf is None:
            data: FloatArray = np.zeros((3, self._initial_capacity), dtype=np.float32)
            buf = ClientBuffer(
                data=data,
                capacity=self._initial_capacity,
                buffer_epoch=self._next_buffer_epoch,
            )
            self._next_buffer_epoch += 1
            self.buffers[client_id] = buf
            self._client_locks[client_id] = RLock()
        return buf

    def _client_lock_unlocked(self, client_id: str) -> RLock:
        client_lock = self._client_locks.get(client_id)
        if client_lock is None:
            client_lock = RLock()
            self._client_locks[client_id] = client_lock
        return client_lock

    @contextmanager
    def locked_client_buffer(
        self,
        client_id: str,
        *,
        create: bool = False,
    ) -> Iterator[ClientBuffer | None]:
        """Yield one client buffer while holding only that client's lock."""
        client_lock: RLock | None = None
        buf: ClientBuffer | None = None
        with self.lock:
            if create:
                buf = self._get_or_create_unlocked(client_id)
            else:
                buf = self.buffers.get(client_id)
            if buf is not None:
                client_lock = self._client_lock_unlocked(client_id)
                client_lock.acquire()
        try:
            yield buf
        finally:
            if client_lock is not None:
                client_lock.release()

    @contextmanager
    def locked_client_buffers(self, client_ids: Iterable[str]) -> Iterator[dict[str, ClientBuffer]]:
        """Yield the requested existing client buffers while holding their locks."""
        locked_buffers: dict[str, ClientBuffer] = {}
        acquired_locks: list[RLock] = []
        with self.lock:
            for client_id in dict.fromkeys(client_ids):
                buf = self.buffers.get(client_id)
                if buf is None:
                    continue
                client_lock = self._client_lock_unlocked(client_id)
                client_lock.acquire()
                acquired_locks.append(client_lock)
                locked_buffers[client_id] = buf
        try:
            yield locked_buffers
        finally:
            for client_lock in reversed(acquired_locks):
                client_lock.release()

    def evict_clients(self, keep_client_ids: set[str]) -> None:
        with self.lock:
            stale_ids = [
                client_id for client_id in self.buffers if client_id not in keep_client_ids
            ]
            for client_id in stale_ids:
                # Detach stale client state under the registry lock only. Threads
                # already working with a stale client's buffer can finish against
                # the detached objects while new lookups will either see no buffer
                # or create a fresh one without blocking on stale locks.
                self.buffers.pop(client_id, None)
                self._client_locks.pop(client_id, None)
