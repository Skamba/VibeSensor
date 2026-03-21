#include "runtime_sampling.h"

#include <math.h>

#include <esp_system.h>
#include <esp_timer.h>

#include "reliability.h"
#include "runtime_config.h"

namespace vibesensor::runtime {
namespace {

void synth_sample(int16_t* x, int16_t* y, int16_t* z) {
  const float t = static_cast<float>(esp_timer_get_time()) / 1.0e6f;
  *x = static_cast<int16_t>(700.0f * sinf(2.0f * PI * 13.0f * t));
  *y = static_cast<int16_t>(350.0f * sinf(2.0f * PI * 27.0f * t + 0.7f));
  *z = static_cast<int16_t>(900.0f * sinf(2.0f * PI * 41.0f * t + 1.1f));
}

bool next_sensor_sample(SamplingState& state,
                        RuntimeStatus& status,
                        int16_t* x,
                        int16_t* y,
                        int16_t* z) {
  if (!state.sensor_ok) {
    return false;
  }
  if (state.sensor_prefetch_count <= kSensorPrefetchLowWaterSamples) {
    bool io_error = false;
    bool fifo_truncated = false;
    size_t max_to_read = kSensorReadBatchSamples;
    size_t free_slots = kSensorPrefetchSamples - state.sensor_prefetch_count;
    if (free_slots < max_to_read) {
      max_to_read = free_slots;
    }
    if (max_to_read > 1) {
      max_to_read = 1 + (esp_random() % max_to_read);
    }
    size_t read_count = state.adxl.read_samples(
        state.sensor_batch_xyz, max_to_read, &io_error, &fifo_truncated);
    if (fifo_truncated) {
      status.sensor_fifo_truncated++;
      set_last_error(status, 2);
    }
    if (io_error) {
      status.sensor_read_errors++;
      state.sensor_consecutive_errors =
          vibesensor::reliability::saturating_inc_u8(state.sensor_consecutive_errors);
      set_last_error(status, 1);
      uint32_t now_ms = millis();
      if (vibesensor::reliability::sensor_should_reinit(
              state.sensor_consecutive_errors,
              kSensorReinitErrorThreshold,
              now_ms,
              state.last_sensor_reinit_ms,
              kSensorReinitCooldownMs)) {
        state.last_sensor_reinit_ms = now_ms;
        status.sensor_reinit_attempts++;
        state.sensor_ok = state.adxl.begin();
        if (state.sensor_ok) {
          status.sensor_reinit_success++;
          state.sensor_consecutive_errors = 0;
          state.sensor_prefetch_head = 0;
          state.sensor_prefetch_tail = 0;
          state.sensor_prefetch_count = 0;
        }
      }
    } else {
      state.sensor_consecutive_errors = 0;
    }
    if (read_count > 0) {
      for (size_t i = 0;
           i < read_count && state.sensor_prefetch_count < kSensorPrefetchSamples;
           ++i) {
        const size_t src = i * 3;
        const size_t dst = state.sensor_prefetch_head * 3;
        state.sensor_prefetch_xyz[dst + 0] = state.sensor_batch_xyz[src + 0];
        state.sensor_prefetch_xyz[dst + 1] = state.sensor_batch_xyz[src + 1];
        state.sensor_prefetch_xyz[dst + 2] = state.sensor_batch_xyz[src + 2];
        state.sensor_prefetch_head =
            (state.sensor_prefetch_head + 1) % kSensorPrefetchSamples;
        state.sensor_prefetch_count++;
      }
    }
  }
  if (state.sensor_prefetch_count == 0) {
    return false;
  }
  const size_t offset = state.sensor_prefetch_tail * 3;
  *x = state.sensor_prefetch_xyz[offset + 0];
  *y = state.sensor_prefetch_xyz[offset + 1];
  *z = state.sensor_prefetch_xyz[offset + 2];
  state.sensor_prefetch_tail =
      (state.sensor_prefetch_tail + 1) % kSensorPrefetchSamples;
  state.sensor_prefetch_count--;
  return true;
}

bool sample_once(SamplingState& state,
                 FrameQueueState& queue_state,
                 RuntimeStatus& status,
                 int64_t clock_offset_us) {
  int16_t x = 0;
  int16_t y = 0;
  int16_t z = 0;

  if (next_sensor_sample(state, status, &x, &y, &z)) {
    state.has_last_real_sample = true;
    state.last_real_x = x;
    state.last_real_y = y;
    state.last_real_z = z;
  } else {
#if VIBESENSOR_ENABLE_SYNTH_FALLBACK
    synth_sample(&x, &y, &z);
#else
    return false;
#endif
  }

  append_sample(queue_state,
                status,
                x,
                y,
                z,
                state.next_sample_due_us,
                clock_offset_us);
  return true;
}

}  // namespace

SamplingState::SamplingState()
    : i2c(Wire), adxl(i2c, kAdxlI2cAddr, kI2cSdaPin, kI2cSclPin) {}

bool begin_sensor(SamplingState& state) {
  state.sensor_ok = state.adxl.begin();
  return state.sensor_ok;
}

void reset_sampling_schedule(SamplingState& state, uint64_t now_us) {
  state.next_sample_due_us = now_us;
}

void service_sampling(SamplingState& state,
                      FrameQueueState& queue_state,
                      RuntimeStatus& status,
                      int64_t clock_offset_us) {
  const uint64_t step_us = 1000000ULL / kSampleRateHz;
  uint64_t now = esp_timer_get_time();
  size_t catch_up_count = 0;
  while (static_cast<int64_t>(now - state.next_sample_due_us) >= 0 &&
         catch_up_count < kMaxCatchUpSamplesPerLoop) {
    if (!sample_once(state, queue_state, status, clock_offset_us)) {
      status.sampling_missed_samples++;
      state.next_sample_due_us += step_us;
      break;
    }
    state.next_sample_due_us += step_us;
    catch_up_count++;
    now = esp_timer_get_time();
  }

  if (static_cast<int64_t>(now - state.next_sample_due_us) >= 0) {
    uint64_t lag_us = now - state.next_sample_due_us;
    uint64_t skipped = (lag_us / step_us) + 1;
    status.sampling_missed_samples += static_cast<uint32_t>(skipped);
    set_last_error(status, 3);
    state.next_sample_due_us += skipped * step_us;
  }
}

}  // namespace vibesensor::runtime
