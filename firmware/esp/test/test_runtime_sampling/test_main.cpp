#include <unity.h>

#include "../../src/runtime_queue.cpp"
#include "../../src/runtime_sample_handoff.cpp"
#include "../../src/runtime_sampling.cpp"

namespace fake_adxl {
size_t fifo_entries = 0;
}  // namespace fake_adxl

ADXL345::ADXL345(TwoWire& wire, uint8_t i2c_addr, int sda_pin, int scl_pin, uint8_t rate_code)
    : wire_(wire),
      i2c_addr_(i2c_addr),
      sda_pin_(sda_pin),
      scl_pin_(scl_pin),
      rate_code_(rate_code),
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

bool ADXL345::read_fifo_entries(size_t* entries, FailureKind* failure_kind) {
  if (failure_kind != nullptr) {
    *failure_kind = FailureKind::kNone;
  }
  *entries = fake_adxl::fifo_entries;
  return true;
}

size_t ADXL345::read_fifo_samples(int16_t* xyz, size_t count, FailureKind* failure_kind) {
  if (failure_kind != nullptr) {
    *failure_kind = FailureKind::kNone;
  }
  // A sensor at rest: constant acceleration on every axis.
  for (size_t i = 0; i < count; ++i) {
    xyz[i * 3 + 0] = 100;
    xyz[i * 3 + 1] = -200;
    xyz[i * 3 + 2] = 256;
  }
  fake_adxl::fifo_entries -= count;
  return count;
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
  sample.sample_us = due_us;
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

void prepare_polling(SamplingState& state) {
  vibesensor::runtime::initialize_sample_handoff(
      state.handoff, state.handoff_storage, vibesensor::runtime::kSampleHandoffQueueSamples);
  state.sample_clock = vibesensor::sample_timing::make_sample_clock(800);
  vibesensor::sample_timing::resampler_init(state.resampler, 800);
  state.sensor_ok = true;
  fake_adxl::fifo_entries = 0;
}

void poll_at(SamplingState& state, uint64_t esp_time_us, size_t fifo_entries) {
  arduino_test::set_esp_time(esp_time_us);
  fake_adxl::fifo_entries = fifo_entries;
  vibesensor::runtime::poll_sensor_fifo(state);
}

// The first poll finds 8 samples at t=100000: the oldest was taken 7.5
// periods earlier. The resampler interpolates over 32 inputs (15 before, 16
// after the output time): its first output is at the 16th input's time and
// it trails the input by 31 samples.
constexpr uint64_t kFirstInputUs = 100000 - 625 - (7 * 1250);
constexpr uint64_t kFirstOutputUs = kFirstInputUs + (15 * 1250);

void test_poll_drains_fifo_and_publishes_samples_on_the_real_time_grid() {
  SamplingState sampling_state;
  prepare_polling(sampling_state);
  DataFrame frames[2] = {};
  FrameQueueState queue_state = make_queue_state(frames, 2);
  RuntimeStatus status{};

  for (uint64_t k = 0; k < 20; ++k) {
    poll_at(sampling_state, 100000 + (k * 10000), 8);
    TEST_ASSERT_EQUAL_UINT32(0, fake_adxl::fifo_entries);
  }
  vibesensor::runtime::service_sample_handoff(sampling_state, queue_state, status, 1000000);

  const DataFrame* frame = vibesensor::runtime::peek_frame(queue_state);
  TEST_ASSERT_NOT_NULL(frame);
  TEST_ASSERT_EQUAL_UINT64(1000000 + kFirstOutputUs, frame->t0_us);
  TEST_ASSERT_EQUAL_UINT16(vibesensor::runtime::kFrameSamples, frame->sample_count);
  expect_xyz_sample(*frame, 0, 100, -200, 256);
  expect_xyz_sample(*frame, 79, 100, -200, 256);
  TEST_ASSERT_EQUAL_UINT64(kFirstOutputUs + (80 * 1250), queue_state.build_t0_us);
  const vibesensor::runtime::SamplingStatusSnapshot snapshot =
      vibesensor::runtime::snapshot_sampling_status(sampling_state);
  TEST_ASSERT_EQUAL_UINT32(160, snapshot.sensor_samples_total);
  TEST_ASSERT_EQUAL_UINT32(160 - 31, snapshot.samples_total);
  TEST_ASSERT_EQUAL_UINT32(0, snapshot.sensor_fifo_overflows);
  TEST_ASSERT_EQUAL_UINT32(0, snapshot.sampling_lost_samples);
  TEST_ASSERT_EQUAL_INT32(0, snapshot.sample_clock_error_us);
}

void test_fifo_overflow_counts_lost_samples_and_starts_a_new_frame() {
  SamplingState sampling_state;
  prepare_polling(sampling_state);
  DataFrame frames[2] = {};
  FrameQueueState queue_state = make_queue_state(frames, 2);
  RuntimeStatus status{};

  for (uint64_t k = 0; k < 4; ++k) {
    poll_at(sampling_state, 100000 + (k * 10000), 8);
  }
  // The task stalls for 90 ms: the FIFO is full and 39 samples were overwritten.
  poll_at(sampling_state, 220000, 33);
  vibesensor::runtime::service_sample_handoff(sampling_state, queue_state, status, 0);

  const vibesensor::runtime::SamplingStatusSnapshot snapshot =
      vibesensor::runtime::snapshot_sampling_status(sampling_state);
  TEST_ASSERT_EQUAL_UINT32(1, snapshot.sensor_fifo_overflows);
  TEST_ASSERT_EQUAL_UINT32(39, snapshot.sampling_lost_samples);
  TEST_ASSERT_EQUAL_UINT32(1, snapshot.sampling_clock_resyncs);
  // The samples before the gap go out as a short frame; the frame after the
  // gap starts on the same grid, at the first point the new input covers.
  const DataFrame* frame = vibesensor::runtime::peek_frame(queue_state);
  TEST_ASSERT_NOT_NULL(frame);
  TEST_ASSERT_EQUAL_UINT16(32 - 31, frame->sample_count);
  TEST_ASSERT_EQUAL_UINT64(kFirstOutputUs, frame->t0_us);
  TEST_ASSERT_EQUAL_UINT16(33 - 31, queue_state.build_count);
  TEST_ASSERT_EQUAL_UINT64(220000 - 625 - (32 * 1250) + (15 * 1250), queue_state.build_t0_us);
}

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_service_sample_handoff_builds_frame_and_updates_snapshot);
  RUN_TEST(test_service_sample_handoff_drops_oldest_frame_when_queue_saturates);
  RUN_TEST(test_poll_drains_fifo_and_publishes_samples_on_the_real_time_grid);
  RUN_TEST(test_fifo_overflow_counts_lost_samples_and_starts_a_new_frame);
  return UNITY_END();
}
