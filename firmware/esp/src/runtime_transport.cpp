#include "runtime_transport.h"

#include <WiFi.h>
#include <esp_timer.h>
#include <string.h>

#include "runtime_config.h"
#include "vibesensor_network.h"
#include "vibesensor_proto.h"

namespace vibesensor::runtime {
namespace {

bool send_control_packet(TransportState& state,
                         RuntimeStatus& status,
                         const uint8_t* packet,
                         size_t len,
                         uint8_t error_code) {
  if (state.control_udp.beginPacket(vibesensor_network::server_ip, kServerControlPort) != 1) {
    set_last_error(status, error_code);
    return false;
  }
  state.control_udp.write(packet, len);
  if (state.control_udp.endPacket() != 1) {
    set_last_error(status, error_code);
    return false;
  }
  return true;
}

void send_ack(TransportState& state,
              RuntimeStatus& status,
              uint32_t cmd_seq,
              uint8_t ack_status) {
  uint8_t packet[vibesensor::kAckBytes];
  size_t len = vibesensor::pack_ack(
      packet, sizeof(packet), state.client_id, cmd_seq, ack_status);
  if (len == 0) {
    return;
  }
  send_control_packet(state, status, packet, len, 8);
}

void send_sync_clock_ack(TransportState& state,
                         RuntimeStatus& status,
                         uint32_t cmd_seq,
                         uint64_t device_receive_us,
                         uint64_t device_send_us,
                         uint8_t ack_status) {
  uint8_t packet[vibesensor::kAckSyncClockBytes];
  size_t len = vibesensor::pack_ack_sync_clock(packet,
                                               sizeof(packet),
                                               state.client_id,
                                               cmd_seq,
                                               device_receive_us,
                                               device_send_us,
                                               ack_status);
  if (len == 0) {
    return;
  }
  send_control_packet(state, status, packet, len, 8);
}

}  // namespace

void initialize_transport(TransportState& state) {
  String mac = WiFi.macAddress();
  if (!vibesensor::parse_mac(mac, state.client_id)) {
    const uint8_t fallback[vibesensor::kClientIdBytes] = {0xD0, 0x5A, 0x00, 0x00, 0x00, 0x01};
    memcpy(state.client_id, fallback, sizeof(state.client_id));
  }
  state.control_port =
      static_cast<uint16_t>(kControlPortBase + (state.client_id[5] % 100));
  state.handshake_complete = false;
  state.data_udp.begin(0);
  state.control_udp.begin(state.control_port);
}

bool send_hello(TransportState& state, RuntimeStatus& status) {
  if (WiFi.status() != WL_CONNECTED) {
    state.handshake_complete = false;
    return false;
  }
  uint8_t packet[128];
  size_t len = vibesensor::pack_hello(packet,
                                      sizeof(packet),
                                      state.client_id,
                                      state.control_port,
                                      kSampleRateHz,
                                      kFrameSamples,
                                      kClientName,
                                      kFirmwareVersion,
                                      status.queue_overflow_drops,
                                      vibesensor::kHelloCapExplicitAck);
  if (len == 0) {
    return false;
  }
  return send_control_packet(state, status, packet, len, 4);
}

void service_hello(TransportState& state, RuntimeStatus& status) {
  uint32_t now = millis();
  if (now - state.last_hello_ms >= kHelloIntervalMs) {
    if (send_hello(state, status)) {
      state.last_hello_ms = now;
    }
  }
}

void service_tx(TransportState& state,
                FrameQueueState& queue_state,
                RuntimeStatus& status) {
  if (WiFi.status() != WL_CONNECTED) {
    state.handshake_complete = false;
    return;
  }
  if (!state.handshake_complete) {
    return;
  }

  uint8_t packet[kMaxDatagramBytes];
  for (size_t sent = 0; sent < kMaxTxFramesPerLoop; ++sent) {
    DataFrame* frame = peek_frame(queue_state);
    if (frame == nullptr) {
      return;
    }

    uint32_t now_ms = millis();
    if (frame->transmitted &&
        (now_ms - frame->last_tx_ms) < kDataRetransmitIntervalMs) {
      return;
    }

    size_t len = vibesensor::pack_data(packet,
                                       sizeof(packet),
                                       state.client_id,
                                       frame->seq,
                                       frame->t0_us,
                                       frame->xyz,
                                       frame->sample_count);
    if (len == 0) {
      status.tx_pack_failures++;
      set_last_error(status, 5);
      drop_front_frame(queue_state);
      continue;
    }

    if (state.data_udp.beginPacket(vibesensor_network::server_ip, kServerDataPort) != 1) {
      status.tx_begin_failures++;
      set_last_error(status, 6);
      break;
    }
    state.data_udp.write(packet, len);
    if (state.data_udp.endPacket() != 1) {
      status.tx_end_failures++;
      set_last_error(status, 7);
      break;
    }
    frame->transmitted = true;
    frame->last_tx_ms = now_ms;
  }
}

void service_control_rx(TransportState& state,
                        FrameQueueState& queue_state,
                        LedState& led_state,
                        RuntimeStatus& status) {
  int packet_size = state.control_udp.parsePacket();
  if (packet_size <= 0) {
    return;
  }
  uint8_t packet[64];
  size_t read = static_cast<size_t>(state.control_udp.read(packet, sizeof(packet)));
  if (read == 0) {
    return;
  }

  if (packet[0] == vibesensor::kMsgHelloAck) {
    if (!vibesensor::parse_hello_ack(packet, read, state.client_id)) {
      status.control_parse_errors++;
      set_last_error(status, 9);
      return;
    }
    state.handshake_complete = true;
    return;
  }

  if (packet[0] == vibesensor::kMsgDataAck) {
    uint32_t last_seq_received = 0;
    bool ok_ack = vibesensor::parse_data_ack(
        packet, read, state.client_id, &last_seq_received);
    if (ok_ack) {
      ack_data_frames(queue_state, last_seq_received);
    }
    return;
  }

  uint8_t cmd_id = 0;
  uint32_t cmd_seq = 0;
  uint16_t identify_ms = 0;
  uint64_t server_time_us = 0;
  int64_t applied_offset_us = 0;
  uint32_t round_trip_us = 0;
  bool ok = vibesensor::parse_cmd(packet,
                                  read,
                                  state.client_id,
                                  &cmd_id,
                                  &cmd_seq,
                                  &identify_ms,
                                  &server_time_us,
                                  &applied_offset_us,
                                  &round_trip_us);
  if (!ok) {
    status.control_parse_errors++;
    set_last_error(status, 9);
    return;
  }

  if (cmd_id == vibesensor::kCmdIdentify) {
    identify_ms = identify_ms > kMaxIdentifyDurationMs ? kMaxIdentifyDurationMs : identify_ms;
    start_identify(led_state, identify_ms, millis());
    send_ack(state, status, cmd_seq, 0);
  } else if (cmd_id == vibesensor::kCmdSyncClock) {
    const uint64_t device_receive_us = static_cast<uint64_t>(esp_timer_get_time());
    if (round_trip_us > 0) {
      state.clock_offset_us = applied_offset_us;
      status.sync_offset_us = applied_offset_us;
      status.sync_round_trip_us = round_trip_us;
    }
    const uint64_t device_send_us = static_cast<uint64_t>(esp_timer_get_time());
    send_sync_clock_ack(
        state, status, cmd_seq, device_receive_us, device_send_us, 0);
  } else {
    send_ack(state, status, cmd_seq, 2);
  }
}

void service_data_rx(TransportState& state,
                     FrameQueueState& queue_state,
                     RuntimeStatus& status) {
  uint8_t packet[32];
  for (size_t i = 0; i < kMaxDataAckPacketsPerLoop; ++i) {
    int packet_size = state.data_udp.parsePacket();
    if (packet_size <= 0) {
      return;
    }
    size_t read = static_cast<size_t>(state.data_udp.read(packet, sizeof(packet)));
    if (read == 0 || packet[0] != vibesensor::kMsgDataAck) {
      continue;
    }
    uint32_t last_seq_received = 0;
    bool ok_ack = vibesensor::parse_data_ack(
        packet, read, state.client_id, &last_seq_received);
    if (ok_ack) {
      ack_data_frames(queue_state, last_seq_received);
    } else {
      status.data_ack_parse_errors++;
      set_last_error(status, 10);
    }
  }
}

}  // namespace vibesensor::runtime
