#pragma once

#include <Arduino.h>

#include "runtime_status.h"

namespace vibesensor::runtime {

// Hotspot credentials the Pi flasher writes to NVS (Preferences namespace
// "vs_wifi", keys "ssid"/"psk"); the compile-time values are the fallback.
constexpr const char* kWifiPrefsNamespace = "vs_wifi";
constexpr size_t kWifiSsidMaxLen = 32;
constexpr size_t kWifiPskMaxLen = 64;

struct WifiState {
  char ssid[kWifiSsidMaxLen + 1] = {};
  char psk[kWifiPskMaxLen + 1] = {};
  uint32_t last_wifi_retry_ms = 0;
  uint32_t last_wifi_scan_ms = 0;
  uint32_t wifi_next_retry_ms = 0;
  uint8_t wifi_retry_failures = 0;
  uint8_t target_bssid[6] = {};
  bool has_target_bssid = false;
  int32_t target_channel = 0;
  bool scan_in_progress = false;
};

// Loads the hotspot SSID/PSK from NVS, falling back to the compile-time values.
void load_wifi_credentials(WifiState& state);
bool connect_wifi(WifiState& state, RuntimeStatus& status);
void service_wifi(WifiState& state, RuntimeStatus& status);

}  // namespace vibesensor::runtime
