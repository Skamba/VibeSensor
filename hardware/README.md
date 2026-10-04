# Hardware

Bill of materials for the VibeSensor prototype.

## Components

| # | Part | Role |
|---|------|------|
| 1 | Raspberry Pi 3 A+ | Wi-Fi AP, server, web UI host |
| 2 | M5Stack ATOM Lite ESP32 | Sensor node — samples accelerometer, streams UDP |
| 3 | M5Stack Accel Unit (ADXL345) | Vibration measurement (3-axis, 800 Hz) |
| 4 | M5Stack Atomic Battery Base (200 mAh) | Portable power for the ATOM Lite node |

Multiple sensor nodes (items 2-4) can connect to a single Pi simultaneously.

## Speed source (pick one)

VibeSensor needs a live road speed to match vibrations to wheel, driveline and
engine orders. The Pi has no built-in GPS. Choose one:

| Part | Gives | Notes |
|------|-------|-------|
| Bluetooth ELM327 OBD-II adapter (recommended) | Live speed and measured engine RPM | **Bluetooth only.** Wi-Fi OBD dongles cannot connect: the Pi's Wi-Fi runs the sensor hotspot. Pair it on the Speed source tab. |
| USB GPS receiver (u-blox based, gpsd-compatible) | Live speed; engine RPM is estimated assuming top gear (or D) | The Pi 3 A+ has a single USB port, which the USB internet uplink also uses. |

Without either, a speed can be typed in, but then the run only holds at
exactly that speed and the results are hedged. The Speed source tab in the web
UI shows the same comparison.

## Wiring

The ESP32 connects to the ADXL345 via I2C over the ATOM Lite 4-pin Unit port:

| Signal | GPIO |
|--------|------|
| SDA | GPIO26 |
| SCL | GPIO32 |
| ADDR | 0x53 |
| Power/GND | Via 4-pin Unit cable |

No soldering required — the M5Stack components connect with plug-in cables.

See [firmware/esp/README.md](../firmware/esp/README.md) for firmware configuration.
