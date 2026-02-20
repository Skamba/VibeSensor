# ESP32 Firmware

PlatformIO firmware for M5Stack ATOM Lite (ESP32-PICO) that reads an ADXL345
accelerometer at 800 Hz and streams samples to the Pi server over UDP.

## Features

- Wi-Fi station mode to Pi AP (`VibeSensor`)
- HELLO + DATA protocol packets
- Buffered frame queue to reduce sample loss during short Wi-Fi stalls
- UDP command listener for identify blink with ACK response
- Identify command triggers RGB LED wave animation on ATOM LEDs
- ADXL345 I2C driver at 800 Hz with error-checked initialisation
- Synthetic waveform fallback when the sensor is absent or I2C fails

## Project Structure

```
firmware/esp/
├── src/
│   └── main.cpp              Firmware entry point
├── lib/
│   ├── adxl345/              I2C driver for ADXL345 accelerometer
│   └── vibesensor_proto/     Protocol packet builder
├── include/
│   ├── vibesensor_network.local.example.h   Network override template
│   └── vibesensor_network.local.h           Local overrides (gitignored)
└── platformio.ini            PlatformIO build config
```

## Error Handling

- **I2C init**: Every register write during `ADXL345::begin()` is validated;
  if any write fails the sensor is marked unavailable and the firmware falls
  back to synthetic waveform generation.
- **I2C reads**: `read_reg()` and `read_multi()` return zeros on bus errors.
  This is safe because the caller (`read_samples()`) only processes FIFO
  entries reported by the hardware status register.
- **Wi-Fi**: Automatic reconnect with configurable retry interval
  (`kWifiRetryIntervalMs`).

## Build and Flash

```bash
cd firmware/esp
pio run -t upload
pio device monitor
```

## Configure

Default network target already matches the Pi hotspot configuration:

- SSID `VibeSensor`
- PSK empty (open test AP)
- Server IP `10.4.0.1`
- UDP ports `9000/9001`

Optional override via local file (recommended for non-default networks):

1. Copy `include/vibesensor_network.local.example.h` to `include/vibesensor_network.local.h`
2. Edit:
  - `VIBESENSOR_WIFI_SSID`
  - `VIBESENSOR_WIFI_PSK`
  - `VIBESENSOR_SERVER_IP_OCTETS`
3. Build and flash again

`include/vibesensor_network.local.h` is gitignored; do not commit secrets.

Other firmware settings (client name / I2C) remain in `src/main.cpp`:

- `kClientName`
- I2C settings (`kI2cSdaPin`, `kI2cSclPin`, `kAdxlI2cAddr`)

Default ATOM Lite Unit-port mapping used in this repo (4-pin Unit cable):

- `SDA = GPIO26`
- `SCL = GPIO32`
- `ADDR = 0x53`
