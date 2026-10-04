#pragma once

#include <Arduino.h>
#include <Wire.h>

#include "adxl345.h"
#include "reliability.h"
#include "sample_timing.h"
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
  int16_t sensor_batch_xyz[ADXL345::kMaxFifoEntries * kAxesPerSample] = {};
  uint8_t sensor_consecutive_errors = 0;
  uint32_t last_sensor_reinit_ms = 0;
  vibesensor::sample_timing::SampleClock sample_clock = {};
  vibesensor::sample_timing::Resampler resampler = {};
  uint32_t poll_rng_state = 1;
  // The next published sample follows missing samples (lost or dropped).
  bool pending_gap = false;
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
