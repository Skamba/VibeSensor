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

void test_clamp_sample_rate_within_range() {
  // Values already in range pass through unchanged.
  TEST_ASSERT_EQUAL_UINT16(400,
      vibesensor::reliability::clamp_sample_rate(400, 25, 3200));
  TEST_ASSERT_EQUAL_UINT16(25,
      vibesensor::reliability::clamp_sample_rate(25, 25, 3200));
  TEST_ASSERT_EQUAL_UINT16(3200,
      vibesensor::reliability::clamp_sample_rate(3200, 25, 3200));
}

void test_clamp_sample_rate_below_minimum() {
  // Values below the minimum are raised to the minimum.
  TEST_ASSERT_EQUAL_UINT16(25,
      vibesensor::reliability::clamp_sample_rate(0, 25, 3200));
  TEST_ASSERT_EQUAL_UINT16(25,
      vibesensor::reliability::clamp_sample_rate(1, 25, 3200));
  TEST_ASSERT_EQUAL_UINT16(25,
      vibesensor::reliability::clamp_sample_rate(24, 25, 3200));
}

void test_clamp_sample_rate_above_maximum() {
  // Values above the maximum are lowered to the maximum.
  TEST_ASSERT_EQUAL_UINT16(3200,
      vibesensor::reliability::clamp_sample_rate(3201, 25, 3200));
  TEST_ASSERT_EQUAL_UINT16(3200,
      vibesensor::reliability::clamp_sample_rate(65535, 25, 3200));
}

void test_retry_due_zero_retry_at_always_true() {
  // retry_at_ms == 0 means "fire immediately on first check".
  TEST_ASSERT_TRUE(vibesensor::reliability::retry_due(0, 0));
  TEST_ASSERT_TRUE(vibesensor::reliability::retry_due(1000, 0));
}

void test_retry_due_respects_wall_clock() {
  // retry_due is true when now >= retry_at (signed comparison for wrap safety).
  TEST_ASSERT_TRUE(vibesensor::reliability::retry_due(5000, 5000));
  TEST_ASSERT_TRUE(vibesensor::reliability::retry_due(5001, 5000));
  TEST_ASSERT_FALSE(vibesensor::reliability::retry_due(4999, 5000));
}

void test_saturating_inc_u8_does_not_wrap() {
  uint8_t v = 0xFE;
  v = vibesensor::reliability::saturating_inc_u8(v);
  TEST_ASSERT_EQUAL_UINT8(0xFF, v);
  // Subsequent increments stay at 0xFF.
  v = vibesensor::reliability::saturating_inc_u8(v);
  TEST_ASSERT_EQUAL_UINT8(0xFF, v);
  v = vibesensor::reliability::saturating_inc_u8(v);
  TEST_ASSERT_EQUAL_UINT8(0xFF, v);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_frame_samples_are_clamped_to_datagram_limit);
  RUN_TEST(test_frame_samples_zero_uses_safe_minimum);
  RUN_TEST(test_frame_samples_clamped_for_mtu_safe_payload);
  RUN_TEST(test_retry_backoff_grows_and_caps_with_jitter);
  RUN_TEST(test_fault_injection_repeated_failures_keep_retry_bounded);
  RUN_TEST(test_clamp_sample_rate_within_range);
  RUN_TEST(test_clamp_sample_rate_below_minimum);
  RUN_TEST(test_clamp_sample_rate_above_maximum);
  RUN_TEST(test_retry_due_zero_retry_at_always_true);
  RUN_TEST(test_retry_due_respects_wall_clock);
  RUN_TEST(test_saturating_inc_u8_does_not_wrap);
  return UNITY_END();
}
