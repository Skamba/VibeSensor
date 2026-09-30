"""Runtime package – runtime coordination.

Submodules
----------
- ``background_tasks``: BackgroundTaskCoordinator (task group tracking + cancellation)
  and TaskSupervisor (managed restart policy + backoff)
- ``client_metadata``: persisted/user-assigned client names
- ``health_snapshot``: runtime health snapshot assembly for HTTP/read-side consumers
- ``health_state``: mutable startup and background-task health state
- ``lifecycle``: LifecycleManager (startup phases, UDP transport, graceful shutdown)
- ``processing_loop``: ProcessingLoop plus its state, tick runner, and failure policy
- ``registry``: ClientRegistry (per-client bookkeeping, dedup, liveness, snapshots)
- ``rotational_speeds``: stateless rotational speed payload helpers
- ``ws_broadcast``: WsBroadcastService (broadcast tick/cache + selected-client assembly)
- ``ws_payload_projection``: LiveWsPayloadProjector (live broadcast payload projection)
"""

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_loop import ProcessingLoopState

__all__ = [
    "ProcessingLoopState",
    "RuntimeHealthState",
]
