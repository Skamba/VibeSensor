#include "runtime_status.h"

#include <WiFi.h>

#include "runtime_config.h"

namespace vibesensor::runtime {

void set_last_error(RuntimeStatus& status, uint8_t error_code) {
  status.last_error_code = error_code;
  status.last_error_ms = millis();
}

void report_runtime_status(RuntimeStatus& status,
                           size_t queue_size,
                           size_t queue_capacity,
                           uint32_t now_ms) {
  if (now_ms - status.last_status_report_ms < kStatusReportIntervalMs) {
    return;
  }
  status.last_status_report_ms = now_ms;
  Serial.printf(
      "status wifi=%d q=%u/%u drop=%lu tx_fail={pack:%lu begin:%lu end:%lu} "
      "sensor={err:%lu trunc:%lu reinit:%lu/%lu miss:%lu budget:%lu} "
      "wifi_retry={attempts:%lu fail:%lu} "
      "parse={ctrl:%lu ack:%lu} last_error=%u@%lu\n",
      WiFi.status(),
      static_cast<unsigned>(queue_size),
      static_cast<unsigned>(queue_capacity),
      static_cast<unsigned long>(status.queue_overflow_drops),
      static_cast<unsigned long>(status.tx_pack_failures),
      static_cast<unsigned long>(status.tx_begin_failures),
      static_cast<unsigned long>(status.tx_end_failures),
      static_cast<unsigned long>(status.sensor_read_errors),
      static_cast<unsigned long>(status.sensor_fifo_truncated),
      static_cast<unsigned long>(status.sensor_reinit_success),
      static_cast<unsigned long>(status.sensor_reinit_attempts),
      static_cast<unsigned long>(status.sampling_missed_samples),
      static_cast<unsigned long>(status.sampling_budget_exhaustions),
      static_cast<unsigned long>(status.wifi_reconnect_attempts),
      static_cast<unsigned long>(status.wifi_connect_failures),
      static_cast<unsigned long>(status.control_parse_errors),
      static_cast<unsigned long>(status.data_ack_parse_errors),
      static_cast<unsigned>(status.last_error_code),
      static_cast<unsigned long>(status.last_error_ms));
}

}  // namespace vibesensor::runtime
