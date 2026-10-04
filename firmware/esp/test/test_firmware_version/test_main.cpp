#include <string.h>
#include <unity.h>

#include "../../src/runtime_config.h"

namespace {

// HELLO sends the version alone; the release tooling finds it in firmware.bin
// after the marker.
void test_hello_version_is_the_tag_after_the_marker() {
  const size_t marker_len = strlen(VIBESENSOR_FIRMWARE_VERSION_MARKER);
  TEST_ASSERT_EQUAL_INT(0,
                        strncmp(vibesensor::runtime::kFirmwareVersionTag,
                                VIBESENSOR_FIRMWARE_VERSION_MARKER,
                                marker_len));
  TEST_ASSERT_EQUAL_PTR(vibesensor::runtime::kFirmwareVersionTag + marker_len,
                        vibesensor::runtime::kFirmwareVersion);
  TEST_ASSERT_EQUAL_STRING("0.0.0-dev", vibesensor::runtime::kFirmwareVersion);
}

}  // namespace

int main(int argc, char** argv) {
  UNITY_BEGIN();
  RUN_TEST(test_hello_version_is_the_tag_after_the_marker);
  return UNITY_END();
}
