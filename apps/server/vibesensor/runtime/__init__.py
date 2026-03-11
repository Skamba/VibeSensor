"""Runtime package – runtime coordination.

Submodules
----------
- ``state``: top-level runtime assembly (RuntimeState)
- ``builders``: focused service builders
- ``processing_loop``: ProcessingLoop (async tick loop + failure tracking)
- ``ws_broadcast``: WsBroadcastService (payload assembly + cache)
- ``lifecycle``: LifecycleManager (start/stop + task management)
- ``rotational_speeds``: Stateless rotational speed payload helpers
"""

from .health_state import RuntimeHealthState
from .processing_loop import ProcessingLoopState
from .state import RuntimeState

__all__ = [
    "ProcessingLoopState",
    "RuntimeHealthState",
    "RuntimeState",
]
