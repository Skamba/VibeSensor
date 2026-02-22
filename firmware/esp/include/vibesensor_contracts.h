#pragma once

// Canonical source of truth:
//   libs/shared/contracts/metrics_fields.json
//   libs/shared/contracts/network_ports.json
//   libs/shared/contracts/report_fields.json
//
// Keep names aligned with shared contracts when firmware embeds field labels
// in logs/debug output.

#define VS_FIELD_VIBRATION_STRENGTH_DB "vibration_strength_db"
#define VS_FIELD_STRENGTH_BUCKET "strength_bucket"
#define VS_FIELD_PEAK_HZ "peak_hz"

#define VS_SERVER_UDP_DATA_PORT 9000
#define VS_SERVER_UDP_CONTROL_PORT 9001
#define VS_FIRMWARE_CONTROL_PORT_BASE 9010
