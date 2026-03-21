#include "runtime_wifi.h"

#include <WiFi.h>
#include <string.h>

#include "reliability.h"
#include "runtime_config.h"
#include "vibesensor_network.h"

namespace vibesensor::runtime {
namespace {

void consume_scan_results(WifiState& state, int found) {
  state.has_target_bssid = false;
  state.target_channel = 0;
  for (int i = 0; i < found; ++i) {
    if (WiFi.SSID(i) != vibesensor_network::wifi_ssid) {
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

void begin_target_wifi(const WifiState& state) {
  const bool has_psk =
      vibesensor_network::wifi_psk != nullptr && strlen(vibesensor_network::wifi_psk) > 0;
  if (state.has_target_bssid && state.target_channel > 0) {
    if (has_psk) {
      WiFi.begin(vibesensor_network::wifi_ssid,
                 vibesensor_network::wifi_psk,
                 state.target_channel,
                 state.target_bssid,
                 true);
    } else {
      WiFi.begin(vibesensor_network::wifi_ssid,
                 nullptr,
                 state.target_channel,
                 state.target_bssid,
                 true);
    }
    return;
  }
  if (has_psk) {
    WiFi.begin(vibesensor_network::wifi_ssid, vibesensor_network::wifi_psk);
  } else {
    WiFi.begin(vibesensor_network::wifi_ssid);
  }
}

}  // namespace

bool connect_wifi(WifiState& state, RuntimeStatus& status) {
  WiFi.mode(WIFI_STA);
#ifdef WIFI_AUTH_WPA_PSK
  WiFi.setMinSecurity(WIFI_AUTH_WPA_PSK);
#endif
  WiFi.setSleep(false);
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
    WiFi.disconnect(true, true);
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
  WiFi.disconnect(true, false);
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
