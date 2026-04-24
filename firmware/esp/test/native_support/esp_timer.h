#pragma once

#include <cstdint>

#include "Arduino.h"
#include "esp_err.h"

using esp_timer_handle_t = void*;

struct esp_timer_create_args_t {
  void (*callback)(void*) = nullptr;
  void* arg = nullptr;
  int dispatch_method = 0;
  const char* name = nullptr;
};

constexpr int ESP_TIMER_TASK = 0;

inline int64_t esp_timer_get_time() {
  return static_cast<int64_t>(arduino_test::next_esp_time());
}

inline esp_err_t esp_timer_create(const esp_timer_create_args_t*, esp_timer_handle_t* out_handle) {
  if (out_handle != nullptr) {
    *out_handle = reinterpret_cast<void*>(0x1);
  }
  return ESP_OK;
}

inline esp_err_t esp_timer_start_periodic(esp_timer_handle_t, uint64_t) { return ESP_OK; }

inline esp_err_t esp_timer_delete(esp_timer_handle_t) { return ESP_OK; }
