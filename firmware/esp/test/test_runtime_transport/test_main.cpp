#include <unity.h>

#include <array>

#include "../native_support/generated_protocol_contract_fixtures.h"

#include "../../lib/vibesensor_proto/vibesensor_proto.cpp"
#include "../../src/runtime_led.cpp"
#include "../../src/runtime_queue.cpp"
#include "../../src/runtime_status.cpp"
#include "../../src/runtime_transport.cpp"

namespace {

namespace fixture = vibesensor::test_support;

using vibesensor::runtime::DataFrame;
using vibesensor::runtime::FrameQueueState;
using vibesensor::runtime::LedState;
using vibesensor::runtime::RuntimeStatus;
using vibesensor::runtime::TransportState;

FrameQueueState make_queue_state(DataFrame* frames, size_t capacity) {
  FrameQueueState state{};
  state.queue = frames;
  state.capacity = capacity;
  return state;
}

void append_full_frame(FrameQueueState& state,
                       RuntimeStatus& status,
                       int16_t sample_base,
                       uint64_t first_sample_us,
                       int64_t clock_offset_us) {
  for (uint16_t i = 0; i < vibesensor::runtime::kFrameSamples; ++i) {
    const int16_t value = static_cast<int16_t>(sample_base + static_cast<int16_t>(i));
    vibesensor::runtime::append_sample(state,
                                       status,
                                       value,
                                       static_cast<int16_t>(value + 1),
                                       static_cast<int16_t>(value + 2),
                                       first_sample_us + i,
                                       false,
                                       clock_offset_us);
  }
}

void copy_client_id(uint8_t out[vibesensor::kClientIdBytes],
                    const std::array<uint8_t, vibesensor::kClientIdBytes>& value) {
  for (size_t i = 0; i < value.size(); ++i) {
    out[i] = value[i];
  }
}

}  // namespace

void setUp() {
  arduino_test::reset_time();
  WiFi.reset();
  ESP.setEfuseMac(0xD05A00000001ULL);
  const uint8_t station_mac[vibesensor::kClientIdBytes] = {0xD0, 0x5A, 0x00, 0x00, 0x00, 0x01};
  arduino_test::set_station_mac(station_mac);
}

void test_service_tx_tracks_send_failures_and_retries_after_backoff() {
  DataFrame frames[1] = {};
  FrameQueueState queue_state = make_queue_state(frames, 1);
  RuntimeStatus status{};
  TransportState transport{};
  copy_client_id(transport.client_id, fixture::kCommandClientId);
  transport.handshake_complete = true;
  WiFi.setStatus(WL_CONNECTED);
  arduino_test::set_millis(1000);
  append_full_frame(queue_state, status, 10, 1000, 0);

  transport.data_udp.setBeginPacketResults({0});
  vibesensor::runtime::service_tx(transport, queue_state, status);
  TEST_ASSERT_EQUAL_UINT32(1, status.tx_begin_failures);
  TEST_ASSERT_EQUAL_UINT8(6, status.last_error_code);
  TEST_ASSERT_EQUAL_UINT32(0, transport.data_udp.sent_packets.size());
  TEST_ASSERT_FALSE(vibesensor::runtime::peek_frame(queue_state)->transmitted);

  transport.data_udp.setBeginPacketResults({1, 1});
  transport.data_udp.setEndPacketResults({1, 1});
  vibesensor::runtime::service_tx(transport, queue_state, status);
  TEST_ASSERT_EQUAL_UINT32(1, transport.data_udp.sent_packets.size());
  TEST_ASSERT_TRUE(vibesensor::runtime::peek_frame(queue_state)->transmitted);
  TEST_ASSERT_EQUAL_UINT32(1000, vibesensor::runtime::peek_frame(queue_state)->last_tx_ms);

  vibesensor::runtime::service_tx(transport, queue_state, status);
  TEST_ASSERT_EQUAL_UINT32(1, transport.data_udp.sent_packets.size());

  arduino_test::advance_millis(vibesensor::runtime::kDataRetransmitIntervalMs);
  vibesensor::runtime::service_tx(transport, queue_state, status);
  TEST_ASSERT_EQUAL_UINT32(2, transport.data_udp.sent_packets.size());
}

void test_service_control_rx_handles_handshake_identify_and_sync_clock() {
  DataFrame frames[1] = {};
  FrameQueueState queue_state = make_queue_state(frames, 1);
  RuntimeStatus status{};
  TransportState transport{};
  LedState led_state;
  vibesensor::runtime::begin_leds(led_state);
  copy_client_id(transport.client_id, fixture::kCommandClientId);

  uint8_t hello_ack[vibesensor::kHelloAckBytes] = {};
  const size_t hello_ack_len =
      vibesensor::pack_hello_ack(hello_ack, sizeof(hello_ack), transport.client_id);
  transport.control_udp.queueIncoming(hello_ack, hello_ack_len);
  vibesensor::runtime::service_control_rx(transport, queue_state, led_state, status);
  TEST_ASSERT_TRUE(transport.handshake_complete);

  arduino_test::set_millis(5000);
  transport.control_udp.queueIncoming(
      fixture::kIdentifyPacket.data(), fixture::kIdentifyPacket.size());
  vibesensor::runtime::service_control_rx(transport, queue_state, led_state, status);
  TEST_ASSERT_EQUAL_UINT32(6500, led_state.blink_until_ms);
  TEST_ASSERT_EQUAL_UINT32(1, transport.control_udp.sent_packets.size());
  uint8_t expected_ack[vibesensor::kAckBytes] = {};
  const size_t expected_ack_len = vibesensor::pack_ack(
      expected_ack, sizeof(expected_ack), transport.client_id, fixture::kIdentifyCmdSeq, 0);
  TEST_ASSERT_EQUAL_UINT32(expected_ack_len, transport.control_udp.sent_packets[0].payload.size());
  TEST_ASSERT_EQUAL_UINT8_ARRAY(
      expected_ack, transport.control_udp.sent_packets[0].payload.data(), expected_ack_len);

  arduino_test::set_esp_time(fixture::kSyncClockAckReceiveUs);
  arduino_test::set_esp_time_step(
      fixture::kSyncClockAckSendUs - fixture::kSyncClockAckReceiveUs);
  transport.control_udp.queueIncoming(
      fixture::kSyncClockPacket.data(), fixture::kSyncClockPacket.size());
  vibesensor::runtime::service_control_rx(transport, queue_state, led_state, status);
  TEST_ASSERT_EQUAL_INT64(fixture::kSyncClockAppliedOffsetUs, transport.clock_offset_us);
  TEST_ASSERT_EQUAL_INT64(fixture::kSyncClockAppliedOffsetUs, status.sync_offset_us);
  TEST_ASSERT_EQUAL_UINT32(fixture::kSyncClockRoundTripUs, status.sync_round_trip_us);
  TEST_ASSERT_EQUAL_UINT32(2, transport.control_udp.sent_packets.size());
  TEST_ASSERT_EQUAL_UINT8_ARRAY(fixture::kSyncClockAckPacket.data(),
                                transport.control_udp.sent_packets[1].payload.data(),
                                fixture::kSyncClockAckPacket.size());
}

void test_service_tx_drops_stale_and_retry_exhausted_frames() {
  DataFrame frames[1] = {};
  FrameQueueState queue_state = make_queue_state(frames, 1);
  RuntimeStatus status{};
  TransportState transport{};
  copy_client_id(transport.client_id, fixture::kCommandClientId);
  transport.handshake_complete = true;
  WiFi.setStatus(WL_CONNECTED);

  arduino_test::set_millis(1000);
  append_full_frame(queue_state, status, 10, 1000, 0);
  DataFrame* frame = vibesensor::runtime::peek_frame(queue_state);
  TEST_ASSERT_NOT_NULL(frame);
  frame->queued_ms = 1000U - vibesensor::runtime::kDataMaxFrameAgeMs;

  vibesensor::runtime::service_tx(transport, queue_state, status);
  TEST_ASSERT_EQUAL_UINT32(1, status.tx_stale_frame_drops);
  TEST_ASSERT_EQUAL_UINT8(11, status.last_error_code);
  TEST_ASSERT_NULL(vibesensor::runtime::peek_frame(queue_state));

  append_full_frame(queue_state, status, 100, 2000, 0);
  frame = vibesensor::runtime::peek_frame(queue_state);
  TEST_ASSERT_NOT_NULL(frame);
  frame->transmitted = true;
  frame->queued_ms = 1000;
  frame->first_tx_ms = 1000;
  frame->last_tx_ms = 1000;
  frame->tx_attempts = static_cast<uint8_t>(vibesensor::runtime::kDataMaxRetransmits + 1U);
  arduino_test::set_millis(1000 + vibesensor::runtime::kDataRetransmitIntervalMs);

  vibesensor::runtime::service_tx(transport, queue_state, status);
  TEST_ASSERT_EQUAL_UINT32(1, status.tx_retransmit_limit_drops);
  TEST_ASSERT_EQUAL_UINT8(12, status.last_error_code);
  TEST_ASSERT_NULL(vibesensor::runtime::peek_frame(queue_state));
}

void test_frames_queued_during_a_short_wifi_drop_are_sent_after_reconnect() {
  DataFrame frames[32] = {};
  FrameQueueState queue_state = make_queue_state(frames, 32);
  RuntimeStatus status{};
  TransportState transport{};
  copy_client_id(transport.client_id, fixture::kCommandClientId);
  WiFi.setStatus(WL_DISCONNECTED);

  // One frame from before the drop: 3 s old once Wi-Fi is back.
  arduino_test::set_millis(500);
  append_full_frame(queue_state, status, 0, 500000, 0);
  // 2.5 s without Wi-Fi: 25 frames of 100 ms queue up, none sent or dropped yet.
  for (uint32_t i = 0; i < 25; ++i) {
    const uint32_t now_ms = 1000 + i * 100;
    arduino_test::set_millis(now_ms);
    append_full_frame(queue_state, status, static_cast<int16_t>(i), now_ms * 1000ULL, 0);
    vibesensor::runtime::service_tx(transport, queue_state, status);
  }
  TEST_ASSERT_EQUAL_UINT32(0, transport.data_udp.sent_packets.size());
  TEST_ASSERT_EQUAL_UINT32(0, status.tx_stale_frame_drops);

  arduino_test::set_millis(3500);
  WiFi.setStatus(WL_CONNECTED);
  transport.handshake_complete = true;
  for (int i = 0; i < 64 && vibesensor::runtime::peek_frame(queue_state) != nullptr; ++i) {
    vibesensor::runtime::service_tx(transport, queue_state, status);
    const DataFrame* head = vibesensor::runtime::peek_frame(queue_state);
    if (head != nullptr && head->transmitted) {
      vibesensor::runtime::ack_data_frames(queue_state, head->seq);
    }
  }

  // Everything the drop queued is delivered; only the 3 s old frame is not.
  TEST_ASSERT_NULL(vibesensor::runtime::peek_frame(queue_state));
  TEST_ASSERT_EQUAL_UINT32(1, status.tx_stale_frame_drops);
  TEST_ASSERT_EQUAL_UINT32(25, transport.data_udp.sent_packets.size());
  TEST_ASSERT_EQUAL_UINT32(0, status.queue_overflow_drops);
}

void test_initialize_transport_uses_station_mac_while_wifi_is_down() {
  TransportState transport{};
  WiFi.setStatus(WL_DISCONNECTED);
  const uint8_t station_mac[vibesensor::kClientIdBytes] = {0x24, 0x0A, 0xC4, 0x12, 0x34, 0x63};
  arduino_test::set_station_mac(station_mac);

  vibesensor::runtime::initialize_transport(transport);

  TEST_ASSERT_EQUAL_UINT8_ARRAY(station_mac, transport.client_id, vibesensor::kClientIdBytes);
  TEST_ASSERT_EQUAL_UINT16(
      vibesensor::runtime::kControlPortBase + (0x63U % 100U),
      transport.control_port);
}

void test_initialize_transport_uses_efuse_fallback_client_id_when_mac_read_fails() {
  TransportState transport{};
  const uint8_t unused_mac[vibesensor::kClientIdBytes] = {};
  arduino_test::set_station_mac(unused_mac, ESP_FAIL);
  ESP.setEfuseMac(0x112233445566ULL);

  vibesensor::runtime::initialize_transport(transport);

  const uint8_t expected_client_id[vibesensor::kClientIdBytes] = {
      0x11, 0x22, 0x33, 0x44, 0x55, 0x66};
  TEST_ASSERT_EQUAL_UINT8_ARRAY(expected_client_id, transport.client_id, vibesensor::kClientIdBytes);
  TEST_ASSERT_EQUAL_UINT16(
      vibesensor::runtime::kControlPortBase + 2U,
      transport.control_port);
}

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_service_tx_tracks_send_failures_and_retries_after_backoff);
  RUN_TEST(test_service_control_rx_handles_handshake_identify_and_sync_clock);
  RUN_TEST(test_service_tx_drops_stale_and_retry_exhausted_frames);
  RUN_TEST(test_frames_queued_during_a_short_wifi_drop_are_sent_after_reconnect);
  RUN_TEST(test_initialize_transport_uses_station_mac_while_wifi_is_down);
  RUN_TEST(test_initialize_transport_uses_efuse_fallback_client_id_when_mac_read_fails);
  return UNITY_END();
}
