#include "runtime_led.h"

#include "runtime_config.h"

namespace vibesensor::runtime {
namespace {

void clear_leds(LedState& state) {
  state.led_strip.clear();
  state.led_strip.show();
}

void render_identify_blink(LedState& state, uint32_t now_ms) {
  bool led_on = ((now_ms / kIdentifyBlinkPeriodMs) % 2U) == 0U;
  if (led_on) {
    state.led_strip.setPixelColor(
        0, state.led_strip.Color(0, kIdentifyBrightness, kIdentifyBrightness));
  } else {
    state.led_strip.setPixelColor(0, 0);
  }
  state.led_strip.show();
}

}  // namespace

LedState::LedState() : led_strip(kLedPixels, kLedPin, NEO_GRB + NEO_KHZ800) {}

void begin_leds(LedState& state) {
  state.led_strip.begin();
  clear_leds(state);
}

void start_identify(LedState& state, uint16_t duration_ms, uint32_t now_ms) {
  state.blink_until_ms = now_ms + duration_ms;
  state.led_next_update_ms = 0;
}

void service_blink(LedState& state, uint32_t now_ms) {
  if (state.blink_until_ms == 0 ||
      static_cast<int32_t>(state.blink_until_ms - now_ms) <= 0) {
    if (state.identify_leds_active) {
      clear_leds(state);
      state.identify_leds_active = false;
    }
    state.blink_until_ms = 0;
    return;
  }

  if (now_ms >= state.led_next_update_ms) {
    render_identify_blink(state, now_ms);
    state.identify_leds_active = true;
    state.led_next_update_ms = now_ms + (kIdentifyBlinkPeriodMs / 2U);
  }
}

}  // namespace vibesensor::runtime
