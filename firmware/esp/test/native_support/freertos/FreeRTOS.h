#pragma once

#include <cstdint>

using BaseType_t = int;
using UBaseType_t = unsigned int;
using portMUX_TYPE = int;

constexpr BaseType_t pdTRUE = 1;
constexpr BaseType_t pdPASS = 1;
constexpr uint32_t portMAX_DELAY = 0xffffffffU;
constexpr UBaseType_t configMAX_PRIORITIES = 25;

#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(lock) (void)(lock)
#define portEXIT_CRITICAL(lock) (void)(lock)
