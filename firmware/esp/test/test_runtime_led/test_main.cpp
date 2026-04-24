#include <unity.h>

#include "../../src/runtime_led.cpp"

using vibesensor::runtime::LedState;

void test_begin_leds_clears_boot_state() {
  LedState state;

  vibesensor::runtime::begin_leds(state);

  TEST_ASSERT_TRUE(state.led_strip.begun());
  TEST_ASSERT_EQUAL_UINT32(1, state.led_strip.show_count());
  TEST_ASSERT_EQUAL_UINT32(0, state.led_strip.getPixelColor(0));
}

void test_service_blink_toggles_identify_and_clears_after_expiry() {
  LedState state;
  vibesensor::runtime::begin_leds(state);
  vibesensor::runtime::start_identify(state, 600, 1350);

  vibesensor::runtime::service_blink(state, 1350);
  TEST_ASSERT_TRUE(state.identify_leds_active);
  TEST_ASSERT_EQUAL_UINT32(
      state.led_strip.Color(0, vibesensor::runtime::kIdentifyBrightness, vibesensor::runtime::kIdentifyBrightness),
      state.led_strip.getPixelColor(0));

  vibesensor::runtime::service_blink(state, 1500);
  TEST_ASSERT_EQUAL_UINT32(0, state.led_strip.getPixelColor(0));

  vibesensor::runtime::service_blink(state, 1950);
  TEST_ASSERT_FALSE(state.identify_leds_active);
  TEST_ASSERT_EQUAL_UINT32(0, state.led_strip.getPixelColor(0));
}

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_begin_leds_clears_boot_state);
  RUN_TEST(test_service_blink_toggles_identify_and_clears_after_expiry);
  return UNITY_END();
}
