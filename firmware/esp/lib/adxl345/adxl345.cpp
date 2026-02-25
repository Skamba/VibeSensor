#include "adxl345.h"

namespace {
constexpr uint8_t REG_DEVID = 0x00;
constexpr uint8_t REG_BW_RATE = 0x2C;
constexpr uint8_t REG_POWER_CTL = 0x2D;
constexpr uint8_t REG_INT_ENABLE = 0x2E;
constexpr uint8_t REG_DATA_FORMAT = 0x31;
constexpr uint8_t REG_DATAX0 = 0x32;
constexpr uint8_t REG_FIFO_CTL = 0x38;
constexpr uint8_t REG_FIFO_STATUS = 0x39;

constexpr uint8_t VALUE_DEVID = 0xE5;
constexpr uint32_t kI2cClockHz = 400000;
}  // namespace

ADXL345::ADXL345(TwoWire& wire,
                 uint8_t i2c_addr,
                 int sda_pin,
                 int scl_pin,
                 uint8_t fifo_watermark)
    : wire_(wire),
      i2c_addr_(i2c_addr),
      sda_pin_(sda_pin),
      scl_pin_(scl_pin),
      fifo_watermark_(fifo_watermark),
      available_(false) {}

bool ADXL345::begin() {
  wire_.begin(sda_pin_, scl_pin_);
  wire_.setClock(kI2cClockHz);

  uint8_t devid = 0;
  if (!read_reg(REG_DEVID, &devid)) {
    available_ = false;
    return false;
  }
  if (devid != VALUE_DEVID) {
    available_ = false;
    return false;
  }

  // Standby while configuring.
  if (!write_reg(REG_POWER_CTL, 0x00)) { available_ = false; return false; }
  // Full resolution + +/-16g.
  if (!write_reg(REG_DATA_FORMAT, 0x0B)) { available_ = false; return false; }
  // 400 Hz output data rate.
  if (!write_reg(REG_BW_RATE, 0x0C)) { available_ = false; return false; }
  // FIFO stream mode with configurable watermark.
  if (!write_reg(REG_FIFO_CTL, static_cast<uint8_t>(0x80 | (fifo_watermark_ & 0x1F)))) {
    available_ = false; return false;
  }
  // Enable watermark interrupt bit (optional, polled in this prototype).
  if (!write_reg(REG_INT_ENABLE, 0x02)) { available_ = false; return false; }
  // Measurement mode.
  if (!write_reg(REG_POWER_CTL, 0x08)) { available_ = false; return false; }

  available_ = true;
  return true;
}

bool ADXL345::available() const {
  return available_;
}

size_t ADXL345::read_samples(int16_t* xyz_interleaved,
                             size_t max_samples,
                             bool* had_io_error,
                             bool* fifo_truncated) {
  if (had_io_error != nullptr) {
    *had_io_error = false;
  }
  if (fifo_truncated != nullptr) {
    *fifo_truncated = false;
  }
  if (!available_ || max_samples == 0 || xyz_interleaved == nullptr) {
    return 0;
  }

  uint8_t fifo_status = 0;
  if (!read_reg(REG_FIFO_STATUS, &fifo_status)) {
    if (had_io_error != nullptr) {
      *had_io_error = true;
    }
    return 0;
  }
  size_t entries = static_cast<size_t>(fifo_status & 0x3F);
  if (entries == 0) {
    return 0;
  }
  size_t count = entries < max_samples ? entries : max_samples;
  if (fifo_truncated != nullptr && entries > max_samples) {
    *fifo_truncated = true;
  }

  // Read each FIFO entry individually (6 bytes per entry).
  // The ADXL345 FIFO pops one entry per complete 6-byte read of
  // registers 0x32-0x37.  A single I2C transaction requesting more
  // than 6 bytes reads past the data registers into FIFO_CTL/STATUS
  // and the rest of the register map — corrupting every sample after
  // the first.
  //
  // The datasheet requires >= 5 µs between the end of one data-register
  // read (transition past 0x37) and the start of the next FIFO read or
  // FIFO_STATUS read, so the FIFO entry is fully popped.
  uint8_t raw[6];
  for (size_t i = 0; i < count; ++i) {
    if (i > 0) {
      delayMicroseconds(5);
    }
    if (!read_multi(REG_DATAX0, raw, 6)) {
      if (had_io_error != nullptr) {
        *had_io_error = true;
      }
      return i;
    }
    const size_t out = i * 3;
    xyz_interleaved[out + 0] = static_cast<int16_t>(raw[0] | (raw[1] << 8));
    xyz_interleaved[out + 1] = static_cast<int16_t>(raw[2] | (raw[3] << 8));
    xyz_interleaved[out + 2] = static_cast<int16_t>(raw[4] | (raw[5] << 8));
  }
  return count;
}

bool ADXL345::read_reg(uint8_t reg, uint8_t* out_value) {
  wire_.beginTransmission(i2c_addr_);
  wire_.write(reg);
  if (wire_.endTransmission(false) != 0) {
    return false;
  }
  if (wire_.requestFrom(i2c_addr_, static_cast<size_t>(1), true) != 1) {
    return false;
  }
  if (out_value != nullptr) {
    *out_value = static_cast<uint8_t>(wire_.read());
  } else {
    (void)wire_.read();
  }
  return true;
}

bool ADXL345::write_reg(uint8_t reg, uint8_t value) {
  wire_.beginTransmission(i2c_addr_);
  wire_.write(reg);
  wire_.write(value);
  return wire_.endTransmission(true) == 0;
}

bool ADXL345::read_multi(uint8_t reg, uint8_t* out, size_t len) {
  wire_.beginTransmission(i2c_addr_);
  wire_.write(reg);
  if (wire_.endTransmission(false) != 0) {
    memset(out, 0, len);
    return false;
  }
  size_t got = wire_.requestFrom(i2c_addr_, len, true);
  for (size_t i = 0; i < len; ++i) {
    if (i < got) {
      out[i] = wire_.read();
    } else {
      out[i] = 0;
    }
  }
  return got == len;
}
