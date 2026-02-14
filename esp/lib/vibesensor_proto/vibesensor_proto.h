#pragma once

#include <Arduino.h>

namespace vibesensor {

constexpr uint8_t kProtoVersion = 1;

enum MessageType : uint8_t {
  kMsgHello = 1,
  kMsgData = 2,
  kMsgCmd = 3,
  kMsgAck = 4,
};

enum CommandId : uint8_t {
  kCmdIdentify = 1,
};

bool parse_mac(const String& mac, uint8_t out_client_id[6]);
String client_id_hex(const uint8_t client_id[6]);

size_t pack_hello(uint8_t* out,
                  size_t out_len,
                  const uint8_t client_id[6],
                  uint16_t control_port,
                  uint16_t sample_rate_hz,
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
               uint16_t* out_identify_duration_ms);

size_t pack_ack(uint8_t* out,
                size_t out_len,
                const uint8_t client_id[6],
                uint32_t cmd_seq,
                uint8_t status);

}  // namespace vibesensor
