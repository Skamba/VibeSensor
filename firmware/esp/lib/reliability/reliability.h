#pragma once

#include <stddef.h>
#include <stdint.h>

namespace vibesensor::reliability {

constexpr uint16_t clamp_sample_rate(uint16_t configured_hz,
                                     uint16_t min_hz,
                                     uint16_t max_hz) {
  return configured_hz < min_hz ? min_hz : (configured_hz > max_hz ? max_hz : configured_hz);
}

inline uint16_t clamp_frame_samples(uint16_t configured_samples,
                                    size_t max_datagram_bytes,
                                    size_t data_header_bytes) {
  const size_t max_by_datagram = (max_datagram_bytes - data_header_bytes) / 6U;
  const uint16_t hi = static_cast<uint16_t>(max_by_datagram > 0xFFFF ? 0xFFFF : max_by_datagram);
  if (configured_samples == 0) {
    return 1;
  }
  return configured_samples > hi ? hi : configured_samples;
}

inline uint8_t saturating_inc_u8(uint8_t value) {
  return value == 0xFF ? value : static_cast<uint8_t>(value + 1);
}

inline uint32_t compute_retry_delay_ms(uint32_t base_ms,
                                       uint32_t max_ms,
                                       uint8_t failure_count,
                                       uint32_t random_value) {
  const uint8_t shift = failure_count < 6 ? failure_count : 6;
  uint32_t delay_ms = base_ms << shift;
  if (delay_ms > max_ms) {
    delay_ms = max_ms;
  }
  const uint32_t jitter_span = delay_ms / 4U;
  if (jitter_span == 0) {
    return delay_ms;
  }
  const uint32_t jittered = delay_ms - (jitter_span / 2U) + (random_value % jitter_span);
  return jittered > max_ms ? max_ms : jittered;
}

inline bool retry_due(uint32_t now_ms, uint32_t retry_at_ms) {
  return retry_at_ms == 0 || static_cast<int32_t>(now_ms - retry_at_ms) >= 0;
}

}  // namespace vibesensor::reliability
