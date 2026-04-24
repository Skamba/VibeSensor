#include "runtime_queue.h"

#include <esp_heap_caps.h>
#include <string.h>

#include "runtime_config.h"

namespace vibesensor::runtime {
namespace {

bool seq_less_or_equal(uint32_t lhs, uint32_t rhs) {
  return static_cast<int32_t>(lhs - rhs) <= 0;
}

void enqueue_frame(FrameQueueState& state,
                   RuntimeStatus& status,
                   int64_t clock_offset_us) {
  if (state.build_count == 0) {
    return;
  }
  if (state.queue == nullptr || state.capacity == 0) {
    status.queue_overflow_drops++;
    state.build_count = 0;
    return;
  }

  if (state.size == state.capacity) {
    status.queue_overflow_drops++;
    state.tail = (state.tail + 1) % state.capacity;
    state.size--;
  }

  DataFrame& frame = state.queue[state.head];
  frame.seq = state.next_seq++;
  frame.t0_us = static_cast<uint64_t>(static_cast<int64_t>(state.build_t0_us) + clock_offset_us);
  frame.sample_count = state.build_count;
  frame.transmitted = false;
  frame.tx_attempts = 0;
  frame.queued_ms = millis();
  frame.first_tx_ms = 0;
  frame.last_tx_ms = 0;
  memcpy(frame.xyz,
         state.build_xyz,
         static_cast<size_t>(state.build_count) * kAxesPerSample * sizeof(int16_t));

  state.head = (state.head + 1) % state.capacity;
  state.size++;
  state.build_count = 0;
}

}  // namespace

bool allocate_frame_queue(FrameQueueState& state) {
  for (size_t cap = kFrameQueueLenTarget; cap >= kFrameQueueLenMin; --cap) {
    auto* mem = static_cast<DataFrame*>(
        heap_caps_malloc(cap * sizeof(DataFrame), MALLOC_CAP_8BIT));
    if (mem != nullptr) {
      state.queue = mem;
      state.capacity = cap;
      return true;
    }
    if (cap == kFrameQueueLenMin) {
      break;
    }
  }
  return false;
}

size_t frame_queue_size(const FrameQueueState& state) {
  return state.size;
}

size_t frame_queue_capacity(const FrameQueueState& state) {
  return state.capacity;
}

size_t frame_queue_bytes(const FrameQueueState& state) {
  return state.capacity * sizeof(DataFrame);
}

void append_sample(FrameQueueState& state,
                   RuntimeStatus& status,
                   int16_t x,
                   int16_t y,
                   int16_t z,
                   uint64_t sample_due_us,
                   int64_t clock_offset_us) {
  if (state.build_count == 0) {
    state.build_t0_us = sample_due_us;
  }

  const size_t idx = static_cast<size_t>(state.build_count) * kAxesPerSample;
  state.build_xyz[idx + 0] = x;
  state.build_xyz[idx + 1] = y;
  state.build_xyz[idx + 2] = z;
  state.build_count++;

  if (state.build_count >= kFrameSamples) {
    enqueue_frame(state, status, clock_offset_us);
  }
}

DataFrame* peek_frame(FrameQueueState& state) {
  if (state.size == 0) {
    return nullptr;
  }
  return &state.queue[state.tail];
}

void drop_front_frame(FrameQueueState& state) {
  if (state.size == 0) {
    return;
  }
  state.tail = (state.tail + 1) % state.capacity;
  state.size--;
}

void ack_data_frames(FrameQueueState& state, uint32_t last_seq_received) {
  while (state.size > 0) {
    const DataFrame& front = state.queue[state.tail];
    if (!seq_less_or_equal(front.seq, last_seq_received)) {
      break;
    }
    drop_front_frame(state);
  }
}

}  // namespace vibesensor::runtime
