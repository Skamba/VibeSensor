"""VibeSensor simulator package.

Module layout:
- ``sim_client.py``: pure simulated sensor state and frame generation
- ``sim_scene.py``: pure multi-sensor road-scene mutation logic
- ``scripted_scenarios.py``: reusable multi-phase simulator run definitions
- ``sim_runtime.py``: asyncio UDP protocols and runtime loops
- ``sim_sender.py``: CLI entry point and top-level orchestration
"""
