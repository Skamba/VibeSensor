#pragma once

#include <cstdint>

class ESPClass {
 public:
  void setEfuseMac(uint64_t value) { efuse_mac_ = value; }

  uint64_t getEfuseMac() const { return efuse_mac_; }

 private:
  uint64_t efuse_mac_ = 0xD05A00000001ULL;
};

static ESPClass ESP;
