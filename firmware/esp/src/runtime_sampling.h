#pragma once

#include <Arduino.h>
#include <Wire.h>

#include "adxl345.h"
#include "reliability.h"
#include "runtime_config.h"
#include "runtime_queue.h"
#include "runtime_sample_handoff.h"
#include "runtime_status.h"

namespace vibesensor::runtime {

struct SamplingState {
  SamplingState();

  TwoWire& i2c;
  ADXL345 adxl;
  bool sensor_ok = false;
  int16_t sensor_batch_xyz[kSensorPrefetchSamples * kAxesPerSample] = {};
  int16_t sensor_prefetch_xyz[kSensorPrefetchSamples * kAxesPerSample] = {};
  size_t sensor_prefetch_head = 0;
  size_t sensor_prefetch_tail = 0;
  size_t sensor_prefetch_count = 0;
  uint8_t sensor_consecutive_errors = 0;
  uint32_t last_sensor_reinit_ms = 0;
  uint64_t next_sample_due_us = 0;
  vibesensor::reliability::SamplingIntervalSchedule due_schedule = {};
  vibesensor::reliability::SamplingIntervalSchedule timer_schedule = {};
  size_t last_refill_request = 0;
  size_t last_refill_count = 0;
  bool recent_refill_shortfall = false;
  PendingSample handoff_storage[kSampleHandoffQueueSamples] = {};
  SampleHandoffState handoff;
  SamplingStatusSnapshot status = {};
};

bool begin_sampling(SamplingState& state);
void service_sample_handoff(SamplingState& state,
                            FrameQueueState& queue_state,
                            RuntimeStatus& status,
                            int64_t clock_offset_us);
SamplingStatusSnapshot snapshot_sampling_status(SamplingState& state);

}  // namespace vibesensor::runtime
