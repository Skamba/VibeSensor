"""Runtime package – subsystem-based runtime coordination.

Submodules
----------
- ``state``: top-level runtime assembly (RuntimeState) and subsystem containers
- ``builders``: focused subsystem builders
- ``processing_loop``: ProcessingLoop (async tick loop + failure tracking)
- ``ws_broadcast``: WsBroadcastService (payload assembly + cache)
- ``lifecycle``: LifecycleManager (start/stop + task management)
- ``rotational_speeds``: Stateless rotational speed payload helpers
"""

from .health_state import RuntimeHealthState
from .processing_loop import ProcessingLoopState
from .rotational_speeds import (
    build_rotational_speeds_payload as _build_rotational_speeds_payload,
)
from .rotational_speeds import (
    rotational_basis_speed_source as _rotational_basis_speed_source,
)
from .state import (
    RuntimeIngressSubsystem,
    RuntimePersistenceSubsystem,
    RuntimeProcessingSubsystem,
    RuntimeSettingsSubsystem,
    RuntimeState,
    RuntimeWebsocketSubsystem,
)
from .ws_broadcast import WsBroadcastCache

__all__ = [
    "ProcessingLoopState",
    "RuntimeHealthState",
    "RuntimeIngressSubsystem",
    "RuntimePersistenceSubsystem",
    "RuntimeProcessingSubsystem",
    "RuntimeSettingsSubsystem",
    "RuntimeState",
    "RuntimeWebsocketSubsystem",
    "WsBroadcastCache",
    "_build_rotational_speeds_payload",
    "_rotational_basis_speed_source",
]
