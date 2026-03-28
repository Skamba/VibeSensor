#include <unity.h>

#include <limits>
#include <stdint.h>
#include <stdio.h>

#include "../../src/runtime_queue.cpp"

namespace {

using vibesensor::runtime::DataFrame;
using vibesensor::runtime::FrameQueueState;
using vibesensor::runtime::RuntimeStatus;

constexpr uint64_t kStepUs = 1000000ULL / vibesensor::runtime::kSampleRateHz;
constexpr uint64_t kRunDurationUs = 12000000ULL;
constexpr uint64_t kFrameIntervalUs =
    static_cast<uint64_t>(vibesensor::runtime::kFrameSamples) * kStepUs;
constexpr uint64_t kAckPauseStartUs = 2000000ULL;
constexpr uint64_t kAckPauseDurationUs = 750000ULL;
constexpr uint64_t kStatusSpikeIntervalUs = 10000000ULL;
constexpr uint32_t kPreSamplingWorkUs = 120;
constexpr uint32_t kPostSamplingWorkUs = 90;
constexpr uint32_t kStatusSpikeCostUs = 2200;
constexpr uint32_t kRefillFixedUs = 70;
constexpr uint32_t kRefillPerSampleUs = 105;
constexpr uint32_t kAppendSampleCostUs = 10;
constexpr uint32_t kLegacyIdleDelayUs = 1000;
constexpr uint32_t kIdleWakeGuardUs = 150;
constexpr uint32_t kIdleDelayCapUs = 1000;
constexpr size_t kSimulationQueueCapacity = 8;
constexpr uint32_t kLegacyRandomSeed = 0x12345678U;

enum class IdlePolicy {
  kLegacyDelay1Ms,
  kDeterministicSleep,
};

enum class RefillPolicy {
  kLegacyRandomized,
  kDeterministicDithered,
};

struct SimulationMetrics {
  uint64_t loops = 0;
  uint64_t samples_emitted = 0;
  uint64_t catch_up_loops = 0;
  uint64_t catch_up_iterations = 0;
  uint64_t max_samples_per_loop = 0;
  uint64_t budget_exhaustions = 0;
  uint64_t missed_samples = 0;
  uint64_t refill_events = 0;
  uint64_t refill_samples = 0;
  uint64_t refill_duration_min_us = std::numeric_limits<uint64_t>::max();
  uint64_t refill_duration_max_us = 0;
  uint64_t queue_peak = 0;
  uint64_t frames_drained = 0;
  uint64_t loop_interval_min_us = std::numeric_limits<uint64_t>::max();
  uint64_t loop_interval_max_us = 0;
  uint64_t max_sample_lateness_us = 0;
  uint64_t total_sample_lateness_us = 0;
  uint64_t idle_total_us = 0;
  RuntimeStatus status = {};
};

struct SimulationState {
  DataFrame frames[kSimulationQueueCapacity] = {};
  FrameQueueState queue = {};
  size_t prefetch_count = 0;
  uint64_t now_us = 0;
  uint64_t next_sample_due_us = 0;
  uint64_t next_ack_us = kFrameIntervalUs;
  uint64_t next_status_spike_us = kStatusSpikeIntervalUs;
  uint32_t random_state = kLegacyRandomSeed;
  uint32_t refill_cycle = 0;
  int16_t next_sample_value = 0;
};

FrameQueueState make_queue_state(DataFrame* frames, size_t capacity) {
  FrameQueueState state{};
  state.queue = frames;
  state.capacity = capacity;
  return state;
}

uint32_t advance_legacy_random(uint32_t& state) {
  state = (state * 1664525U) + 1013904223U;
  return state;
}

size_t legacy_randomized_refill_count(size_t prefetch_count, uint32_t& random_state) {
  size_t max_to_read = vibesensor::runtime::kSensorReadBatchSamples;
  const size_t free_slots = vibesensor::runtime::kSensorPrefetchSamples - prefetch_count;
  if (free_slots < max_to_read) {
    max_to_read = free_slots;
  }
  if (max_to_read > 1) {
    max_to_read = 1 + (advance_legacy_random(random_state) % max_to_read);
  }
  return max_to_read;
}

bool in_ack_pause_window(uint64_t ack_slot_us) {
  return ack_slot_us >= kAckPauseStartUs &&
         ack_slot_us < (kAckPauseStartUs + kAckPauseDurationUs);
}

void update_queue_peak(SimulationMetrics& metrics, const FrameQueueState& queue_state) {
  const uint64_t size = static_cast<uint64_t>(vibesensor::runtime::frame_queue_size(queue_state));
  if (size > metrics.queue_peak) {
    metrics.queue_peak = size;
  }
}

void drain_acked_frames(SimulationState& state, SimulationMetrics& metrics) {
  while (state.now_us >= state.next_ack_us) {
    if (!in_ack_pause_window(state.next_ack_us)) {
      DataFrame* frame = vibesensor::runtime::peek_frame(state.queue);
      if (frame != nullptr) {
        vibesensor::runtime::ack_data_frames(state.queue, frame->seq);
        metrics.frames_drained++;
      }
    }
    state.next_ack_us += kFrameIntervalUs;
  }
  update_queue_peak(metrics, state.queue);
}

SimulationMetrics run_simulation(IdlePolicy idle_policy, RefillPolicy refill_policy) {
  SimulationState state{};
  SimulationMetrics metrics{};
  state.queue = make_queue_state(state.frames, kSimulationQueueCapacity);

  uint64_t previous_loop_start_us = 0;
  bool have_previous_loop_start = false;

  while (state.now_us < kRunDurationUs) {
    const uint64_t loop_start_us = state.now_us;
    metrics.loops++;
    if (have_previous_loop_start) {
      const uint64_t loop_interval_us = loop_start_us - previous_loop_start_us;
      if (loop_interval_us < metrics.loop_interval_min_us) {
        metrics.loop_interval_min_us = loop_interval_us;
      }
      if (loop_interval_us > metrics.loop_interval_max_us) {
        metrics.loop_interval_max_us = loop_interval_us;
      }
    }
    previous_loop_start_us = loop_start_us;
    have_previous_loop_start = true;

    state.now_us += kPreSamplingWorkUs;
    const uint64_t sampling_loop_started_us = state.now_us;
    uint64_t now_us = state.now_us;
    uint64_t samples_this_loop = 0;

    while (vibesensor::reliability::sampling_slots_due(now_us,
                                                       state.next_sample_due_us,
                                                       kStepUs) > 0) {
      if (vibesensor::reliability::sampling_catch_up_budget_exhausted(
              sampling_loop_started_us,
              now_us,
              vibesensor::runtime::kSamplingCatchUpBudgetUs)) {
        metrics.budget_exhaustions++;
        break;
      }

      if (state.prefetch_count <= vibesensor::runtime::kSensorPrefetchLowWaterSamples) {
        const size_t refill_count =
            refill_policy == RefillPolicy::kLegacyRandomized
                ? legacy_randomized_refill_count(state.prefetch_count, state.random_state)
                : vibesensor::reliability::sampling_prefetch_refill_count(
                      state.prefetch_count,
                      vibesensor::runtime::kSensorPrefetchSamples,
                      vibesensor::reliability::sampling_dithered_batch_target(
                          vibesensor::runtime::kSensorReadBatchSamples,
                          state.refill_cycle++));
        if (refill_count > 0) {
          const uint64_t refill_duration_us =
              kRefillFixedUs + (static_cast<uint64_t>(refill_count) * kRefillPerSampleUs);
          metrics.refill_events++;
          metrics.refill_samples += refill_count;
          if (refill_duration_us < metrics.refill_duration_min_us) {
            metrics.refill_duration_min_us = refill_duration_us;
          }
          if (refill_duration_us > metrics.refill_duration_max_us) {
            metrics.refill_duration_max_us = refill_duration_us;
          }
          state.prefetch_count += refill_count;
          now_us += refill_duration_us;
        }
      }

      if (state.prefetch_count == 0) {
        metrics.missed_samples++;
        state.next_sample_due_us += kStepUs;
        break;
      }

      const uint64_t sample_lateness_us =
          now_us > state.next_sample_due_us ? (now_us - state.next_sample_due_us) : 0;
      metrics.total_sample_lateness_us += sample_lateness_us;
      if (sample_lateness_us > metrics.max_sample_lateness_us) {
        metrics.max_sample_lateness_us = sample_lateness_us;
      }

      state.prefetch_count--;
      vibesensor::runtime::append_sample(state.queue,
                                         metrics.status,
                                         state.next_sample_value,
                                         static_cast<int16_t>(state.next_sample_value + 1),
                                         static_cast<int16_t>(state.next_sample_value + 2),
                                         state.next_sample_due_us,
                                         0);
      state.next_sample_value = static_cast<int16_t>(state.next_sample_value + 1);
      samples_this_loop++;
      metrics.samples_emitted++;
      now_us += kAppendSampleCostUs;
      state.next_sample_due_us += kStepUs;
      update_queue_peak(metrics, state.queue);
    }

    const uint64_t skipped_slots =
        vibesensor::reliability::sampling_slots_due(now_us,
                                                    state.next_sample_due_us,
                                                    kStepUs);
    if (skipped_slots > 0) {
      metrics.missed_samples += skipped_slots;
      state.next_sample_due_us += skipped_slots * kStepUs;
    }

    if (samples_this_loop > 1) {
      metrics.catch_up_loops++;
      metrics.catch_up_iterations += (samples_this_loop - 1);
    }
    if (samples_this_loop > metrics.max_samples_per_loop) {
      metrics.max_samples_per_loop = samples_this_loop;
    }

    state.now_us = now_us;
    drain_acked_frames(state, metrics);

    state.now_us += kPostSamplingWorkUs;
    if (state.now_us >= state.next_status_spike_us) {
      state.now_us += kStatusSpikeCostUs;
      state.next_status_spike_us += kStatusSpikeIntervalUs;
    }
    drain_acked_frames(state, metrics);

    const uint32_t idle_delay_us =
        idle_policy == IdlePolicy::kLegacyDelay1Ms
            ? kLegacyIdleDelayUs
            : vibesensor::reliability::sampling_idle_delay_us(state.now_us,
                                                              state.next_sample_due_us,
                                                              kIdleWakeGuardUs,
                                                              kIdleDelayCapUs);
    metrics.idle_total_us += idle_delay_us;
    state.now_us += idle_delay_us;
  }

  if (metrics.loop_interval_min_us == std::numeric_limits<uint64_t>::max()) {
    metrics.loop_interval_min_us = 0;
  }
  if (metrics.refill_duration_min_us == std::numeric_limits<uint64_t>::max()) {
    metrics.refill_duration_min_us = 0;
  }
  metrics.status.sampling_missed_samples = static_cast<uint32_t>(metrics.missed_samples);
  metrics.status.sampling_budget_exhaustions = static_cast<uint32_t>(metrics.budget_exhaustions);
  return metrics;
}

void print_metrics(const char* label, const SimulationMetrics& metrics) {
  const uint64_t average_lateness_us =
      metrics.samples_emitted == 0 ? 0 : (metrics.total_sample_lateness_us / metrics.samples_emitted);
  printf(
      "%s loops=%llu samples=%llu avg_late_us=%llu max_late_us=%llu catch_up_loops=%llu "
      "catch_up_iterations=%llu max_samples_per_loop=%llu refill_events=%llu "
      "refill_samples=%llu refill_span_us=%llu..%llu queue_peak=%llu drained=%llu "
      "missed=%llu budget=%llu loop_interval_us=%llu..%llu idle_total_us=%llu\n",
      label,
      static_cast<unsigned long long>(metrics.loops),
      static_cast<unsigned long long>(metrics.samples_emitted),
      static_cast<unsigned long long>(average_lateness_us),
      static_cast<unsigned long long>(metrics.max_sample_lateness_us),
      static_cast<unsigned long long>(metrics.catch_up_loops),
      static_cast<unsigned long long>(metrics.catch_up_iterations),
      static_cast<unsigned long long>(metrics.max_samples_per_loop),
      static_cast<unsigned long long>(metrics.refill_events),
      static_cast<unsigned long long>(metrics.refill_samples),
      static_cast<unsigned long long>(metrics.refill_duration_min_us),
      static_cast<unsigned long long>(metrics.refill_duration_max_us),
      static_cast<unsigned long long>(metrics.queue_peak),
      static_cast<unsigned long long>(metrics.frames_drained),
      static_cast<unsigned long long>(metrics.missed_samples),
      static_cast<unsigned long long>(metrics.budget_exhaustions),
      static_cast<unsigned long long>(metrics.loop_interval_min_us),
      static_cast<unsigned long long>(metrics.loop_interval_max_us),
      static_cast<unsigned long long>(metrics.idle_total_us));
}

void test_deterministic_idle_strategy_reduces_lateness_and_catch_up() {
  const SimulationMetrics legacy =
      run_simulation(IdlePolicy::kLegacyDelay1Ms, RefillPolicy::kLegacyRandomized);
  const SimulationMetrics candidate =
      run_simulation(IdlePolicy::kDeterministicSleep, RefillPolicy::kLegacyRandomized);

  print_metrics("legacy_idle_random_refill", legacy);
  print_metrics("deterministic_idle_random_refill", candidate);

  TEST_ASSERT_TRUE(candidate.max_sample_lateness_us < legacy.max_sample_lateness_us);
  TEST_ASSERT_TRUE(candidate.catch_up_loops < legacy.catch_up_loops);
  TEST_ASSERT_TRUE(candidate.catch_up_iterations < legacy.catch_up_iterations);
  TEST_ASSERT_TRUE(candidate.loop_interval_max_us < legacy.loop_interval_max_us);
}

void test_deterministic_refill_eliminates_refill_size_variance() {
  const SimulationMetrics legacy =
      run_simulation(IdlePolicy::kDeterministicSleep, RefillPolicy::kLegacyRandomized);
  const SimulationMetrics candidate =
      run_simulation(IdlePolicy::kDeterministicSleep, RefillPolicy::kDeterministicDithered);

  print_metrics("deterministic_idle_random_refill", legacy);
  print_metrics("deterministic_idle_dithered_refill", candidate);

  TEST_ASSERT_TRUE(legacy.refill_duration_max_us > legacy.refill_duration_min_us);
  TEST_ASSERT_TRUE(candidate.refill_duration_max_us > candidate.refill_duration_min_us);
  TEST_ASSERT_TRUE((candidate.refill_duration_max_us - candidate.refill_duration_min_us) <=
                   kRefillPerSampleUs);
  TEST_ASSERT_TRUE(candidate.refill_events <= legacy.refill_events);
  TEST_ASSERT_TRUE(candidate.total_sample_lateness_us < legacy.total_sample_lateness_us);
}

void test_candidate_policy_keeps_queue_stable_through_ack_pause() {
  const SimulationMetrics candidate =
      run_simulation(IdlePolicy::kDeterministicSleep, RefillPolicy::kDeterministicDithered);

  print_metrics("candidate_policy", candidate);

  TEST_ASSERT_EQUAL_UINT32(0, candidate.status.queue_overflow_drops);
  TEST_ASSERT_TRUE(candidate.queue_peak > 0);
  TEST_ASSERT_TRUE(candidate.frames_drained > 0);
  TEST_ASSERT_TRUE(candidate.max_samples_per_loop <= 3);
}

}  // namespace

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_deterministic_idle_strategy_reduces_lateness_and_catch_up);
  RUN_TEST(test_deterministic_refill_eliminates_refill_size_variance);
  RUN_TEST(test_candidate_policy_keeps_queue_stable_through_ack_pause);
  return UNITY_END();
}
