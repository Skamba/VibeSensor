#pragma once

#include <Arduino.h>

#include "runtime_config.h"
#include "runtime_status.h"

namespace vibesensor::runtime {

struct DataFrame {
  uint32_t seq = 0;
  uint64_t t0_us = 0;
  uint16_t sample_count = 0;
  int16_t xyz[static_cast<size_t>(kFrameSamples) * kAxesPerSample] = {};
  bool transmitted = false;
  uint8_t tx_attempts = 0;
  uint32_t queued_ms = 0;
  uint32_t first_tx_ms = 0;
  uint32_t last_tx_ms = 0;
};

struct FrameQueueState {
  DataFrame* queue = nullptr;
  size_t capacity = 0;
  size_t head = 0;
  size_t tail = 0;
  size_t size = 0;
  int16_t build_xyz[static_cast<size_t>(kFrameSamples) * kAxesPerSample] = {};
  uint16_t build_count = 0;
  uint64_t build_t0_us = 0;
  uint32_t next_seq = 0;
};

bool allocate_frame_queue(FrameQueueState& state);
size_t frame_queue_size(const FrameQueueState& state);
size_t frame_queue_capacity(const FrameQueueState& state);
size_t frame_queue_bytes(const FrameQueueState& state);
void append_sample(FrameQueueState& state,
                   RuntimeStatus& status,
                   int16_t x,
                   int16_t y,
                   int16_t z,
                   uint64_t sample_due_us,
                   int64_t clock_offset_us);
DataFrame* peek_frame(FrameQueueState& state);
void drop_front_frame(FrameQueueState& state);
void ack_data_frames(FrameQueueState& state, uint32_t last_seq_received);

}  // namespace vibesensor::runtime
