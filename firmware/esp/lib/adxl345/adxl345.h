#pragma once

#include <Arduino.h>
#include <Wire.h>

// BW_RATE code of a supported output data rate (25 Hz x 2^n up to 3200 Hz), or 0.
constexpr uint8_t adxl345_rate_code(uint32_t rate_hz) {
  return rate_hz == 25     ? 0x08
         : rate_hz == 50   ? 0x09
         : rate_hz == 100  ? 0x0A
         : rate_hz == 200  ? 0x0B
         : rate_hz == 400  ? 0x0C
         : rate_hz == 800  ? 0x0D
         : rate_hz == 1600 ? 0x0E
         : rate_hz == 3200 ? 0x0F
                           : 0;
}

class ADXL345 {
 public:
  enum class FailureKind : uint8_t {
    kNone = 0,
    kFifoStatusRead = 1,
    kFifoDataRead = 2,
    kDeviceIdRead = 3,
    kDeviceIdMismatch = 4,
    kConfigWrite = 5,
  };

  // The FIFO holds 32 samples; one more waits in the output registers.
  static constexpr size_t kMaxFifoEntries = 33;

  // Output data rate code for BW_RATE (0x0D = 800 Hz), see adxl345_rate_code().
  ADXL345(TwoWire& wire, uint8_t i2c_addr, int sda_pin, int scl_pin, uint8_t rate_code);

  bool begin(FailureKind* failure_kind = nullptr);
  bool recover_bus(FailureKind* failure_kind = nullptr);
  bool available() const;

  // Reads how many samples the FIFO holds (FIFO_STATUS entries, 0..33).
  bool read_fifo_entries(size_t* entries, FailureKind* failure_kind = nullptr);

  // Pops `count` FIFO entries into XYZ triples. Returns the number read; fewer
  // than `count` only on an I2C failure (reported through failure_kind).
  size_t read_fifo_samples(int16_t* xyz_interleaved,
                           size_t count,
                           FailureKind* failure_kind = nullptr);

 private:
  TwoWire& wire_;
  uint8_t i2c_addr_;
  int sda_pin_;
  int scl_pin_;
  uint8_t rate_code_;
  bool available_;

  bool read_reg(uint8_t reg, uint8_t* out_value);
  bool write_reg(uint8_t reg, uint8_t value);
  bool read_multi(uint8_t reg, uint8_t* out, size_t len);
};
