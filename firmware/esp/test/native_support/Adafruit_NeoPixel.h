#pragma once

#include <cstdint>
#include <vector>

using neoPixelType = uint16_t;

constexpr neoPixelType NEO_GRB = 0x01;
constexpr neoPixelType NEO_KHZ800 = 0x02;

class Adafruit_NeoPixel {
 public:
  Adafruit_NeoPixel(uint16_t n, int16_t, neoPixelType)
      : pixels_(n, 0) {}

  Adafruit_NeoPixel() = default;

  bool begin() {
    begun_ = true;
    return true;
  }

  void clear() {
    for (size_t i = 0; i < pixels_.size(); ++i) {
      pixels_[i] = 0;
    }
  }

  void show() { show_count_++; }

  void setPixelColor(uint16_t index, uint32_t color) {
    if (index < pixels_.size()) {
      pixels_[index] = color;
    }
  }

  uint32_t getPixelColor(uint16_t index) const {
    return index < pixels_.size() ? pixels_[index] : 0;
  }

  uint32_t Color(uint8_t r, uint8_t g, uint8_t b) const {
    return (static_cast<uint32_t>(r) << 16) | (static_cast<uint32_t>(g) << 8) |
           static_cast<uint32_t>(b);
  }

  bool begun() const { return begun_; }

  uint32_t show_count() const { return show_count_; }

 private:
  std::vector<uint32_t> pixels_;
  bool begun_ = false;
  uint32_t show_count_ = 0;
};
