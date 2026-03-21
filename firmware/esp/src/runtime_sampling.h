#pragma once

#include <Arduino.h>
#include <Wire.h>

#include "adxl345.h"
#include "runtime_config.h"
#include "runtime_queue.h"
#include "runtime_status.h"

namespace vibesensor::runtime {

struct SamplingState {
  SamplingState();

  TwoWire& i2c;
  ADXL345 adxl;
  bool sensor_ok = false;
  int16_t sensor_batch_xyz[kSensorReadBatchSamples * 3] = {};
  int16_t sensor_prefetch_xyz[kSensorPrefetchSamples * 3] = {};
  size_t sensor_prefetch_head = 0;
  size_t sensor_prefetch_tail = 0;
  size_t sensor_prefetch_count = 0;
  uint8_t sensor_consecutive_errors = 0;
  uint32_t last_sensor_reinit_ms = 0;
  uint64_t next_sample_due_us = 0;
  bool has_last_real_sample = false;
  int16_t last_real_x = 0;
  int16_t last_real_y = 0;
  int16_t last_real_z = 0;
};

bool begin_sensor(SamplingState& state);
void reset_sampling_schedule(SamplingState& state, uint64_t now_us);
void service_sampling(SamplingState& state,
                      FrameQueueState& queue_state,
                      RuntimeStatus& status,
                      int64_t clock_offset_us);

}  // namespace vibesensor::runtime
