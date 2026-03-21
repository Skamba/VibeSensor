#pragma once

#include <Arduino.h>

namespace vibesensor::runtime {

struct RuntimeStatus {
  uint32_t last_status_report_ms = 0;
  uint32_t queue_overflow_drops = 0;
  uint32_t sensor_read_errors = 0;
  uint32_t sensor_fifo_truncated = 0;
  uint32_t sensor_reinit_attempts = 0;
  uint32_t sensor_reinit_success = 0;
  uint32_t sampling_missed_samples = 0;
  uint32_t tx_pack_failures = 0;
  uint32_t tx_begin_failures = 0;
  uint32_t tx_end_failures = 0;
  uint32_t control_parse_errors = 0;
  uint32_t data_ack_parse_errors = 0;
  uint32_t wifi_reconnect_attempts = 0;
  uint32_t wifi_connect_failures = 0;
  uint8_t last_error_code = 0;
  uint32_t last_error_ms = 0;
};

void set_last_error(RuntimeStatus& status, uint8_t error_code);
void report_runtime_status(RuntimeStatus& status,
                           size_t queue_size,
                           size_t queue_capacity,
                           uint32_t now_ms);

}  // namespace vibesensor::runtime
