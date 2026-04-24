#include <unity.h>

#include "../../src/runtime_queue.cpp"
#include "../../src/runtime_sample_handoff.cpp"
#include "../../src/runtime_sampling.cpp"

ADXL345::ADXL345(TwoWire& wire, uint8_t i2c_addr, int sda_pin, int scl_pin, uint8_t fifo_watermark)
    : wire_(wire),
      i2c_addr_(i2c_addr),
      sda_pin_(sda_pin),
      scl_pin_(scl_pin),
      fifo_watermark_(fifo_watermark),
      available_(false) {}

bool ADXL345::begin(FailureKind* failure_kind) {
  available_ = true;
  if (failure_kind != nullptr) {
    *failure_kind = FailureKind::kNone;
  }
  return true;
}

bool ADXL345::recover_bus(FailureKind* failure_kind) {
  if (failure_kind != nullptr) {
    *failure_kind = FailureKind::kNone;
  }
  return true;
}

bool ADXL345::available() const { return available_; }

size_t ADXL345::read_samples(
    int16_t*, size_t, FailureKind* failure_kind, bool* fifo_truncated) {
  if (failure_kind != nullptr) {
    *failure_kind = FailureKind::kNone;
  }
  if (fifo_truncated != nullptr) {
    *fifo_truncated = false;
  }
  return 0;
}

bool ADXL345::read_reg(uint8_t, uint8_t*) { return false; }

bool ADXL345::write_reg(uint8_t, uint8_t) { return false; }

bool ADXL345::read_multi(uint8_t, uint8_t*, size_t) { return false; }

namespace {

using vibesensor::runtime::DataFrame;
using vibesensor::runtime::FrameQueueState;
using vibesensor::runtime::PendingSample;
using vibesensor::runtime::RuntimeStatus;
using vibesensor::runtime::SamplingState;

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

void enqueue_sample(SamplingState& state, uint64_t due_us, int16_t base) {
  PendingSample sample{};
  sample.due_us = due_us;
  sample.x = base;
  sample.y = static_cast<int16_t>(base + 1);
  sample.z = static_cast<int16_t>(base + 2);
  TEST_ASSERT_TRUE(vibesensor::runtime::enqueue_pending_sample(state.handoff, sample));
}

}  // namespace

void setUp() { arduino_test::reset_time(); }

void test_service_sample_handoff_builds_frame_and_updates_snapshot() {
  SamplingState sampling_state;
  vibesensor::runtime::initialize_sample_handoff(
      sampling_state.handoff, sampling_state.handoff_storage, vibesensor::runtime::kSampleHandoffQueueSamples);
  DataFrame frames[2] = {};
  FrameQueueState queue_state = make_queue_state(frames, 2);
  RuntimeStatus status{};

  for (uint16_t i = 0; i < vibesensor::runtime::kFrameSamples; ++i) {
    enqueue_sample(sampling_state, 1000 + i, static_cast<int16_t>(10 + i));
  }

  vibesensor::runtime::service_sample_handoff(sampling_state, queue_state, status, 25);

  const DataFrame* frame = vibesensor::runtime::peek_frame(queue_state);
  TEST_ASSERT_NOT_NULL(frame);
  TEST_ASSERT_EQUAL_UINT64(1025, frame->t0_us);
  TEST_ASSERT_EQUAL_UINT16(vibesensor::runtime::kFrameSamples, frame->sample_count);
  expect_xyz_sample(*frame, 0, 10, 11, 12);
  const int16_t last_sample =
      static_cast<int16_t>(10 + vibesensor::runtime::kFrameSamples - 1);
  expect_xyz_sample(*frame,
                    vibesensor::runtime::kFrameSamples - 1,
                    last_sample,
                    static_cast<int16_t>(last_sample + 1),
                    static_cast<int16_t>(last_sample + 2));

  const vibesensor::runtime::SamplingStatusSnapshot snapshot =
      vibesensor::runtime::snapshot_sampling_status(sampling_state);
  TEST_ASSERT_EQUAL_UINT16(0, snapshot.sample_handoff_size);
  TEST_ASSERT_EQUAL_UINT16(
      vibesensor::runtime::kSampleHandoffQueueSamples, snapshot.sample_handoff_capacity);
}

void test_service_sample_handoff_drops_oldest_frame_when_queue_saturates() {
  SamplingState sampling_state;
  vibesensor::runtime::initialize_sample_handoff(
      sampling_state.handoff, sampling_state.handoff_storage, vibesensor::runtime::kSampleHandoffQueueSamples);
  DataFrame frames[1] = {};
  FrameQueueState queue_state = make_queue_state(frames, 1);
  RuntimeStatus status{};

  for (uint16_t i = 0; i < vibesensor::runtime::kFrameSamples; ++i) {
    enqueue_sample(sampling_state, 1000 + i, static_cast<int16_t>(100 + i));
  }
  for (uint16_t i = 0; i < vibesensor::runtime::kFrameSamples; ++i) {
    enqueue_sample(sampling_state, 2000 + i, static_cast<int16_t>(500 + i));
  }

  vibesensor::runtime::service_sample_handoff(sampling_state, queue_state, status, 0);

  const DataFrame* frame = vibesensor::runtime::peek_frame(queue_state);
  TEST_ASSERT_NOT_NULL(frame);
  TEST_ASSERT_EQUAL_UINT32(1, status.queue_overflow_drops);
  TEST_ASSERT_EQUAL_UINT32(1, frame->seq);
  TEST_ASSERT_EQUAL_UINT64(2000, frame->t0_us);
  expect_xyz_sample(*frame, 0, 500, 501, 502);

  const vibesensor::runtime::SamplingStatusSnapshot snapshot =
      vibesensor::runtime::snapshot_sampling_status(sampling_state);
  TEST_ASSERT_EQUAL_UINT16(0, snapshot.sample_handoff_size);
}

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_service_sample_handoff_builds_frame_and_updates_snapshot);
  RUN_TEST(test_service_sample_handoff_drops_oldest_frame_when_queue_saturates);
  return UNITY_END();
}
