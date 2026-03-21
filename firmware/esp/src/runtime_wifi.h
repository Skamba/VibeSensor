#pragma once

#include <Arduino.h>

#include "runtime_status.h"

namespace vibesensor::runtime {

struct WifiState {
  uint32_t last_wifi_retry_ms = 0;
  uint32_t last_wifi_scan_ms = 0;
  uint32_t wifi_next_retry_ms = 0;
  uint8_t wifi_retry_failures = 0;
  uint8_t target_bssid[6] = {};
  bool has_target_bssid = false;
  int32_t target_channel = 0;
  bool scan_in_progress = false;
};

bool connect_wifi(WifiState& state, RuntimeStatus& status);
void service_wifi(WifiState& state, RuntimeStatus& status);

}  // namespace vibesensor::runtime
