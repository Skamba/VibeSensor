#pragma once

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>

namespace vibesensor::runtime {

struct LedState {
  LedState();

  Adafruit_NeoPixel led_strip;
  uint32_t blink_until_ms = 0;
  uint32_t led_next_update_ms = 0;
  bool identify_leds_active = false;
};

void begin_leds(LedState& state);
void start_identify(LedState& state, uint16_t duration_ms, uint32_t now_ms);
void service_blink(LedState& state, uint32_t now_ms);

}  // namespace vibesensor::runtime
