#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_timer.h>

#include "adxl345.h"
#include "vibesensor_proto.h"

namespace {

constexpr char kWifiSsid[] = "VibeSensor";
constexpr char kWifiPsk[] = "vibesensor123";
constexpr char kClientName[] = "vibe-node";
constexpr char kFirmwareVersion[] = "esp32-atom-0.1";

constexpr uint16_t kSampleRateHz = 800;
constexpr uint16_t kFrameSamples = 200;
constexpr uint16_t kServerDataPort = 9000;
constexpr uint16_t kServerControlPort = 9001;
constexpr size_t kFrameQueueLen = 4;
constexpr size_t kMaxDatagramBytes = 1500;
constexpr uint32_t kWifiConnectTimeoutMs = 15000;
constexpr uint32_t kWifiRetryBackoffMs = 2000;
constexpr uint32_t kWifiRetryIntervalMs = 4000;
constexpr uint8_t kWifiInitialConnectAttempts = 3;
constexpr size_t kMaxCatchUpSamplesPerLoop = 8;
constexpr size_t kSensorReadBatchSamples = 8;

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

const IPAddress kServerIp(192, 168, 4, 1);

struct DataFrame {
  uint32_t seq;
  uint64_t t0_us;
  uint16_t sample_count;
  int16_t xyz[kFrameSamples * 3];
};

TwoWire& g_i2c = Wire;
ADXL345 g_adxl(g_i2c, kAdxlI2cAddr, kI2cSdaPin, kI2cSclPin);
WiFiUDP g_data_udp;
WiFiUDP g_control_udp;
Adafruit_NeoPixel g_led_strip(kLedPixels, LED_BUILTIN, NEO_GRB + NEO_KHZ800);

uint8_t g_client_id[6] = {};
uint16_t g_control_port = 9010;

DataFrame g_queue[kFrameQueueLen];
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

  if (g_q_size == kFrameQueueLen) {
    g_queue_overflow_drops++;
    g_q_tail = (g_q_tail + 1) % kFrameQueueLen;
    g_q_size--;
  }

  DataFrame& frame = g_queue[g_q_head];
  frame.seq = g_next_seq++;
  frame.t0_us = g_build_t0_us;
  frame.sample_count = g_build_count;
  memcpy(frame.xyz, g_build_xyz, static_cast<size_t>(g_build_count) * 3 * sizeof(int16_t));

  g_q_head = (g_q_head + 1) % kFrameQueueLen;
  g_q_size++;
  g_build_count = 0;
}

bool pop_frame(DataFrame* out) {
  if (g_q_size == 0 || out == nullptr) {
    return false;
  }
  *out = g_queue[g_q_tail];
  g_q_tail = (g_q_tail + 1) % kFrameQueueLen;
  g_q_size--;
  return true;
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

  if (!next_sensor_sample(&x, &y, &z)) {
    synth_sample(&x, &y, &z);
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
                                      kClientName,
                                      kFirmwareVersion,
                                      g_queue_overflow_drops);
  if (len == 0) {
    return;
  }

  g_control_udp.beginPacket(kServerIp, kServerControlPort);
  g_control_udp.write(packet, len);
  g_control_udp.endPacket();
}

void service_hello() {
  uint32_t now = millis();
  if (now - g_last_hello_ms >= 2000) {
    send_hello();
    g_last_hello_ms = now;
  }
}

void service_tx() {
  DataFrame frame;
  if (!pop_frame(&frame)) {
    return;
  }

  uint8_t packet[kMaxDatagramBytes];
  size_t len = vibesensor::pack_data(packet,
                                     sizeof(packet),
                                     g_client_id,
                                     frame.seq,
                                     frame.t0_us,
                                     frame.xyz,
                                     frame.sample_count);
  if (len == 0) {
    return;
  }

  g_data_udp.beginPacket(kServerIp, kServerDataPort);
  g_data_udp.write(packet, len);
  g_data_udp.endPacket();
}

void send_ack(uint32_t cmd_seq, uint8_t status) {
  uint8_t packet[16];
  size_t len = vibesensor::pack_ack(packet, sizeof(packet), g_client_id, cmd_seq, status);
  if (len == 0) {
    return;
  }
  g_control_udp.beginPacket(kServerIp, kServerControlPort);
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
  for (uint8_t attempt = 1; attempt <= kWifiInitialConnectAttempts; ++attempt) {
    WiFi.begin(kWifiSsid, kWifiPsk);
    Serial.printf("Connecting WiFi (attempt %u/%u)", attempt, kWifiInitialConnectAttempts);
    uint32_t start_ms = millis();
    while (WiFi.status() != WL_CONNECTED) {
      if (millis() - start_ms >= kWifiConnectTimeoutMs) {
        break;
      }
      delay(300);
      Serial.print(".");
    }
    if (WiFi.status() == WL_CONNECTED) {
      Serial.println();
      Serial.print("Connected IP: ");
      Serial.println(WiFi.localIP());
      return true;
    }
    Serial.println("\nWiFi connect timeout.");
    WiFi.disconnect(true, true);
    delay(kWifiRetryBackoffMs);
  }
  Serial.println("WiFi unavailable after retries; continuing and retrying in loop.");
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
  Serial.println("WiFi disconnected, retrying...");
  WiFi.disconnect(true, true);
  WiFi.begin(kWifiSsid, kWifiPsk);
}

}  // namespace

void setup() {
  Serial.begin(115200);
  g_led_strip.begin();
  clear_leds();

  connect_wifi();

  String mac = WiFi.macAddress();
  if (!vibesensor::parse_mac(mac, g_client_id)) {
    Serial.println("Failed to parse MAC, using fallback ID.");
    const uint8_t fallback[6] = {0xD0, 0x5A, 0x00, 0x00, 0x00, 0x01};
    memcpy(g_client_id, fallback, sizeof(g_client_id));
  }

  g_control_port = static_cast<uint16_t>(9010 + (g_client_id[5] % 100));
  g_data_udp.begin(0);
  g_control_udp.begin(g_control_port);

  g_sensor_ok = g_adxl.begin();
  if (g_sensor_ok) {
    Serial.println("ADXL345 detected.");
  } else {
    Serial.println("ADXL345 not detected, synthetic mode enabled.");
  }

  g_next_sample_due_us = esp_timer_get_time();
  send_hello();
}

void loop() {
  service_wifi();
  service_sampling();
  service_tx();
  service_hello();
  service_control_rx();
  service_blink();
  delay(1);
}
