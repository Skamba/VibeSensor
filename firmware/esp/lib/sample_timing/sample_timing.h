#pragma once

// Sample timing for the ADXL345 stream: when the sensor took each sample, and
// the resampling onto the exact declared rate.
//
// The ADXL345 paces its samples with its own oscillator, which is not
// trimmed: one ATOM Lite unit measured 823 Hz for a nominal 800 Hz (+2.9 %).
// The firmware therefore
//   1. drains every sample the sensor makes (SampleClock stamps each one on
//      the ESP clock, measuring the sensor's real period), and
//   2. resamples them onto an exact grid of the declared rate on the ESP clock
//      (Resampler), so the rate the server assumes is true and every frame's
//      t0 is the real time of its first sample.

#include <math.h>
#include <stddef.h>
#include <stdint.h>

namespace vibesensor::sample_timing {

// Exact integer-microsecond steps of a rate: 1e6 / rate with the remainder
// carried, so 3200 Hz alternates 312/313 us and never drifts.
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

// Times are fixed point: microseconds x 2^16 (Q16), so a sensor period such as
// 1215.07 us keeps its fraction. int64 Q16 spans ~4 years of uptime.
constexpr int64_t kQ16One = 65536;

inline int64_t us_to_q16(int64_t us) { return us * kQ16One; }

// ---------------------------------------------------------------------------
// SampleClock: stamps each drained sensor sample on the ESP clock.
//
// The sampling task drains the whole FIFO on every poll. A poll that sees
// `fifo_entries` samples at `observed_us` places the oldest of them
// (fifo_entries - 1) periods plus half a period (the newest is on average
// half a period old) before the observation.
// The clock keeps one continuous timeline and steers it with those
// estimates through a second-order loop: per poll the timeline moves
// 1/kSampleClockPhaseDivisor of the error and the period integrates
// 1/kSampleClockPeriodDivisor of it. So the timeline runs at the sensor's
// real rate with no steady lag, from a few percent off nominal at start-up.
// The loop is fast (time constant ~0.2 s) on purpose: poll traces on hardware
// showed single estimates are good to their half-period quantisation (~350 us
// rms), while the sensor oscillator itself wanders by a few tenths of a
// percent over seconds (+/- several ms of phase); a slow loop would average
// the quantisation better but not follow the wander.
// The timeline never drifts from the ESP clock: any drift shows up as error
// and is corrected.
//
// Samples are only ever lost to a FIFO overflow. A poll that found the FIFO
// full (`fifo_overflowed`) and an error beyond kSampleClockOverflowResyncPeriods
// is that discontinuity: when the timeline is behind, the missing samples are
// counted as lost, and the timeline restarts from the estimate. Without an
// overflow, an error up to kSampleClockResyncPeriods is tracking error (the
// sensor oscillator wandered while observations were skipped) and the loop
// steers it out; only a larger one (a re-initialised sensor) restarts it.
// ---------------------------------------------------------------------------
constexpr int64_t kSampleClockPhaseDivisor = 8;
// Critically damped at ~8 samples per poll: 8 / PeriodDivisor = (1 / PhaseDivisor)^2 / 4.
constexpr int64_t kSampleClockPeriodDivisor = 2048;
constexpr int64_t kSampleClockOverflowResyncPeriods = 8;
constexpr int64_t kSampleClockResyncPeriods = 64;
// The ADXL345 oscillator is off by a few percent; a period beyond this is
// treated as a disturbed measurement and clamped.
constexpr int64_t kSampleClockMaxRateDeviationPercent = 10;

struct SampleClock {
  int64_t nominal_period_q16 = 0;
  int64_t period_q16 = 0;
  int64_t next_sample_q16 = 0;
  uint64_t next_index = 0;
  bool locked = false;
  int64_t last_error_us = 0;
};

struct SampleClockObservation {
  uint32_t lost_samples = 0;
  bool resynced = false;
};

inline SampleClock make_sample_clock(uint32_t nominal_rate_hz) {
  SampleClock clock{};
  if (nominal_rate_hz > 0U) {
    clock.nominal_period_q16 = us_to_q16(1000000) / static_cast<int64_t>(nominal_rate_hz);
  }
  clock.period_q16 = clock.nominal_period_q16;
  return clock;
}

// The sensor's rate as the clock currently tracks it, in milli-Hz.
inline uint32_t sample_clock_rate_mhz(const SampleClock& clock) {
  if (clock.period_q16 <= 0) {
    return 0;
  }
  return static_cast<uint32_t>((us_to_q16(1000000) * 1000) / clock.period_q16);
}

inline int64_t sample_clock_oldest_entry_q16(const SampleClock& clock,
                                             int64_t observed_us,
                                             size_t fifo_entries) {
  const int64_t half_periods = (2 * static_cast<int64_t>(fifo_entries)) - 1;
  return us_to_q16(observed_us) - ((half_periods * clock.period_q16) / 2);
}

inline int64_t sample_clock_clamp_period(const SampleClock& clock, int64_t period_q16) {
  const int64_t max_deviation_q16 =
      (clock.nominal_period_q16 * kSampleClockMaxRateDeviationPercent) / 100;
  if (period_q16 > clock.nominal_period_q16 + max_deviation_q16) {
    return clock.nominal_period_q16 + max_deviation_q16;
  }
  if (period_q16 < clock.nominal_period_q16 - max_deviation_q16) {
    return clock.nominal_period_q16 - max_deviation_q16;
  }
  return period_q16;
}

inline SampleClockObservation sample_clock_observe(SampleClock& clock,
                                                   int64_t observed_us,
                                                   size_t fifo_entries,
                                                   bool fifo_overflowed) {
  SampleClockObservation result{};
  if (fifo_entries == 0 || clock.period_q16 <= 0) {
    return result;
  }
  const int64_t estimate_q16 = sample_clock_oldest_entry_q16(clock, observed_us, fifo_entries);
  if (!clock.locked) {
    clock.next_sample_q16 = estimate_q16;
    clock.last_error_us = 0;
    clock.locked = true;
    return result;
  }
  const int64_t error_q16 = estimate_q16 - clock.next_sample_q16;
  clock.last_error_us = error_q16 / kQ16One;
  const int64_t resync_q16 =
      (fifo_overflowed ? kSampleClockOverflowResyncPeriods : kSampleClockResyncPeriods) *
      clock.period_q16;
  if (error_q16 > resync_q16 || error_q16 < -resync_q16) {
    if (error_q16 > 0 && fifo_overflowed) {
      result.lost_samples =
          static_cast<uint32_t>((error_q16 + (clock.period_q16 / 2)) / clock.period_q16);
    }
    result.resynced = true;
    clock.next_sample_q16 = estimate_q16;
    return result;
  }
  clock.next_sample_q16 += error_q16 / kSampleClockPhaseDivisor;
  clock.period_q16 =
      sample_clock_clamp_period(clock, clock.period_q16 + error_q16 / kSampleClockPeriodDivisor);
  return result;
}

// Returns when the next drained sample was taken (Q16 us) and advances.
inline int64_t sample_clock_take(SampleClock& clock) {
  const int64_t stamp_q16 = clock.next_sample_q16;
  clock.next_sample_q16 += clock.period_q16;
  clock.next_index++;
  return stamp_q16;
}

// ---------------------------------------------------------------------------
// Resampler: turns the stamped sensor samples into samples on an exact grid of
// the declared rate (integer-us steps from SamplingIntervalSchedule).
//
// Each output sample is a Kaiser-windowed-sinc interpolation over
// kResamplerTaps input samples around its time (polyphase table with linear
// interpolation between phases). The cutoff (0.42 of the input rate) keeps
// the band up to ~0.35 of the input rate flat (~290 Hz at 823 Hz) and stops
// what would alias above the output Nyquist for sensors up to ~10 % fast.
// The output lags the input by half the taps (~20 ms), which only delays
// emission: the stamps are the real times.
//
// After a discontinuity (resampler_reset) the output grid continues; grid
// points without input around them are skipped and the caller marks the gap.
// ---------------------------------------------------------------------------
constexpr size_t kResamplerTaps = 32;
constexpr size_t kResamplerHalfTaps = kResamplerTaps / 2;
constexpr size_t kResamplerPhases = 64;
constexpr size_t kResamplerHistory = 64;
constexpr float kResamplerCutoff = 0.42f;
constexpr float kResamplerKaiserBeta = 6.0f;
constexpr size_t kAxes = 3;

static_assert((kResamplerHistory & (kResamplerHistory - 1)) == 0,
              "resampler history must be a power of two");
static_assert(kResamplerHistory >= 2 * kResamplerTaps, "resampler history too short");

struct ResampledSample {
  int64_t sample_us = 0;
  int16_t xyz[kAxes] = {};
};

struct Resampler {
  float kernel[(kResamplerPhases + 1) * kResamplerTaps] = {};
  float history[kResamplerHistory * kAxes] = {};
  int64_t stamps_q16[kResamplerHistory] = {};
  uint64_t pushed = 0;
  uint64_t cursor = 0;
  SamplingIntervalSchedule schedule = {};
  int64_t next_output_us = 0;
  bool grid_started = false;
  bool primed = false;
};

inline double resampler_bessel_i0(double x) {
  double sum = 1.0;
  double term = 1.0;
  for (int k = 1; k < 32; ++k) {
    term *= (x / (2.0 * k)) * (x / (2.0 * k));
    sum += term;
  }
  return sum;
}

inline void resampler_init(Resampler& resampler, uint32_t output_rate_hz) {
  const double pi = 3.14159265358979323846;
  const double half_span = static_cast<double>(kResamplerHalfTaps);
  const double i0_beta = resampler_bessel_i0(kResamplerKaiserBeta);
  for (size_t phase = 0; phase <= kResamplerPhases; ++phase) {
    const double frac = static_cast<double>(phase) / static_cast<double>(kResamplerPhases);
    float* row = &resampler.kernel[phase * kResamplerTaps];
    double sum = 0.0;
    for (size_t tap = 0; tap < kResamplerTaps; ++tap) {
      // Input sample (cursor - 15 + tap) sits this many input periods from
      // the output time, which is `frac` past the cursor sample.
      const double distance =
          (static_cast<double>(tap) - static_cast<double>(kResamplerHalfTaps - 1)) - frac;
      const double x = 2.0 * kResamplerCutoff * distance;
      const double sinc = (x == 0.0) ? 1.0 : sin(pi * x) / (pi * x);
      const double ratio = distance / half_span;
      const double window =
          (ratio <= -1.0 || ratio >= 1.0)
              ? 0.0
              : resampler_bessel_i0(kResamplerKaiserBeta * sqrt(1.0 - ratio * ratio)) / i0_beta;
      const double value = sinc * window;
      row[tap] = static_cast<float>(value);
      sum += value;
    }
    for (size_t tap = 0; tap < kResamplerTaps; ++tap) {
      row[tap] = static_cast<float>(row[tap] / sum);
    }
  }
  resampler.schedule = make_sampling_interval_schedule(output_rate_hz);
  resampler.pushed = 0;
  resampler.cursor = 0;
  resampler.next_output_us = 0;
  resampler.grid_started = false;
  resampler.primed = false;
}

// Drops the input history after a discontinuity; the output grid continues.
inline void resampler_reset(Resampler& resampler) {
  resampler.pushed = 0;
  resampler.cursor = 0;
  resampler.primed = false;
}

inline int64_t resampler_stamp(const Resampler& resampler, uint64_t index) {
  return resampler.stamps_q16[index & (kResamplerHistory - 1)];
}

// Grid points skipped to reach the first output after a reset.
inline uint64_t resampler_prime(Resampler& resampler) {
  const uint64_t first_index = kResamplerHalfTaps - 1;
  const int64_t earliest_q16 = resampler_stamp(resampler, first_index);
  const int64_t earliest_us = (earliest_q16 + kQ16One - 1) / kQ16One;
  uint64_t skipped = 0;
  if (!resampler.grid_started) {
    resampler.next_output_us = earliest_us;
    resampler.grid_started = true;
  } else if (resampler.next_output_us < earliest_us) {
    const int64_t base_us = static_cast<int64_t>(resampler.schedule.base_interval_us);
    const int64_t behind_us = earliest_us - resampler.next_output_us;
    uint64_t bulk = static_cast<uint64_t>(behind_us / (base_us + 1));
    if (bulk > 0) {
      resampler.next_output_us +=
          static_cast<int64_t>(sampling_schedule_advance_us(resampler.schedule, bulk));
      skipped += bulk;
    }
    while (resampler.next_output_us < earliest_us) {
      resampler.next_output_us +=
          static_cast<int64_t>(sampling_schedule_advance_us(resampler.schedule));
      skipped++;
    }
  }
  resampler.cursor = first_index;
  resampler.primed = true;
  return skipped;
}

// Adds one stamped input sample and writes the output samples it completes
// (at most out_capacity) to `out`; returns how many. `skipped_outputs`
// (optional) receives grid points skipped after a reset.
inline size_t resampler_push(Resampler& resampler,
                             const int16_t* xyz,
                             int64_t stamp_q16,
                             ResampledSample* out,
                             size_t out_capacity,
                             uint64_t* skipped_outputs = nullptr) {
  const size_t slot = static_cast<size_t>(resampler.pushed & (kResamplerHistory - 1));
  for (size_t axis = 0; axis < kAxes; ++axis) {
    resampler.history[slot * kAxes + axis] = static_cast<float>(xyz[axis]);
  }
  resampler.stamps_q16[slot] = stamp_q16;
  resampler.pushed++;

  if (!resampler.primed) {
    if (resampler.pushed < kResamplerHalfTaps) {
      return 0;
    }
    const uint64_t skipped = resampler_prime(resampler);
    if (skipped_outputs != nullptr) {
      *skipped_outputs += skipped;
    }
  }

  size_t emitted = 0;
  while (emitted < out_capacity) {
    const int64_t output_q16 = us_to_q16(resampler.next_output_us);
    while (resampler.cursor + 1 < resampler.pushed &&
           resampler_stamp(resampler, resampler.cursor + 1) <= output_q16) {
      resampler.cursor++;
    }
    // The newest input must reach half the taps past the cursor.
    if (resampler.cursor + kResamplerHalfTaps >= resampler.pushed) {
      break;
    }
    const int64_t left_q16 = resampler_stamp(resampler, resampler.cursor);
    const int64_t right_q16 = resampler_stamp(resampler, resampler.cursor + 1);
    float frac = 0.0f;
    if (right_q16 > left_q16 && output_q16 > left_q16) {
      frac = static_cast<float>(static_cast<double>(output_q16 - left_q16) /
                                static_cast<double>(right_q16 - left_q16));
    }
    if (frac > 1.0f) {
      frac = 1.0f;
    }
    const float phase_pos = frac * static_cast<float>(kResamplerPhases);
    size_t phase = static_cast<size_t>(phase_pos);
    if (phase >= kResamplerPhases) {
      phase = kResamplerPhases - 1;
    }
    const float blend = phase_pos - static_cast<float>(phase);
    const float* row0 = &resampler.kernel[phase * kResamplerTaps];
    const float* row1 = row0 + kResamplerTaps;
    float acc[kAxes] = {0.0f, 0.0f, 0.0f};
    const uint64_t first = resampler.cursor - (kResamplerHalfTaps - 1);
    for (size_t tap = 0; tap < kResamplerTaps; ++tap) {
      const float coeff = row0[tap] + (row1[tap] - row0[tap]) * blend;
      const size_t index = static_cast<size_t>((first + tap) & (kResamplerHistory - 1));
      for (size_t axis = 0; axis < kAxes; ++axis) {
        acc[axis] += coeff * resampler.history[index * kAxes + axis];
      }
    }
    ResampledSample& sample = out[emitted++];
    sample.sample_us = resampler.next_output_us;
    for (size_t axis = 0; axis < kAxes; ++axis) {
      const float rounded = acc[axis] >= 0.0f ? acc[axis] + 0.5f : acc[axis] - 0.5f;
      const float clamped = rounded > 32767.0f ? 32767.0f : (rounded < -32768.0f ? -32768.0f : rounded);
      sample.xyz[axis] = static_cast<int16_t>(clamped);
    }
    resampler.next_output_us +=
        static_cast<int64_t>(sampling_schedule_advance_us(resampler.schedule));
  }
  return emitted;
}

// ---------------------------------------------------------------------------
// FIFO poll cadence. The poll interval varies between base - jitter and
// base + jitter. A fixed cadence makes the I2C read bursts a periodic
// disturbance that imprints a narrowband line and its harmonics on idle
// spectra (#507/#508); a varying cadence spreads that energy across the band.
// xorshift32 keeps the sequence deterministic for tests; state must be
// non-zero.
// ---------------------------------------------------------------------------
inline uint32_t xorshift32(uint32_t& state) {
  uint32_t x = state;
  x ^= x << 13;
  x ^= x >> 17;
  x ^= x << 5;
  state = x;
  return x;
}

inline uint32_t sampling_poll_interval_us(uint32_t& rng_state,
                                          uint32_t base_us,
                                          uint32_t jitter_us) {
  if (jitter_us == 0U || jitter_us >= base_us) {
    return base_us;
  }
  const uint32_t span = (2U * jitter_us) + 1U;
  return base_us - jitter_us + (xorshift32(rng_state) % span);
}

}  // namespace vibesensor::sample_timing
