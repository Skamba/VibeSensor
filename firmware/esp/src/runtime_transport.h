#pragma once

#include <Arduino.h>
#include <WiFiUdp.h>

#include "runtime_led.h"
#include "runtime_queue.h"
#include "runtime_status.h"

namespace vibesensor::runtime {

struct TransportState {
  WiFiUDP data_udp;
  WiFiUDP control_udp;
  uint8_t client_id[6] = {};
  uint16_t control_port = 0;
  uint32_t last_hello_ms = 0;
  bool handshake_complete = false;
  int64_t clock_offset_us = 0;
};

void initialize_transport(TransportState& state);
bool send_hello(TransportState& state, RuntimeStatus& status);
void service_hello(TransportState& state, RuntimeStatus& status);
void service_tx(TransportState& state,
                FrameQueueState& queue_state,
                RuntimeStatus& status);
void service_control_rx(TransportState& state,
                        FrameQueueState& queue_state,
                        LedState& led_state,
                        RuntimeStatus& status);
void service_data_rx(TransportState& state,
                     FrameQueueState& queue_state,
                     RuntimeStatus& status);

}  // namespace vibesensor::runtime
