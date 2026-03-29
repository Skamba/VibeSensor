#include <unity.h>

#include "../../src/runtime_config.h"

namespace {

void test_preferred_sampling_task_core_uses_opposite_core_on_dual_core() {
  TEST_ASSERT_EQUAL_INT(1, vibesensor::runtime::preferred_sampling_task_core(0, 2));
  TEST_ASSERT_EQUAL_INT(0, vibesensor::runtime::preferred_sampling_task_core(1, 2));
}

void test_preferred_sampling_task_core_uses_fallback_when_loop_has_no_affinity() {
  TEST_ASSERT_EQUAL_INT(0, vibesensor::runtime::preferred_sampling_task_core(-1, 2));
  TEST_ASSERT_EQUAL_INT(1, vibesensor::runtime::preferred_sampling_task_core(-1, 2, 1));
}

void test_preferred_sampling_task_core_stays_valid_on_single_core() {
  TEST_ASSERT_EQUAL_INT(0, vibesensor::runtime::preferred_sampling_task_core(0, 1));
  TEST_ASSERT_EQUAL_INT(0, vibesensor::runtime::preferred_sampling_task_core(-1, 1));
}

void test_configured_sampling_task_core_is_explicit_and_in_range() {
  TEST_ASSERT_GREATER_OR_EQUAL_INT(0, vibesensor::runtime::kSamplingTaskCore);
  TEST_ASSERT_LESS_THAN_INT(vibesensor::runtime::kRuntimeCoreCount,
                            vibesensor::runtime::kSamplingTaskCore);
  TEST_ASSERT_GREATER_OR_EQUAL_INT(-1, vibesensor::runtime::kArduinoLoopTaskCore);
  TEST_ASSERT_LESS_THAN_INT(vibesensor::runtime::kRuntimeCoreCount,
                            vibesensor::runtime::kDefaultSamplingTaskCore);
}

}  // namespace

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_preferred_sampling_task_core_uses_opposite_core_on_dual_core);
  RUN_TEST(test_preferred_sampling_task_core_uses_fallback_when_loop_has_no_affinity);
  RUN_TEST(test_preferred_sampling_task_core_stays_valid_on_single_core);
  RUN_TEST(test_configured_sampling_task_core_is_explicit_and_in_range);
  return UNITY_END();
}
