"""Runtime package – runtime coordination.

Submodules
----------
- ``builders``: focused service builders
- ``client_metadata``: persisted/user-assigned client metadata helpers
- ``background_task_coordinator``: lifecycle-owned task tracking + cancellation
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
