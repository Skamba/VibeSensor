#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_heap_caps.h>
#include <esp_system.h>
#include <esp_timer.h>

#include "adxl345.h"
#include "reliability.h"
#include "vibesensor_contracts.h"
#include "vibesensor_network.h"
#include "vibesensor_proto.h"

namespace {

constexpr char kClientName[] = "vibe-node";
constexpr char kFirmwareVersion[] = "esp32-atom-0.1";
// Conservative UDP payload cap that avoids IP fragmentation on MTU-1500 paths.
// 1500 (link MTU) − 20 (IP header) − 8 (UDP header) = 1472 safe payload bytes.
// Override via build_flags: -D VIBESENSOR_MAX_UDP_PAYLOAD=<bytes>
#ifndef VIBESENSOR_MAX_UDP_PAYLOAD
#define VIBESENSOR_MAX_UDP_PAYLOAD 1472
#endif
constexpr size_t kMaxDatagramBytes = static_cast<size_t>(VIBESENSOR_MAX_UDP_PAYLOAD);

#ifndef VIBESENSOR_SAMPLE_RATE_HZ
#define VIBESENSOR_SAMPLE_RATE_HZ 400
#endif
#ifndef VIBESENSOR_FRAME_SAMPLES
#define VIBESENSOR_FRAME_SAMPLES 200
#endif
#ifndef VIBESENSOR_SERVER_DATA_PORT
#define VIBESENSOR_SERVER_DATA_PORT VS_SERVER_UDP_DATA_PORT
#endif
#ifndef VIBESENSOR_SERVER_CONTROL_PORT
#define VIBESENSOR_SERVER_CONTROL_PORT VS_SERVER_UDP_CONTROL_PORT
#endif
#ifndef VIBESENSOR_CONTROL_PORT_BASE
#define VIBESENSOR_CONTROL_PORT_BASE VS_FIRMWARE_CONTROL_PORT_BASE
#endif

constexpr uint16_t kSampleRateMinHz = 25;
constexpr uint16_t kSampleRateMaxHz = 3200;
constexpr uint16_t kConfiguredSampleRateHz = static_cast<uint16_t>(VIBESENSOR_SAMPLE_RATE_HZ);
constexpr uint16_t kSampleRateHz = vibesensor::reliability::clamp_sample_rate(
    kConfiguredSampleRateHz, kSampleRateMinHz, kSampleRateMaxHz);
constexpr uint16_t kFrameSamplesMaxByDatagram =
    // Each sample contributes 3 axes * 2 bytes = 6 payload bytes.
    static_cast<uint16_t>((kMaxDatagramBytes - vibesensor::kDataHeaderBytes) / 6);
constexpr uint16_t kConfiguredFrameSamples = static_cast<uint16_t>(VIBESENSOR_FRAME_SAMPLES);
constexpr uint16_t kFrameSamples = (kConfiguredFrameSamples == 0)
                                       ? 1
                                       : ((kConfiguredFrameSamples > kFrameSamplesMaxByDatagram)
                                              ? kFrameSamplesMaxByDatagram
                                              : kConfiguredFrameSamples);
constexpr uint16_t kServerDataPort = static_cast<uint16_t>(VIBESENSOR_SERVER_DATA_PORT);
constexpr uint16_t kServerControlPort = static_cast<uint16_t>(VIBESENSOR_SERVER_CONTROL_PORT);
constexpr uint16_t kControlPortBase = static_cast<uint16_t>(VIBESENSOR_CONTROL_PORT_BASE);
// Use a larger queue target and allocate from heap at runtime to avoid
// static DRAM linker limits while still maximizing buffering when RAM allows.
#ifndef VIBESENSOR_FRAME_QUEUE_LEN_TARGET
#define VIBESENSOR_FRAME_QUEUE_LEN_TARGET 128
#endif
#ifndef VIBESENSOR_FRAME_QUEUE_LEN_MIN
#define VIBESENSOR_FRAME_QUEUE_LEN_MIN 16
#endif
constexpr size_t kFrameQueueLenTarget = static_cast<size_t>(VIBESENSOR_FRAME_QUEUE_LEN_TARGET);
constexpr size_t kFrameQueueLenMin = static_cast<size_t>(VIBESENSOR_FRAME_QUEUE_LEN_MIN);
constexpr uint32_t kHelloIntervalMs = 2000;
#ifndef VIBESENSOR_WIFI_CONNECT_TIMEOUT_MS
#define VIBESENSOR_WIFI_CONNECT_TIMEOUT_MS 15000
#endif
#ifndef VIBESENSOR_WIFI_RETRY_BACKOFF_MS
#define VIBESENSOR_WIFI_RETRY_BACKOFF_MS 2000
#endif
#ifndef VIBESENSOR_WIFI_RETRY_INTERVAL_MS
#define VIBESENSOR_WIFI_RETRY_INTERVAL_MS 4000
#endif
#ifndef VIBESENSOR_WIFI_INITIAL_CONNECT_ATTEMPTS
#define VIBESENSOR_WIFI_INITIAL_CONNECT_ATTEMPTS 3
#endif
constexpr uint32_t kWifiConnectTimeoutMs = static_cast<uint32_t>(VIBESENSOR_WIFI_CONNECT_TIMEOUT_MS);
constexpr uint32_t kWifiRetryBackoffMs = static_cast<uint32_t>(VIBESENSOR_WIFI_RETRY_BACKOFF_MS);
constexpr uint32_t kWifiRetryIntervalMs = static_cast<uint32_t>(VIBESENSOR_WIFI_RETRY_INTERVAL_MS);
constexpr uint8_t kWifiInitialConnectAttempts =
  static_cast<uint8_t>(VIBESENSOR_WIFI_INITIAL_CONNECT_ATTEMPTS);
constexpr size_t kMaxCatchUpSamplesPerLoop = 8;
constexpr size_t kSensorReadBatchSamples = 8;
constexpr size_t kMaxTxFramesPerLoop = 2;
constexpr uint32_t kDataRetransmitIntervalMs = 120;
constexpr uint32_t kStatusReportIntervalMs = 10000;
constexpr uint16_t kMaxIdentifyDurationMs = 10000;
constexpr uint8_t kSensorReinitErrorThreshold = 3;
constexpr uint32_t kSensorReinitCooldownMs = 5000;
constexpr uint32_t kWifiRetryIntervalMaxMs = 60000;
#ifndef VIBESENSOR_WIFI_SCAN_INTERVAL_MS
#define VIBESENSOR_WIFI_SCAN_INTERVAL_MS 20000
#endif
constexpr uint32_t kWifiScanIntervalMs = static_cast<uint32_t>(VIBESENSOR_WIFI_SCAN_INTERVAL_MS);
#ifndef VIBESENSOR_ENABLE_SYNTH_FALLBACK
#define VIBESENSOR_ENABLE_SYNTH_FALLBACK 0
#endif

static_assert(VIBESENSOR_SAMPLE_RATE_HZ > 0, "VIBESENSOR_SAMPLE_RATE_HZ must be > 0");
static_assert(VIBESENSOR_FRAME_SAMPLES > 0, "VIBESENSOR_FRAME_SAMPLES must be > 0");
static_assert(VIBESENSOR_FRAME_QUEUE_LEN_MIN > 0,
        "VIBESENSOR_FRAME_QUEUE_LEN_MIN must be > 0");
static_assert(VIBESENSOR_FRAME_QUEUE_LEN_TARGET >= VIBESENSOR_FRAME_QUEUE_LEN_MIN,
        "VIBESENSOR_FRAME_QUEUE_LEN_TARGET must be >= VIBESENSOR_FRAME_QUEUE_LEN_MIN");
static_assert(VIBESENSOR_WIFI_INITIAL_CONNECT_ATTEMPTS > 0,
        "VIBESENSOR_WIFI_INITIAL_CONNECT_ATTEMPTS must be > 0");
static_assert(kFrameSamplesMaxByDatagram > 0, "kMaxDatagramBytes too small for protocol");

// Default I2C pins for M5Stack ATOM Lite Unit port (4-pin cable).
constexpr int kI2cSdaPin = 26;
constexpr int kI2cSclPin = 32;
constexpr uint8_t kAdxlI2cAddr = 0x53;

#ifndef LED_BUILTIN
constexpr int LED_BUILTIN = 27;
#endif
constexpr uint16_t kLedPixels = 1;
constexpr uint16_t kIdentifyBlinkPeriodMs = 300;
constexpr uint8_t kIdentifyBrightness = 64;

struct DataFrame {
  // One UDP payload worth of accelerometer samples, tracked until ACKed.
  uint32_t seq;
  uint64_t t0_us;
  uint16_t sample_count;
  int16_t xyz[kFrameSamples * 3];
  bool transmitted;
  uint32_t last_tx_ms;
};

TwoWire& g_i2c = Wire;
ADXL345 g_adxl(g_i2c, kAdxlI2cAddr, kI2cSdaPin, kI2cSclPin);
WiFiUDP g_data_udp;
WiFiUDP g_control_udp;
Adafruit_NeoPixel g_led_strip(kLedPixels, LED_BUILTIN, NEO_GRB + NEO_KHZ800);

uint8_t g_client_id[6] = {};
uint16_t g_control_port = kControlPortBase;

DataFrame* g_queue = nullptr;
size_t g_queue_capacity = 0;
// Head points to next write slot, tail points to oldest queued frame.
size_t g_q_head = 0;
size_t g_q_tail = 0;
size_t g_q_size = 0;

int16_t g_build_xyz[kFrameSamples * 3] = {};
uint16_t g_build_count = 0;
uint64_t g_build_t0_us = 0;
uint32_t g_next_seq = 0;
uint64_t g_next_sample_due_us = 0;

uint32_t g_last_hello_ms = 0;
bool g_sensor_ok = false;
int16_t g_sensor_batch_xyz[kSensorReadBatchSamples * 3] = {};
size_t g_sensor_batch_count = 0;
size_t g_sensor_batch_index = 0;

uint32_t g_blink_until_ms = 0;
int64_t g_clock_offset_us = 0;
uint32_t g_led_next_update_ms = 0;
bool g_identify_leds_active = false;
uint32_t g_last_wifi_retry_ms = 0;
uint32_t g_queue_overflow_drops = 0;
uint32_t g_last_wifi_scan_ms = 0;
uint32_t g_last_status_report_ms = 0;
uint32_t g_sensor_read_errors = 0;
uint32_t g_sensor_fifo_truncated = 0;
uint32_t g_sensor_reinit_attempts = 0;
uint32_t g_sensor_reinit_success = 0;
uint8_t g_sensor_consecutive_errors = 0;
uint32_t g_last_sensor_reinit_ms = 0;
uint32_t g_sampling_missed_samples = 0;
uint32_t g_tx_pack_failures = 0;
uint32_t g_tx_begin_failures = 0;
uint32_t g_tx_end_failures = 0;
uint32_t g_control_parse_errors = 0;
uint32_t g_data_ack_parse_errors = 0;
uint32_t g_wifi_reconnect_attempts = 0;
uint32_t g_wifi_connect_failures = 0;
uint8_t g_wifi_retry_failures = 0;
uint32_t g_wifi_next_retry_ms = 0;
uint8_t g_last_error_code = 0;
uint32_t g_last_error_ms = 0;
uint8_t g_target_bssid[6] = {};
bool g_has_target_bssid = false;
int32_t g_target_channel = 0;
bool g_has_last_real_sample = false;
int16_t g_last_real_x = 0;
int16_t g_last_real_y = 0;
int16_t g_last_real_z = 0;

void set_last_error(uint8_t error_code) {
  g_last_error_code = error_code;
  g_last_error_ms = millis();
}

void report_runtime_status(uint32_t now_ms) {
  if (now_ms - g_last_status_report_ms < kStatusReportIntervalMs) {
    return;
  }
  g_last_status_report_ms = now_ms;
  Serial.printf(
      "status wifi=%d q=%u/%u drop=%lu tx_fail={pack:%lu begin:%lu end:%lu} "
      "sensor={err:%lu trunc:%lu reinit:%lu/%lu miss:%lu} wifi_retry={attempts:%lu fail:%lu} "
      "parse={ctrl:%lu ack:%lu} last_error=%u@%lu\n",
      WiFi.status(),
      static_cast<unsigned>(g_q_size),
      static_cast<unsigned>(g_queue_capacity),
      static_cast<unsigned long>(g_queue_overflow_drops),
      static_cast<unsigned long>(g_tx_pack_failures),
      static_cast<unsigned long>(g_tx_begin_failures),
      static_cast<unsigned long>(g_tx_end_failures),
      static_cast<unsigned long>(g_sensor_read_errors),
      static_cast<unsigned long>(g_sensor_fifo_truncated),
      static_cast<unsigned long>(g_sensor_reinit_success),
      static_cast<unsigned long>(g_sensor_reinit_attempts),
      static_cast<unsigned long>(g_sampling_missed_samples),
      static_cast<unsigned long>(g_wifi_reconnect_attempts),
      static_cast<unsigned long>(g_wifi_connect_failures),
      static_cast<unsigned long>(g_control_parse_errors),
      static_cast<unsigned long>(g_data_ack_parse_errors),
      static_cast<unsigned>(g_last_error_code),
      static_cast<unsigned long>(g_last_error_ms));
}

bool refresh_target_ap() {
  int found = WiFi.scanNetworks(false, true);
  g_has_target_bssid = false;
  g_target_channel = 0;
  for (int i = 0; i < found; ++i) {
    if (WiFi.SSID(i) != vibesensor_network::wifi_ssid) {
      continue;
    }
    const uint8_t* bssid = WiFi.BSSID(i);
    if (bssid == nullptr) {
      continue;
    }
    memcpy(g_target_bssid, bssid, sizeof(g_target_bssid));
    g_target_channel = WiFi.channel(i);
    g_has_target_bssid = true;
    break;
  }
  WiFi.scanDelete();
  return g_has_target_bssid;
}

void begin_target_wifi() {
  const bool has_psk = vibesensor_network::wifi_psk != nullptr && strlen(vibesensor_network::wifi_psk) > 0;
  if (g_has_target_bssid && g_target_channel > 0) {
    if (has_psk) {
      WiFi.begin(vibesensor_network::wifi_ssid,
                 vibesensor_network::wifi_psk,
                 g_target_channel,
                 g_target_bssid,
                 true);
    } else {
      WiFi.begin(vibesensor_network::wifi_ssid, nullptr, g_target_channel, g_target_bssid, true);
    }
    return;
  }
  if (has_psk) {
    WiFi.begin(vibesensor_network::wifi_ssid, vibesensor_network::wifi_psk);
  } else {
    WiFi.begin(vibesensor_network::wifi_ssid);
  }
}

void clear_leds() {
  g_led_strip.clear();
  g_led_strip.show();
}

void render_identify_blink(uint32_t now_ms) {
  bool led_on = ((now_ms / kIdentifyBlinkPeriodMs) % 2U) == 0U;
  if (led_on) {
    g_led_strip.setPixelColor(0, g_led_strip.Color(0, kIdentifyBrightness, kIdentifyBrightness));
  } else {
    g_led_strip.setPixelColor(0, 0);
  }
  g_led_strip.show();
}

void enqueue_frame() {
  if (g_build_count == 0) {
    return;
  }
  if (g_queue == nullptr || g_queue_capacity == 0) {
    g_queue_overflow_drops++;
    g_build_count = 0;
    return;
  }

  if (g_q_size == g_queue_capacity) {
    // Ring buffer is full: drop oldest frame so freshest samples stay prioritized.
    g_queue_overflow_drops++;
    g_q_tail = (g_q_tail + 1) % g_queue_capacity;
    g_q_size--;
  }

  DataFrame& frame = g_queue[g_q_head];
  frame.seq = g_next_seq++;
  // Apply clock offset from CMD_SYNC_CLOCK to make t0_us server-relative.
  // g_build_t0_us is always from esp_timer_get_time() (µs since boot)
  // which stays well within int64_t range for any practical uptime.
  frame.t0_us = static_cast<uint64_t>(
      static_cast<int64_t>(g_build_t0_us) + g_clock_offset_us);
  frame.sample_count = g_build_count;
  frame.transmitted = false;
  frame.last_tx_ms = 0;
  memcpy(frame.xyz, g_build_xyz, static_cast<size_t>(g_build_count) * 3 * sizeof(int16_t));

  g_q_head = (g_q_head + 1) % g_queue_capacity;
  g_q_size++;
  g_build_count = 0;
}

DataFrame* peek_frame() {
  if (g_q_size == 0) {
    return nullptr;
  }
  return &g_queue[g_q_tail];
}

void drop_front_frame() {
  if (g_q_size == 0) {
    return;
  }
  g_q_tail = (g_q_tail + 1) % g_queue_capacity;
  g_q_size--;
}

bool seq_less_or_equal(uint32_t lhs, uint32_t rhs) {
  // Signed subtraction keeps comparisons valid across uint32 wrap-around.
  return static_cast<int32_t>(lhs - rhs) <= 0;
}

void ack_data_frames(uint32_t last_seq_received) {
  while (g_q_size > 0) {
    const DataFrame& front = g_queue[g_q_tail];
    if (!seq_less_or_equal(front.seq, last_seq_received)) {
      break;
    }
    drop_front_frame();
  }
}

void synth_sample(int16_t* x, int16_t* y, int16_t* z) {
  const float t = static_cast<float>(esp_timer_get_time()) / 1.0e6f;
  *x = static_cast<int16_t>(700.0f * sinf(2.0f * PI * 13.0f * t));
  *y = static_cast<int16_t>(350.0f * sinf(2.0f * PI * 27.0f * t + 0.7f));
  *z = static_cast<int16_t>(900.0f * sinf(2.0f * PI * 41.0f * t + 1.1f));
}

bool next_sensor_sample(int16_t* x, int16_t* y, int16_t* z) {
  if (!g_sensor_ok) {
    return false;
  }
  if (g_sensor_batch_index >= g_sensor_batch_count) {
    bool io_error = false;
    bool fifo_truncated = false;
    g_sensor_batch_count = g_adxl.read_samples(
        g_sensor_batch_xyz, kSensorReadBatchSamples, &io_error, &fifo_truncated);
    g_sensor_batch_index = 0;
    if (fifo_truncated) {
      g_sensor_fifo_truncated++;
      set_last_error(2);
    }
    if (io_error) {
      g_sensor_read_errors++;
      g_sensor_consecutive_errors++;
      set_last_error(1);
      uint32_t now_ms = millis();
      if (g_sensor_consecutive_errors >= kSensorReinitErrorThreshold &&
          (now_ms - g_last_sensor_reinit_ms) >= kSensorReinitCooldownMs) {
        g_last_sensor_reinit_ms = now_ms;
        g_sensor_reinit_attempts++;
        g_sensor_ok = g_adxl.begin();
        if (g_sensor_ok) {
          g_sensor_reinit_success++;
          g_sensor_consecutive_errors = 0;
        }
      }
    } else if (g_sensor_batch_count > 0) {
      g_sensor_consecutive_errors = 0;
    }
  }
  if (g_sensor_batch_count == 0) {
    return false;
  }
  const size_t offset = g_sensor_batch_index * 3;
  *x = g_sensor_batch_xyz[offset + 0];
  *y = g_sensor_batch_xyz[offset + 1];
  *z = g_sensor_batch_xyz[offset + 2];
  g_sensor_batch_index++;
  return true;
}

bool sample_once() {
  int16_t x = 0;
  int16_t y = 0;
  int16_t z = 0;

  if (next_sensor_sample(&x, &y, &z)) {
    g_has_last_real_sample = true;
    g_last_real_x = x;
    g_last_real_y = y;
    g_last_real_z = z;
  } else {
#if VIBESENSOR_ENABLE_SYNTH_FALLBACK
    synth_sample(&x, &y, &z);
#else
    // Do not inject synthetic or held samples in production.
    // Repeating the previous sample creates artificial tones in the FFT.
    return false;
#endif
  }

  if (g_build_count == 0) {
    g_build_t0_us = g_next_sample_due_us;
  }

  const size_t idx = static_cast<size_t>(g_build_count) * 3;
  g_build_xyz[idx + 0] = x;
  g_build_xyz[idx + 1] = y;
  g_build_xyz[idx + 2] = z;
  g_build_count++;

  if (g_build_count >= kFrameSamples) {
    enqueue_frame();
  }
  return true;
}

void service_sampling() {
  // Keep up with wall-clock sampling; if we fall behind, account for skipped samples.
  const uint64_t step_us = 1000000ULL / kSampleRateHz;
  uint64_t now = esp_timer_get_time();
  size_t catch_up_count = 0;
  while (static_cast<int64_t>(now - g_next_sample_due_us) >= 0 &&
         catch_up_count < kMaxCatchUpSamplesPerLoop) {
    if (!sample_once()) {
      g_sampling_missed_samples++;
      break;
    }
    g_next_sample_due_us += step_us;
    catch_up_count++;
    now = esp_timer_get_time();
  }

  if (static_cast<int64_t>(now - g_next_sample_due_us) >= 0) {
    uint64_t lag_us = now - g_next_sample_due_us;
    uint64_t skipped = (lag_us / step_us) + 1;
    g_sampling_missed_samples += static_cast<uint32_t>(skipped);
    set_last_error(3);
    g_next_sample_due_us += skipped * step_us;
  }
}

void send_hello() {
  uint8_t packet[128];
  size_t len = vibesensor::pack_hello(packet,
                                      sizeof(packet),
                                      g_client_id,
                                      g_control_port,
                                      kSampleRateHz,
                                      kFrameSamples,
                                      kClientName,
                                      kFirmwareVersion,
                                      g_queue_overflow_drops);
  if (len == 0) {
    return;
  }

  g_control_udp.beginPacket(vibesensor_network::server_ip, kServerControlPort);
  g_control_udp.write(packet, len);
  if (g_control_udp.endPacket() != 1) {
    set_last_error(4);
  }
}

void service_hello() {
  uint32_t now = millis();
  if (now - g_last_hello_ms >= kHelloIntervalMs) {
    send_hello();
    g_last_hello_ms = now;
  }
}

void service_tx() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  uint8_t packet[kMaxDatagramBytes];
  for (size_t sent = 0; sent < kMaxTxFramesPerLoop; ++sent) {
    DataFrame* frame = peek_frame();
    if (frame == nullptr) {
      return;
    }

    uint32_t now_ms = millis();
    // Retry unacked frames at a bounded cadence to avoid flooding.
    if (frame->transmitted && (now_ms - frame->last_tx_ms) < kDataRetransmitIntervalMs) {
      return;
    }

    size_t len = vibesensor::pack_data(packet,
                                       sizeof(packet),
                                       g_client_id,
                                       frame->seq,
                                       frame->t0_us,
                                       frame->xyz,
                                       frame->sample_count);
    if (len == 0) {
      g_tx_pack_failures++;
      set_last_error(5);
      drop_front_frame();
      continue;
    }

    if (g_data_udp.beginPacket(vibesensor_network::server_ip, kServerDataPort) != 1) {
      g_tx_begin_failures++;
      set_last_error(6);
      break;
    }
    g_data_udp.write(packet, len);
    if (g_data_udp.endPacket() != 1) {
      g_tx_end_failures++;
      set_last_error(7);
      break;
    }
    frame->transmitted = true;
    frame->last_tx_ms = now_ms;
  }
}

void send_ack(uint32_t cmd_seq, uint8_t status) {
  uint8_t packet[16];
  size_t len = vibesensor::pack_ack(packet, sizeof(packet), g_client_id, cmd_seq, status);
  if (len == 0) {
    return;
  }
  g_control_udp.beginPacket(vibesensor_network::server_ip, kServerControlPort);
  g_control_udp.write(packet, len);
  if (g_control_udp.endPacket() != 1) {
    set_last_error(8);
  }
}

void service_control_rx() {
  int packet_size = g_control_udp.parsePacket();
  if (packet_size <= 0) {
    return;
  }
  uint8_t packet[64];
  size_t read = static_cast<size_t>(g_control_udp.read(packet, sizeof(packet)));
  if (read == 0) {
    return;
  }

  if (packet[0] == vibesensor::kMsgDataAck) {
    // Control socket may also receive ACKs; accept them here for robustness.
    uint32_t last_seq_received = 0;
    bool ok_ack = vibesensor::parse_data_ack(packet, read, g_client_id, &last_seq_received);
    if (ok_ack) {
      ack_data_frames(last_seq_received);
    }
    return;
  }

  uint8_t cmd_id = 0;
  uint32_t cmd_seq = 0;
  uint16_t identify_ms = 0;
  uint64_t server_time_us = 0;
  bool ok = vibesensor::parse_cmd(packet,
                                  read,
                                  g_client_id,
                                  &cmd_id,
                                  &cmd_seq,
                                  &identify_ms,
                                  &server_time_us);
  if (!ok) {
    g_control_parse_errors++;
    set_last_error(9);
    return;
  }

  if (cmd_id == vibesensor::kCmdIdentify) {
    identify_ms = identify_ms > kMaxIdentifyDurationMs ? kMaxIdentifyDurationMs : identify_ms;
    g_blink_until_ms = millis() + identify_ms;
    g_led_next_update_ms = 0;
    send_ack(cmd_seq, 0);
  } else if (cmd_id == vibesensor::kCmdSyncClock) {
    int64_t local_us = static_cast<int64_t>(esp_timer_get_time());
    g_clock_offset_us = static_cast<int64_t>(server_time_us) - local_us;
    send_ack(cmd_seq, 0);
  } else {
    send_ack(cmd_seq, 2);
  }
}

void service_data_rx() {
  while (true) {
    int packet_size = g_data_udp.parsePacket();
    if (packet_size <= 0) {
      return;
    }
    uint8_t packet[32];
    size_t read = static_cast<size_t>(g_data_udp.read(packet, sizeof(packet)));
    if (read == 0 || packet[0] != vibesensor::kMsgDataAck) {
      continue;
    }
    uint32_t last_seq_received = 0;
    bool ok_ack = vibesensor::parse_data_ack(packet, read, g_client_id, &last_seq_received);
    if (ok_ack) {
      ack_data_frames(last_seq_received);
    } else {
      g_data_ack_parse_errors++;
      set_last_error(10);
    }
  }
}

void service_blink() {
  uint32_t now = millis();
  if (g_blink_until_ms == 0 || static_cast<int32_t>(g_blink_until_ms - now) <= 0) {
    if (g_identify_leds_active) {
      clear_leds();
      g_identify_leds_active = false;
    }
    g_blink_until_ms = 0;
    return;
  }

  if (now >= g_led_next_update_ms) {
    render_identify_blink(now);
    g_identify_leds_active = true;
    g_led_next_update_ms = now + (kIdentifyBlinkPeriodMs / 2U);
  }
}

bool connect_wifi() {
  WiFi.mode(WIFI_STA);
#ifdef WIFI_AUTH_WPA_PSK
  WiFi.setMinSecurity(WIFI_AUTH_WPA_PSK);
#endif
  WiFi.setSleep(false);
  refresh_target_ap();
  // Give boot-time connectivity a few bounded retries before background recovery.
  for (uint8_t attempt = 1; attempt <= kWifiInitialConnectAttempts; ++attempt) {
    begin_target_wifi();
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
    g_wifi_connect_failures++;
    set_last_error(11);
    WiFi.disconnect(true, true);
    delay(kWifiRetryBackoffMs);
  }
  return false;
}

void service_wifi() {
  if (WiFi.status() == WL_CONNECTED) {
    g_wifi_retry_failures = 0;
    g_wifi_next_retry_ms = 0;
    return;
  }
  uint32_t now = millis();
  if (!vibesensor::reliability::retry_due(now, g_wifi_next_retry_ms)) {
    return;
  }
  g_last_wifi_retry_ms = now;
  g_wifi_reconnect_attempts++;
  set_last_error(12);
  if (now - g_last_wifi_scan_ms >= kWifiScanIntervalMs) {
    g_last_wifi_scan_ms = now;
    refresh_target_ap();
  }
  WiFi.disconnect(true, true);
  begin_target_wifi();
  g_wifi_retry_failures = vibesensor::reliability::saturating_inc_u8(g_wifi_retry_failures);
  g_wifi_next_retry_ms = now + vibesensor::reliability::compute_retry_delay_ms(
                                   kWifiRetryIntervalMs,
                                   kWifiRetryIntervalMaxMs,
                                   g_wifi_retry_failures,
                                   esp_random());
}

}  // namespace

void setup() {
  Serial.begin(115200);
  if (kSampleRateHz != kConfiguredSampleRateHz) {
    Serial.printf("clamped sample rate from %u to %u\n",
                  static_cast<unsigned>(kConfiguredSampleRateHz),
                  static_cast<unsigned>(kSampleRateHz));
  }
  if (kFrameSamples != kConfiguredFrameSamples) {
    Serial.printf("clamped frame samples from %u to %u for MTU safety\n",
                  static_cast<unsigned>(kConfiguredFrameSamples),
                  static_cast<unsigned>(kFrameSamples));
  }
  for (size_t cap = kFrameQueueLenTarget; cap >= kFrameQueueLenMin; --cap) {
    // Try the largest queue first, then gracefully degrade if RAM is tight.
    auto* mem = static_cast<DataFrame*>(
        heap_caps_malloc(cap * sizeof(DataFrame), MALLOC_CAP_8BIT));
    if (mem != nullptr) {
      g_queue = mem;
      g_queue_capacity = cap;
      break;
    }
    if (cap == kFrameQueueLenMin) {
      break;
    }
  }

  g_led_strip.begin();
  clear_leds();

  connect_wifi();

  String mac = WiFi.macAddress();
  if (!vibesensor::parse_mac(mac, g_client_id)) {
    const uint8_t fallback[6] = {0xD0, 0x5A, 0x00, 0x00, 0x00, 0x01};
    memcpy(g_client_id, fallback, sizeof(g_client_id));
  }

  g_control_port = static_cast<uint16_t>(kControlPortBase + (g_client_id[5] % 100));
  g_data_udp.begin(0);
  g_control_udp.begin(g_control_port);

  g_sensor_ok = g_adxl.begin();

  g_next_sample_due_us = esp_timer_get_time();
  send_hello();
}

void loop() {
  // Cooperative scheduler: each service call handles one concern and returns quickly.
  uint32_t now_ms = millis();
  service_wifi();
  service_data_rx();
  service_sampling();
  service_tx();
  service_hello();
  service_control_rx();
  service_blink();
  report_runtime_status(now_ms);
  // Yield briefly so Wi-Fi and other background tasks can run.
  delay(1);
}
