#include <unity.h>

#include <array>

#include "../native_support/generated_protocol_contract_fixtures.h"

#include "../../lib/vibesensor_proto/vibesensor_proto.cpp"

namespace fixture = vibesensor::test_support;

template <size_t N>
void expect_packet_matches_fixture(const std::array<uint8_t, N>& expected,
                                   const std::array<uint8_t, N>& actual,
                                   size_t len) {
  TEST_ASSERT_EQUAL_UINT32(expected.size(), len);
  TEST_ASSERT_EQUAL_UINT8_ARRAY(expected.data(), actual.data(), expected.size());
}

void test_pack_hello_matches_python_fixture() {
  std::array<uint8_t, fixture::kHelloPacket.size()> packet = {};
  const size_t len = vibesensor::pack_hello(packet.data(),
                                            packet.size(),
                                            fixture::kHelloClientId.data(),
                                            fixture::kHelloControlPort,
                                            fixture::kHelloSampleRateHz,
                                            fixture::kHelloFrameSamples,
                                            fixture::kHelloName,
                                            fixture::kHelloFirmwareVersion,
                                            fixture::kHelloQueueOverflowDrops,
                                            fixture::kHelloCapabilities);
  expect_packet_matches_fixture(fixture::kHelloPacket, packet, len);
}

void test_pack_hello_ack_matches_python_fixture() {
  std::array<uint8_t, fixture::kHelloAckPacket.size()> packet = {};
  const size_t len = vibesensor::pack_hello_ack(
      packet.data(), packet.size(), fixture::kHelloClientId.data());
  expect_packet_matches_fixture(fixture::kHelloAckPacket, packet, len);
}

void test_parse_hello_ack_matches_python_fixture() {
  const bool ok = vibesensor::parse_hello_ack(fixture::kHelloAckPacket.data(),
                                              fixture::kHelloAckPacket.size(),
                                              fixture::kHelloClientId.data());
  TEST_ASSERT_TRUE(ok);
}

void test_pack_data_matches_python_fixture() {
  std::array<uint8_t, fixture::kDataPacket.size()> packet = {};
  const size_t len = vibesensor::pack_data(packet.data(),
                                           packet.size(),
                                           fixture::kDataClientId.data(),
                                           fixture::kDataSeq,
                                           fixture::kDataT0Us,
                                           fixture::kDataSamples.data(),
                                           fixture::kDataSampleCount);
  expect_packet_matches_fixture(fixture::kDataPacket, packet, len);
}

void test_parse_identify_matches_python_fixture() {
  uint8_t cmd_id = 0;
  uint32_t cmd_seq = 0;
  uint16_t identify_duration_ms = 0;
  const bool ok = vibesensor::parse_cmd(fixture::kIdentifyPacket.data(),
                                        fixture::kIdentifyPacket.size(),
                                        fixture::kCommandClientId.data(),
                                        &cmd_id,
                                        &cmd_seq,
                                        &identify_duration_ms,
                                        nullptr);
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_UINT8(vibesensor::kCmdIdentify, cmd_id);
  TEST_ASSERT_EQUAL_UINT32(fixture::kIdentifyCmdSeq, cmd_seq);
  TEST_ASSERT_EQUAL_UINT16(fixture::kIdentifyDurationMs, identify_duration_ms);
}

void test_parse_sync_clock_matches_python_fixture() {
  uint8_t cmd_id = 0;
  uint32_t cmd_seq = 0;
  uint16_t identify_duration_ms = 0;
  uint64_t server_time_us = 0;
  int64_t applied_offset_us = 0;
  uint32_t round_trip_us = 0;
  const bool ok = vibesensor::parse_cmd(fixture::kSyncClockPacket.data(),
                                        fixture::kSyncClockPacket.size(),
                                        fixture::kCommandClientId.data(),
                                        &cmd_id,
                                        &cmd_seq,
                                        &identify_duration_ms,
                                        &server_time_us,
                                        &applied_offset_us,
                                        &round_trip_us);
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_UINT8(vibesensor::kCmdSyncClock, cmd_id);
  TEST_ASSERT_EQUAL_UINT32(fixture::kSyncClockCmdSeq, cmd_seq);
  TEST_ASSERT_EQUAL_UINT64(fixture::kSyncClockServerTimeUs, server_time_us);
  TEST_ASSERT_EQUAL_INT64(fixture::kSyncClockAppliedOffsetUs, applied_offset_us);
  TEST_ASSERT_EQUAL_UINT32(fixture::kSyncClockRoundTripUs, round_trip_us);
}

void test_pack_sync_clock_ack_matches_python_fixture() {
  std::array<uint8_t, fixture::kSyncClockAckPacket.size()> packet = {};
  const size_t len = vibesensor::pack_ack_sync_clock(packet.data(),
                                                     packet.size(),
                                                     fixture::kCommandClientId.data(),
                                                     fixture::kSyncClockCmdSeq,
                                                     fixture::kSyncClockAckReceiveUs,
                                                     fixture::kSyncClockAckSendUs,
                                                     0);
  expect_packet_matches_fixture(fixture::kSyncClockAckPacket, packet, len);
}

void test_pack_ack_matches_python_fixture() {
  std::array<uint8_t, fixture::kAckPacket.size()> packet = {};
  const size_t len = vibesensor::pack_ack(packet.data(),
                                          packet.size(),
                                          fixture::kAckClientId.data(),
                                          fixture::kAckCmdSeq,
                                          fixture::kAckStatus);
  expect_packet_matches_fixture(fixture::kAckPacket, packet, len);
}

void test_parse_data_ack_matches_python_fixture() {
  uint32_t last_seq_received = 0;
  const bool ok = vibesensor::parse_data_ack(fixture::kDataAckPacket.data(),
                                             fixture::kDataAckPacket.size(),
                                             fixture::kDataClientId.data(),
                                             &last_seq_received);
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_UINT32(fixture::kDataAckLastSeqReceived, last_seq_received);
}

void test_pack_data_ack_matches_python_fixture() {
  std::array<uint8_t, fixture::kDataAckPacket.size()> packet = {};
  const size_t len = vibesensor::pack_data_ack(packet.data(),
                                               packet.size(),
                                               fixture::kDataClientId.data(),
                                               fixture::kDataAckLastSeqReceived);
  expect_packet_matches_fixture(fixture::kDataAckPacket, packet, len);
}

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_pack_hello_matches_python_fixture);
  RUN_TEST(test_pack_hello_ack_matches_python_fixture);
  RUN_TEST(test_parse_hello_ack_matches_python_fixture);
  RUN_TEST(test_pack_data_matches_python_fixture);
  RUN_TEST(test_parse_identify_matches_python_fixture);
  RUN_TEST(test_parse_sync_clock_matches_python_fixture);
  RUN_TEST(test_pack_sync_clock_ack_matches_python_fixture);
  RUN_TEST(test_pack_ack_matches_python_fixture);
  RUN_TEST(test_parse_data_ack_matches_python_fixture);
  RUN_TEST(test_pack_data_ack_matches_python_fixture);
  return UNITY_END();
}
