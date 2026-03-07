"""Runtime package – subsystem-based runtime coordination.

Submodules
----------
- ``_state``: RuntimeState thin coordinator
- ``processing_loop``: ProcessingLoop (async tick loop + failure tracking)
- ``ws_broadcast``: WsBroadcastService (payload assembly + cache)
- ``lifecycle``: LifecycleManager (start/stop + task management)
- ``settings_sync``: Stateless settings applicator functions
- ``rotational_speeds``: Stateless rotational speed payload helpers
"""

from ._state import RuntimeState
from .processing_loop import ProcessingLoopState
from .rotational_speeds import (
    build_rotational_speeds_payload as _build_rotational_speeds_payload,
)
from .rotational_speeds import (
    rotational_basis_speed_source as _rotational_basis_speed_source,
)
from .ws_broadcast import WsBroadcastCache

__all__ = [
    "RuntimeState",
    "ProcessingLoopState",
    "WsBroadcastCache",
    "_build_rotational_speeds_payload",
    "_rotational_basis_speed_source",
]
