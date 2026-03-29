#include "runtime_sample_handoff.h"

namespace vibesensor::runtime {

void initialize_sample_handoff(SampleHandoffState& state,
                               PendingSample* storage,
                               size_t capacity) {
  state.queue = storage;
  state.capacity = capacity;
  state.head = 0;
  state.tail = 0;
  state.size = 0;
  state.overflow_drops = 0;
  state.high_watermark = 0;
}

size_t sample_handoff_size(const SampleHandoffState& state) {
  return state.size;
}

size_t sample_handoff_capacity(const SampleHandoffState& state) {
  return state.capacity;
}

size_t sample_handoff_free_slots(const SampleHandoffState& state) {
  return state.capacity > state.size ? (state.capacity - state.size) : 0;
}

bool enqueue_pending_sample(SampleHandoffState& state, const PendingSample& sample) {
  if (state.queue == nullptr || state.capacity == 0) {
    state.overflow_drops++;
    return false;
  }
  if (state.size == state.capacity) {
    state.overflow_drops++;
    return false;
  }
  state.queue[state.head] = sample;
  state.head = (state.head + 1) % state.capacity;
  state.size++;
  if (state.size > state.high_watermark) {
    state.high_watermark = state.size;
  }
  return true;
}

bool dequeue_pending_sample(SampleHandoffState& state, PendingSample* sample) {
  if (sample == nullptr || state.size == 0 || state.queue == nullptr || state.capacity == 0) {
    return false;
  }
  *sample = state.queue[state.tail];
  state.tail = (state.tail + 1) % state.capacity;
  state.size--;
  return true;
}

}  // namespace vibesensor::runtime
