#include "runtime_wifi.h"

#include <Preferences.h>
#include <WiFi.h>
#include <string.h>

#include "reliability.h"
#include "runtime_config.h"
#include "vibesensor_network.h"

namespace vibesensor::runtime {
namespace {

// Arduino-ESP32 3.x defaults a stuck scan to 60 s and makes disconnect() wait up to
// 100 ms for the link to drop. Keep the 2.x behaviour: 20 x the 300 ms per-channel
// dwell for scans, and no blocking wait on disconnect (it runs on the loop task that
// drains the 200 ms sample handoff queue).
constexpr uint32_t kWifiScanTimeoutMs = 6000;
constexpr unsigned long kWifiDisconnectWaitMs = 0;

void consume_scan_results(WifiState& state, int found) {
  state.has_target_bssid = false;
  state.target_channel = 0;
  for (int i = 0; i < found; ++i) {
    if (WiFi.SSID(i) != state.ssid) {
      continue;
    }
    const uint8_t* bssid = WiFi.BSSID(i);
    if (bssid == nullptr) {
      continue;
    }
    memcpy(state.target_bssid, bssid, sizeof(state.target_bssid));
    state.target_channel = WiFi.channel(i);
    state.has_target_bssid = true;
    break;
  }
  WiFi.scanDelete();
}

bool refresh_target_ap(WifiState& state) {
  int found = WiFi.scanNetworks(/*async=*/false, /*show_hidden=*/true);
  consume_scan_results(state, found);
  return state.has_target_bssid;
}

void start_ap_scan(WifiState& state, RuntimeStatus& status) {
  if (state.scan_in_progress) {
    return;
  }
  int16_t rc = WiFi.scanNetworks(/*async=*/true, /*show_hidden=*/true);
  if (rc == WIFI_SCAN_RUNNING) {
    state.scan_in_progress = true;
  } else {
    set_last_error(status, 13);
  }
}

bool poll_ap_scan(WifiState& state) {
  if (!state.scan_in_progress) {
    return false;
  }
  int16_t found = WiFi.scanComplete();
  if (found == WIFI_SCAN_RUNNING) {
    return false;
  }
  state.scan_in_progress = false;
  if (found > 0) {
    consume_scan_results(state, static_cast<int>(found));
  }
  return true;
}

void copy_credential(char* dest, size_t capacity, const char* value) {
  strncpy(dest, value == nullptr ? "" : value, capacity - 1);
  dest[capacity - 1] = '\0';
}

void begin_target_wifi(const WifiState& state) {
  const char* psk = state.psk[0] != '\0' ? state.psk : nullptr;
  if (state.has_target_bssid && state.target_channel > 0) {
    WiFi.begin(state.ssid, psk, state.target_channel, state.target_bssid, true);
    return;
  }
  if (psk != nullptr) {
    WiFi.begin(state.ssid, psk);
  } else {
    WiFi.begin(state.ssid);
  }
}

}  // namespace

void load_wifi_credentials(WifiState& state) {
  copy_credential(state.ssid, sizeof(state.ssid), vibesensor_network::wifi_ssid);
  copy_credential(state.psk, sizeof(state.psk), vibesensor_network::wifi_psk);
  Preferences prefs;
  if (!prefs.begin(kWifiPrefsNamespace, /*readOnly=*/true)) {
    return;
  }
  char ssid[sizeof(state.ssid)] = {};
  char psk[sizeof(state.psk)] = {};
  if (prefs.getString("ssid", ssid, sizeof(ssid)) > 0 && ssid[0] != '\0') {
    copy_credential(state.ssid, sizeof(state.ssid), ssid);
    // An SSID without a stored PSK means an open hotspot.
    prefs.getString("psk", psk, sizeof(psk));
    copy_credential(state.psk, sizeof(state.psk), psk);
  }
  prefs.end();
}

bool connect_wifi(WifiState& state, RuntimeStatus& status) {
  load_wifi_credentials(state);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setScanTimeout(kWifiScanTimeoutMs);
  refresh_target_ap(state);
  for (uint8_t attempt = 1; attempt <= kWifiInitialConnectAttempts; ++attempt) {
    begin_target_wifi(state);
    uint32_t start_ms = millis();
    while (WiFi.status() != WL_CONNECTED) {
      if (millis() - start_ms >= kWifiConnectTimeoutMs) {
        break;
      }
      delay(50);
    }
    if (WiFi.status() == WL_CONNECTED) {
      return true;
    }
    status.wifi_connect_failures++;
    set_last_error(status, 11);
    WiFi.disconnect(true, true, kWifiDisconnectWaitMs);
    delay(kWifiRetryBackoffMs);
  }
  return false;
}

void service_wifi(WifiState& state, RuntimeStatus& status) {
  poll_ap_scan(state);

  if (WiFi.status() == WL_CONNECTED) {
    state.wifi_retry_failures = 0;
    state.wifi_next_retry_ms = 0;
    return;
  }
  uint32_t now = millis();

  if (!state.scan_in_progress && (now - state.last_wifi_scan_ms >= kWifiScanIntervalMs)) {
    state.last_wifi_scan_ms = now;
    start_ap_scan(state, status);
  }

  if (!vibesensor::reliability::retry_due(now, state.wifi_next_retry_ms)) {
    return;
  }
  state.last_wifi_retry_ms = now;
  status.wifi_reconnect_attempts++;
  set_last_error(status, 12);
  WiFi.disconnect(true, false, kWifiDisconnectWaitMs);
  begin_target_wifi(state);
  state.wifi_retry_failures =
      vibesensor::reliability::saturating_inc_u8(state.wifi_retry_failures);
  state.wifi_next_retry_ms =
      now + vibesensor::reliability::compute_retry_delay_ms(kWifiRetryIntervalMs,
                                                            kWifiRetryIntervalMaxMs,
                                                            state.wifi_retry_failures,
                                                            esp_random());
}

}  // namespace vibesensor::runtime
