#pragma once

#include "freertos/FreeRTOS.h"

using TaskHandle_t = void*;

inline BaseType_t xTaskCreatePinnedToCore(void (*)(void*),
                                          const char*,
                                          uint32_t,
                                          void*,
                                          UBaseType_t,
                                          TaskHandle_t* out_handle,
                                          BaseType_t) {
  if (out_handle != nullptr) {
    *out_handle = reinterpret_cast<void*>(0x1);
  }
  return pdPASS;
}

inline void vTaskDelete(TaskHandle_t) {}

inline UBaseType_t uxTaskPriorityGet(void*) { return 1; }

inline uint32_t ulTaskNotifyTake(BaseType_t, uint32_t) { return 0; }

inline BaseType_t xTaskNotifyGive(TaskHandle_t) { return pdPASS; }

inline BaseType_t xPortGetCoreID() { return 0; }
