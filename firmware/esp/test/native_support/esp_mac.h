#pragma once

#include <cstdint>
#include <cstring>

#include "esp_err.h"

typedef enum {
  ESP_MAC_WIFI_STA,
} esp_mac_type_t;

namespace arduino_test {

inline esp_err_t& read_mac_result() {
  static esp_err_t result = ESP_OK;
  return result;
}

inline uint8_t* station_mac() {
  static uint8_t mac[6] = {0xD0, 0x5A, 0x00, 0x00, 0x00, 0x01};
  return mac;
}

inline void set_station_mac(const uint8_t mac[6], esp_err_t result = ESP_OK) {
  memcpy(station_mac(), mac, 6);
  read_mac_result() = result;
}

}  // namespace arduino_test

inline esp_err_t esp_read_mac(uint8_t* mac, esp_mac_type_t) {
  if (arduino_test::read_mac_result() != ESP_OK) {
    return arduino_test::read_mac_result();
  }
  memcpy(mac, arduino_test::station_mac(), 6);
  return ESP_OK;
}
