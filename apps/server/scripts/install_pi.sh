#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_TEMPLATE="${PI_DIR}/systemd/vibesensor.service"
HOTSPOT_SERVICE_TEMPLATE="${PI_DIR}/systemd/vibesensor-hotspot.service"
RFKILL_SERVICE_TEMPLATE="${PI_DIR}/systemd/vibesensor-rfkill-unblock.service"
HOTSPOT_HEAL_SERVICE_TEMPLATE="${PI_DIR}/systemd/vibesensor-hotspot-self-heal.service"
HOTSPOT_HEAL_TIMER_TEMPLATE="${PI_DIR}/systemd/vibesensor-hotspot-self-heal.timer"
VENV_DIR="${PI_DIR}/.venv"
SKIP_SERVICE_START="${VIBESENSOR_SKIP_SERVICE_START:-0}"

if [ "$(id -u)" -eq 0 ]; then
  AS_ROOT=""
else
  AS_ROOT="sudo"
fi

run_as_root() {
  if [ -n "${AS_ROOT}" ]; then
    sudo "$@"
  else
    "$@"
  fi
}

if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
  SERVICE_USER="${SUDO_USER}"
elif id -u pi >/dev/null 2>&1; then
  SERVICE_USER="pi"
else
  SERVICE_USER="$(id -un)"
fi

run_as_root apt-get update
run_as_root apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  network-manager \
  dnsmasq \
  rfkill \
  iw \
  gpsd \
  gpsd-clients

python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -e "${PI_DIR}"
"${VENV_DIR}/bin/python" "${PI_DIR}/../tools/config/config_preflight.py" "${PI_DIR}/config.example.yaml" >/dev/null

run_as_root install -d /etc/vibesensor
run_as_root install -d /etc/tmpfiles.d
run_as_root install -d -m 0755 /var/lib/vibesensor
run_as_root install -d -m 0755 /var/log/vibesensor
run_as_root install -d -m 0755 /var/log/wifi
run_as_root chown "${SERVICE_USER}:${SERVICE_USER}" /var/lib/vibesensor /var/log/vibesensor
run_as_root tee /etc/tmpfiles.d/vibesensor-wifi.conf >/dev/null <<'EOF'
d /var/log/wifi 0755 root root -
EOF
run_as_root systemd-tmpfiles --create /etc/tmpfiles.d/vibesensor-wifi.conf >/dev/null 2>&1 || true
if [ ! -f /etc/vibesensor/config.yaml ]; then
  run_as_root cp "${PI_DIR}/config.example.yaml" /etc/vibesensor/config.yaml
fi
if [ ! -f /etc/vibesensor/wifi-secrets.env ]; then
  run_as_root cp "${PI_DIR}/wifi-secrets.example.env" /etc/vibesensor/wifi-secrets.env
fi
run_as_root chmod 600 /etc/vibesensor/wifi-secrets.env

sed \
  -e "s#__PI_DIR__#${PI_DIR}#g" \
  -e "s#__VENV_DIR__#${VENV_DIR}#g" \
  -e "s#__SERVICE_USER__#${SERVICE_USER}#g" \
  "${SERVICE_TEMPLATE}" | run_as_root tee /etc/systemd/system/vibesensor.service >/dev/null

sed \
  -e "s#__PI_DIR__#${PI_DIR}#g" \
  -e "s#__VENV_DIR__#${VENV_DIR}#g" \
  "${HOTSPOT_SERVICE_TEMPLATE}" | run_as_root tee /etc/systemd/system/vibesensor-hotspot.service >/dev/null

sed \
  -e "s#__PI_DIR__#${PI_DIR}#g" \
  -e "s#__VENV_DIR__#${VENV_DIR}#g" \
  "${RFKILL_SERVICE_TEMPLATE}" | run_as_root tee /etc/systemd/system/vibesensor-rfkill-unblock.service >/dev/null

sed \
  -e "s#__PI_DIR__#${PI_DIR}#g" \
  -e "s#__VENV_DIR__#${VENV_DIR}#g" \
  "${HOTSPOT_HEAL_SERVICE_TEMPLATE}" | run_as_root tee /etc/systemd/system/vibesensor-hotspot-self-heal.service >/dev/null

sed \
  -e "s#__PI_DIR__#${PI_DIR}#g" \
  -e "s#__VENV_DIR__#${VENV_DIR}#g" \
  "${HOTSPOT_HEAL_TIMER_TEMPLATE}" | run_as_root tee /etc/systemd/system/vibesensor-hotspot-self-heal.timer >/dev/null

if [ "${SKIP_SERVICE_START}" = "1" ]; then
  run_as_root systemctl daemon-reload >/dev/null 2>&1 || true
  if ! run_as_root systemctl enable vibesensor.service >/dev/null 2>&1; then
    run_as_root install -d /etc/systemd/system/multi-user.target.wants
    run_as_root ln -sf \
      /etc/systemd/system/vibesensor.service \
      /etc/systemd/system/multi-user.target.wants/vibesensor.service
  fi
  if ! run_as_root systemctl enable vibesensor-hotspot.service >/dev/null 2>&1; then
    run_as_root install -d /etc/systemd/system/multi-user.target.wants
    run_as_root ln -sf \
      /etc/systemd/system/vibesensor-hotspot.service \
      /etc/systemd/system/multi-user.target.wants/vibesensor-hotspot.service
  fi
  if ! run_as_root systemctl enable vibesensor-rfkill-unblock.service >/dev/null 2>&1; then
    run_as_root install -d /etc/systemd/system/NetworkManager.service.wants
    run_as_root ln -sf \
      /etc/systemd/system/vibesensor-rfkill-unblock.service \
      /etc/systemd/system/NetworkManager.service.wants/vibesensor-rfkill-unblock.service
  fi
  if ! run_as_root systemctl enable vibesensor-hotspot-self-heal.timer >/dev/null 2>&1; then
    run_as_root install -d /etc/systemd/system/timers.target.wants
    run_as_root ln -sf \
      /etc/systemd/system/vibesensor-hotspot-self-heal.timer \
      /etc/systemd/system/timers.target.wants/vibesensor-hotspot-self-heal.timer
  fi
else
  run_as_root systemctl daemon-reload
  run_as_root systemctl enable --now vibesensor-rfkill-unblock.service
  run_as_root systemctl enable --now vibesensor.service
  run_as_root systemctl enable --now vibesensor-hotspot.service
  run_as_root systemctl enable --now vibesensor-hotspot-self-heal.timer
  run_as_root systemctl status vibesensor.service --no-pager
fi
