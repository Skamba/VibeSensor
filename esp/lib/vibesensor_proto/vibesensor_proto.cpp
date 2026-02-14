#include "vibesensor_proto.h"

#include <cstring>

namespace vibesensor {
namespace {

void write_u16_le(uint8_t* dst, uint16_t v) {
  dst[0] = static_cast<uint8_t>(v & 0xFF);
  dst[1] = static_cast<uint8_t>((v >> 8) & 0xFF);
}

void write_u32_le(uint8_t* dst, uint32_t v) {
  dst[0] = static_cast<uint8_t>(v & 0xFF);
  dst[1] = static_cast<uint8_t>((v >> 8) & 0xFF);
  dst[2] = static_cast<uint8_t>((v >> 16) & 0xFF);
  dst[3] = static_cast<uint8_t>((v >> 24) & 0xFF);
}

void write_u64_le(uint8_t* dst, uint64_t v) {
  for (uint8_t i = 0; i < 8; ++i) {
    dst[i] = static_cast<uint8_t>((v >> (8 * i)) & 0xFF);
  }
}

uint16_t read_u16_le(const uint8_t* src) {
  return static_cast<uint16_t>(src[0]) |
         (static_cast<uint16_t>(src[1]) << 8);
}

uint32_t read_u32_le(const uint8_t* src) {
  return static_cast<uint32_t>(src[0]) |
         (static_cast<uint32_t>(src[1]) << 8) |
         (static_cast<uint32_t>(src[2]) << 16) |
         (static_cast<uint32_t>(src[3]) << 24);
}

}  // namespace

bool parse_mac(const String& mac, uint8_t out_client_id[6]) {
  int values[6];
  if (sscanf(mac.c_str(), "%x:%x:%x:%x:%x:%x",
             &values[0], &values[1], &values[2],
             &values[3], &values[4], &values[5]) != 6) {
    return false;
  }
  for (size_t i = 0; i < 6; ++i) {
    out_client_id[i] = static_cast<uint8_t>(values[i] & 0xFF);
  }
  return true;
}

String client_id_hex(const uint8_t client_id[6]) {
  char buf[13];
  snprintf(buf, sizeof(buf), "%02x%02x%02x%02x%02x%02x",
           client_id[0], client_id[1], client_id[2],
           client_id[3], client_id[4], client_id[5]);
  return String(buf);
}

size_t pack_hello(uint8_t* out,
                  size_t out_len,
                  const uint8_t client_id[6],
                  uint16_t control_port,
                  uint16_t sample_rate_hz,
                  const char* name,
                  const char* firmware_version,
                  uint32_t queue_overflow_drops) {
  const size_t name_len = strnlen(name, 32);
  const size_t fw_len = strnlen(firmware_version, 32);
  const size_t need = kHelloFixedBytes + name_len + fw_len;
  if (out_len < need) {
    return 0;
  }
  size_t o = 0;
  out[o++] = kMsgHello;
  out[o++] = kProtoVersion;
  memcpy(out + o, client_id, 6);
  o += 6;
  write_u16_le(out + o, control_port);
  o += 2;
  write_u16_le(out + o, sample_rate_hz);
  o += 2;
  out[o++] = static_cast<uint8_t>(name_len);
  memcpy(out + o, name, name_len);
  o += name_len;
  out[o++] = static_cast<uint8_t>(fw_len);
  memcpy(out + o, firmware_version, fw_len);
  o += fw_len;
  write_u32_le(out + o, queue_overflow_drops);
  o += 4;
  return o;
}

size_t pack_data(uint8_t* out,
                 size_t out_len,
                 const uint8_t client_id[6],
                 uint32_t seq,
                 uint64_t t0_us,
                 const int16_t* xyz_interleaved,
                 uint16_t sample_count) {
  const size_t payload_len = static_cast<size_t>(sample_count) * 6;
  const size_t need = kDataHeaderBytes + payload_len;
  if (out_len < need) {
    return 0;
  }
  size_t o = 0;
  out[o++] = kMsgData;
  out[o++] = kProtoVersion;
  memcpy(out + o, client_id, 6);
  o += 6;
  write_u32_le(out + o, seq);
  o += 4;
  write_u64_le(out + o, t0_us);
  o += 8;
  write_u16_le(out + o, sample_count);
  o += 2;
  memcpy(out + o, xyz_interleaved, payload_len);
  o += payload_len;
  return o;
}

bool parse_cmd(const uint8_t* data,
               size_t len,
               const uint8_t expected_client_id[6],
               uint8_t* out_cmd_id,
               uint32_t* out_cmd_seq,
               uint16_t* out_identify_duration_ms) {
  const size_t base = kCmdHeaderBytes;
  if (len < base) {
    return false;
  }
  if (data[0] != kMsgCmd || data[1] != kProtoVersion) {
    return false;
  }
  if (memcmp(data + 2, expected_client_id, 6) != 0) {
    return false;
  }

  uint8_t cmd_id = data[8];
  uint32_t cmd_seq = read_u32_le(data + 9);
  if (out_cmd_id != nullptr) {
    *out_cmd_id = cmd_id;
  }
  if (out_cmd_seq != nullptr) {
    *out_cmd_seq = cmd_seq;
  }

  if (cmd_id == kCmdIdentify) {
    if (len < base + 2) {
      return false;
    }
    if (out_identify_duration_ms != nullptr) {
      *out_identify_duration_ms = read_u16_le(data + base);
    }
  }

  return true;
}

size_t pack_ack(uint8_t* out,
                size_t out_len,
                const uint8_t client_id[6],
                uint32_t cmd_seq,
                uint8_t status) {
  const size_t need = kAckBytes;
  if (out_len < need) {
    return 0;
  }
  size_t o = 0;
  out[o++] = kMsgAck;
  out[o++] = kProtoVersion;
  memcpy(out + o, client_id, 6);
  o += 6;
  write_u32_le(out + o, cmd_seq);
  o += 4;
  out[o++] = status;
  return o;
}

}  // namespace vibesensor
