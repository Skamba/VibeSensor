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
  TEST_ASSERT_EQUAL_INT(WIFI_AUTH_WPA_PSK, WiFi.min_security);
  TEST_ASSERT_EQUAL_UINT32(3, WiFi.begin_calls.size());
  TEST_ASSERT_TRUE(WiFi.begin_calls[0].used_bssid);
  TEST_ASSERT_EQUAL_INT32(6, WiFi.begin_calls[0].channel);
  TEST_ASSERT_EQUAL_UINT8_ARRAY(scan_results[1].bssid.data(), WiFi.begin_calls[0].bssid.data(), 6);
  TEST_ASSERT_EQUAL_UINT32(2, WiFi.disconnect_calls.size());
  TEST_ASSERT_TRUE(WiFi.disconnect_calls[0].wifioff);
  TEST_ASSERT_TRUE(WiFi.disconnect_calls[0].eraseap);
}

void test_service_wifi_starts_async_scan_and_schedules_backoff_retry() {
  WifiState state{};
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

  arduino_test::set_millis(26000);
  vibesensor::runtime::service_wifi(state, status);

  TEST_ASSERT_FALSE(state.scan_in_progress);
  TEST_ASSERT_TRUE(state.has_target_bssid);
  TEST_ASSERT_EQUAL_INT32(6, state.target_channel);
  TEST_ASSERT_EQUAL_UINT32(1, status.wifi_reconnect_attempts);
}

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_connect_wifi_retries_until_connected_and_uses_scanned_bssid);
  RUN_TEST(test_service_wifi_starts_async_scan_and_schedules_backoff_retry);
  return UNITY_END();
}
