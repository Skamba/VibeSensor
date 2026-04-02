"""VibeSensor simulator package.

Module layout:
- ``sim_client.py``: pure simulated sensor state and frame generation
- ``sim_scene.py``: pure multi-sensor road-scene mutation logic
- ``scripted_scenario_library.py``: scripted scenario schema and large registry data
- ``scripted_targeting.py``: target matching and phase-application helpers
- ``scripted_speed_sync.py``: scripted server-speed sync policy helpers
- ``scripted_scenarios.py``: async scripted runner loop
- ``sim_runtime.py``: asyncio UDP protocols and runtime loops
- ``sim_sender.py``: CLI entry point and top-level orchestration
"""
