#pragma once

#include <Arduino.h>

namespace vibesensor::runtime {

struct PendingSample {
  uint64_t due_us = 0;
  int16_t x = 0;
  int16_t y = 0;
  int16_t z = 0;
};

struct SampleHandoffState {
  PendingSample* queue = nullptr;
  size_t capacity = 0;
  size_t head = 0;
  size_t tail = 0;
  size_t size = 0;
  uint32_t overflow_drops = 0;
  size_t high_watermark = 0;
};

void initialize_sample_handoff(SampleHandoffState& state,
                               PendingSample* storage,
                               size_t capacity);
size_t sample_handoff_size(const SampleHandoffState& state);
size_t sample_handoff_capacity(const SampleHandoffState& state);
size_t sample_handoff_free_slots(const SampleHandoffState& state);
bool enqueue_pending_sample(SampleHandoffState& state, const PendingSample& sample);
bool dequeue_pending_sample(SampleHandoffState& state, PendingSample* sample);

}  // namespace vibesensor::runtime
