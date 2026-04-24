#pragma once

#include <array>
#include <cstdint>
#include <deque>
#include <vector>

#include "Arduino.h"

using wl_status_t = int;

constexpr wl_status_t WL_CONNECTED = 3;
constexpr wl_status_t WL_DISCONNECTED = 6;
constexpr int WIFI_STA = 1;
constexpr int WIFI_SCAN_RUNNING = -1;
#ifndef WIFI_AUTH_WPA_PSK
#define WIFI_AUTH_WPA_PSK 1
#endif

class WiFiClass {
 public:
  struct ScanResult {
    String ssid;
    std::array<uint8_t, 6> bssid = {};
    int32_t channel = 0;
    bool has_bssid = true;
  };

  struct BeginCall {
    String ssid;
    String psk;
    int32_t channel = 0;
    std::array<uint8_t, 6> bssid = {};
    bool used_bssid = false;
    bool connect = false;
  };

  struct DisconnectCall {
    bool wifioff = false;
    bool eraseap = false;
  };

  void reset() {
    begin_calls.clear();
    disconnect_calls.clear();
    scan_results_.clear();
    begin_outcomes_.clear();
    scan_delete_count = 0;
    mode_value = 0;
    min_security = -1;
    sleep_enabled = true;
    mac_address = "D0:5A:00:00:00:01";
    async_scan_response = WIFI_SCAN_RUNNING;
    scan_complete_response = WIFI_SCAN_RUNNING;
    connected_ = false;
    begin_status_polls_remaining_ = -1;
    status_value = WL_DISCONNECTED;
  }

  void setStatus(wl_status_t value) {
    status_value = value;
    connected_ = (value == WL_CONNECTED);
  }

  void setScanResults(const std::vector<ScanResult>& results) { scan_results_ = results; }

  void setAsyncScanResponse(int16_t value) { async_scan_response = value; }

  void setScanCompleteResponse(int16_t value) { scan_complete_response = value; }

  void queueBeginOutcome(int status_polls_until_connected) {
    begin_outcomes_.push_back(status_polls_until_connected);
  }

  void setMacAddress(const String& value) { mac_address = value; }

  void mode(int value) { mode_value = value; }

  void setMinSecurity(int value) { min_security = value; }

  void setSleep(bool value) { sleep_enabled = value; }

  int scanNetworks(bool async = false, bool = true) {
    return async ? async_scan_response : static_cast<int>(scan_results_.size());
  }

  int scanComplete() { return scan_complete_response; }

  void scanDelete() {
    scan_delete_count++;
    scan_complete_response = 0;
  }

  String SSID(int index) const { return scan_results_[static_cast<size_t>(index)].ssid; }

  const uint8_t* BSSID(int index) const {
    const ScanResult& result = scan_results_[static_cast<size_t>(index)];
    return result.has_bssid ? result.bssid.data() : nullptr;
  }

  int32_t channel(int index) const {
    return scan_results_[static_cast<size_t>(index)].channel;
  }

  void begin(const char* ssid) { record_begin(ssid, nullptr, 0, nullptr, false); }

  void begin(const char* ssid, const char* psk) { record_begin(ssid, psk, 0, nullptr, false); }

  void begin(const char* ssid,
             const char* psk,
             int32_t channel,
             const uint8_t* bssid,
             bool connect) {
    record_begin(ssid, psk, channel, bssid, connect);
  }

  wl_status_t status() {
    if (connected_) {
      return WL_CONNECTED;
    }
    if (begin_status_polls_remaining_ == 0) {
      connected_ = true;
      status_value = WL_CONNECTED;
      return WL_CONNECTED;
    }
    if (begin_status_polls_remaining_ > 0) {
      begin_status_polls_remaining_--;
    }
    return status_value;
  }

  void disconnect(bool wifioff, bool eraseap) {
    DisconnectCall call;
    call.wifioff = wifioff;
    call.eraseap = eraseap;
    disconnect_calls.push_back(call);
    connected_ = false;
    status_value = WL_DISCONNECTED;
  }

  String macAddress() const { return mac_address; }

  std::vector<BeginCall> begin_calls;
  std::vector<DisconnectCall> disconnect_calls;
  int scan_delete_count = 0;
  int mode_value = 0;
  int min_security = -1;
  bool sleep_enabled = true;
  String mac_address = "D0:5A:00:00:00:01";
  int16_t async_scan_response = WIFI_SCAN_RUNNING;
  int16_t scan_complete_response = WIFI_SCAN_RUNNING;

 private:
  void record_begin(const char* ssid,
                    const char* psk,
                    int32_t channel,
                    const uint8_t* bssid,
                    bool connect) {
    BeginCall call{};
    call.ssid = ssid == nullptr ? "" : String(ssid);
    call.psk = psk == nullptr ? "" : String(psk);
    call.channel = channel;
    call.used_bssid = bssid != nullptr;
    call.connect = connect;
    if (bssid != nullptr) {
      for (size_t i = 0; i < call.bssid.size(); ++i) {
        call.bssid[i] = bssid[i];
      }
    }
    begin_calls.push_back(call);
    connected_ = false;
    status_value = WL_DISCONNECTED;
    if (begin_outcomes_.empty()) {
      begin_status_polls_remaining_ = -1;
      return;
    }
    begin_status_polls_remaining_ = begin_outcomes_.front();
    begin_outcomes_.pop_front();
  }

  std::vector<ScanResult> scan_results_;
  std::deque<int> begin_outcomes_;
  bool connected_ = false;
  int begin_status_polls_remaining_ = -1;
  wl_status_t status_value = WL_DISCONNECTED;
};

static WiFiClass WiFi;
