#pragma once

#include <cstring>
#include <map>
#include <string>

// Host-side stand-in for the Arduino-ESP32 Preferences (NVS) API; tests seed
// `Preferences::store` with "<namespace>/<key>" entries.
class Preferences {
 public:
  static std::map<std::string, std::string>& store() {
    static std::map<std::string, std::string> values;
    return values;
  }

  bool begin(const char* name, bool /*readOnly*/ = false) {
    namespace_ = name;
    for (const auto& entry : store()) {
      if (entry.first.rfind(namespace_ + "/", 0) == 0) {
        return true;
      }
    }
    return false;  // read-only open of a missing namespace fails on device too
  }

  void end() { namespace_.clear(); }

  size_t getString(const char* key, char* value, size_t max_len) {
    const auto it = store().find(namespace_ + "/" + key);
    if (it == store().end() || it->second.size() + 1 > max_len) {
      return 0;
    }
    std::memcpy(value, it->second.c_str(), it->second.size() + 1);
    return it->second.size() + 1;
  }

 private:
  std::string namespace_;
};
