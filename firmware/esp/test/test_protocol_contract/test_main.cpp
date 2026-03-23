#include <unity.h>

#include "../native_support/generated_protocol_contract_fixtures.h"

#include "../../lib/vibesensor_proto/vibesensor_proto.cpp"

namespace fixture = vibesensor::test_support;

void test_pack_hello_matches_python_fixture() {
  uint8_t packet[fixture::kHelloPacket.size()] = {};
  const size_t len = vibesensor::pack_hello(packet,
                                            sizeof(packet),
                                            fixture::kHelloClientId.data(),
                                            fixture::kHelloControlPort,
                                            fixture::kHelloSampleRateHz,
                                            fixture::kHelloFrameSamples,
                                            fixture::kHelloName,
                                            fixture::kHelloFirmwareVersion,
                                            fixture::kHelloQueueOverflowDrops);
  TEST_ASSERT_EQUAL_UINT32(fixture::kHelloPacket.size(), len);
  TEST_ASSERT_EQUAL_UINT8_ARRAY(
      fixture::kHelloPacket.data(), packet, fixture::kHelloPacket.size());
}

void test_pack_data_matches_python_fixture() {
  uint8_t packet[fixture::kDataPacket.size()] = {};
  const size_t len = vibesensor::pack_data(packet,
                                           sizeof(packet),
                                           fixture::kDataClientId.data(),
                                           fixture::kDataSeq,
                                           fixture::kDataT0Us,
                                           fixture::kDataSamples.data(),
                                           fixture::kDataSampleCount);
  TEST_ASSERT_EQUAL_UINT32(fixture::kDataPacket.size(), len);
  TEST_ASSERT_EQUAL_UINT8_ARRAY(
      fixture::kDataPacket.data(), packet, fixture::kDataPacket.size());
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
  const bool ok = vibesensor::parse_cmd(fixture::kSyncClockPacket.data(),
                                        fixture::kSyncClockPacket.size(),
                                        fixture::kCommandClientId.data(),
                                        &cmd_id,
                                        &cmd_seq,
                                        &identify_duration_ms,
                                        &server_time_us);
  TEST_ASSERT_TRUE(ok);
  TEST_ASSERT_EQUAL_UINT8(vibesensor::kCmdSyncClock, cmd_id);
  TEST_ASSERT_EQUAL_UINT32(fixture::kSyncClockCmdSeq, cmd_seq);
  TEST_ASSERT_EQUAL_UINT64(fixture::kSyncClockServerTimeUs, server_time_us);
}

void test_pack_ack_matches_python_fixture() {
  uint8_t packet[fixture::kAckPacket.size()] = {};
  const size_t len = vibesensor::pack_ack(packet,
                                          sizeof(packet),
                                          fixture::kAckClientId.data(),
                                          fixture::kAckCmdSeq,
                                          fixture::kAckStatus);
  TEST_ASSERT_EQUAL_UINT32(fixture::kAckPacket.size(), len);
  TEST_ASSERT_EQUAL_UINT8_ARRAY(
      fixture::kAckPacket.data(), packet, fixture::kAckPacket.size());
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
  uint8_t packet[fixture::kDataAckPacket.size()] = {};
  const size_t len = vibesensor::pack_data_ack(packet,
                                               sizeof(packet),
                                               fixture::kDataClientId.data(),
                                               fixture::kDataAckLastSeqReceived);
  TEST_ASSERT_EQUAL_UINT32(fixture::kDataAckPacket.size(), len);
  TEST_ASSERT_EQUAL_UINT8_ARRAY(
      fixture::kDataAckPacket.data(), packet, fixture::kDataAckPacket.size());
}

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_pack_hello_matches_python_fixture);
  RUN_TEST(test_pack_data_matches_python_fixture);
  RUN_TEST(test_parse_identify_matches_python_fixture);
  RUN_TEST(test_parse_sync_clock_matches_python_fixture);
  RUN_TEST(test_pack_ack_matches_python_fixture);
  RUN_TEST(test_parse_data_ack_matches_python_fixture);
  RUN_TEST(test_pack_data_ack_matches_python_fixture);
  return UNITY_END();
}
