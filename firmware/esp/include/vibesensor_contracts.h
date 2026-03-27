#pragma once

// Keep these firmware-side field labels and port constants aligned with the
// shared backend/UI contracts whenever names or defaults change. Firmware only
// embeds them for protocol constants and debug output.

#define VS_FIELD_VIBRATION_STRENGTH_DB "vibration_strength_db"
#define VS_FIELD_STRENGTH_BUCKET "strength_bucket"
#define VS_FIELD_PEAK_HZ "peak_hz"

#define VS_SERVER_UDP_DATA_PORT 9000
#define VS_SERVER_UDP_CONTROL_PORT 9001
#define VS_FIRMWARE_CONTROL_PORT_BASE 9010
