#include <unity.h>

#include <vector>

#include "../../src/runtime_status.cpp"
#include "../../src/runtime_wifi.cpp"

namespace {

using vibesensor::runtime::RuntimeStatus;
using vibesensor::runtime::WifiState;

std::vector<WiFiClass::ScanResult> target_scan_results() {
  WiFiClass::ScanResult other;
  other.ssid = "OtherNetwork";
  other.bssid = {{0, 1, 2, 3, 4, 5}};
  other.channel = 1;
  other.has_bssid = true;

  WiFiClass::ScanResult target;
  target.ssid = vibesensor_network::wifi_ssid;
  target.bssid = {{6, 7, 8, 9, 10, 11}};
  target.channel = 6;
  target.has_bssid = true;

  std::vector<WiFiClass::ScanResult> results;
  results.push_back(other);
  results.push_back(target);
  return results;
}

}  // namespace

void setUp() {
  arduino_test::reset_time();
  WiFi.reset();
  Preferences::store().clear();
}

void test_load_wifi_credentials_prefers_nvs_and_falls_back_to_build_defaults() {
  WifiState fallback{};
  vibesensor::runtime::load_wifi_credentials(fallback);
  TEST_ASSERT_EQUAL_STRING(vibesensor_network::wifi_ssid, fallback.ssid);
  TEST_ASSERT_EQUAL_STRING(vibesensor_network::wifi_psk, fallback.psk);

  Preferences::store()["vs_wifi/ssid"] = "Workshop";
  Preferences::store()["vs_wifi/psk"] = "secret-psk";
  WifiState stored{};
  vibesensor::runtime::load_wifi_credentials(stored);
  TEST_ASSERT_EQUAL_STRING("Workshop", stored.ssid);
  TEST_ASSERT_EQUAL_STRING("secret-psk", stored.psk);

  // An SSID without a PSK is an open hotspot, not the build-time PSK.
  Preferences::store().erase("vs_wifi/psk");
  WifiState open_ap{};
  vibesensor::runtime::load_wifi_credentials(open_ap);
  TEST_ASSERT_EQUAL_STRING("Workshop", open_ap.ssid);
  TEST_ASSERT_EQUAL_STRING("", open_ap.psk);
}

void test_connect_wifi_joins_the_hotspot_stored_in_nvs() {
  Preferences::store()["vs_wifi/ssid"] = "Workshop";
  Preferences::store()["vs_wifi/psk"] = "secret-psk";
  WiFiClass::ScanResult target;
  target.ssid = "Workshop";
  target.bssid = {{1, 2, 3, 4, 5, 6}};
  target.channel = 11;
  WiFi.setScanResults({target});
  WiFi.queueBeginOutcome(0);
  WifiState state{};
  RuntimeStatus status{};

  TEST_ASSERT_TRUE(vibesensor::runtime::connect_wifi(state, status));

  TEST_ASSERT_EQUAL_INT32(11, state.target_channel);
  TEST_ASSERT_EQUAL_UINT32(1, WiFi.begin_calls.size());
  TEST_ASSERT_EQUAL_STRING("Workshop", WiFi.begin_calls[0].ssid.c_str());
  TEST_ASSERT_EQUAL_STRING("secret-psk", WiFi.begin_calls[0].psk.c_str());
}

void test_connect_wifi_retries_until_connected_and_uses_scanned_bssid() {
  WifiState state{};
  RuntimeStatus status{};
  const std::vector<WiFiClass::ScanResult> scan_results = target_scan_results();
  WiFi.setScanResults(scan_results);
  WiFi.queueBeginOutcome(-1);
  WiFi.queueBeginOutcome(-1);
  WiFi.queueBeginOutcome(2);

  const bool ok = vibesensor::runtime::connect_wifi(state, status);

  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_TRUE(state.has_target_bssid);
  TEST_ASSERT_EQUAL_INT32(6, state.target_channel);
  TEST_ASSERT_EQUAL_UINT8_ARRAY(scan_results[1].bssid.data(), state.target_bssid, 6);
  TEST_ASSERT_EQUAL_UINT32(2, status.wifi_connect_failures);
  TEST_ASSERT_EQUAL_UINT8(11, status.last_error_code);
  TEST_ASSERT_EQUAL_INT(WIFI_STA, WiFi.mode_value);
  TEST_ASSERT_FALSE(WiFi.sleep_enabled);
  TEST_ASSERT_EQUAL_UINT32(6000, WiFi.scan_timeout_ms);
  TEST_ASSERT_EQUAL_UINT32(3, WiFi.begin_calls.size());
  TEST_ASSERT_TRUE(WiFi.begin_calls[0].used_bssid);
  TEST_ASSERT_EQUAL_INT32(6, WiFi.begin_calls[0].channel);
  TEST_ASSERT_EQUAL_UINT8_ARRAY(scan_results[1].bssid.data(), WiFi.begin_calls[0].bssid.data(), 6);
  TEST_ASSERT_EQUAL_UINT32(2, WiFi.disconnect_calls.size());
  TEST_ASSERT_TRUE(WiFi.disconnect_calls[0].wifioff);
  TEST_ASSERT_TRUE(WiFi.disconnect_calls[0].eraseap);
  TEST_ASSERT_EQUAL_UINT32(0, WiFi.disconnect_calls[0].timeout_ms);
}

void test_service_wifi_starts_async_scan_and_schedules_backoff_retry() {
  WifiState state{};
  vibesensor::runtime::load_wifi_credentials(state);  // done by connect_wifi() at boot
  RuntimeStatus status{};
  WiFi.setStatus(WL_DISCONNECTED);
  WiFi.setScanResults(target_scan_results());
  WiFi.setAsyncScanResponse(WIFI_SCAN_RUNNING);
  WiFi.setScanCompleteResponse(2);
  WiFi.queueBeginOutcome(-1);
  arduino_test::set_random_value(0);
  arduino_test::set_millis(25000);

  vibesensor::runtime::service_wifi(state, status);

  TEST_ASSERT_TRUE(state.scan_in_progress);
  TEST_ASSERT_EQUAL_UINT32(25000, state.last_wifi_scan_ms);
  TEST_ASSERT_EQUAL_UINT32(1, status.wifi_reconnect_attempts);
  TEST_ASSERT_EQUAL_UINT32(25000, state.last_wifi_retry_ms);
  TEST_ASSERT_EQUAL_UINT32(32000, state.wifi_next_retry_ms);
  TEST_ASSERT_EQUAL_UINT8(1, state.wifi_retry_failures);
  TEST_ASSERT_EQUAL_UINT8(12, status.last_error_code);
  TEST_ASSERT_EQUAL_UINT32(1, WiFi.disconnect_calls.size());
  TEST_ASSERT_TRUE(WiFi.disconnect_calls[0].wifioff);
  TEST_ASSERT_FALSE(WiFi.disconnect_calls[0].eraseap);
  TEST_ASSERT_EQUAL_UINT32(0, WiFi.disconnect_calls[0].timeout_ms);

  arduino_test::set_millis(26000);
  vibesensor::runtime::service_wifi(state, status);

  TEST_ASSERT_FALSE(state.scan_in_progress);
  TEST_ASSERT_TRUE(state.has_target_bssid);
  TEST_ASSERT_EQUAL_INT32(6, state.target_channel);
  TEST_ASSERT_EQUAL_UINT32(1, status.wifi_reconnect_attempts);
}

void test_a_sensor_that_lost_the_hotspot_retries_at_least_every_10_s() {
  WifiState state{};
  vibesensor::runtime::load_wifi_credentials(state);
  RuntimeStatus status{};
  WiFi.setStatus(WL_DISCONNECTED);
  uint32_t attempts = 0;
  uint32_t last_attempt_ms = 0;
  uint32_t longest_gap_ms = 0;

  // Two minutes without the hotspot (the Pi rebooting), checked every millisecond.
  for (uint32_t now_ms = 1000; now_ms <= 121000; ++now_ms) {
    arduino_test::set_millis(now_ms);
    arduino_test::set_random_value(now_ms * 2654435761U);
    vibesensor::runtime::service_wifi(state, status);
    if (status.wifi_reconnect_attempts != attempts) {
      if (attempts > 0 && now_ms - last_attempt_ms > longest_gap_ms) {
        longest_gap_ms = now_ms - last_attempt_ms;
      }
      attempts = status.wifi_reconnect_attempts;
      last_attempt_ms = now_ms;
    }
  }

  TEST_ASSERT_TRUE(longest_gap_ms <= 10000);
  TEST_ASSERT_TRUE(longest_gap_ms >= 8000);  // still backed off, not hammering
  TEST_ASSERT_TRUE(attempts >= 12);
}

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_load_wifi_credentials_prefers_nvs_and_falls_back_to_build_defaults);
  RUN_TEST(test_connect_wifi_joins_the_hotspot_stored_in_nvs);
  RUN_TEST(test_connect_wifi_retries_until_connected_and_uses_scanned_bssid);
  RUN_TEST(test_service_wifi_starts_async_scan_and_schedules_backoff_retry);
  RUN_TEST(test_a_sensor_that_lost_the_hotspot_retries_at_least_every_10_s);
  return UNITY_END();
}
