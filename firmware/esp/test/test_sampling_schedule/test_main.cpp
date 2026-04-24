#include <unity.h>

#include "reliability.h"

namespace {

void test_divisor_rate_schedule_stays_exact() {
  auto schedule = vibesensor::reliability::make_sampling_interval_schedule(800);
  uint64_t total_elapsed_us = 0;

  for (size_t i = 0; i < 800; ++i) {
    const uint64_t step_us = vibesensor::reliability::sampling_schedule_advance_us(schedule);
    TEST_ASSERT_EQUAL_UINT64(1250, step_us);
    total_elapsed_us += step_us;
  }

  TEST_ASSERT_EQUAL_UINT64(1000000ULL, total_elapsed_us);
}

void test_non_divisor_rate_schedule_distributes_fractional_remainder_without_drift() {
  auto schedule = vibesensor::reliability::make_sampling_interval_schedule(3200);
  uint64_t total_elapsed_us = 0;

  TEST_ASSERT_EQUAL_UINT64(312, vibesensor::reliability::sampling_schedule_advance_us(schedule));
  TEST_ASSERT_EQUAL_UINT64(313, vibesensor::reliability::sampling_schedule_advance_us(schedule));
  TEST_ASSERT_EQUAL_UINT64(312, vibesensor::reliability::sampling_schedule_advance_us(schedule));
  TEST_ASSERT_EQUAL_UINT64(313, vibesensor::reliability::sampling_schedule_advance_us(schedule));

  total_elapsed_us += 1250;
  for (size_t i = 4; i < 3200; ++i) {
    total_elapsed_us += vibesensor::reliability::sampling_schedule_advance_us(schedule);
  }

  TEST_ASSERT_EQUAL_UINT64(1000000ULL, total_elapsed_us);
}

void test_non_divisor_rate_due_slots_follow_fractional_schedule() {
  auto schedule = vibesensor::reliability::make_sampling_interval_schedule(3200);
  const uint64_t next_due_us = vibesensor::reliability::sampling_schedule_advance_us(schedule);

  TEST_ASSERT_EQUAL_UINT64(0, vibesensor::reliability::sampling_slots_due(311, next_due_us, schedule));
  TEST_ASSERT_EQUAL_UINT64(1, vibesensor::reliability::sampling_slots_due(624, next_due_us, schedule));
  TEST_ASSERT_EQUAL_UINT64(2, vibesensor::reliability::sampling_slots_due(625, next_due_us, schedule));
  TEST_ASSERT_EQUAL_UINT64(4, vibesensor::reliability::sampling_slots_due(1250, next_due_us, schedule));
}

}  // namespace

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_divisor_rate_schedule_stays_exact);
  RUN_TEST(test_non_divisor_rate_schedule_distributes_fractional_remainder_without_drift);
  RUN_TEST(test_non_divisor_rate_due_slots_follow_fractional_schedule);
  return UNITY_END();
}
