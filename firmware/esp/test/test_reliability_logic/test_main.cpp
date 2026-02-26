#include <unity.h>

#include "reliability.h"

namespace {
constexpr size_t kDataHeaderBytes = 18;
}

void test_frame_samples_are_clamped_to_datagram_limit() {
  const uint16_t clamped =
      vibesensor::reliability::clamp_frame_samples(500, 1500, kDataHeaderBytes);
  TEST_ASSERT_EQUAL_UINT16(247, clamped);
}

void test_frame_samples_zero_uses_safe_minimum() {
  const uint16_t clamped =
      vibesensor::reliability::clamp_frame_samples(0, 1500, kDataHeaderBytes);
  TEST_ASSERT_EQUAL_UINT16(1, clamped);
}

void test_frame_samples_clamped_for_mtu_safe_payload() {
  // MTU-safe default: 1472 bytes payload (1500 MTU − 20 IP − 8 UDP).
  // Real protocol header is 22 bytes; (1472 − 22) / 6 = 241 max samples.
  const uint16_t clamped =
      vibesensor::reliability::clamp_frame_samples(500, 1472, 22);
  TEST_ASSERT_EQUAL_UINT16(241, clamped);
}

void test_retry_backoff_grows_and_caps_with_jitter() {
  const uint32_t base = 4000;
  const uint32_t cap = 60000;
  const uint32_t d1 = vibesensor::reliability::compute_retry_delay_ms(base, cap, 1, 1);
  const uint32_t d5 = vibesensor::reliability::compute_retry_delay_ms(base, cap, 5, 2);
  const uint32_t d20 = vibesensor::reliability::compute_retry_delay_ms(base, cap, 20, 3);
  TEST_ASSERT_TRUE(d1 >= 7000 && d1 <= 8999);
  TEST_ASSERT_TRUE(d5 >= 52500 && d5 <= 60000);
  TEST_ASSERT_TRUE(d20 >= 52500 && d20 <= 60000);
}

void test_fault_injection_repeated_failures_keep_retry_bounded() {
  uint8_t failures = 0;
  uint32_t now = 1000;
  for (uint32_t i = 0; i < 300; ++i) {
    failures = vibesensor::reliability::saturating_inc_u8(failures);
    const uint32_t delay = vibesensor::reliability::compute_retry_delay_ms(4000, 60000, failures, i);
    TEST_ASSERT_TRUE(delay >= 4000 && delay <= 60000);
    if (i > 6) {
      TEST_ASSERT_TRUE(delay >= 52500);
    }
    now += delay;
    TEST_ASSERT_TRUE(vibesensor::reliability::retry_due(now, now));
    TEST_ASSERT_FALSE(vibesensor::reliability::retry_due(now - 1, now));
  }
  TEST_ASSERT_EQUAL_UINT8(0xFF, failures);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_frame_samples_are_clamped_to_datagram_limit);
  RUN_TEST(test_frame_samples_zero_uses_safe_minimum);
  RUN_TEST(test_frame_samples_clamped_for_mtu_safe_payload);
  RUN_TEST(test_retry_backoff_grows_and_caps_with_jitter);
  RUN_TEST(test_fault_injection_repeated_failures_keep_retry_bounded);
  return UNITY_END();
}
