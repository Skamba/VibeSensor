#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_heap_caps.h>
#include <esp_timer.h>

#include "adxl345.h"
#include "vibesensor_contracts.h"
#include "vibesensor_network.h"
#include "vibesensor_proto.h"

namespace {

constexpr char kClientName[] = "vibe-node";
constexpr char kFirmwareVersion[] = "esp32-atom-0.1";

#ifndef VIBESENSOR_SAMPLE_RATE_HZ
#define VIBESENSOR_SAMPLE_RATE_HZ 800
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

constexpr uint16_t kSampleRateHz = static_cast<uint16_t>(VIBESENSOR_SAMPLE_RATE_HZ);
constexpr uint16_t kFrameSamples = static_cast<uint16_t>(VIBESENSOR_FRAME_SAMPLES);
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
constexpr size_t kMaxDatagramBytes = 1500;
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

// Default I2C pins for M5Stack ATOM Lite Unit port (4-pin cable).
constexpr int kI2cSdaPin = 26;
constexpr int kI2cSclPin = 32;
constexpr uint8_t kAdxlI2cAddr = 0x53;

#ifndef LED_BUILTIN
constexpr int LED_BUILTIN = 27;
#endif
#ifndef VIBESENSOR_LED_PIXELS
constexpr uint16_t kLedPixels = 25;
#else
constexpr uint16_t kLedPixels = static_cast<uint16_t>(VIBESENSOR_LED_PIXELS);
#endif
constexpr uint16_t kLedWavePeriodMs = 900;
constexpr uint16_t kLedWaveStepMs = 30;

struct DataFrame {
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
uint32_t g_led_next_update_ms = 0;
uint8_t g_identify_wave_shift = 0;
bool g_identify_leds_active = false;
uint32_t g_last_wifi_retry_ms = 0;
uint32_t g_queue_overflow_drops = 0;
uint32_t g_last_wifi_scan_ms = 0;
uint8_t g_target_bssid[6] = {};
bool g_has_target_bssid = false;
int32_t g_target_channel = 0;
bool g_has_last_real_sample = false;
int16_t g_last_real_x = 0;
int16_t g_last_real_y = 0;
int16_t g_last_real_z = 0;

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

void render_identify_wave(uint32_t now_ms) {
  const uint16_t phase = static_cast<uint16_t>(now_ms % kLedWavePeriodMs);
  const uint16_t base = static_cast<uint16_t>((phase * 255U) / kLedWavePeriodMs);

  for (uint16_t i = 0; i < kLedPixels; ++i) {
    uint16_t pixel_span = static_cast<uint16_t>(kLedPixels == 0 ? 1 : kLedPixels);
    uint8_t wave = static_cast<uint8_t>(
        (base + g_identify_wave_shift + (i * (255U / pixel_span))) & 0xFF);
    uint8_t tri = wave < 128 ? static_cast<uint8_t>(wave * 2) : static_cast<uint8_t>((255 - wave) * 2);

    uint8_t r = static_cast<uint8_t>(10 + (tri / 5));
    uint8_t g = static_cast<uint8_t>(35 + (tri / 2));
    uint8_t b = static_cast<uint8_t>(45 + tri);
    g_led_strip.setPixelColor(i, g_led_strip.Color(r, g, b));
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
    g_queue_overflow_drops++;
    g_q_tail = (g_q_tail + 1) % g_queue_capacity;
    g_q_size--;
  }

  DataFrame& frame = g_queue[g_q_head];
  frame.seq = g_next_seq++;
  frame.t0_us = g_build_t0_us;
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
    g_sensor_batch_count = g_adxl.read_samples(g_sensor_batch_xyz, kSensorReadBatchSamples);
    g_sensor_batch_index = 0;
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

void sample_once() {
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
    // Never inject synthetic vibration in production.
    // If FIFO is momentarily empty, hold last real sample to avoid fake spectral peaks.
    if (g_has_last_real_sample) {
      x = g_last_real_x;
      y = g_last_real_y;
      z = g_last_real_z;
    } else {
      x = 0;
      y = 0;
      z = 0;
    }
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
}

void service_sampling() {
  const uint64_t step_us = 1000000ULL / kSampleRateHz;
  uint64_t now = esp_timer_get_time();
  size_t catch_up_count = 0;
  while (static_cast<int64_t>(now - g_next_sample_due_us) >= 0 &&
         catch_up_count < kMaxCatchUpSamplesPerLoop) {
    sample_once();
    g_next_sample_due_us += step_us;
    catch_up_count++;
    now = esp_timer_get_time();
  }

  if (static_cast<int64_t>(now - g_next_sample_due_us) >= 0) {
    uint64_t lag_us = now - g_next_sample_due_us;
    uint64_t skipped = (lag_us / step_us) + 1;
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
  g_control_udp.endPacket();
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
      drop_front_frame();
      continue;
    }

    if (g_data_udp.beginPacket(vibesensor_network::server_ip, kServerDataPort) != 1) {
      break;
    }
    g_data_udp.write(packet, len);
    if (g_data_udp.endPacket() != 1) {
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
  g_control_udp.endPacket();
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
  bool ok = vibesensor::parse_cmd(packet,
                                  read,
                                  g_client_id,
                                  &cmd_id,
                                  &cmd_seq,
                                  &identify_ms);
  if (!ok) {
    return;
  }

  if (cmd_id == vibesensor::kCmdIdentify) {
    g_blink_until_ms = millis() + identify_ms;
    g_led_next_update_ms = 0;
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
    render_identify_wave(now);
    g_identify_leds_active = true;
    g_identify_wave_shift = static_cast<uint8_t>(g_identify_wave_shift + 3);
    g_led_next_update_ms = now + kLedWaveStepMs;
  }
}

bool connect_wifi() {
  WiFi.mode(WIFI_STA);
#ifdef WIFI_AUTH_WPA_PSK
  WiFi.setMinSecurity(WIFI_AUTH_WPA_PSK);
#endif
  WiFi.setSleep(false);
  refresh_target_ap();
  for (uint8_t attempt = 1; attempt <= kWifiInitialConnectAttempts; ++attempt) {
    begin_target_wifi();
    uint32_t start_ms = millis();
    while (WiFi.status() != WL_CONNECTED) {
      if (millis() - start_ms >= kWifiConnectTimeoutMs) {
        break;
      }
      delay(300);
    }
    if (WiFi.status() == WL_CONNECTED) {
      return true;
    }
    WiFi.disconnect(true, true);
    delay(kWifiRetryBackoffMs);
  }
  return false;
}

void service_wifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }
  uint32_t now = millis();
  if (now - g_last_wifi_retry_ms < kWifiRetryIntervalMs) {
    return;
  }
  g_last_wifi_retry_ms = now;
  if (now - g_last_wifi_scan_ms >= kWifiScanIntervalMs) {
    g_last_wifi_scan_ms = now;
    refresh_target_ap();
  }
  WiFi.disconnect(true, true);
  begin_target_wifi();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  for (size_t cap = kFrameQueueLenTarget; cap >= kFrameQueueLenMin; --cap) {
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
  service_wifi();
  service_data_rx();
  service_sampling();
  service_tx();
  service_hello();
  service_control_rx();
  service_blink();
  delay(1);
}
