#include <unity.h>

#include <math.h>

#include <deque>
#include <set>
#include <vector>

#include "sample_timing.h"

namespace {

namespace timing = vibesensor::sample_timing;
using timing::SampleClock;
using timing::SampleClockObservation;

void test_divisor_rate_schedule_stays_exact() {
  auto schedule = timing::make_sampling_interval_schedule(800);
  uint64_t total_elapsed_us = 0;

  for (size_t i = 0; i < 800; ++i) {
    const uint64_t step_us = timing::sampling_schedule_advance_us(schedule);
    TEST_ASSERT_EQUAL_UINT64(1250, step_us);
    total_elapsed_us += step_us;
  }

  TEST_ASSERT_EQUAL_UINT64(1000000ULL, total_elapsed_us);
}

void test_non_divisor_rate_schedule_distributes_fractional_remainder_without_drift() {
  auto schedule = timing::make_sampling_interval_schedule(3200);
  uint64_t total_elapsed_us = 0;

  TEST_ASSERT_EQUAL_UINT64(312, timing::sampling_schedule_advance_us(schedule));
  TEST_ASSERT_EQUAL_UINT64(313, timing::sampling_schedule_advance_us(schedule));
  TEST_ASSERT_EQUAL_UINT64(312, timing::sampling_schedule_advance_us(schedule));
  TEST_ASSERT_EQUAL_UINT64(313, timing::sampling_schedule_advance_us(schedule));

  total_elapsed_us += 1250;
  for (size_t i = 4; i < 3200; ++i) {
    total_elapsed_us += timing::sampling_schedule_advance_us(schedule);
  }

  TEST_ASSERT_EQUAL_UINT64(1000000ULL, total_elapsed_us);
}

// An ADXL345 running on its own oscillator, drained by a poll loop whose wake-up
// is late by a random dispatch latency, as on the device. Each drained sample is
// stamped by the SampleClock and compared against when the sensor took it.
struct SimulationResult {
  uint64_t produced = 0;
  uint64_t delivered = 0;
  uint64_t actually_lost = 0;
  uint64_t counted_lost = 0;
  int64_t max_abs_error_us = 0;
  int64_t mean_error_first_half_us = 0;
  int64_t mean_error_second_half_us = 0;
};

// When the simulated ADXL345 takes sample `index`. Its oscillator is off
// nominal and, as measured on hardware (poll traces of an ATOM Lite), wanders
// by a few tenths of a percent over seconds: modelled as +/-1.5 ms of phase
// at 0.3 Hz on top of the constant rate.
double sensor_sample_time_us(double period_us, uint64_t index) {
  constexpr double kPhaseUs = 437.0;
  constexpr double kWanderUs = 1500.0;
  constexpr double kWanderHz = 0.3;
  const double nominal_us = static_cast<double>(index) * period_us;
  return nominal_us + kPhaseUs + kWanderUs * sin(2.0 * M_PI * kWanderHz * nominal_us / 1e6);
}

SimulationResult simulate(double sensor_rate_hz,
                          uint64_t duration_us,
                          uint64_t stall_at_us = 0,
                          uint64_t stall_us = 0,
                          SampleClock* clock_out = nullptr) {
  constexpr size_t kFifoCapacity = 33;
  // Acquisition (~0.3 s) plus a few time constants of the tracking loop.
  constexpr uint64_t kSettleUs = 12000000;
  SimulationResult result{};
  SampleClock clock = timing::make_sample_clock(800);
  uint32_t poll_rng = 0x12345678U;
  uint32_t latency_rng = 0x9E3779B9U;
  const double period_us = 1000000.0 / sensor_rate_hz;
  std::deque<int64_t> fifo;
  uint64_t next_sample_index = 0;
  int64_t sum_first = 0;
  int64_t sum_second = 0;
  uint64_t count_first = 0;
  uint64_t count_second = 0;
  uint64_t poll_due_us = 10000;
  bool stalled = false;

  while (poll_due_us < duration_us) {
    const uint64_t latency_us = timing::xorshift32(latency_rng) % 3000U;
    uint64_t now_us = poll_due_us + latency_us;
    if (!stalled && stall_us > 0 && now_us >= stall_at_us) {
      stalled = true;
      now_us += stall_us;
    }
    while (sensor_sample_time_us(period_us, next_sample_index) <= static_cast<double>(now_us)) {
      fifo.push_back(static_cast<int64_t>(sensor_sample_time_us(period_us, next_sample_index)));
      next_sample_index++;
      result.produced++;
      if (fifo.size() > kFifoCapacity) {
        fifo.pop_front();
        result.actually_lost++;
      }
    }
    const SampleClockObservation observation = timing::sample_clock_observe(
        clock, static_cast<int64_t>(now_us), fifo.size(), fifo.size() >= 32);
    result.counted_lost += observation.lost_samples;
    while (!fifo.empty()) {
      const int64_t true_us = fifo.front();
      fifo.pop_front();
      const int64_t error_us = timing::sample_clock_take(clock) / timing::kQ16One - true_us;
      result.delivered++;
      if (static_cast<uint64_t>(true_us) < kSettleUs ||
          (stall_us > 0 && static_cast<uint64_t>(true_us) < stall_at_us + stall_us + kSettleUs &&
           static_cast<uint64_t>(true_us) >= stall_at_us)) {
        continue;
      }
      const int64_t abs_error_us = error_us < 0 ? -error_us : error_us;
      if (abs_error_us > result.max_abs_error_us) {
        result.max_abs_error_us = abs_error_us;
      }
      if (static_cast<uint64_t>(true_us) < duration_us / 2) {
        sum_first += error_us;
        count_first++;
      } else {
        sum_second += error_us;
        count_second++;
      }
    }
    // Poll from start to start, as arm_next_poll does.
    poll_due_us = now_us + timing::sampling_poll_interval_us(poll_rng, 10000, 5000);
  }
  if (clock_out != nullptr) {
    *clock_out = clock;
  }
  result.mean_error_first_half_us = count_first > 0 ? sum_first / static_cast<int64_t>(count_first) : 0;
  result.mean_error_second_half_us =
      count_second > 0 ? sum_second / static_cast<int64_t>(count_second) : 0;
  return result;
}

void test_stamps_follow_sensor_time_without_drift_despite_poll_latency() {
  // Ten minutes: the old per-sample timer lost ~5 % here (33 s); this must not move.
  const SimulationResult result = simulate(800.0, 600000000ULL);
  TEST_ASSERT_EQUAL_UINT64(result.produced, result.delivered);
  TEST_ASSERT_EQUAL_UINT64(0, result.actually_lost);
  TEST_ASSERT_EQUAL_UINT64(0, result.counted_lost);
  TEST_ASSERT_LESS_THAN_INT64(500, result.max_abs_error_us);
  const int64_t drift_us = result.mean_error_second_half_us - result.mean_error_first_half_us;
  TEST_ASSERT_INT64_WITHIN(100, 0, drift_us);
}

void test_off_nominal_sensor_rate_is_measured_and_tracked_without_lag() {
  // The measured unit ran at 823 Hz; the clock measures that period and its
  // stamps stay on the sensor's real sample times.
  const double rates_hz[] = {823.0, 760.0};
  for (double rate_hz : rates_hz) {
    SampleClock clock{};
    const SimulationResult result = simulate(rate_hz, 300000000ULL, 0, 0, &clock);
    TEST_ASSERT_EQUAL_UINT64(result.produced, result.delivered);
    TEST_ASSERT_EQUAL_UINT64(0, result.counted_lost);
    // Within about half a sensor period, centred on the true times.
    TEST_ASSERT_LESS_THAN_INT64(700, result.max_abs_error_us);
    TEST_ASSERT_INT64_WITHIN(100, 0, result.mean_error_first_half_us);
    const int64_t drift_us = result.mean_error_second_half_us - result.mean_error_first_half_us;
    TEST_ASSERT_INT64_WITHIN(100, 0, drift_us);
    // The tracked rate follows the modelled oscillator wander (+/-0.28 %).
    TEST_ASSERT_UINT32_WITHIN(static_cast<uint32_t>(rate_hz * 3.0), static_cast<uint32_t>(rate_hz * 1000.0),
                              timing::sample_clock_rate_mhz(clock));
  }
}

void test_fifo_overflow_during_a_stall_is_counted_and_the_timeline_resyncs() {
  // A 100 ms stall overflows the 33-entry FIFO (41 ms): the lost samples are
  // counted, and stamps after the gap are on real time again.
  const SimulationResult result = simulate(800.0, 30000000ULL, 10000000ULL, 100000ULL);
  TEST_ASSERT_TRUE(result.actually_lost > 40);
  TEST_ASSERT_UINT64_WITHIN(1, result.actually_lost, result.counted_lost);
  TEST_ASSERT_EQUAL_UINT64(result.produced - result.actually_lost, result.delivered);
  TEST_ASSERT_LESS_THAN_INT64(500, result.max_abs_error_us);
}

void test_first_observation_locks_on_the_oldest_fifo_entry() {
  SampleClock clock = timing::make_sample_clock(800);
  // 4 entries seen at t=10000: the newest is ~625 us old, the oldest 3 periods before it.
  const SampleClockObservation observation =
      timing::sample_clock_observe(clock, 10000, 4, false);
  TEST_ASSERT_FALSE(observation.resynced);
  TEST_ASSERT_TRUE(clock.locked);
  TEST_ASSERT_EQUAL_INT64(timing::us_to_q16(10000 - 625 - 3 * 1250), timing::sample_clock_take(clock));
  TEST_ASSERT_EQUAL_INT64(timing::us_to_q16(10000 - 625 - 2 * 1250), timing::sample_clock_take(clock));
}

void test_only_a_full_fifo_counts_lost_samples() {
  // The timeline is 12.5 ms (10 periods) behind the estimate. Without an
  // overflow nothing can have been lost: it is tracking error, steered out.
  // With the FIFO full the 10 samples were overwritten: counted, and resynced.
  const bool overflowed[] = {false, true};
  for (bool fifo_overflowed : overflowed) {
    SampleClock clock = timing::make_sample_clock(800);
    timing::sample_clock_observe(clock, 10000, 8, false);
    for (int i = 0; i < 8; ++i) {
      timing::sample_clock_take(clock);
    }
    // Next oldest sample expected at 10000 - 625 - 7*1250 + 8*1250 = 10625.
    const size_t entries = fifo_overflowed ? 32 : 8;
    const int64_t observed_us = 10625 + 12500 + 625 + static_cast<int64_t>(entries - 1) * 1250;
    const SampleClockObservation observation =
        timing::sample_clock_observe(clock, observed_us, entries, fifo_overflowed);
    TEST_ASSERT_EQUAL(fifo_overflowed, observation.resynced);
    TEST_ASSERT_EQUAL_UINT32(fifo_overflowed ? 10U : 0U, observation.lost_samples);
  }
}

void test_poll_interval_varies_within_bounds() {
  uint32_t rng = 1;
  std::set<uint32_t> distinct;
  for (int i = 0; i < 2000; ++i) {
    const uint32_t interval_us = timing::sampling_poll_interval_us(rng, 10000, 5000);
    TEST_ASSERT_TRUE(interval_us >= 5000 && interval_us <= 15000);
    distinct.insert(interval_us);
  }
  // A fixed read cadence imprints a spectral line (#507/#508).
  TEST_ASSERT_TRUE(distinct.size() > 1000);
  TEST_ASSERT_EQUAL_UINT32(10000, timing::sampling_poll_interval_us(rng, 10000, 0));
}

// A sensor at `sensor_rate_hz` sampling a tone; its samples go through the
// SampleClock and Resampler as on the device. Returns the output samples.
std::vector<timing::ResampledSample> resample_tone(double sensor_rate_hz,
                                                   double tone_hz,
                                                   double amplitude,
                                                   uint64_t duration_us) {
  SampleClock clock = timing::make_sample_clock(800);
  static timing::Resampler resampler;
  timing::resampler_init(resampler, 800);
  uint32_t poll_rng = 0xC0FFEEU;
  const double period_us = 1000000.0 / sensor_rate_hz;
  std::vector<timing::ResampledSample> outputs;
  uint64_t next_index = 0;
  uint64_t drained_index = 0;
  uint64_t now_us = 10000;
  while (now_us < duration_us) {
    while (sensor_sample_time_us(period_us, next_index) <= static_cast<double>(now_us)) {
      next_index++;
    }
    timing::sample_clock_observe(clock, static_cast<int64_t>(now_us), next_index - drained_index,
                                 false);
    for (; drained_index < next_index; ++drained_index) {
      const double t_s = sensor_sample_time_us(period_us, drained_index) / 1e6;
      const int16_t value = static_cast<int16_t>(lround(amplitude * sin(2.0 * M_PI * tone_hz * t_s)));
      const int16_t xyz[3] = {value, 0, static_cast<int16_t>(-value)};
      timing::ResampledSample out[4];
      const size_t count = timing::resampler_push(
          resampler, xyz, timing::sample_clock_take(clock), out, 4);
      outputs.insert(outputs.end(), out, out + count);
    }
    now_us += timing::sampling_poll_interval_us(poll_rng, 10000, 5000);
  }
  return outputs;
}

// Least-squares fit of a*sin + b*cos at `tone_hz` over the output stamps;
// returns the fitted amplitude and the rms residual.
void fit_tone(const std::vector<timing::ResampledSample>& outputs,
              size_t first,
              double tone_hz,
              double* amplitude,
              double* residual_rms) {
  double ss = 0, cc = 0, sc = 0, ys = 0, yc = 0;
  for (size_t i = first; i < outputs.size(); ++i) {
    const double t_s = static_cast<double>(outputs[i].sample_us) / 1e6;
    const double sv = sin(2.0 * M_PI * tone_hz * t_s);
    const double cv = cos(2.0 * M_PI * tone_hz * t_s);
    const double y = outputs[i].xyz[0];
    ss += sv * sv; cc += cv * cv; sc += sv * cv; ys += y * sv; yc += y * cv;
  }
  const double det = ss * cc - sc * sc;
  const double a = (ys * cc - yc * sc) / det;
  const double b = (yc * ss - ys * sc) / det;
  double residual = 0;
  for (size_t i = first; i < outputs.size(); ++i) {
    const double t_s = static_cast<double>(outputs[i].sample_us) / 1e6;
    const double e = outputs[i].xyz[0] - (a * sin(2.0 * M_PI * tone_hz * t_s) +
                                          b * cos(2.0 * M_PI * tone_hz * t_s));
    residual += e * e;
  }
  *amplitude = sqrt(a * a + b * b);
  *residual_rms = sqrt(residual / static_cast<double>(outputs.size() - first));
}

void test_resampler_outputs_the_declared_rate_on_an_exact_grid() {
  const std::vector<timing::ResampledSample> outputs = resample_tone(823.0, 37.0, 1000.0, 60000000ULL);
  // 60 s of a sensor at 823 Hz become 800 samples per ESP second, 1250 us apart.
  TEST_ASSERT_UINT64_WITHIN(60, 48000, outputs.size());
  for (size_t i = 1; i < outputs.size(); ++i) {
    TEST_ASSERT_EQUAL_INT64(1250, outputs[i].sample_us - outputs[i - 1].sample_us);
  }
}

void test_resampled_tones_keep_their_true_frequency_and_amplitude() {
  // Labelled at 800 Hz, the raw 823 Hz stream would put a 37 Hz tone at 36 Hz.
  // After resampling the tone fits at its true frequency on the output stamps.
  const double tones_hz[] = {37.0, 120.0, 250.0};
  for (double tone_hz : tones_hz) {
    const std::vector<timing::ResampledSample> outputs =
        resample_tone(823.0, tone_hz, 1000.0, 40000000ULL);
    double amplitude = 0;
    double residual_rms = 0;
    fit_tone(outputs, 16000, tone_hz, &amplitude, &residual_rms);
    // Within 0.25 dB: the timing wander below costs ~2 % at 250 Hz.
    TEST_ASSERT_FLOAT_WITHIN(30.0f, 1000.0f, static_cast<float>(amplitude));
    // What remains is timing wander of the stamps (the clock's tracking error
    // against the wandering oscillator) plus int16 rounding: express it as
    // the rms timing error that would leave this residual on the tone.
    const double timing_error_us = residual_rms * sqrt(2.0) / (2.0 * M_PI * tone_hz * 1000.0) * 1e6;
    TEST_ASSERT_TRUE(timing_error_us < 150.0);
  }
}

}  // namespace

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_divisor_rate_schedule_stays_exact);
  RUN_TEST(test_non_divisor_rate_schedule_distributes_fractional_remainder_without_drift);
  RUN_TEST(test_stamps_follow_sensor_time_without_drift_despite_poll_latency);
  RUN_TEST(test_off_nominal_sensor_rate_is_measured_and_tracked_without_lag);
  RUN_TEST(test_fifo_overflow_during_a_stall_is_counted_and_the_timeline_resyncs);
  RUN_TEST(test_first_observation_locks_on_the_oldest_fifo_entry);
  RUN_TEST(test_only_a_full_fifo_counts_lost_samples);
  RUN_TEST(test_poll_interval_varies_within_bounds);
  RUN_TEST(test_resampler_outputs_the_declared_rate_on_an_exact_grid);
  RUN_TEST(test_resampled_tones_keep_their_true_frequency_and_amplitude);
  return UNITY_END();
}
