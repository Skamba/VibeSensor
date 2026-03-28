#pragma once

#include <Arduino.h>

#include "reliability.h"
#include "vibesensor_contracts.h"
#include "vibesensor_proto.h"

namespace vibesensor::runtime {

constexpr char kClientName[] = "vibe-node";
constexpr char kFirmwareVersion[] = "esp32-atom-0.1";

// Conservative UDP payload cap that avoids IP fragmentation on MTU-1500 paths.
// 1500 (link MTU) - 20 (IP header) - 8 (UDP header) = 1472 safe payload bytes.
// Override via build_flags: -D VIBESENSOR_MAX_UDP_PAYLOAD=<bytes>
#ifndef VIBESENSOR_MAX_UDP_PAYLOAD
#define VIBESENSOR_MAX_UDP_PAYLOAD 1472
#endif
constexpr size_t kMaxDatagramBytes = static_cast<size_t>(VIBESENSOR_MAX_UDP_PAYLOAD);

#ifndef VIBESENSOR_SAMPLE_RATE_HZ
#define VIBESENSOR_SAMPLE_RATE_HZ 800
#endif
#ifndef VIBESENSOR_FRAME_SAMPLES
#define VIBESENSOR_FRAME_SAMPLES 200
#endif
#ifndef VIBESENSOR_SERVER_DATA_PORT
#define VIBESENSOR_SERVER_DATA_PORT VS_SERVER_UDP_DATA_PORT
#endif
#ifndef VIBESENSOR_SERVER_CONTROL_PORT
#define VIBESENSOR_SERVER_CONTROL_PORT VS_SERVER_UDP_CONTROL_PORT
#endif
#ifndef VIBESENSOR_CONTROL_PORT_BASE
#define VIBESENSOR_CONTROL_PORT_BASE VS_FIRMWARE_CONTROL_PORT_BASE
#endif

constexpr uint16_t kSampleRateMinHz = 25;
constexpr uint16_t kSampleRateMaxHz = 3200;
constexpr uint16_t kConfiguredSampleRateHz = static_cast<uint16_t>(VIBESENSOR_SAMPLE_RATE_HZ);
constexpr uint16_t kSampleRateHz = vibesensor::reliability::clamp_sample_rate(
    kConfiguredSampleRateHz, kSampleRateMinHz, kSampleRateMaxHz);
constexpr uint16_t kFrameSamplesMaxByDatagram =
    static_cast<uint16_t>((kMaxDatagramBytes - vibesensor::kDataHeaderBytes) / 6);
constexpr uint16_t kConfiguredFrameSamples = static_cast<uint16_t>(VIBESENSOR_FRAME_SAMPLES);
constexpr uint16_t kFrameSamples = (kConfiguredFrameSamples == 0)
                                       ? 1
                                       : ((kConfiguredFrameSamples > kFrameSamplesMaxByDatagram)
                                              ? kFrameSamplesMaxByDatagram
                                              : kConfiguredFrameSamples);
constexpr uint16_t kServerDataPort = static_cast<uint16_t>(VIBESENSOR_SERVER_DATA_PORT);
constexpr uint16_t kServerControlPort = static_cast<uint16_t>(VIBESENSOR_SERVER_CONTROL_PORT);
constexpr uint16_t kControlPortBase = static_cast<uint16_t>(VIBESENSOR_CONTROL_PORT_BASE);
constexpr size_t kAxesPerSample = 3;

#ifndef VIBESENSOR_FRAME_QUEUE_LEN_TARGET
#define VIBESENSOR_FRAME_QUEUE_LEN_TARGET 128
#endif
#ifndef VIBESENSOR_FRAME_QUEUE_LEN_MIN
#define VIBESENSOR_FRAME_QUEUE_LEN_MIN 16
#endif
constexpr size_t kFrameQueueLenTarget = static_cast<size_t>(VIBESENSOR_FRAME_QUEUE_LEN_TARGET);
constexpr size_t kFrameQueueLenMin = static_cast<size_t>(VIBESENSOR_FRAME_QUEUE_LEN_MIN);

constexpr uint32_t kHelloIntervalMs = 2000;

#ifndef VIBESENSOR_WIFI_CONNECT_TIMEOUT_MS
#define VIBESENSOR_WIFI_CONNECT_TIMEOUT_MS 15000
#endif
#ifndef VIBESENSOR_WIFI_RETRY_BACKOFF_MS
#define VIBESENSOR_WIFI_RETRY_BACKOFF_MS 2000
#endif
#ifndef VIBESENSOR_WIFI_RETRY_INTERVAL_MS
#define VIBESENSOR_WIFI_RETRY_INTERVAL_MS 4000
#endif
#ifndef VIBESENSOR_WIFI_INITIAL_CONNECT_ATTEMPTS
#define VIBESENSOR_WIFI_INITIAL_CONNECT_ATTEMPTS 3
#endif
constexpr uint32_t kWifiConnectTimeoutMs = static_cast<uint32_t>(VIBESENSOR_WIFI_CONNECT_TIMEOUT_MS);
constexpr uint32_t kWifiRetryBackoffMs = static_cast<uint32_t>(VIBESENSOR_WIFI_RETRY_BACKOFF_MS);
constexpr uint32_t kWifiRetryIntervalMs = static_cast<uint32_t>(VIBESENSOR_WIFI_RETRY_INTERVAL_MS);
constexpr uint8_t kWifiInitialConnectAttempts =
    static_cast<uint8_t>(VIBESENSOR_WIFI_INITIAL_CONNECT_ATTEMPTS);

#ifndef VIBESENSOR_SAMPLING_CATCHUP_BUDGET_US
#define VIBESENSOR_SAMPLING_CATCHUP_BUDGET_US 10000
#endif
constexpr uint32_t kSamplingCatchUpBudgetUs =
    static_cast<uint32_t>(VIBESENSOR_SAMPLING_CATCHUP_BUDGET_US);

constexpr size_t kSensorReadBatchSamples = 8;
constexpr size_t kSensorPrefetchSamples = 32;
constexpr size_t kSensorPrefetchLowWaterSamples = 8;
constexpr size_t kMaxTxFramesPerLoop = 2;
constexpr size_t kMaxDataAckPacketsPerLoop = 8;
constexpr uint32_t kDataRetransmitIntervalMs = 120;
constexpr uint32_t kStatusReportIntervalMs = 10000;
constexpr uint16_t kMaxIdentifyDurationMs = 10000;
constexpr uint8_t kSensorReinitErrorThreshold = 3;
constexpr uint32_t kSensorReinitCooldownMs = 5000;
constexpr uint32_t kWifiRetryIntervalMaxMs = 60000;

#ifndef VIBESENSOR_WIFI_SCAN_INTERVAL_MS
#define VIBESENSOR_WIFI_SCAN_INTERVAL_MS 20000
#endif
constexpr uint32_t kWifiScanIntervalMs = static_cast<uint32_t>(VIBESENSOR_WIFI_SCAN_INTERVAL_MS);

#ifndef VIBESENSOR_ENABLE_SYNTH_FALLBACK
#define VIBESENSOR_ENABLE_SYNTH_FALLBACK 0
#endif

static_assert(VIBESENSOR_SAMPLE_RATE_HZ > 0, "VIBESENSOR_SAMPLE_RATE_HZ must be > 0");
static_assert(VIBESENSOR_FRAME_SAMPLES > 0, "VIBESENSOR_FRAME_SAMPLES must be > 0");
static_assert(VIBESENSOR_SAMPLING_CATCHUP_BUDGET_US > 0,
              "VIBESENSOR_SAMPLING_CATCHUP_BUDGET_US must be > 0");
static_assert(VIBESENSOR_FRAME_QUEUE_LEN_MIN > 0,
              "VIBESENSOR_FRAME_QUEUE_LEN_MIN must be > 0");
static_assert(VIBESENSOR_FRAME_QUEUE_LEN_TARGET >= VIBESENSOR_FRAME_QUEUE_LEN_MIN,
              "VIBESENSOR_FRAME_QUEUE_LEN_TARGET must be >= VIBESENSOR_FRAME_QUEUE_LEN_MIN");
static_assert(VIBESENSOR_WIFI_INITIAL_CONNECT_ATTEMPTS > 0,
              "VIBESENSOR_WIFI_INITIAL_CONNECT_ATTEMPTS must be > 0");
static_assert(kFrameSamplesMaxByDatagram > 0, "kMaxDatagramBytes too small for protocol");
static_assert(kSensorPrefetchLowWaterSamples < kSensorPrefetchSamples,
              "sensor prefetch low-water must be below prefetch capacity");

constexpr int kI2cSdaPin = 26;
constexpr int kI2cSclPin = 32;
constexpr uint8_t kAdxlI2cAddr = 0x53;

#ifndef LED_BUILTIN
constexpr int kLedPin = 27;
#else
constexpr int kLedPin = LED_BUILTIN;
#endif
constexpr uint16_t kLedPixels = 1;
constexpr uint16_t kIdentifyBlinkPeriodMs = 300;
constexpr uint8_t kIdentifyBrightness = 64;

}  // namespace vibesensor::runtime
