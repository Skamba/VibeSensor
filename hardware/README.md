# Hardware Used

This prototype is built with the following hardware:

1. Raspberry Pi 3 A+
2. M5Stack ATOM Lite ESP32 IoT M5 Development Kit
3. M5Stack 3-Axis Digital Accelerometer Unit (ADXL345)
4. M5Stack Atomic Battery Base (200mAh)

## Role Of Each Part

1. Raspberry Pi 3 A+:
Hosts the local Wi-Fi AP, runs the VibeSensor server, and serves the web UI.

2. M5Stack ATOM Lite ESP32:
Runs the firmware that samples accelerometer data and streams UDP telemetry to the Pi.

3. M5Stack ADXL345 Unit:
Provides 3-axis acceleration measurements for vibration analysis.

4. M5Stack Atomic Battery Base (200mAh):
Portable power base for the ATOM Lite node.

## ESP32 <-> ADXL345 4-Pin Unit Cable (Current Firmware Defaults)

The firmware is configured for I2C over the ATOM Lite Unit port:

- `SDA -> GPIO26`
- `SCL -> GPIO32`
- `ADDR = 0x53`
- `Power/GND via the 4-pin Unit cable`

See `esp/README.md` for firmware and pin configuration details.
