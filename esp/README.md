# ESP32 Firmware (ATOM ESP32-PICO)

This PlatformIO project streams ADXL345 acceleration data to the Pi over UDP.
Default PlatformIO environment targets `m5stack-atom` (ATOM ESP32-PICO).

## Features

- Wi-Fi station mode to Pi AP (`VibeSensor`)
- HELLO + DATA protocol packets
- Buffered frame queue to reduce sample loss during short Wi-Fi stalls
- UDP command listener for identify blink with ACK response
- Identify command triggers RGB LED wave animation on ATOM LEDs
- ADXL345 I2C driver at 800 Hz with error-checked initialisation
- Synthetic waveform fallback when the sensor is absent or I2C fails

## Error handling

- **I2C init**: Every register write during `ADXL345::begin()` is validated;
  if any write fails the sensor is marked unavailable and the firmware falls
  back to synthetic waveform generation.
- **I2C reads**: `read_reg()` and `read_multi()` return zeros on bus errors.
  This is safe because the caller (`read_samples()`) only processes FIFO
  entries reported by the hardware status register.
- **Wi-Fi**: Automatic reconnect with configurable retry interval
  (`kWifiRetryIntervalMs`).

## Build and flash

```bash
cd esp
pio run -t upload
pio device monitor
```

## Configure

Edit constants in `src/main.cpp`:

- `kWifiSsid`, `kWifiPsk` — must match `pi/config.yaml` `ap.ssid` / `ap.psk`
- `kServerIp`, `kServerDataPort`, `kServerControlPort` — must match `pi/config.yaml` `udp.*`
- `kClientName`
- I2C settings (`kI2cSdaPin`, `kI2cSclPin`, `kAdxlI2cAddr`)

Default ATOM Lite Unit-port mapping used in this repo (4-pin Unit cable):

- `SDA = GPIO26`
- `SCL = GPIO32`
- `ADDR = 0x53`
