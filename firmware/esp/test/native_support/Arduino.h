#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

using String = std::string;
using byte = uint8_t;

class IPAddress {
 public:
  IPAddress(uint8_t a = 0, uint8_t b = 0, uint8_t c = 0, uint8_t d = 0)
      : octets_{a, b, c, d} {}

  uint8_t operator[](size_t index) const { return octets_[index]; }

  bool operator==(const IPAddress& other) const {
    return octets_[0] == other.octets_[0] && octets_[1] == other.octets_[1] &&
           octets_[2] == other.octets_[2] && octets_[3] == other.octets_[3];
  }

 private:
  uint8_t octets_[4];
};

namespace arduino_test {

inline uint32_t& millis_ref() {
  static uint32_t value = 0;
  return value;
}

inline uint64_t& esp_time_ref() {
  static uint64_t value = 0;
  return value;
}

inline uint64_t& esp_time_step_ref() {
  static uint64_t value = 0;
  return value;
}

inline uint32_t& random_value_ref() {
  static uint32_t value = 0;
  return value;
}

inline void reset_time() {
  millis_ref() = 0;
  esp_time_ref() = 0;
  esp_time_step_ref() = 0;
}

inline void set_millis(uint32_t value) { millis_ref() = value; }

inline void advance_millis(uint32_t delta_ms) { millis_ref() += delta_ms; }

inline void set_esp_time(uint64_t value) { esp_time_ref() = value; }

inline void set_esp_time_step(uint64_t value) { esp_time_step_ref() = value; }

inline uint64_t next_esp_time() {
  const uint64_t current = esp_time_ref();
  esp_time_ref() += esp_time_step_ref();
  return current;
}

inline void set_random_value(uint32_t value) { random_value_ref() = value; }

}  // namespace arduino_test

inline uint32_t millis() { return arduino_test::millis_ref(); }

inline void delay(uint32_t ms) { arduino_test::advance_millis(ms); }

inline uint32_t esp_random() { return arduino_test::random_value_ref(); }

struct HardwareSerial {
  void begin(unsigned long) {}

  template <typename... Args>
  void printf(const char*, Args...) {}
};

static HardwareSerial Serial;

#ifndef PI
#define PI 3.14159265358979323846
#endif
