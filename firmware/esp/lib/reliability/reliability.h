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

struct SamplingIntervalSchedule {
  uint32_t sample_rate_hz = 0;
  uint64_t base_interval_us = 0;
  uint32_t remainder_us = 0;
  uint32_t accumulated_remainder_us = 0;
};

inline SamplingIntervalSchedule make_sampling_interval_schedule(uint32_t sample_rate_hz) {
  SamplingIntervalSchedule schedule{};
  schedule.sample_rate_hz = sample_rate_hz;
  if (sample_rate_hz == 0U) {
    return schedule;
  }
  schedule.base_interval_us = 1000000ULL / sample_rate_hz;
  schedule.remainder_us = static_cast<uint32_t>(1000000ULL % sample_rate_hz);
  return schedule;
}

inline uint64_t sampling_schedule_advance_us(SamplingIntervalSchedule& schedule,
                                             uint64_t slot_count = 1U) {
  if (slot_count == 0U || schedule.sample_rate_hz == 0U) {
    return 0;
  }
  const uint64_t total_remainder =
      static_cast<uint64_t>(schedule.accumulated_remainder_us) +
      (static_cast<uint64_t>(schedule.remainder_us) * slot_count);
  const uint64_t carry_us = total_remainder / schedule.sample_rate_hz;
  schedule.accumulated_remainder_us =
      static_cast<uint32_t>(total_remainder % schedule.sample_rate_hz);
  return (schedule.base_interval_us * slot_count) + carry_us;
}

inline uint64_t sampling_slots_due(uint64_t now_us,
                                   uint64_t next_due_us,
                                   uint64_t step_us) {
  if (step_us == 0 || now_us < next_due_us) {
    return 0;
  }
  return ((now_us - next_due_us) / step_us) + 1;
}

inline uint64_t sampling_slots_due(uint64_t now_us,
                                   uint64_t next_due_us,
                                   SamplingIntervalSchedule schedule) {
  if (schedule.sample_rate_hz == 0U || next_due_us == 0U || now_us < next_due_us) {
    return 0;
  }
  uint64_t due_slots = 1;
  uint64_t candidate_due_us = next_due_us + sampling_schedule_advance_us(schedule);
  while (candidate_due_us <= now_us) {
    due_slots++;
    candidate_due_us += sampling_schedule_advance_us(schedule);
  }
  return due_slots;
}

enum class SensorFailureClass : uint8_t {
  kNone = 0,
  kRegisterAccess = 1,
  kFifoData = 2,
  kPartialFifoDrain = 3,
  kRepeatedCommunication = 4,
  kSensorIdentity = 5,
  kSensorConfiguration = 6,
};

inline bool sensor_failure_is_communication(SensorFailureClass failure_class) {
  return failure_class == SensorFailureClass::kRegisterAccess ||
         failure_class == SensorFailureClass::kFifoData ||
         failure_class == SensorFailureClass::kPartialFifoDrain ||
         failure_class == SensorFailureClass::kRepeatedCommunication;
}

inline bool sensor_failure_requires_forced_reinit(SensorFailureClass failure_class) {
  return failure_class == SensorFailureClass::kSensorIdentity ||
         failure_class == SensorFailureClass::kSensorConfiguration;
}

struct SamplingRefillRetryStep {
  bool retry_read = false;
  bool recover_bus = false;
};

inline SamplingRefillRetryStep sampling_refill_retry_step(uint8_t exhausted_failures,
                                                          SensorFailureClass failure_class,
                                                          size_t requested_samples,
                                                          size_t recovered_samples) {
  SamplingRefillRetryStep step{};
  if (requested_samples == 0 || recovered_samples >= requested_samples ||
      !sensor_failure_is_communication(failure_class)) {
    return step;
  }
  if (exhausted_failures == 0U) {
    step.retry_read = true;
    return step;
  }
  if (exhausted_failures == 1U) {
    step.retry_read = true;
    step.recover_bus = true;
  }
  return step;
}

struct SamplingRefillPlan {
  size_t request_samples = 0;
  size_t target_prefetch = 0;
  bool aggressive = false;
};

inline SamplingRefillPlan sampling_prefetch_refill_plan(size_t prefetch_count,
                                                        size_t prefetch_capacity,
                                                        size_t low_water_samples,
                                                        size_t steady_target_samples,
                                                        size_t late_target_samples,
                                                        size_t due_slots,
                                                        bool recent_refill_shortfall) {
  SamplingRefillPlan plan{};
  if (prefetch_capacity <= prefetch_count) {
    return plan;
  }

  const bool late = due_slots > 1 || recent_refill_shortfall;
  const size_t trigger = late ? steady_target_samples : low_water_samples;
  if (prefetch_count > trigger) {
    return plan;
  }

  const size_t desired_target = late ? late_target_samples : steady_target_samples;
  const size_t capped_target =
      desired_target > prefetch_capacity ? prefetch_capacity : desired_target;
  if (capped_target <= prefetch_count) {
    return plan;
  }

  plan.target_prefetch = capped_target;
  plan.request_samples = capped_target - prefetch_count;
  plan.aggressive = late;
  return plan;
}

struct SamplingRecoveryPlan {
  size_t attempt_slots = 0;
  size_t missed_slots = 0;
};

inline bool sampling_recovery_abandoned(size_t missed_slots) {
  return missed_slots > 1U;
}

inline SamplingRecoveryPlan sampling_recovery_plan(size_t due_slots,
                                                   size_t handoff_headroom,
                                                   size_t prefetch_count,
                                                   size_t last_refill_request,
                                                   size_t last_refill_count) {
  SamplingRecoveryPlan plan{};
  if (due_slots == 0) {
    return plan;
  }
  if (handoff_headroom == 0) {
    plan.missed_slots = due_slots;
    return plan;
  }

  const size_t deliverable_slots = due_slots < handoff_headroom ? due_slots : handoff_headroom;
  if (due_slots == 1) {
    plan.attempt_slots = deliverable_slots;
    plan.missed_slots = due_slots - deliverable_slots;
    return plan;
  }
  if (prefetch_count >= deliverable_slots) {
    plan.attempt_slots = deliverable_slots;
    plan.missed_slots = due_slots - deliverable_slots;
    return plan;
  }
  if (last_refill_count == 0) {
    plan.attempt_slots = prefetch_count > 0 ? 1U : 0U;
    plan.missed_slots = due_slots - plan.attempt_slots;
    return plan;
  }
  if (last_refill_count < last_refill_request && prefetch_count == 0) {
    plan.missed_slots = due_slots;
    return plan;
  }

  plan.attempt_slots = deliverable_slots;
  plan.missed_slots = due_slots - deliverable_slots;
  return plan;
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
