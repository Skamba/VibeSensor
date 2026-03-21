#include <Arduino.h>
#include <esp_timer.h>

#include "runtime_config.h"
#include "runtime_led.h"
#include "runtime_queue.h"
#include "runtime_sampling.h"
#include "runtime_status.h"
#include "runtime_transport.h"
#include "runtime_wifi.h"

namespace {

struct RuntimeApp {
  vibesensor::runtime::RuntimeStatus status;
  vibesensor::runtime::FrameQueueState queue;
  vibesensor::runtime::SamplingState sampling;
  vibesensor::runtime::TransportState transport;
  vibesensor::runtime::WifiState wifi;
  vibesensor::runtime::LedState led;
};

RuntimeApp g_runtime;

}  // namespace

void setup() {
  using namespace vibesensor::runtime;

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
  begin_sensor(g_runtime.sampling);
  reset_sampling_schedule(g_runtime.sampling, esp_timer_get_time());
  send_hello(g_runtime.transport, g_runtime.status);
  g_runtime.transport.last_hello_ms = millis();
}

void loop() {
  using namespace vibesensor::runtime;

  uint32_t now_ms = millis();
  service_wifi(g_runtime.wifi, g_runtime.status);
  service_data_rx(g_runtime.transport, g_runtime.queue, g_runtime.status);
  service_sampling(
      g_runtime.sampling, g_runtime.queue, g_runtime.status, g_runtime.transport.clock_offset_us);
  service_tx(g_runtime.transport, g_runtime.queue, g_runtime.status);
  service_hello(g_runtime.transport, g_runtime.status);
  service_control_rx(g_runtime.transport, g_runtime.queue, g_runtime.led, g_runtime.status);
  service_blink(g_runtime.led, now_ms);
  report_runtime_status(g_runtime.status,
                        frame_queue_size(g_runtime.queue),
                        frame_queue_capacity(g_runtime.queue),
                        now_ms);
  delay(1);
}
