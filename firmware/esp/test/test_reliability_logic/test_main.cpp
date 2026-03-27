#include <unity.h>

#include "reliability.h"

namespace {
constexpr size_t kDataHeaderBytes = 18;
constexpr uint32_t kRetryBaseMs = 4000;
constexpr uint32_t kRetryCapMs = 60000;
constexpr uint16_t kMinSampleRateHz = 25;
constexpr uint16_t kMaxSampleRateHz = 3200;
constexpr uint8_t kSensorReinitThreshold = 3;
constexpr uint32_t kSensorReinitCooldownMs = 5000;
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
  const uint32_t d1 =
      vibesensor::reliability::compute_retry_delay_ms(kRetryBaseMs, kRetryCapMs, 1, 1);
  const uint32_t d5 =
      vibesensor::reliability::compute_retry_delay_ms(kRetryBaseMs, kRetryCapMs, 5, 2);
  const uint32_t d20 =
      vibesensor::reliability::compute_retry_delay_ms(kRetryBaseMs, kRetryCapMs, 20, 3);
  TEST_ASSERT_TRUE(d1 >= 7000 && d1 <= 8999);
  TEST_ASSERT_TRUE(d5 >= 52500 && d5 <= 60000);
  TEST_ASSERT_TRUE(d20 >= 52500 && d20 <= 60000);
}

void test_fault_injection_repeated_failures_keep_retry_bounded() {
  uint8_t failures = 0;
  uint32_t now = 1000;
  for (uint32_t i = 0; i < 300; ++i) {
    failures = vibesensor::reliability::saturating_inc_u8(failures);
    const uint32_t delay =
        vibesensor::reliability::compute_retry_delay_ms(kRetryBaseMs, kRetryCapMs, failures, i);
    TEST_ASSERT_TRUE(delay >= kRetryBaseMs && delay <= kRetryCapMs);
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
  TEST_ASSERT_EQUAL_UINT16(
      400,
      vibesensor::reliability::clamp_sample_rate(400, kMinSampleRateHz, kMaxSampleRateHz));
  TEST_ASSERT_EQUAL_UINT16(
      kMinSampleRateHz,
      vibesensor::reliability::clamp_sample_rate(
          kMinSampleRateHz, kMinSampleRateHz, kMaxSampleRateHz));
  TEST_ASSERT_EQUAL_UINT16(
      kMaxSampleRateHz,
      vibesensor::reliability::clamp_sample_rate(
          kMaxSampleRateHz, kMinSampleRateHz, kMaxSampleRateHz));
}

void test_clamp_sample_rate_below_minimum() {
  // Values below the minimum are raised to the minimum.
  TEST_ASSERT_EQUAL_UINT16(
      kMinSampleRateHz,
      vibesensor::reliability::clamp_sample_rate(0, kMinSampleRateHz, kMaxSampleRateHz));
  TEST_ASSERT_EQUAL_UINT16(
      kMinSampleRateHz,
      vibesensor::reliability::clamp_sample_rate(1, kMinSampleRateHz, kMaxSampleRateHz));
  TEST_ASSERT_EQUAL_UINT16(
      kMinSampleRateHz,
      vibesensor::reliability::clamp_sample_rate(
          kMinSampleRateHz - 1, kMinSampleRateHz, kMaxSampleRateHz));
}

void test_clamp_sample_rate_above_maximum() {
  // Values above the maximum are lowered to the maximum.
  TEST_ASSERT_EQUAL_UINT16(
      kMaxSampleRateHz,
      vibesensor::reliability::clamp_sample_rate(
          kMaxSampleRateHz + 1, kMinSampleRateHz, kMaxSampleRateHz));
  TEST_ASSERT_EQUAL_UINT16(
      kMaxSampleRateHz,
      vibesensor::reliability::clamp_sample_rate(
          UINT16_MAX, kMinSampleRateHz, kMaxSampleRateHz));
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

// ---------------------------------------------------------------------------
// Flaky-sensor tests: sensor_should_reinit()
// ---------------------------------------------------------------------------

// Below threshold → reinit not triggered, even with no cooldown constraint.
void test_flaky_sensor_below_threshold_no_reinit() {
  TEST_ASSERT_FALSE(
      vibesensor::reliability::sensor_should_reinit(
          0, kSensorReinitThreshold, 5000, 0, kSensorReinitCooldownMs));
  TEST_ASSERT_FALSE(
      vibesensor::reliability::sensor_should_reinit(
          2, kSensorReinitThreshold, 5000, 0, kSensorReinitCooldownMs));
}

// At/above threshold with cooldown satisfied → reinit triggered.
void test_flaky_sensor_at_threshold_triggers_reinit() {
  // Exactly at threshold; last_reinit_ms=0 so cooldown is always satisfied.
  TEST_ASSERT_TRUE(
      vibesensor::reliability::sensor_should_reinit(
          kSensorReinitThreshold,
          kSensorReinitThreshold,
          5000,
          0,
          kSensorReinitCooldownMs));
  // Above threshold.
  TEST_ASSERT_TRUE(
      vibesensor::reliability::sensor_should_reinit(
          10, kSensorReinitThreshold, 5000, 0, kSensorReinitCooldownMs));
}

// Cooldown not yet elapsed → reinit blocked even though threshold is met.
void test_flaky_sensor_cooldown_blocks_rapid_reinit() {
  // last_reinit_ms=3000, now=6000, cooldown=5000 → elapsed=3000 < 5000
  TEST_ASSERT_FALSE(
      vibesensor::reliability::sensor_should_reinit(
          5, kSensorReinitThreshold, 6000, 3000, kSensorReinitCooldownMs));
}

// Cooldown just satisfied → reinit allowed.
void test_flaky_sensor_cooldown_satisfied_allows_reinit() {
  // last_reinit_ms=3000, now=8001, cooldown=5000 → elapsed=5001 >= 5000
  TEST_ASSERT_TRUE(
      vibesensor::reliability::sensor_should_reinit(
          5, kSensorReinitThreshold, 8001, 3000, kSensorReinitCooldownMs));
  // Exactly at boundary: elapsed == cooldown.
  TEST_ASSERT_TRUE(
      vibesensor::reliability::sensor_should_reinit(
          5, kSensorReinitThreshold, 8000, 3000, kSensorReinitCooldownMs));
}

// Simulates a sustained sensor failure: errors saturate at 0xFF, reinit
// keeps triggering each time the cooldown elapses.
void test_flaky_sensor_sustained_failure_reinit_cycles() {
  uint8_t errs = 0;
  uint32_t now = 0;
  uint32_t last_reinit = 0;
  uint32_t reinit_count = 0;

  // Run enough iterations that the error counter saturates at 0xFF.
  // Use 300 iterations at 1 s each → saturation guaranteed by iteration 255.
  for (uint32_t i = 0; i < 300; ++i) {
    now += 1000;  // 1 s per iteration
    errs = vibesensor::reliability::saturating_inc_u8(errs);

    if (vibesensor::reliability::sensor_should_reinit(
            errs, kSensorReinitThreshold, now, last_reinit, kSensorReinitCooldownMs)) {
      reinit_count++;
      last_reinit = now;
      // Reinit fails: errors stay high (not reset to 0).
    }
  }
  // At 1 s/iteration with 5 s cooldown, ~60 reinits expected over 300 s.
  TEST_ASSERT_TRUE(reinit_count >= 55 && reinit_count <= 65);
  // Error counter saturated at 0xFF, never wrapped.
  TEST_ASSERT_EQUAL_UINT8(0xFF, errs);
}

// After a successful reinit (errors reset to 0), reinit is NOT immediately
// re-triggered on the very next error.
void test_flaky_sensor_reinit_success_resets_counter() {
  uint8_t errs = 0xFF;
  const uint32_t now = 10000;
  const uint32_t last_reinit = now - kSensorReinitCooldownMs;  // cooldown satisfied

  // Before reset: reinit is triggered.
  TEST_ASSERT_TRUE(
       vibesensor::reliability::sensor_should_reinit(
           errs, kSensorReinitThreshold, now, last_reinit, kSensorReinitCooldownMs));

  // Simulate successful reinit: reset error counter and update last_reinit.
  errs = 0;
  const uint32_t new_reinit_ts = now;

  // A single new error after successful reinit should not re-trigger reinit.
  errs = vibesensor::reliability::saturating_inc_u8(errs);
  TEST_ASSERT_FALSE(
       vibesensor::reliability::sensor_should_reinit(
           errs, kSensorReinitThreshold, now, new_reinit_ts, kSensorReinitCooldownMs));
}

// ---------------------------------------------------------------------------
// Flaky-WiFi tests: retry backoff and reconnect behaviour
// ---------------------------------------------------------------------------

// After a rapid sequence of failures, the retry delay should accumulate and
// be capped, never exceeding the maximum or dropping below the minimum.
void test_flaky_wifi_backoff_bounded_across_many_failures() {
  uint8_t failures = 0;
  for (uint32_t i = 0; i < 200; ++i) {
    failures = vibesensor::reliability::saturating_inc_u8(failures);
    const uint32_t delay =
        vibesensor::reliability::compute_retry_delay_ms(kRetryBaseMs, kRetryCapMs, failures, i);
    TEST_ASSERT_TRUE(delay >= kRetryBaseMs);
    TEST_ASSERT_TRUE(delay <= kRetryCapMs);
  }
}

// After many consecutive failures the delay converges near the cap; after a
// successful reconnect (failures reset to 0), the next delay is short again.
void test_flaky_wifi_reconnect_success_resets_backoff() {
  uint8_t failures = 20;
  // When heavily backed off, delay is near the cap.
  const uint32_t long_delay =
      vibesensor::reliability::compute_retry_delay_ms(kRetryBaseMs, kRetryCapMs, failures, 0);
  TEST_ASSERT_TRUE(long_delay >= 52500);

  // On reconnect success failures are reset to 0.
  failures = 0;
  const uint32_t short_delay =
      vibesensor::reliability::compute_retry_delay_ms(kRetryBaseMs, kRetryCapMs, failures, 0);
  // First retry after success should be well below 10 s.
  TEST_ASSERT_TRUE(short_delay < 10000);
}

// Simulate a flaky AP: repeated connect/disconnect cycles.  The retry timer
// must always be set in the future and must never regress below the minimum.
void test_flaky_wifi_repeated_connect_disconnect_cycles() {
  uint8_t failures = 0;
  uint32_t now = 1000;
  uint32_t retry_at = 0;  // fire immediately on first check

  for (uint32_t cycle = 0; cycle < 30; ++cycle) {
    // Advance time to when retry is due.
    TEST_ASSERT_TRUE(vibesensor::reliability::retry_due(now, retry_at));

    // Attempt reconnect (fails).
    failures = vibesensor::reliability::saturating_inc_u8(failures);
    const uint32_t delay =
        vibesensor::reliability::compute_retry_delay_ms(
            kRetryBaseMs, kRetryCapMs, failures, cycle);
    retry_at = now + delay;

    // Not yet due immediately after scheduling.
    TEST_ASSERT_FALSE(vibesensor::reliability::retry_due(now, retry_at));

    // Advance time past the retry window.
    now = retry_at + 1;
    TEST_ASSERT_TRUE(vibesensor::reliability::retry_due(now, retry_at));

    // Simulate an occasional successful reconnect (every 7 cycles).
    if (cycle % 7 == 6) {
      failures = 0;
      retry_at = 0;  // reset → retry_due fires immediately next check
    }
  }
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
  // Flaky sensor
  RUN_TEST(test_flaky_sensor_below_threshold_no_reinit);
  RUN_TEST(test_flaky_sensor_at_threshold_triggers_reinit);
  RUN_TEST(test_flaky_sensor_cooldown_blocks_rapid_reinit);
  RUN_TEST(test_flaky_sensor_cooldown_satisfied_allows_reinit);
  RUN_TEST(test_flaky_sensor_sustained_failure_reinit_cycles);
  RUN_TEST(test_flaky_sensor_reinit_success_resets_counter);
  // Flaky WiFi
  RUN_TEST(test_flaky_wifi_backoff_bounded_across_many_failures);
  RUN_TEST(test_flaky_wifi_reconnect_success_resets_backoff);
  RUN_TEST(test_flaky_wifi_repeated_connect_disconnect_cycles);
  return UNITY_END();
}
