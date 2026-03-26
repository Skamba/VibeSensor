"""Runtime package – runtime coordination.

Submodules
----------
- ``client_metadata``: persisted/user-assigned client metadata helpers
- ``client_liveness_policy``: live/stale retention rules for tracked clients
- ``client_snapshot_assembler``: locked client-snapshot assembly from registry state
- ``client_snapshot_projection``: pure projection of registry records into API snapshots
- ``background_task_coordinator``: lifecycle-owned task tracking + cancellation
- ``dedup_window``: sliding DATA-sequence dedup tracking
- ``health_snapshot``: runtime health snapshot assembly for HTTP/read-side consumers
- ``health_state``: mutable startup and background-task health state
- ``registry_updates``: DATA-message dedup/reset bookkeeping
- ``processing_loop``: ProcessingLoop (async tick loop + failure tracking)
- ``task_supervisor``: TaskSupervisor (managed restart policy + backoff)
- ``udp_transport_lifecycle``: UdpTransportLifecycle (UDP startup + cleanup seam)
- ``ws_broadcast``: WsBroadcastService (payload assembly + cache)
- ``lifecycle``: LifecycleManager (phase sequencing + graceful shutdown)
- ``rotational_speeds``: Stateless rotational speed payload helpers
"""

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_loop import ProcessingLoopState

__all__ = [
    "ProcessingLoopState",
    "RuntimeHealthState",
]
