"""VibeSensor simulator package.

Module layout:
- ``sim_client.py``: pure simulated sensor state and frame generation
- ``sim_scene.py``: pure multi-sensor road-scene mutation logic
- ``scripted_scenario_models.py``: typed simulator scenario dataclasses
- ``scripted_scenario_loader.py``: strict resource loading and validation
- ``scripted_scenario_catalog.py``: scenario registry and lookup helpers
- ``scripted_targeting.py``: target matching and phase-application helpers
- ``scripted_speed_sync.py``: scripted server-speed sync policy helpers
- ``scripted_scenarios.py``: async scripted runner loop
- ``sim_runtime.py``: asyncio UDP protocols and runtime loops
- ``sim_sender.py``: CLI entry point and top-level orchestration
"""
