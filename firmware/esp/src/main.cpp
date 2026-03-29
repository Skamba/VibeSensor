#include <Arduino.h>
#include <esp_system.h>
#include <esp_task_wdt.h>

#include "runtime_config.h"
#include "runtime_led.h"
#include "runtime_queue.h"
#include "runtime_sampling.h"
#include "runtime_status.h"
#include "runtime_transport.h"
#include "runtime_wifi.h"

namespace {

constexpr uint32_t kLoopWatchdogTimeoutSeconds = 15;

struct RuntimeApp {
  vibesensor::runtime::RuntimeStatus status;
  vibesensor::runtime::FrameQueueState queue;
  vibesensor::runtime::SamplingState sampling;
  vibesensor::runtime::TransportState transport;
  vibesensor::runtime::WifiState wifi;
  vibesensor::runtime::LedState led;
};

RuntimeApp g_runtime;

const char* reset_reason_name(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_UNKNOWN:
      return "unknown";
    case ESP_RST_POWERON:
      return "power_on";
    case ESP_RST_EXT:
      return "external";
    case ESP_RST_SW:
      return "software";
    case ESP_RST_PANIC:
      return "panic";
    case ESP_RST_INT_WDT:
      return "interrupt_wdt";
    case ESP_RST_TASK_WDT:
      return "task_wdt";
    case ESP_RST_WDT:
      return "other_wdt";
    case ESP_RST_DEEPSLEEP:
      return "deep_sleep";
    case ESP_RST_BROWNOUT:
      return "brownout";
    case ESP_RST_SDIO:
      return "sdio";
    default:
      return "other";
  }
}

void enable_runtime_watchdog() {
  const esp_err_t err = esp_task_wdt_init(kLoopWatchdogTimeoutSeconds, true);
  if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
    Serial.printf("WARN: failed to init task watchdog (%d)\n", static_cast<int>(err));
    return;
  }
  enableLoopWDT();
}

}  // namespace

void setup() {
  using namespace vibesensor::runtime;

  Serial.begin(115200);
  const esp_reset_reason_t reason = esp_reset_reason();
  Serial.printf(
      "reset reason: %s (%d)\n", reset_reason_name(reason), static_cast<int>(reason));
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

  allocate_frame_queue(g_runtime.queue);
  if (frame_queue_capacity(g_runtime.queue) == 0) {
    Serial.printf("WARN: frame queue alloc failed; running without buffering\n");
  } else {
    Serial.printf("frame queue: %u slots (%u bytes)\n",
                  static_cast<unsigned>(frame_queue_capacity(g_runtime.queue)),
                  static_cast<unsigned>(frame_queue_bytes(g_runtime.queue)));
  }

  begin_leds(g_runtime.led);
  connect_wifi(g_runtime.wifi, g_runtime.status);
  initialize_transport(g_runtime.transport);
  if (!begin_sampling(g_runtime.sampling)) {
    Serial.printf("WARN: sampling task startup failed\n");
  }
  if (send_hello(g_runtime.transport, g_runtime.status)) {
    g_runtime.transport.last_hello_ms = millis();
  }
  enable_runtime_watchdog();
}

void loop() {
  using namespace vibesensor::runtime;

  service_data_rx(g_runtime.transport, g_runtime.queue, g_runtime.status);
  service_control_rx(g_runtime.transport, g_runtime.queue, g_runtime.led, g_runtime.status);
  service_sample_handoff(
      g_runtime.sampling, g_runtime.queue, g_runtime.status, g_runtime.transport.clock_offset_us);
  service_tx(g_runtime.transport, g_runtime.queue, g_runtime.status);
  service_hello(g_runtime.transport, g_runtime.status);
  service_wifi(g_runtime.wifi, g_runtime.status);

  const uint32_t now_ms = millis();
  service_blink(g_runtime.led, now_ms);
  const SamplingStatusSnapshot sampling_status = snapshot_sampling_status(g_runtime.sampling);
  report_runtime_status(
      g_runtime.status, sampling_status, frame_queue_size(g_runtime.queue), frame_queue_capacity(g_runtime.queue), now_ms);
  delay(0);
}
