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
}  // namespace

ADXL345::ADXL345(SPIClass& spi,
                 int cs_pin,
                 int sck_pin,
                 int miso_pin,
                 int mosi_pin,
                 uint8_t fifo_watermark)
    : spi_(spi),
      cs_pin_(cs_pin),
      sck_pin_(sck_pin),
      miso_pin_(miso_pin),
      mosi_pin_(mosi_pin),
      fifo_watermark_(fifo_watermark),
      available_(false) {}

bool ADXL345::begin() {
  pinMode(cs_pin_, OUTPUT);
  digitalWrite(cs_pin_, HIGH);
  spi_.begin(sck_pin_, miso_pin_, mosi_pin_, cs_pin_);

  uint8_t devid = read_reg(REG_DEVID);
  if (devid != VALUE_DEVID) {
    available_ = false;
    return false;
  }

  // Standby while configuring.
  write_reg(REG_POWER_CTL, 0x00);
  // Full resolution + +/-16g.
  write_reg(REG_DATA_FORMAT, 0x0B);
  // 800 Hz output data rate.
  write_reg(REG_BW_RATE, 0x0D);
  // FIFO stream mode with configurable watermark.
  write_reg(REG_FIFO_CTL, static_cast<uint8_t>(0x80 | (fifo_watermark_ & 0x1F)));
  // Enable watermark interrupt bit (optional, polled in this prototype).
  write_reg(REG_INT_ENABLE, 0x02);
  // Measurement mode.
  write_reg(REG_POWER_CTL, 0x08);

  available_ = true;
  return true;
}

bool ADXL345::available() const {
  return available_;
}

size_t ADXL345::read_samples(int16_t* xyz_interleaved, size_t max_samples) {
  if (!available_ || max_samples == 0 || xyz_interleaved == nullptr) {
    return 0;
  }

  uint8_t fifo_status = read_reg(REG_FIFO_STATUS);
  size_t entries = static_cast<size_t>(fifo_status & 0x3F);
  if (entries == 0) {
    return 0;
  }
  size_t count = entries < max_samples ? entries : max_samples;

  uint8_t raw[6];
  for (size_t i = 0; i < count; ++i) {
    read_multi(REG_DATAX0, raw, sizeof(raw));
    xyz_interleaved[i * 3 + 0] = static_cast<int16_t>(raw[0] | (raw[1] << 8));
    xyz_interleaved[i * 3 + 1] = static_cast<int16_t>(raw[2] | (raw[3] << 8));
    xyz_interleaved[i * 3 + 2] = static_cast<int16_t>(raw[4] | (raw[5] << 8));
  }
  return count;
}

uint8_t ADXL345::read_reg(uint8_t reg) {
  digitalWrite(cs_pin_, LOW);
  spi_.transfer(static_cast<uint8_t>(reg | 0x80));
  uint8_t value = spi_.transfer(0x00);
  digitalWrite(cs_pin_, HIGH);
  return value;
}

void ADXL345::write_reg(uint8_t reg, uint8_t value) {
  digitalWrite(cs_pin_, LOW);
  spi_.transfer(static_cast<uint8_t>(reg & 0x3F));
  spi_.transfer(value);
  digitalWrite(cs_pin_, HIGH);
}

void ADXL345::read_multi(uint8_t reg, uint8_t* out, size_t len) {
  digitalWrite(cs_pin_, LOW);
  spi_.transfer(static_cast<uint8_t>(reg | 0xC0));
  for (size_t i = 0; i < len; ++i) {
    out[i] = spi_.transfer(0x00);
  }
  digitalWrite(cs_pin_, HIGH);
}
