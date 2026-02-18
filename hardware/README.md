# Hardware

Bill of materials for the VibeSensor prototype.

## Components

| # | Part | Role |
|---|------|------|
| 1 | Raspberry Pi 3 A+ | Wi-Fi AP, server, web UI host |
| 2 | M5Stack ATOM Lite ESP32 | Sensor node — samples accelerometer, streams UDP |
| 3 | M5Stack ADXL345 3-Axis Accelerometer Unit | Vibration measurement (3-axis, 800 Hz) |
| 4 | M5Stack Atomic Battery Base (200 mAh) | Portable power for the ATOM Lite node |

Multiple sensor nodes (items 2-4) can connect to a single Pi simultaneously.

## Wiring

The ESP32 connects to the ADXL345 via I2C over the ATOM Lite 4-pin Unit port:

| Signal | GPIO |
|--------|------|
| SDA | GPIO26 |
| SCL | GPIO32 |
| ADDR | 0x53 |
| Power/GND | Via 4-pin Unit cable |

No soldering required — the M5Stack components connect with plug-in cables.

See [esp/README.md](../esp/README.md) for firmware configuration.
