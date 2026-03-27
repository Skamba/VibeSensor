#include <unity.h>

#include "../../src/runtime_queue.cpp"

namespace {

using vibesensor::runtime::DataFrame;
using vibesensor::runtime::FrameQueueState;
using vibesensor::runtime::RuntimeStatus;

FrameQueueState make_queue_state(DataFrame* frames, size_t capacity) {
  FrameQueueState state{};
  state.queue = frames;
  state.capacity = capacity;
  return state;
}

void expect_xyz_sample(const DataFrame& frame,
                       uint16_t sample_index,
                       int16_t expected_x,
                       int16_t expected_y,
                       int16_t expected_z) {
  const size_t offset = static_cast<size_t>(sample_index) * vibesensor::runtime::kAxesPerSample;
  TEST_ASSERT_EQUAL_INT16(expected_x, frame.xyz[offset + 0]);
  TEST_ASSERT_EQUAL_INT16(expected_y, frame.xyz[offset + 1]);
  TEST_ASSERT_EQUAL_INT16(expected_z, frame.xyz[offset + 2]);
}

void append_full_frame(FrameQueueState& state,
                       RuntimeStatus& status,
                       int16_t sample_base,
                       uint64_t first_due_us,
                       int64_t clock_offset_us) {
  for (uint16_t i = 0; i < vibesensor::runtime::kFrameSamples; ++i) {
    const int16_t value = static_cast<int16_t>(sample_base + static_cast<int16_t>(i));
    vibesensor::runtime::append_sample(state,
                                       status,
                                       value,
                                       static_cast<int16_t>(value + 1),
                                       static_cast<int16_t>(value + 2),
                                       first_due_us + i,
                                       clock_offset_us);
  }
}

}  // namespace

void test_append_sample_builds_frame_and_applies_clock_offset() {
  DataFrame frames[2] = {};
  RuntimeStatus status{};
  FrameQueueState state = make_queue_state(frames, 2);

  append_full_frame(state, status, 10, 1000, 50);

  const DataFrame* frame = vibesensor::runtime::peek_frame(state);
  TEST_ASSERT_NOT_NULL(frame);
  TEST_ASSERT_EQUAL_UINT32(0, frame->seq);
  TEST_ASSERT_EQUAL_UINT64(1050, frame->t0_us);
  TEST_ASSERT_EQUAL_UINT16(vibesensor::runtime::kFrameSamples, frame->sample_count);
  expect_xyz_sample(*frame, 0, 10, 11, 12);
  const int16_t last_sample = static_cast<int16_t>(10 + vibesensor::runtime::kFrameSamples - 1);
  expect_xyz_sample(*frame,
                    vibesensor::runtime::kFrameSamples - 1,
                    last_sample,
                    static_cast<int16_t>(last_sample + 1),
                    static_cast<int16_t>(last_sample + 2));
  TEST_ASSERT_EQUAL_UINT32(0, status.queue_overflow_drops);
}

void test_queue_overflow_drops_oldest_frame() {
  DataFrame frames[1] = {};
  RuntimeStatus status{};
  FrameQueueState state = make_queue_state(frames, 1);

  append_full_frame(state, status, 10, 1000, 0);
  append_full_frame(state, status, 500, 2000, 0);

  const DataFrame* frame = vibesensor::runtime::peek_frame(state);
  TEST_ASSERT_NOT_NULL(frame);
  TEST_ASSERT_EQUAL_UINT32(1, status.queue_overflow_drops);
  TEST_ASSERT_EQUAL_UINT32(1, frame->seq);
  TEST_ASSERT_EQUAL_UINT64(2000, frame->t0_us);
  expect_xyz_sample(*frame, 0, 500, 501, 502);
}

void test_ack_data_frames_handles_wraparound_after_partial_drain() {
  DataFrame frames[2] = {};
  RuntimeStatus status{};
  FrameQueueState state = make_queue_state(frames, 2);

  append_full_frame(state, status, 0, 1000, 0);
  append_full_frame(state, status, 1000, 2000, 0);
  vibesensor::runtime::ack_data_frames(state, 0);
  append_full_frame(state, status, 2000, 3000, 0);

  TEST_ASSERT_EQUAL_UINT32(2, state.size);
  const DataFrame* frame = vibesensor::runtime::peek_frame(state);
  TEST_ASSERT_NOT_NULL(frame);
  TEST_ASSERT_EQUAL_UINT32(1, frame->seq);
  vibesensor::runtime::ack_data_frames(state, 2);
  TEST_ASSERT_EQUAL_UINT32(0, state.size);
  TEST_ASSERT_NULL(vibesensor::runtime::peek_frame(state));
}

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_append_sample_builds_frame_and_applies_clock_offset);
  RUN_TEST(test_queue_overflow_drops_oldest_frame);
  RUN_TEST(test_ack_data_frames_handles_wraparound_after_partial_drain);
  return UNITY_END();
}
