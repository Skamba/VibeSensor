"""Runtime package – runtime coordination.

Submodules
----------
- ``builders``: focused service builders
- ``processing_loop``: ProcessingLoop (async tick loop + failure tracking)
- ``ws_broadcast``: WsBroadcastService (payload assembly + cache)
- ``lifecycle``: LifecycleManager (start/stop + task management)
- ``rotational_speeds``: Stateless rotational speed payload helpers
"""

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_loop import ProcessingLoopState

__all__ = [
    "ProcessingLoopState",
    "RuntimeHealthState",
]
