#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdlib>

constexpr uint32_t MALLOC_CAP_8BIT = 0;

// Native tests only need a host-backed stand-in for ESP-IDF's heap-cap API.
inline void* heap_caps_malloc(size_t size, uint32_t) {
  return std::malloc(size);
}
