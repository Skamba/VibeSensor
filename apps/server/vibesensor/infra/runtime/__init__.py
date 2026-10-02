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
- ``ws_payload_projection``: LiveWsPayloadProjector (builds the live WebSocket payload)
"""
