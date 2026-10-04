#include "runtime_sampling.h"

#include <esp_err.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include "reliability.h"
#include "sample_timing.h"
#include "runtime_config.h"

namespace vibesensor::runtime {
namespace {

constexpr char kSamplingTaskName[] = "vs_sampling";
constexpr uint32_t kSamplingTaskStackBytes = 6144;
constexpr uint8_t kSamplingErrorSensorRead = 1;
constexpr uint8_t kSamplingErrorFifoOverflow = 2;
constexpr uint8_t kSamplingErrorLostSamples = 3;
constexpr uint8_t kSamplingErrorHandoffOverflow = 14;
// The FIFO holds 32 samples; a poll that finds it full may have lost some.
constexpr size_t kAdxlFifoFullEntries = 32;
// A FIFO_STATUS read that took longer than this (the task was preempted) does
// not tell when the samples were taken precisely enough to steer the clock.
constexpr int64_t kMaxClockObservationWindowUs = 500;

// Each input sample completes at most two output samples (rates within 10 %).
constexpr size_t kResampledPerInput = 4;

using SensorFailureClass = vibesensor::reliability::SensorFailureClass;
namespace timing = vibesensor::sample_timing;

struct SensorDrainAttempt {
  size_t samples_read = 0;
  ADXL345::FailureKind failure_kind = ADXL345::FailureKind::kNone;
};

TaskHandle_t g_sampling_task_handle = nullptr;
esp_timer_handle_t g_sampling_timer_handle = nullptr;
portMUX_TYPE g_sampling_lock = portMUX_INITIALIZER_UNLOCKED;

void record_sampling_error_locked(SamplingState& state, uint8_t error_code, uint32_t now_ms) {
  state.status.last_error_code = error_code;
  state.status.last_error_ms = now_ms;
}

void sync_sampling_snapshot_locked(SamplingState& state) {
  state.status.sample_handoff_size = static_cast<uint16_t>(sample_handoff_size(state.handoff));
  state.status.sample_handoff_capacity =
      static_cast<uint16_t>(sample_handoff_capacity(state.handoff));
  state.status.sampling_handoff_overflow_drops = state.handoff.overflow_drops;
}

void sync_sampling_snapshot(SamplingState& state) {
  portENTER_CRITICAL(&g_sampling_lock);
  sync_sampling_snapshot_locked(state);
  portEXIT_CRITICAL(&g_sampling_lock);
}

void note_fifo_poll(SamplingState& state, size_t entries) {
  const uint32_t now_ms = millis();
  const int64_t clock_error_us = state.sample_clock.last_error_us;
  const uint32_t sensor_rate_mhz = timing::sample_clock_rate_mhz(state.sample_clock);
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.last_fifo_entries = static_cast<uint16_t>(entries);
  state.status.sample_clock_error_us = static_cast<int32_t>(clock_error_us);
  state.status.sensor_rate_mhz = sensor_rate_mhz;
  if (entries >= kAdxlFifoFullEntries) {
    state.status.sensor_fifo_overflows++;
    record_sampling_error_locked(state, kSamplingErrorFifoOverflow, now_ms);
  }
  portEXIT_CRITICAL(&g_sampling_lock);
}

void note_clock_resync(SamplingState& state, uint32_t lost_samples) {
  const uint32_t now_ms = millis();
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sampling_clock_resyncs++;
  state.status.sampling_lost_samples += lost_samples;
  if (lost_samples > 0) {
    record_sampling_error_locked(state, kSamplingErrorLostSamples, now_ms);
  }
  portEXIT_CRITICAL(&g_sampling_lock);
}

void note_sensor_reinit_attempt(SamplingState& state) {
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sensor_reinit_attempts++;
  portEXIT_CRITICAL(&g_sampling_lock);
}

void note_sensor_reinit_success(SamplingState& state) {
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sensor_reinit_success++;
  portEXIT_CRITICAL(&g_sampling_lock);
}

void note_sensor_bus_recovery_attempt(SamplingState& state) {
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sensor_bus_recovery_attempts++;
  portEXIT_CRITICAL(&g_sampling_lock);
}

void note_sensor_bus_recovery_success(SamplingState& state) {
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sensor_bus_recovery_success++;
  portEXIT_CRITICAL(&g_sampling_lock);
}

void note_sensor_read_error(SamplingState& state, ADXL345::FailureKind failure_kind) {
  const uint32_t now_ms = millis();
  state.sensor_consecutive_errors =
      vibesensor::reliability::saturating_inc_u8(state.sensor_consecutive_errors);
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sensor_read_errors++;
  if (failure_kind == ADXL345::FailureKind::kFifoStatusRead) {
    state.status.sensor_fifo_status_failures++;
  } else if (failure_kind == ADXL345::FailureKind::kFifoDataRead) {
    state.status.sensor_fifo_data_failures++;
  }
  record_sampling_error_locked(state, kSamplingErrorSensorRead, now_ms);
  portEXIT_CRITICAL(&g_sampling_lock);
}

void publish_sample(SamplingState& state, const timing::ResampledSample& resampled) {
  PendingSample sample{};
  sample.sample_us = static_cast<uint64_t>(resampled.sample_us);
  sample.x = resampled.xyz[0];
  sample.y = resampled.xyz[1];
  sample.z = resampled.xyz[2];
  sample.gap_before = state.pending_gap;
  const uint32_t now_ms = millis();
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.samples_total++;
  const bool ok = enqueue_pending_sample(state.handoff, sample);
  if (!ok) {
    record_sampling_error_locked(state, kSamplingErrorHandoffOverflow, now_ms);
  }
  sync_sampling_snapshot_locked(state);
  portEXIT_CRITICAL(&g_sampling_lock);
  // A dropped sample leaves a hole the next published sample has to mark.
  state.pending_gap = !ok;
}

// Stamps one drained sensor sample and publishes the resampled samples it completes.
void resample_and_publish(SamplingState& state, const int16_t* xyz) {
  timing::ResampledSample resampled[kResampledPerInput];
  const int64_t stamp_q16 = timing::sample_clock_take(state.sample_clock);
  const size_t count =
      timing::resampler_push(state.resampler, xyz, stamp_q16, resampled, kResampledPerInput);
  for (size_t i = 0; i < count; ++i) {
    publish_sample(state, resampled[i]);
  }
}

SensorFailureClass classify_sensor_failure(ADXL345::FailureKind failure_kind,
                                           size_t samples_read) {
  switch (failure_kind) {
    case ADXL345::FailureKind::kNone:
      return SensorFailureClass::kNone;
    case ADXL345::FailureKind::kFifoStatusRead:
      return SensorFailureClass::kRegisterAccess;
    case ADXL345::FailureKind::kFifoDataRead:
      return samples_read > 0 ? SensorFailureClass::kPartialFifoDrain
                              : SensorFailureClass::kFifoData;
    case ADXL345::FailureKind::kDeviceIdRead:
      return SensorFailureClass::kRepeatedCommunication;
    case ADXL345::FailureKind::kDeviceIdMismatch:
      return SensorFailureClass::kSensorIdentity;
    case ADXL345::FailureKind::kConfigWrite:
      return SensorFailureClass::kSensorConfiguration;
  }
  return SensorFailureClass::kNone;
}

// Reads the FIFO depth, steers the sample clock with it, then drains and
// publishes every sample the FIFO holds.
SensorDrainAttempt drain_sensor_fifo_once(SamplingState& state) {
  SensorDrainAttempt attempt{};
  size_t entries = 0;
  const int64_t before_us = esp_timer_get_time();
  const bool status_ok = state.adxl.read_fifo_entries(&entries, &attempt.failure_kind);
  const int64_t after_us = esp_timer_get_time();
  if (!status_ok) {
    return attempt;
  }
  if (entries > ADXL345::kMaxFifoEntries) {
    entries = ADXL345::kMaxFifoEntries;
  }
  // A full FIFO may have lost samples: always observe it, so the loss is
  // counted (a slow read only blurs the estimate by its duration).
  const bool fifo_overflowed = entries >= kAdxlFifoFullEntries;
  if (entries > 0 && (!state.sample_clock.locked || fifo_overflowed ||
                      (after_us - before_us) <= kMaxClockObservationWindowUs)) {
    const timing::SampleClockObservation observation = timing::sample_clock_observe(
        state.sample_clock, before_us + ((after_us - before_us) / 2), entries, fifo_overflowed);
    if (observation.resynced) {
      // The samples around the discontinuity cannot be interpolated across.
      note_clock_resync(state, observation.lost_samples);
      timing::resampler_reset(state.resampler);
      state.pending_gap = true;
    }
  }
  note_fifo_poll(state, entries);
  if (entries == 0) {
    return attempt;
  }

  attempt.samples_read =
      state.adxl.read_fifo_samples(state.sensor_batch_xyz, entries, &attempt.failure_kind);
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sensor_samples_total += static_cast<uint32_t>(attempt.samples_read);
  portEXIT_CRITICAL(&g_sampling_lock);
  for (size_t i = 0; i < attempt.samples_read; ++i) {
    resample_and_publish(state, &state.sensor_batch_xyz[i * kAxesPerSample]);
  }
  return attempt;
}

bool recover_sensor_bus(SamplingState& state, ADXL345::FailureKind* failure_kind) {
  note_sensor_bus_recovery_attempt(state);
  const bool recovered = state.adxl.recover_bus(failure_kind);
  if (recovered) {
    note_sensor_bus_recovery_success(state);
  }
  return recovered;
}

bool maybe_reinit_sensor(SamplingState& state, bool force = false) {
  const uint32_t now_ms = millis();
  const bool initial_retry = state.last_sensor_reinit_ms == 0;
  const bool cooldown_ready =
      initial_retry ||
      static_cast<int32_t>(now_ms - state.last_sensor_reinit_ms) >=
          static_cast<int32_t>(kSensorReinitCooldownMs);
  if (!cooldown_ready) {
    return false;
  }
  if (!force && !initial_retry &&
      !vibesensor::reliability::sensor_should_reinit(state.sensor_consecutive_errors,
                                                     kSensorReinitErrorThreshold,
                                                     now_ms,
                                                     state.last_sensor_reinit_ms,
                                                     kSensorReinitCooldownMs)) {
    return false;
  }

  state.last_sensor_reinit_ms = now_ms;
  note_sensor_reinit_attempt(state);
  // A re-init empties the FIFO; the sample clock sees the gap and resyncs.
  state.sensor_ok = state.adxl.begin();
  if (state.sensor_ok) {
    state.sensor_consecutive_errors = 0;
    note_sensor_reinit_success(state);
  }
  return state.sensor_ok;
}

void poll_sensor_fifo(SamplingState& state) {
  if (!state.sensor_ok && !maybe_reinit_sensor(state, true)) {
    return;
  }

  size_t samples_read = 0;
  ADXL345::FailureKind failure_kind = ADXL345::FailureKind::kNone;
  SensorFailureClass failure_class = SensorFailureClass::kNone;
  uint8_t exhausted_failures = 0;
  while (true) {
    const SensorDrainAttempt attempt = drain_sensor_fifo_once(state);
    samples_read += attempt.samples_read;
    failure_kind = attempt.failure_kind;
    failure_class = classify_sensor_failure(failure_kind, samples_read);
    if (failure_kind == ADXL345::FailureKind::kNone) {
      break;
    }
    const vibesensor::reliability::SensorReadRetryStep retry_step =
        vibesensor::reliability::sensor_read_retry_step(exhausted_failures, failure_class);
    if (!retry_step.retry_read) {
      break;
    }
    exhausted_failures++;
    if (retry_step.recover_bus) {
      ADXL345::FailureKind recovery_failure = ADXL345::FailureKind::kNone;
      if (!recover_sensor_bus(state, &recovery_failure)) {
        failure_kind = recovery_failure;
        failure_class = classify_sensor_failure(recovery_failure, samples_read);
        break;
      }
    }
  }

  if (failure_class == SensorFailureClass::kNone) {
    state.sensor_consecutive_errors = 0;
    return;
  }
  note_sensor_read_error(state, failure_kind);
  if (vibesensor::reliability::sensor_failure_requires_forced_reinit(failure_class)) {
    state.sensor_ok = false;
    (void)maybe_reinit_sensor(state, true);
  } else if (vibesensor::reliability::sensor_should_reinit(state.sensor_consecutive_errors,
                                                           kSensorReinitErrorThreshold,
                                                           millis(),
                                                           state.last_sensor_reinit_ms,
                                                           kSensorReinitCooldownMs)) {
    state.sensor_ok = false;
    (void)maybe_reinit_sensor(state);
  }
}

void sampling_timer_callback(void*) {
  if (g_sampling_task_handle != nullptr) {
    xTaskNotifyGive(g_sampling_task_handle);
  }
}

// Each poll arms the next one first, so the interval runs from poll start to
// poll start. The interval only sets how often the FIFO is drained, never the
// sample rate or the stamps, so its jitter costs nothing.
void arm_next_poll(SamplingState& state) {
  const uint32_t interval_us = timing::sampling_poll_interval_us(
      state.poll_rng_state, kSamplingPollIntervalUs, kSamplingPollJitterUs);
  const esp_err_t err = esp_timer_start_once(g_sampling_timer_handle, interval_us);
  if (err != ESP_OK) {
    Serial.printf("WARN: failed to arm sampling timer (%d)\n", static_cast<int>(err));
  }
}

void sampling_task_main(void* arg) {
  auto& state = *static_cast<SamplingState*>(arg);
  while (true) {
    (void)ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    arm_next_poll(state);
    poll_sensor_fifo(state);
  }
}

}  // namespace

SamplingState::SamplingState()
    : i2c(Wire), adxl(i2c, kAdxlI2cAddr, kI2cSdaPin, kI2cSclPin, kAdxlRateCode) {}

bool begin_sampling(SamplingState& state) {
  initialize_sample_handoff(state.handoff, state.handoff_storage, kSampleHandoffQueueSamples);
  sync_sampling_snapshot(state);
  state.sample_clock = timing::make_sample_clock(kSampleRateHz);
  timing::resampler_init(state.resampler, kSampleRateHz);
  state.poll_rng_state = static_cast<uint32_t>(esp_timer_get_time()) | 1U;

  state.sensor_ok = state.adxl.begin();
  if (!state.sensor_ok) {
    const uint32_t now_ms = millis();
    portENTER_CRITICAL(&g_sampling_lock);
    record_sampling_error_locked(state, kSamplingErrorSensorRead, now_ms);
    portEXIT_CRITICAL(&g_sampling_lock);
  }

  esp_timer_create_args_t timer_args = {};
  timer_args.callback = &sampling_timer_callback;
  timer_args.arg = nullptr;
  timer_args.dispatch_method = ESP_TIMER_TASK;
  timer_args.name = "vs_sampling";
  const esp_err_t timer_err = esp_timer_create(&timer_args, &g_sampling_timer_handle);
  if (timer_err != ESP_OK) {
    Serial.printf("WARN: failed to create sampling timer (%d)\n", static_cast<int>(timer_err));
    g_sampling_timer_handle = nullptr;
    return false;
  }

  const UBaseType_t loop_priority = uxTaskPriorityGet(nullptr);
  const UBaseType_t sampling_priority =
      loop_priority < (configMAX_PRIORITIES - 1) ? (loop_priority + 1) : loop_priority;
  const BaseType_t created = xTaskCreatePinnedToCore(sampling_task_main,
                                                     kSamplingTaskName,
                                                     kSamplingTaskStackBytes,
                                                     &state,
                                                     sampling_priority,
                                                     &g_sampling_task_handle,
                                                     static_cast<BaseType_t>(kSamplingTaskCore));
  if (created != pdPASS) {
    Serial.printf("WARN: failed to create sampling task\n");
    g_sampling_task_handle = nullptr;
    esp_timer_delete(g_sampling_timer_handle);
    g_sampling_timer_handle = nullptr;
    return false;
  }
  Serial.printf("task cores: loop=%d current=%d sampling=%d\n",
                kArduinoLoopTaskCore,
                static_cast<int>(xPortGetCoreID()),
                kSamplingTaskCore);

  // The first poll arms every later one.
  xTaskNotifyGive(g_sampling_task_handle);
  return true;
}

void service_sample_handoff(SamplingState& state,
                            FrameQueueState& queue_state,
                            RuntimeStatus& status,
                            int64_t clock_offset_us) {
  PendingSample sample{};
  while (true) {
    bool has_sample = false;
    portENTER_CRITICAL(&g_sampling_lock);
    has_sample = dequeue_pending_sample(state.handoff, &sample);
    if (has_sample) {
      sync_sampling_snapshot_locked(state);
    }
    portEXIT_CRITICAL(&g_sampling_lock);
    if (!has_sample) {
      return;
    }

    append_sample(queue_state,
                  status,
                  sample.x,
                  sample.y,
                  sample.z,
                  sample.sample_us,
                  sample.gap_before,
                  clock_offset_us);
  }
}

SamplingStatusSnapshot snapshot_sampling_status(SamplingState& state) {
  SamplingStatusSnapshot snapshot{};
  portENTER_CRITICAL(&g_sampling_lock);
  snapshot = state.status;
  portEXIT_CRITICAL(&g_sampling_lock);
  return snapshot;
}

}  // namespace vibesensor::runtime
