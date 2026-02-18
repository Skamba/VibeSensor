#pragma once

#include <Arduino.h>

#if __has_include("vibesensor_network.local.h")
#include "vibesensor_network.local.h"
#endif

#ifndef VIBESENSOR_WIFI_SSID
#define VIBESENSOR_WIFI_SSID "VibeSensor"
#endif

#ifndef VIBESENSOR_WIFI_PSK
#define VIBESENSOR_WIFI_PSK "vibesensor123"
#endif

#ifndef VIBESENSOR_SERVER_IP_OCTETS
#define VIBESENSOR_SERVER_IP_OCTETS 192, 168, 4, 1
#endif

namespace vibesensor_network {

static constexpr const char* wifi_ssid = VIBESENSOR_WIFI_SSID;
static constexpr const char* wifi_psk = VIBESENSOR_WIFI_PSK;
static const IPAddress server_ip(VIBESENSOR_SERVER_IP_OCTETS);

}  // namespace vibesensor_network
