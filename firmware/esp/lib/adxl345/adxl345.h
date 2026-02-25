#pragma once

#include <Arduino.h>
#include <Wire.h>

class ADXL345 {
 public:
  ADXL345(TwoWire& wire,
          uint8_t i2c_addr,
          int sda_pin,
          int scl_pin,
          uint8_t fifo_watermark = 16);

  bool begin();
  bool available() const;

  // Reads up to max_samples from FIFO and writes XYZ triples into xyz_interleaved.
  // Returns number of samples written.
  size_t read_samples(int16_t* xyz_interleaved,
                      size_t max_samples,
                      bool* had_io_error = nullptr,
                      bool* fifo_truncated = nullptr);

 private:
  TwoWire& wire_;
  uint8_t i2c_addr_;
  int sda_pin_;
  int scl_pin_;
  uint8_t fifo_watermark_;
  bool available_;

  bool read_reg(uint8_t reg, uint8_t* out_value);
  bool write_reg(uint8_t reg, uint8_t value);
  bool read_multi(uint8_t reg, uint8_t* out, size_t len);
};
