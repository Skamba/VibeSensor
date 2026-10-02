from __future__ import annotations

from dataclasses import dataclass

UPLINK_CONNECTION_NAME = "VibeSensor-Uplink"
UPLINK_CONNECT_WAIT_S = 30
UPLINK_CONNECT_RETRIES = 3
UPLINK_RESCAN_DELAY_S = 2.0
UPLINK_FALLBACK_DNS = "1.1.1.1,1.0.0.1"
DNS_READY_MIN_WAIT_S = 10.0
DNS_RETRY_INTERVAL_S = 1.0
DNS_PROBE_HOST = "api.github.com"
NMCLI_TIMEOUT_S = 30.0
HOTSPOT_RESTORE_RETRIES = 3
HOTSPOT_RESTORE_DELAY_S = 2.0


@dataclass(frozen=True, slots=True)
class UpdateWifiConfig:
    """Static knobs for the updater's hotspot-to-uplink handoff."""

    ap_con_name: str
    wifi_ifname: str
    uplink_connection_name: str
    uplink_connect_wait_s: int
    uplink_connect_retries: int
    uplink_rescan_delay_s: float
    uplink_fallback_dns: str
    dns_ready_min_wait_s: float
    dns_retry_interval_s: float
    dns_probe_host: str
    nmcli_timeout_s: float
    hotspot_restore_retries: int
    hotspot_restore_delay_s: float


def build_default_wifi_config(*, ap_con_name: str, wifi_ifname: str) -> UpdateWifiConfig:
    """Build the default updater Wi-Fi configuration for the active device."""

    return UpdateWifiConfig(
        ap_con_name=ap_con_name,
        wifi_ifname=wifi_ifname,
        uplink_connection_name=UPLINK_CONNECTION_NAME,
        uplink_connect_wait_s=UPLINK_CONNECT_WAIT_S,
        uplink_connect_retries=UPLINK_CONNECT_RETRIES,
        uplink_rescan_delay_s=UPLINK_RESCAN_DELAY_S,
        uplink_fallback_dns=UPLINK_FALLBACK_DNS,
        dns_ready_min_wait_s=DNS_READY_MIN_WAIT_S,
        dns_retry_interval_s=DNS_RETRY_INTERVAL_S,
        dns_probe_host=DNS_PROBE_HOST,
        nmcli_timeout_s=NMCLI_TIMEOUT_S,
        hotspot_restore_retries=HOTSPOT_RESTORE_RETRIES,
        hotspot_restore_delay_s=HOTSPOT_RESTORE_DELAY_S,
    )
