#include "runtime_sampling.h"

#include <math.h>

#include <esp_err.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include "reliability.h"
#include "runtime_config.h"

namespace vibesensor::runtime {
namespace {

constexpr char kSamplingTaskName[] = "vs_sampling";
constexpr uint32_t kSamplingTaskStackBytes = 6144;
constexpr uint8_t kSamplingErrorSensorRead = 1;
constexpr uint8_t kSamplingErrorFifoTruncated = 2;
constexpr uint8_t kSamplingErrorMissedSample = 3;
constexpr uint8_t kSamplingErrorHandoffOverflow = 14;

using SensorFailureClass = vibesensor::reliability::SensorFailureClass;

struct SensorRefillAttempt {
  size_t recovered_samples = 0;
  bool fifo_truncated = false;
  ADXL345::FailureKind failure_kind = ADXL345::FailureKind::kNone;
  SensorFailureClass failure_class = SensorFailureClass::kNone;
};

TaskHandle_t g_sampling_task_handle = nullptr;
esp_timer_handle_t g_sampling_timer_handle = nullptr;
portMUX_TYPE g_sampling_lock = portMUX_INITIALIZER_UNLOCKED;

void synth_sample(int16_t* x, int16_t* y, int16_t* z) {
  const float t = static_cast<float>(esp_timer_get_time()) / 1.0e6f;
  *x = static_cast<int16_t>(700.0f * sinf(2.0f * PI * 13.0f * t));
  *y = static_cast<int16_t>(350.0f * sinf(2.0f * PI * 27.0f * t + 0.7f));
  *z = static_cast<int16_t>(900.0f * sinf(2.0f * PI * 41.0f * t + 1.1f));
}

void record_sampling_error_locked(SamplingState& state, uint8_t error_code, uint32_t now_ms) {
  state.status.last_error_code = error_code;
  state.status.last_error_ms = now_ms;
}

void sync_sampling_snapshot_locked(SamplingState& state) {
  state.status.sample_handoff_size = static_cast<uint16_t>(sample_handoff_size(state.handoff));
  state.status.sample_handoff_capacity =
      static_cast<uint16_t>(sample_handoff_capacity(state.handoff));
  state.status.sensor_prefetch_count = static_cast<uint16_t>(state.sensor_prefetch_count);
  state.status.last_refill_request = static_cast<uint16_t>(state.last_refill_request);
  state.status.last_refill_count = static_cast<uint16_t>(state.last_refill_count);
  state.status.sampling_handoff_overflow_drops = state.handoff.overflow_drops;
}

void sync_sampling_snapshot(SamplingState& state) {
  portENTER_CRITICAL(&g_sampling_lock);
  sync_sampling_snapshot_locked(state);
  portEXIT_CRITICAL(&g_sampling_lock);
}

void clear_sensor_prefetch(SamplingState& state) {
  state.sensor_prefetch_head = 0;
  state.sensor_prefetch_tail = 0;
  state.sensor_prefetch_count = 0;
}

void note_fifo_truncated(SamplingState& state) {
  const uint32_t now_ms = millis();
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sensor_fifo_truncated++;
  record_sampling_error_locked(state, kSamplingErrorFifoTruncated, now_ms);
  sync_sampling_snapshot_locked(state);
  portEXIT_CRITICAL(&g_sampling_lock);
}

void note_sensor_reinit_attempt(SamplingState& state) {
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sensor_reinit_attempts++;
  sync_sampling_snapshot_locked(state);
  portEXIT_CRITICAL(&g_sampling_lock);
}

void note_sensor_reinit_success(SamplingState& state) {
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sensor_reinit_success++;
  sync_sampling_snapshot_locked(state);
  portEXIT_CRITICAL(&g_sampling_lock);
}

void note_sensor_bus_recovery_attempt(SamplingState& state) {
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sensor_bus_recovery_attempts++;
  sync_sampling_snapshot_locked(state);
  portEXIT_CRITICAL(&g_sampling_lock);
}

void note_sensor_bus_recovery_success(SamplingState& state) {
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sensor_bus_recovery_success++;
  sync_sampling_snapshot_locked(state);
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
  sync_sampling_snapshot_locked(state);
  portEXIT_CRITICAL(&g_sampling_lock);
}

void note_missed_samples(SamplingState& state, uint32_t missed_samples, bool abandoned_recovery) {
  if (missed_samples == 0) {
    return;
  }
  const uint32_t now_ms = millis();
  portENTER_CRITICAL(&g_sampling_lock);
  state.status.sampling_missed_samples += missed_samples;
  if (abandoned_recovery) {
    state.status.sampling_recovery_abandons++;
  }
  record_sampling_error_locked(state, kSamplingErrorMissedSample, now_ms);
  sync_sampling_snapshot_locked(state);
  portEXIT_CRITICAL(&g_sampling_lock);
}

bool publish_sample(SamplingState& state, const PendingSample& sample) {
  const uint32_t now_ms = millis();
  bool ok = false;
  portENTER_CRITICAL(&g_sampling_lock);
  ok = enqueue_pending_sample(state.handoff, sample);
  if (!ok) {
    record_sampling_error_locked(state, kSamplingErrorHandoffOverflow, now_ms);
  }
  sync_sampling_snapshot_locked(state);
  portEXIT_CRITICAL(&g_sampling_lock);
  return ok;
}

SensorFailureClass classify_sensor_failure(ADXL345::FailureKind failure_kind,
                                           size_t recovered_samples,
                                           bool fifo_truncated) {
  switch (failure_kind) {
    case ADXL345::FailureKind::kNone:
      return fifo_truncated ? SensorFailureClass::kPartialFifoDrain
                            : SensorFailureClass::kNone;
    case ADXL345::FailureKind::kFifoStatusRead:
      return SensorFailureClass::kRegisterAccess;
    case ADXL345::FailureKind::kFifoDataRead:
      return (recovered_samples > 0 || fifo_truncated)
                 ? SensorFailureClass::kPartialFifoDrain
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

size_t append_sensor_prefetch_samples(SamplingState& state,
                                      const int16_t* batch_xyz,
                                      size_t read_count) {
  size_t appended = 0;
  for (; appended < read_count && state.sensor_prefetch_count < kSensorPrefetchSamples; ++appended) {
    const size_t src = appended * kAxesPerSample;
    const size_t dst = state.sensor_prefetch_head * kAxesPerSample;
    state.sensor_prefetch_xyz[dst + 0] = batch_xyz[src + 0];
    state.sensor_prefetch_xyz[dst + 1] = batch_xyz[src + 1];
    state.sensor_prefetch_xyz[dst + 2] = batch_xyz[src + 2];
    state.sensor_prefetch_head = (state.sensor_prefetch_head + 1) % kSensorPrefetchSamples;
    state.sensor_prefetch_count++;
  }
  return appended;
}

SensorRefillAttempt refill_sensor_prefetch_once(SamplingState& state, size_t request_samples) {
  SensorRefillAttempt attempt{};
  if (request_samples == 0) {
    return attempt;
  }

  ADXL345::FailureKind failure_kind = ADXL345::FailureKind::kNone;
  bool fifo_truncated = false;
  const size_t read_count = state.adxl.read_samples(
      state.sensor_batch_xyz, request_samples, &failure_kind, &fifo_truncated);
  attempt.recovered_samples =
      append_sensor_prefetch_samples(state, state.sensor_batch_xyz, read_count);
  attempt.fifo_truncated = fifo_truncated;
  attempt.failure_kind = failure_kind;
  attempt.failure_class =
      classify_sensor_failure(failure_kind, attempt.recovered_samples, fifo_truncated);
  if (fifo_truncated) {
    note_fifo_truncated(state);
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
  state.sensor_ok = state.adxl.begin();
  if (state.sensor_ok) {
    state.sensor_consecutive_errors = 0;
    clear_sensor_prefetch(state);
    state.last_refill_request = 0;
    state.last_refill_count = 0;
    state.recent_refill_shortfall = false;
    note_sensor_reinit_success(state);
  }
  return state.sensor_ok;
}

bool ensure_sensor_ready(SamplingState& state) {
  return state.sensor_ok || maybe_reinit_sensor(state, true);
}

void maybe_refill_sensor_prefetch(SamplingState& state, size_t due_slots) {
  state.last_refill_request = 0;
  state.last_refill_count = 0;

  if (!ensure_sensor_ready(state)) {
    state.recent_refill_shortfall = true;
    sync_sampling_snapshot(state);
    return;
  }

  const vibesensor::reliability::SamplingRefillPlan plan =
      vibesensor::reliability::sampling_prefetch_refill_plan(
          state.sensor_prefetch_count,
          kSensorPrefetchSamples,
          kSensorPrefetchLowWaterSamples,
          kSensorPrefetchSteadyTargetSamples,
          kSensorPrefetchLateTargetSamples,
          due_slots,
          state.recent_refill_shortfall);
  if (plan.request_samples == 0) {
    sync_sampling_snapshot(state);
    return;
  }

  state.last_refill_request = plan.request_samples;
  size_t recovered_samples = 0;
  ADXL345::FailureKind final_failure_kind = ADXL345::FailureKind::kNone;
  SensorFailureClass final_failure_class = SensorFailureClass::kNone;
  uint8_t exhausted_failures = 0;

  while (recovered_samples < plan.request_samples) {
    const SensorRefillAttempt attempt =
        refill_sensor_prefetch_once(state, plan.request_samples - recovered_samples);
    recovered_samples += attempt.recovered_samples;
    final_failure_kind = attempt.failure_kind;
    final_failure_class = attempt.failure_class;

    if (attempt.failure_kind == ADXL345::FailureKind::kNone) {
      final_failure_class = SensorFailureClass::kNone;
      break;
    }

    const vibesensor::reliability::SamplingRefillRetryStep retry_step =
        vibesensor::reliability::sampling_refill_retry_step(
            exhausted_failures, final_failure_class, plan.request_samples, recovered_samples);
    if (!retry_step.retry_read) {
      break;
    }

    exhausted_failures++;
    if (retry_step.recover_bus) {
      ADXL345::FailureKind recovery_failure = ADXL345::FailureKind::kNone;
      if (!recover_sensor_bus(state, &recovery_failure)) {
        final_failure_kind = recovery_failure;
        final_failure_class =
            classify_sensor_failure(recovery_failure, recovered_samples, false);
        break;
      }
    }
  }

  state.last_refill_count = recovered_samples;
  state.recent_refill_shortfall = recovered_samples < plan.request_samples;

  if (final_failure_class != SensorFailureClass::kNone &&
      recovered_samples < plan.request_samples) {
    note_sensor_read_error(state, final_failure_kind);
    if (vibesensor::reliability::sensor_failure_requires_forced_reinit(final_failure_class)) {
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
  } else {
    state.sensor_consecutive_errors = 0;
  }

  sync_sampling_snapshot(state);
}

bool next_sensor_sample(SamplingState& state,
                        size_t due_slots,
                        int16_t* x,
                        int16_t* y,
                        int16_t* z) {
  maybe_refill_sensor_prefetch(state, due_slots);
  if (state.sensor_prefetch_count == 0) {
    return false;
  }

  const size_t offset = state.sensor_prefetch_tail * kAxesPerSample;
  *x = state.sensor_prefetch_xyz[offset + 0];
  *y = state.sensor_prefetch_xyz[offset + 1];
  *z = state.sensor_prefetch_xyz[offset + 2];
  state.sensor_prefetch_tail =
      (state.sensor_prefetch_tail + 1) % kSensorPrefetchSamples;
  state.sensor_prefetch_count--;
  sync_sampling_snapshot(state);
  return true;
}

bool sample_once(SamplingState& state, size_t due_slots, PendingSample* sample) {
  int16_t x = 0;
  int16_t y = 0;
  int16_t z = 0;

  if (!next_sensor_sample(state, due_slots, &x, &y, &z)) {
#if VIBESENSOR_ENABLE_SYNTH_FALLBACK
    synth_sample(&x, &y, &z);
#else
    return false;
#endif
  }

  sample->due_us = state.next_sample_due_us;
  sample->x = x;
  sample->y = y;
  sample->z = z;
  return true;
}

size_t current_handoff_headroom(SamplingState& state) {
  size_t free_slots = 0;
  portENTER_CRITICAL(&g_sampling_lock);
  free_slots = sample_handoff_free_slots(state.handoff);
  portEXIT_CRITICAL(&g_sampling_lock);
  return free_slots;
}

uint64_t advance_due_schedule(SamplingState& state, uint64_t slot_count = 1U) {
  return vibesensor::reliability::sampling_schedule_advance_us(state.due_schedule, slot_count);
}

void process_due_samples(SamplingState& state, uint32_t due_slots) {
  if (due_slots == 0) {
    return;
  }

  maybe_refill_sensor_prefetch(state, due_slots);
  const vibesensor::reliability::SamplingRecoveryPlan recovery =
      vibesensor::reliability::sampling_recovery_plan(due_slots,
                                                      current_handoff_headroom(state),
                                                      state.sensor_prefetch_count,
                                                      state.last_refill_request,
                                                      state.last_refill_count);

  size_t produced = 0;
  while (produced < recovery.attempt_slots) {
    PendingSample sample{};
    const size_t remaining_due = static_cast<size_t>(due_slots) - produced;
    if (!sample_once(state, remaining_due, &sample) || !publish_sample(state, sample)) {
      const uint32_t missed_samples = static_cast<uint32_t>(remaining_due);
      note_missed_samples(state, missed_samples, remaining_due > 1);
      state.next_sample_due_us += advance_due_schedule(state, missed_samples);
      return;
    }
    produced++;
    state.next_sample_due_us += advance_due_schedule(state);
  }

  if (recovery.missed_slots > 0) {
    note_missed_samples(
        state,
        static_cast<uint32_t>(recovery.missed_slots),
        vibesensor::reliability::sampling_recovery_abandoned(recovery.missed_slots));
    state.next_sample_due_us += advance_due_schedule(state, recovery.missed_slots);
  }
}

void sampling_timer_callback(void* arg) {
  auto& state = *static_cast<SamplingState*>(arg);
  if (g_sampling_task_handle != nullptr) {
    xTaskNotifyGive(g_sampling_task_handle);
  }
  if (g_sampling_timer_handle == nullptr) {
    return;
  }
  const uint64_t next_step_us =
      vibesensor::reliability::sampling_schedule_advance_us(state.timer_schedule);
  if (next_step_us == 0U) {
    return;
  }
  const esp_err_t rearm_err = esp_timer_start_once(g_sampling_timer_handle, next_step_us);
  if (rearm_err != ESP_OK) {
    Serial.printf("WARN: failed to rearm sampling timer (%d)\n", static_cast<int>(rearm_err));
  }
}

void sampling_task_main(void* arg) {
  auto& state = *static_cast<SamplingState*>(arg);
  while (true) {
    const uint32_t due_slots =
        static_cast<uint32_t>(ulTaskNotifyTake(pdTRUE, portMAX_DELAY));
    process_due_samples(state, due_slots);
  }
}

}  // namespace

SamplingState::SamplingState()
    : i2c(Wire), adxl(i2c, kAdxlI2cAddr, kI2cSdaPin, kI2cSclPin) {}

bool begin_sampling(SamplingState& state) {
  initialize_sample_handoff(state.handoff, state.handoff_storage, kSampleHandoffQueueSamples);
  sync_sampling_snapshot(state);

  state.sensor_ok = state.adxl.begin();
  if (!state.sensor_ok) {
    const uint32_t now_ms = millis();
    portENTER_CRITICAL(&g_sampling_lock);
    record_sampling_error_locked(state, kSamplingErrorSensorRead, now_ms);
    sync_sampling_snapshot_locked(state);
    portEXIT_CRITICAL(&g_sampling_lock);
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
    return false;
  }
  Serial.printf("task cores: loop=%d current=%d sampling=%d\n",
                kArduinoLoopTaskCore,
                static_cast<int>(xPortGetCoreID()),
                kSamplingTaskCore);

  state.due_schedule = vibesensor::reliability::make_sampling_interval_schedule(kSampleRateHz);
  state.timer_schedule = vibesensor::reliability::make_sampling_interval_schedule(kSampleRateHz);
  const uint64_t first_due_step_us =
      vibesensor::reliability::sampling_schedule_advance_us(state.due_schedule);
  const uint64_t first_timer_step_us =
      vibesensor::reliability::sampling_schedule_advance_us(state.timer_schedule);
  state.next_sample_due_us = esp_timer_get_time() + first_due_step_us;

  esp_timer_create_args_t timer_args = {};
  timer_args.callback = &sampling_timer_callback;
  timer_args.arg = &state;
  timer_args.dispatch_method = ESP_TIMER_TASK;
  timer_args.name = "vs_sampling";
  const esp_err_t timer_err = esp_timer_create(&timer_args, &g_sampling_timer_handle);
  if (timer_err != ESP_OK) {
    Serial.printf("WARN: failed to create sampling timer (%d)\n", static_cast<int>(timer_err));
    vTaskDelete(g_sampling_task_handle);
    g_sampling_task_handle = nullptr;
    g_sampling_timer_handle = nullptr;
    return false;
  }

  const esp_err_t start_err = esp_timer_start_once(g_sampling_timer_handle, first_timer_step_us);
  if (start_err != ESP_OK) {
    Serial.printf("WARN: failed to start sampling timer (%d)\n", static_cast<int>(start_err));
    esp_timer_delete(g_sampling_timer_handle);
    g_sampling_timer_handle = nullptr;
    vTaskDelete(g_sampling_task_handle);
    g_sampling_task_handle = nullptr;
    return false;
  }

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

    append_sample(
        queue_state, status, sample.x, sample.y, sample.z, sample.due_us, clock_offset_us);
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
