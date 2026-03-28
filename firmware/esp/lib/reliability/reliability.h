#pragma once

#include <stddef.h>
#include <stdint.h>

namespace vibesensor::reliability {

constexpr size_t kBytesPerXyzSample = 6U;
constexpr uint8_t kMaxUint8Value = 0xFF;
constexpr uint16_t kMaxUint16Value = 0xFFFF;
constexpr uint8_t kRetryBackoffShiftCap = 6;
constexpr uint32_t kRetryJitterDivisor = 4U;

constexpr uint16_t clamp_sample_rate(uint16_t configured_hz,
                                     uint16_t min_hz,
                                     uint16_t max_hz) {
  return configured_hz < min_hz
             ? min_hz
             : (configured_hz > max_hz ? max_hz : configured_hz);
}

inline uint64_t sampling_slots_due(uint64_t now_us,
                                   uint64_t next_due_us,
                                   uint64_t step_us) {
  if (step_us == 0 || now_us < next_due_us) {
    return 0;
  }
  return ((now_us - next_due_us) / step_us) + 1;
}

inline bool sampling_catch_up_budget_exhausted(uint64_t loop_started_us,
                                               uint64_t now_us,
                                               uint32_t budget_us) {
  if (now_us < loop_started_us) {
    return false;
  }
  return (now_us - loop_started_us) >= static_cast<uint64_t>(budget_us);
}

inline uint16_t clamp_frame_samples(uint16_t configured_samples,
                                    size_t max_datagram_bytes,
                                    size_t data_header_bytes) {
  const size_t max_by_datagram = (max_datagram_bytes - data_header_bytes) / kBytesPerXyzSample;
  const uint16_t hi =
      static_cast<uint16_t>(max_by_datagram > kMaxUint16Value ? kMaxUint16Value : max_by_datagram);
  if (configured_samples == 0) {
    return 1;
  }
  return configured_samples > hi ? hi : configured_samples;
}

inline uint8_t saturating_inc_u8(uint8_t value) {
  return value == kMaxUint8Value ? value : static_cast<uint8_t>(value + 1);
}

inline uint32_t compute_retry_delay_ms(uint32_t base_ms,
                                       uint32_t max_ms,
                                       uint8_t failure_count,
                                       uint32_t random_value) {
  const uint8_t shift =
      failure_count < kRetryBackoffShiftCap ? failure_count : kRetryBackoffShiftCap;
  uint32_t delay_ms = base_ms << shift;
  if (delay_ms > max_ms) {
    delay_ms = max_ms;
  }
  const uint32_t jitter_span = delay_ms / kRetryJitterDivisor;
  if (jitter_span == 0) {
    return delay_ms;
  }
  const uint32_t jittered = delay_ms - (jitter_span / 2U) + (random_value % jitter_span);
  return jittered > max_ms ? max_ms : jittered;
}

inline bool retry_due(uint32_t now_ms, uint32_t retry_at_ms) {
  return retry_at_ms == 0 || static_cast<int32_t>(now_ms - retry_at_ms) >= 0;
}

// Returns true when the sensor consecutive-error count has reached
// error_threshold AND the reinit cooldown has elapsed since the last attempt.
// Uses signed subtraction for millis() wrap-around safety (same idiom as
// retry_due).
inline bool sensor_should_reinit(uint8_t consecutive_errors,
                                  uint8_t error_threshold,
                                  uint32_t now_ms,
                                  uint32_t last_reinit_ms,
                                  uint32_t cooldown_ms) {
  return consecutive_errors >= error_threshold &&
         static_cast<int32_t>(now_ms - last_reinit_ms) >= static_cast<int32_t>(cooldown_ms);
}

}  // namespace vibesensor::reliability
