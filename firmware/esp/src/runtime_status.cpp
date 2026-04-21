#include "runtime_status.h"

#include <WiFi.h>

#include "runtime_config.h"

namespace vibesensor::runtime {
namespace {

bool sampling_error_is_newer(const RuntimeStatus& runtime_status,
                             const SamplingStatusSnapshot& sampling_status) {
  return static_cast<int32_t>(sampling_status.last_error_ms - runtime_status.last_error_ms) > 0;
}

}  // namespace

void set_last_error(RuntimeStatus& status, uint8_t error_code) {
  status.last_error_code = error_code;
  status.last_error_ms = millis();
}

void report_runtime_status(RuntimeStatus& status,
                           const SamplingStatusSnapshot& sampling,
                           size_t queue_size,
                           size_t queue_capacity,
                           uint32_t now_ms) {
  if (now_ms - status.last_status_report_ms < kStatusReportIntervalMs) {
    return;
  }
  status.last_status_report_ms = now_ms;

  const bool sampling_error_newer = sampling_error_is_newer(status, sampling);
  const uint8_t last_error_code =
      sampling_error_newer ? sampling.last_error_code : status.last_error_code;
  const uint32_t last_error_ms =
      sampling_error_newer ? sampling.last_error_ms : status.last_error_ms;

  Serial.printf(
      "status wifi=%d q=%u/%u drop=%lu tx_fail={pack:%lu begin:%lu end:%lu} "
      "sensor={err:%lu stat:%lu data:%lu trunc:%lu bus:%lu/%lu reinit:%lu/%lu miss:%lu late:%lu handoff:%lu "
      "sq:%u/%u prefetch:%u refill:%u/%u} "
      "wifi_retry={attempts:%lu fail:%lu} sync={offset_us:%lld rtt_us:%lu} "
      "parse={ctrl:%lu ack:%lu} last_error=%u@%lu\n",
      WiFi.status(),
      static_cast<unsigned>(queue_size),
      static_cast<unsigned>(queue_capacity),
      static_cast<unsigned long>(status.queue_overflow_drops),
      static_cast<unsigned long>(status.tx_pack_failures),
      static_cast<unsigned long>(status.tx_begin_failures),
      static_cast<unsigned long>(status.tx_end_failures),
      static_cast<unsigned long>(sampling.sensor_read_errors),
      static_cast<unsigned long>(sampling.sensor_fifo_status_failures),
      static_cast<unsigned long>(sampling.sensor_fifo_data_failures),
      static_cast<unsigned long>(sampling.sensor_fifo_truncated),
      static_cast<unsigned long>(sampling.sensor_bus_recovery_success),
      static_cast<unsigned long>(sampling.sensor_bus_recovery_attempts),
      static_cast<unsigned long>(sampling.sensor_reinit_success),
      static_cast<unsigned long>(sampling.sensor_reinit_attempts),
      static_cast<unsigned long>(sampling.sampling_missed_samples),
      static_cast<unsigned long>(sampling.sampling_recovery_abandons),
      static_cast<unsigned long>(sampling.sampling_handoff_overflow_drops),
      static_cast<unsigned>(sampling.sample_handoff_size),
      static_cast<unsigned>(sampling.sample_handoff_capacity),
      static_cast<unsigned>(sampling.sensor_prefetch_count),
      static_cast<unsigned>(sampling.last_refill_count),
      static_cast<unsigned>(sampling.last_refill_request),
      static_cast<unsigned long>(status.wifi_reconnect_attempts),
      static_cast<unsigned long>(status.wifi_connect_failures),
      static_cast<long long>(status.sync_offset_us),
      static_cast<unsigned long>(status.sync_round_trip_us),
      static_cast<unsigned long>(status.control_parse_errors),
      static_cast<unsigned long>(status.data_ack_parse_errors),
      static_cast<unsigned>(last_error_code),
      static_cast<unsigned long>(last_error_ms));
}

}  // namespace vibesensor::runtime
