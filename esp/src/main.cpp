#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_timer.h>

#include "adxl345.h"
#include "vibesenser_proto.h"

namespace {

constexpr char kWifiSsid[] = "VibeSensor";
constexpr char kWifiPsk[] = "vibesensor123";
constexpr char kClientName[] = "vibe-node";
constexpr char kFirmwareVersion[] = "esp-c3-0.1";

constexpr uint16_t kSampleRateHz = 800;
constexpr uint16_t kFrameSamples = 200;
constexpr uint16_t kServerDataPort = 9000;
constexpr uint16_t kServerControlPort = 9001;
constexpr size_t kFrameQueueLen = 4;
constexpr size_t kMaxDatagramBytes = 1500;

// Default pins for LOLIN C3 Mini. Edit these for your wiring.
constexpr int kSpiSckPin = 4;
constexpr int kSpiMisoPin = 5;
constexpr int kSpiMosiPin = 6;
constexpr int kAdxlCsPin = 7;

#ifndef LED_BUILTIN
constexpr int LED_BUILTIN = 8;
#endif

const IPAddress kServerIp(192, 168, 4, 1);

struct DataFrame {
  uint32_t seq;
  uint64_t t0_us;
  uint16_t sample_count;
  int16_t xyz[kFrameSamples * 3];
};

SPIClass g_spi(FSPI);
ADXL345 g_adxl(g_spi, kAdxlCsPin, kSpiSckPin, kSpiMisoPin, kSpiMosiPin);
WiFiUDP g_data_udp;
WiFiUDP g_control_udp;

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

uint32_t g_blink_until_ms = 0;
uint32_t g_blink_toggle_ms = 0;
bool g_led_state = false;

inline void set_led(bool on) {
  digitalWrite(LED_BUILTIN, on ? HIGH : LOW);
  g_led_state = on;
}

void enqueue_frame() {
  if (g_build_count == 0) {
    return;
  }

  if (g_q_size == kFrameQueueLen) {
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

void sample_once() {
  int16_t x = 0;
  int16_t y = 0;
  int16_t z = 0;

  if (g_sensor_ok) {
    int16_t one_sample[3];
    size_t got = g_adxl.read_samples(one_sample, 1);
    if (got == 1) {
      x = one_sample[0];
      y = one_sample[1];
      z = one_sample[2];
    } else {
      synth_sample(&x, &y, &z);
    }
  } else {
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
  while (static_cast<int64_t>(now - g_next_sample_due_us) >= 0) {
    sample_once();
    g_next_sample_due_us += step_us;
    now = esp_timer_get_time();
  }
}

void send_hello() {
  uint8_t packet[128];
  size_t len = vibesenser::pack_hello(packet,
                                      sizeof(packet),
                                      g_client_id,
                                      g_control_port,
                                      kSampleRateHz,
                                      kClientName,
                                      kFirmwareVersion);
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
  size_t len = vibesenser::pack_data(packet,
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
  size_t len = vibesenser::pack_ack(packet, sizeof(packet), g_client_id, cmd_seq, status);
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
  bool ok = vibesenser::parse_cmd(packet,
                                  read,
                                  g_client_id,
                                  &cmd_id,
                                  &cmd_seq,
                                  &identify_ms);
  if (!ok) {
    return;
  }

  if (cmd_id == vibesenser::kCmdIdentify) {
    g_blink_until_ms = millis() + identify_ms;
    g_blink_toggle_ms = 0;
    send_ack(cmd_seq, 0);
  } else {
    send_ack(cmd_seq, 2);
  }
}

void service_blink() {
  uint32_t now = millis();
  if (g_blink_until_ms == 0 || static_cast<int32_t>(g_blink_until_ms - now) <= 0) {
    if (g_led_state) {
      set_led(false);
    }
    g_blink_until_ms = 0;
    return;
  }

  if (now >= g_blink_toggle_ms) {
    set_led(!g_led_state);
    g_blink_toggle_ms = now + 120;
  }
}

void connect_wifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(kWifiSsid, kWifiPsk);
  Serial.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Connected IP: ");
  Serial.println(WiFi.localIP());
}

}  // namespace

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  set_led(false);

  connect_wifi();

  String mac = WiFi.macAddress();
  if (!vibesenser::parse_mac(mac, g_client_id)) {
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
  service_sampling();
  service_tx();
  service_hello();
  service_control_rx();
  service_blink();
  delay(1);
}
