#include <unity.h>

#include <limits>
#include <stdint.h>
#include <stdio.h>

#include "reliability.h"
#include "../../src/runtime_config.h"
#include "../../src/runtime_sample_handoff.cpp"

namespace {

using vibesensor::runtime::PendingSample;
using vibesensor::runtime::SampleHandoffState;

constexpr uint64_t kRunDurationUs = 12000000ULL;
constexpr uint64_t kStatusSpikeIntervalUs = 10000000ULL;
constexpr uint32_t kPreLoopWorkUs = 120;
constexpr uint32_t kPostLoopWorkUs = 90;
constexpr uint32_t kStatusSpikeCostUs = 2200;
constexpr uint32_t kRefillFixedUs = 70;
constexpr uint32_t kRefillPerSampleUs = 90;
constexpr uint32_t kProduceSampleCostUs = 10;
constexpr size_t kSimulationHandoffCapacity = 96;

struct SimulationMetrics {
  uint64_t loop_iterations = 0;
  uint64_t samples_produced = 0;
  uint64_t samples_consumed = 0;
  uint64_t missed_samples = 0;
  uint64_t total_lateness_us = 0;
  uint64_t max_lateness_us = 0;
  uint64_t refill_events = 0;
  uint64_t refill_duration_min_us = std::numeric_limits<uint64_t>::max();
  uint64_t refill_duration_max_us = 0;
  uint64_t handoff_peak = 0;
  uint64_t handoff_overflow_drops = 0;
};

struct ProducerState {
  PendingSample handoff_storage[kSimulationHandoffCapacity] = {};
  SampleHandoffState handoff = {};
  size_t prefetch_count = 0;
  size_t last_refill_request = 0;
  size_t last_refill_count = 0;
  bool recent_refill_shortfall = false;
  vibesensor::reliability::SamplingIntervalSchedule due_schedule =
      vibesensor::reliability::make_sampling_interval_schedule(vibesensor::runtime::kSampleRateHz);
  uint64_t next_due_us = 0;
  uint64_t producer_now_us = 0;
};

void initialize_schedule(ProducerState& state) {
  state.next_due_us = vibesensor::reliability::sampling_schedule_advance_us(state.due_schedule);
}

void update_refill_metrics(SimulationMetrics& metrics, size_t refill_count) {
  if (refill_count == 0) {
    return;
  }
  const uint64_t refill_duration_us =
      kRefillFixedUs + (static_cast<uint64_t>(refill_count) * kRefillPerSampleUs);
  metrics.refill_events++;
  if (refill_duration_us < metrics.refill_duration_min_us) {
    metrics.refill_duration_min_us = refill_duration_us;
  }
  if (refill_duration_us > metrics.refill_duration_max_us) {
    metrics.refill_duration_max_us = refill_duration_us;
  }
}

void maybe_refill(ProducerState& state, size_t due_slots, SimulationMetrics& metrics) {
  state.last_refill_request = 0;
  state.last_refill_count = 0;
  const vibesensor::reliability::SamplingRefillPlan plan =
      vibesensor::reliability::sampling_prefetch_refill_plan(
          state.prefetch_count,
          vibesensor::runtime::kSensorPrefetchSamples,
          vibesensor::runtime::kSensorPrefetchLowWaterSamples,
          vibesensor::runtime::kSensorPrefetchSteadyTargetSamples,
          vibesensor::runtime::kSensorPrefetchLateTargetSamples,
          due_slots,
          state.recent_refill_shortfall);
  if (plan.request_samples == 0) {
    return;
  }

  state.last_refill_request = plan.request_samples;
  state.last_refill_count = plan.request_samples;
  state.recent_refill_shortfall = false;
  state.prefetch_count += plan.request_samples;
  state.producer_now_us +=
      kRefillFixedUs + (static_cast<uint64_t>(plan.request_samples) * kRefillPerSampleUs);
  update_refill_metrics(metrics, plan.request_samples);
}

void update_lateness_metrics(SimulationMetrics& metrics,
                             uint64_t produced_at_us,
                             uint64_t due_us) {
  const uint64_t lateness_us = produced_at_us > due_us ? (produced_at_us - due_us) : 0;
  metrics.total_lateness_us += lateness_us;
  if (lateness_us > metrics.max_lateness_us) {
    metrics.max_lateness_us = lateness_us;
  }
}

void produce_due_slots(ProducerState& state,
                       size_t due_slots,
                       bool publish_to_handoff,
                       SimulationMetrics& metrics) {
  if (due_slots == 0) {
    return;
  }

  maybe_refill(state, due_slots, metrics);
  const size_t headroom = publish_to_handoff ? vibesensor::runtime::sample_handoff_free_slots(state.handoff)
                                             : due_slots;
  const vibesensor::reliability::SamplingRecoveryPlan recovery =
      vibesensor::reliability::sampling_recovery_plan(
          due_slots, headroom, state.prefetch_count, state.last_refill_request, state.last_refill_count);

  size_t produced = 0;
  while (produced < recovery.attempt_slots) {
    const size_t remaining_due = due_slots - produced;
    maybe_refill(state, remaining_due, metrics);
    if (state.prefetch_count == 0) {
      break;
    }

    update_lateness_metrics(metrics, state.producer_now_us, state.next_due_us);
    state.prefetch_count--;

    if (publish_to_handoff) {
      PendingSample sample{};
      sample.due_us = state.next_due_us;
      sample.x = static_cast<int16_t>(metrics.samples_produced);
      sample.y = static_cast<int16_t>(metrics.samples_produced + 1);
      sample.z = static_cast<int16_t>(metrics.samples_produced + 2);
      if (!vibesensor::runtime::enqueue_pending_sample(state.handoff, sample)) {
        metrics.handoff_overflow_drops = state.handoff.overflow_drops;
        break;
      }
      if (state.handoff.high_watermark > metrics.handoff_peak) {
        metrics.handoff_peak = state.handoff.high_watermark;
      }
    }

    metrics.samples_produced++;
    state.producer_now_us += kProduceSampleCostUs;
    state.next_due_us += vibesensor::reliability::sampling_schedule_advance_us(state.due_schedule);
    produced++;
  }

  const size_t missed_slots = due_slots - produced;
  if (missed_slots > 0) {
    metrics.missed_samples += missed_slots;
    state.next_due_us +=
        vibesensor::reliability::sampling_schedule_advance_us(state.due_schedule, missed_slots);
  }
  metrics.handoff_overflow_drops = state.handoff.overflow_drops;
}

void advance_dedicated_producer_to(uint64_t wall_time_us,
                                   ProducerState& state,
                                   SimulationMetrics& metrics) {
  while (state.next_due_us <= wall_time_us) {
    if (state.producer_now_us < state.next_due_us) {
      state.producer_now_us = state.next_due_us;
    }
    const size_t due_slots = static_cast<size_t>(vibesensor::reliability::sampling_slots_due(
        state.producer_now_us,
        state.next_due_us,
        state.due_schedule));
    produce_due_slots(state, due_slots, true, metrics);
  }
}

void drain_handoff(ProducerState& state, SimulationMetrics& metrics) {
  PendingSample sample{};
  while (vibesensor::runtime::dequeue_pending_sample(state.handoff, &sample)) {
    metrics.samples_consumed++;
  }
}

SimulationMetrics run_cooperative_simulation() {
  ProducerState state{};
  initialize_schedule(state);
  SimulationMetrics metrics{};
  uint64_t loop_now_us = 0;
  uint64_t next_status_spike_us = kStatusSpikeIntervalUs;

  while (loop_now_us < kRunDurationUs) {
    metrics.loop_iterations++;
    loop_now_us += kPreLoopWorkUs;
    state.producer_now_us = loop_now_us;
    if (state.next_due_us <= state.producer_now_us) {
      const size_t due_slots = static_cast<size_t>(vibesensor::reliability::sampling_slots_due(
          state.producer_now_us,
          state.next_due_us,
          state.due_schedule));
      produce_due_slots(state, due_slots, false, metrics);
      loop_now_us = state.producer_now_us;
    }
    loop_now_us += kPostLoopWorkUs;
    if (loop_now_us >= next_status_spike_us) {
      loop_now_us += kStatusSpikeCostUs;
      next_status_spike_us += kStatusSpikeIntervalUs;
    }
  }

  if (metrics.refill_duration_min_us == std::numeric_limits<uint64_t>::max()) {
    metrics.refill_duration_min_us = 0;
  }
  return metrics;
}

SimulationMetrics run_dedicated_simulation() {
  ProducerState state{};
  initialize_schedule(state);
  SimulationMetrics metrics{};
  uint64_t loop_now_us = 0;
  uint64_t next_status_spike_us = kStatusSpikeIntervalUs;
  vibesensor::runtime::initialize_sample_handoff(
      state.handoff, state.handoff_storage, kSimulationHandoffCapacity);

  while (loop_now_us < kRunDurationUs) {
    metrics.loop_iterations++;
    advance_dedicated_producer_to(loop_now_us, state, metrics);
    loop_now_us += kPreLoopWorkUs;
    advance_dedicated_producer_to(loop_now_us, state, metrics);
    drain_handoff(state, metrics);
    loop_now_us += kPostLoopWorkUs;
    if (loop_now_us >= next_status_spike_us) {
      loop_now_us += kStatusSpikeCostUs;
      next_status_spike_us += kStatusSpikeIntervalUs;
    }
    advance_dedicated_producer_to(loop_now_us, state, metrics);
  }

  drain_handoff(state, metrics);
  if (metrics.refill_duration_min_us == std::numeric_limits<uint64_t>::max()) {
    metrics.refill_duration_min_us = 0;
  }
  return metrics;
}

void print_metrics(const char* label, const SimulationMetrics& metrics) {
  const uint64_t average_lateness_us =
      metrics.samples_produced == 0 ? 0 : (metrics.total_lateness_us / metrics.samples_produced);
  printf(
      "%s loops=%llu produced=%llu consumed=%llu missed=%llu avg_late_us=%llu max_late_us=%llu "
      "refill_events=%llu refill_span_us=%llu..%llu handoff_peak=%llu handoff_drops=%llu\n",
      label,
      static_cast<unsigned long long>(metrics.loop_iterations),
      static_cast<unsigned long long>(metrics.samples_produced),
      static_cast<unsigned long long>(metrics.samples_consumed),
      static_cast<unsigned long long>(metrics.missed_samples),
      static_cast<unsigned long long>(average_lateness_us),
      static_cast<unsigned long long>(metrics.max_lateness_us),
      static_cast<unsigned long long>(metrics.refill_events),
      static_cast<unsigned long long>(metrics.refill_duration_min_us),
      static_cast<unsigned long long>(metrics.refill_duration_max_us),
      static_cast<unsigned long long>(metrics.handoff_peak),
      static_cast<unsigned long long>(metrics.handoff_overflow_drops));
}

void test_dedicated_sampling_task_isolates_cadence_from_loop_spikes() {
  const SimulationMetrics cooperative = run_cooperative_simulation();
  const SimulationMetrics dedicated = run_dedicated_simulation();

  print_metrics("cooperative_sampling", cooperative);
  print_metrics("dedicated_sampling_task", dedicated);

  TEST_ASSERT_TRUE(dedicated.max_lateness_us < cooperative.max_lateness_us);
  TEST_ASSERT_TRUE(dedicated.total_lateness_us < cooperative.total_lateness_us);
  TEST_ASSERT_TRUE(dedicated.missed_samples <= cooperative.missed_samples);
}

void test_dedicated_sampling_keeps_handoff_bounded_and_ordered() {
  const SimulationMetrics dedicated = run_dedicated_simulation();

  print_metrics("dedicated_sampling_task", dedicated);

  TEST_ASSERT_TRUE(dedicated.handoff_peak > 0);
  TEST_ASSERT_EQUAL_UINT64(0, dedicated.handoff_overflow_drops);
  TEST_ASSERT_EQUAL_UINT64(dedicated.samples_produced, dedicated.samples_consumed);
}

}  // namespace

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_dedicated_sampling_task_isolates_cadence_from_loop_spikes);
  RUN_TEST(test_dedicated_sampling_keeps_handoff_bounded_and_ordered);
  return UNITY_END();
}
