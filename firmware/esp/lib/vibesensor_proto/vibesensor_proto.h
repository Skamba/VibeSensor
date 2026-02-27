#pragma once

#include <Arduino.h>

namespace vibesensor {

constexpr uint8_t kProtoVersion = 1;
constexpr size_t kClientIdBytes = 6;
constexpr size_t kHelloFixedBytes = 1 + 1 + kClientIdBytes + 2 + 2 + 2 + 1 + 1 + 4;
constexpr size_t kDataHeaderBytes = 1 + 1 + kClientIdBytes + 4 + 8 + 2;
constexpr size_t kAckBytes = 1 + 1 + kClientIdBytes + 4 + 1;
constexpr size_t kDataAckBytes = 1 + 1 + kClientIdBytes + 4;
constexpr size_t kCmdHeaderBytes = 1 + 1 + kClientIdBytes + 1 + 4;
constexpr size_t kCmdIdentifyBytes = kCmdHeaderBytes + 2;
constexpr size_t kCmdSyncClockBytes = kCmdHeaderBytes + 8;

enum MessageType : uint8_t {
  kMsgHello = 1,
  kMsgData = 2,
  kMsgCmd = 3,
  kMsgAck = 4,
  kMsgDataAck = 5,
};

enum CommandId : uint8_t {
  kCmdIdentify = 1,
  kCmdSyncClock = 2,
};

bool parse_mac(const String& mac, uint8_t out_client_id[6]);
String client_id_hex(const uint8_t client_id[6]);

size_t pack_hello(uint8_t* out,
                  size_t out_len,
                  const uint8_t client_id[6],
                  uint16_t control_port,
                  uint16_t sample_rate_hz,
                  uint16_t frame_samples,
                  const char* name,
                  const char* firmware_version,
                  uint32_t queue_overflow_drops = 0);

size_t pack_data(uint8_t* out,
                 size_t out_len,
                 const uint8_t client_id[6],
                 uint32_t seq,
                 uint64_t t0_us,
                 const int16_t* xyz_interleaved,
                 uint16_t sample_count);

bool parse_cmd(const uint8_t* data,
               size_t len,
               const uint8_t expected_client_id[6],
               uint8_t* out_cmd_id,
               uint32_t* out_cmd_seq,
               uint16_t* out_identify_duration_ms,
               uint64_t* out_server_time_us = nullptr);

size_t pack_ack(uint8_t* out,
                size_t out_len,
                const uint8_t client_id[6],
                uint32_t cmd_seq,
                uint8_t status);

size_t pack_data_ack(uint8_t* out,
                     size_t out_len,
                     const uint8_t client_id[6],
                     uint32_t last_seq_received);

bool parse_data_ack(const uint8_t* data,
                    size_t len,
                    const uint8_t expected_client_id[6],
                    uint32_t* out_last_seq_received);

}  // namespace vibesensor
