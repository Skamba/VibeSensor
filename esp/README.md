# ESP32 Firmware (LOLIN C3 Mini)

This PlatformIO project streams ADXL345 acceleration data to the Pi over UDP.

## Features

- Wi-Fi station mode to Pi AP (`VibeSensor`)
- HELLO + DATA protocol packets
- Buffered frame queue to reduce sample loss during short Wi-Fi stalls
- UDP command listener for identify blink with ACK response
- ADXL345 SPI driver at 800 Hz
- Synthetic waveform fallback when the sensor is absent

## Build and flash

```bash
cd esp
pio run -t upload
pio device monitor
```

## Configure

Edit constants in `src/main.cpp`:

- `kWifiSsid`, `kWifiPsk`
- `kServerIp`, ports
- `kClientName`
- SPI pin constants (`kSpiSckPin`, `kSpiMisoPin`, `kSpiMosiPin`, `kAdxlCsPin`)

