"""Runtime package – subsystem-based runtime coordination.

Submodules
----------
- ``_state``: top-level runtime assembly
- ``builders``: focused subsystem builders
- ``subsystems``: concern-owned runtime containers
- ``composition``: runtime assembly from explicit subsystems
- ``processing_loop``: ProcessingLoop (async tick loop + failure tracking)
- ``ws_broadcast``: WsBroadcastService (payload assembly + cache)
- ``lifecycle``: LifecycleManager (start/stop + task management)
- ``settings_sync``: Stateless settings applicator functions
- ``rotational_speeds``: Stateless rotational speed payload helpers
"""

from ._state import RuntimeState
from .composition import build_runtime_state
from .health_state import RuntimeHealthState
from .processing_loop import ProcessingLoopState
from .rotational_speeds import (
    build_rotational_speeds_payload as _build_rotational_speeds_payload,
)
from .rotational_speeds import (
    rotational_basis_speed_source as _rotational_basis_speed_source,
)
from .subsystems import (
    RuntimeDiagnosticsSubsystem,
    RuntimeIngressSubsystem,
    RuntimePersistenceSubsystem,
    RuntimeProcessingSubsystem,
    RuntimeRouteServices,
    RuntimeSettingsSubsystem,
    RuntimeUpdateSubsystem,
    RuntimeWebsocketSubsystem,
)
from .ws_broadcast import WsBroadcastCache

__all__ = [
    "RuntimeState",
    "build_runtime_state",
    "RuntimeIngressSubsystem",
    "RuntimeSettingsSubsystem",
    "RuntimeDiagnosticsSubsystem",
    "RuntimePersistenceSubsystem",
    "RuntimeUpdateSubsystem",
    "RuntimeProcessingSubsystem",
    "RuntimeWebsocketSubsystem",
    "RuntimeRouteServices",
    "ProcessingLoopState",
    "RuntimeHealthState",
    "WsBroadcastCache",
    "_build_rotational_speeds_payload",
    "_rotational_basis_speed_source",
]
