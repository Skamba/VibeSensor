#include <unity.h>

#include "../../src/runtime_sample_handoff.cpp"

namespace {

using vibesensor::runtime::PendingSample;
using vibesensor::runtime::SampleHandoffState;

SampleHandoffState make_state(PendingSample* storage, size_t capacity) {
  SampleHandoffState state{};
  vibesensor::runtime::initialize_sample_handoff(state, storage, capacity);
  return state;
}

PendingSample make_sample(uint64_t due_us, int16_t base) {
  PendingSample sample{};
  sample.due_us = due_us;
  sample.x = base;
  sample.y = static_cast<int16_t>(base + 1);
  sample.z = static_cast<int16_t>(base + 2);
  return sample;
}

void test_sample_handoff_preserves_fifo_order_across_wrap() {
  PendingSample storage[3] = {};
  SampleHandoffState state = make_state(storage, 3);

  TEST_ASSERT_TRUE(vibesensor::runtime::enqueue_pending_sample(state, make_sample(10, 1)));
  TEST_ASSERT_TRUE(vibesensor::runtime::enqueue_pending_sample(state, make_sample(20, 10)));

  PendingSample drained{};
  TEST_ASSERT_TRUE(vibesensor::runtime::dequeue_pending_sample(state, &drained));
  TEST_ASSERT_EQUAL_UINT64(10, drained.due_us);
  TEST_ASSERT_EQUAL_INT16(1, drained.x);

  TEST_ASSERT_TRUE(vibesensor::runtime::enqueue_pending_sample(state, make_sample(30, 20)));
  TEST_ASSERT_TRUE(vibesensor::runtime::enqueue_pending_sample(state, make_sample(40, 30)));

  TEST_ASSERT_TRUE(vibesensor::runtime::dequeue_pending_sample(state, &drained));
  TEST_ASSERT_EQUAL_UINT64(20, drained.due_us);
  TEST_ASSERT_TRUE(vibesensor::runtime::dequeue_pending_sample(state, &drained));
  TEST_ASSERT_EQUAL_UINT64(30, drained.due_us);
  TEST_ASSERT_TRUE(vibesensor::runtime::dequeue_pending_sample(state, &drained));
  TEST_ASSERT_EQUAL_UINT64(40, drained.due_us);
  TEST_ASSERT_FALSE(vibesensor::runtime::dequeue_pending_sample(state, &drained));
}

void test_sample_handoff_rejects_new_samples_when_full() {
  PendingSample storage[2] = {};
  SampleHandoffState state = make_state(storage, 2);

  TEST_ASSERT_TRUE(vibesensor::runtime::enqueue_pending_sample(state, make_sample(10, 1)));
  TEST_ASSERT_TRUE(vibesensor::runtime::enqueue_pending_sample(state, make_sample(20, 10)));
  TEST_ASSERT_FALSE(vibesensor::runtime::enqueue_pending_sample(state, make_sample(30, 20)));

  TEST_ASSERT_EQUAL_UINT32(1, state.overflow_drops);
  TEST_ASSERT_EQUAL_UINT64(2, vibesensor::runtime::sample_handoff_size(state));
  TEST_ASSERT_EQUAL_UINT64(2, state.high_watermark);
}

}  // namespace

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_sample_handoff_preserves_fifo_order_across_wrap);
  RUN_TEST(test_sample_handoff_rejects_new_samples_when_full);
  return UNITY_END();
}
