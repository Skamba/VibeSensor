"""vibesensor.core — internal domain logic for VibeSensor.

Sub-modules
-----------
strength_bands
    Band definitions (l0–l5), bucket classification, hysteresis constants.
vibration_strength
    Canonical spectrum, floor, peak-RMS, and dB computations.
sensor_units
    Hardware scale-factor helpers (g-per-LSB).
"""
