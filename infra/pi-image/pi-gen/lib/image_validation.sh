read_supported_python_floor_from_pyproject() {
  local pyproject_path="$1"
  local floor
  floor="$(
    sed -n 's/^requires-python = ">=\([0-9][0-9]*\.[0-9][0-9]*\)"$/\1/p' "${pyproject_path}" | head -n 1
  )"
  if [ -z "${floor}" ]; then
    return 1
  fi
  printf '%s\n' "${floor}"
}

read_env_file_value() {
  local env_file="$1"
  local key="$2"
  awk -F= -v key="${key}" '
    $1 == key {
      print substr($0, index($0, "=") + 1)
      found = 1
      exit
    }
    END {
      exit(found ? 0 : 1)
    }
  ' "${env_file}"
}

python_version_meets_floor() {
  local actual_version="$1"
  local floor="$2"
  local actual_major actual_minor floor_major floor_minor
  IFS=. read -r actual_major actual_minor _ <<<"${actual_version}"
  IFS=. read -r floor_major floor_minor <<<"${floor}"

  if ! [[ "${actual_major}" =~ ^[0-9]+$ && "${actual_minor}" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  if ! [[ "${floor_major}" =~ ^[0-9]+$ && "${floor_minor}" =~ ^[0-9]+$ ]]; then
    return 1
  fi

  if [ "${actual_major}" -gt "${floor_major}" ]; then
    return 0
  fi
  if [ "${actual_major}" -lt "${floor_major}" ]; then
    return 1
  fi
  [ "${actual_minor}" -ge "${floor_minor}" ]
}

validate_image_artifact() {
  local FINAL_ARTIFACT="$1"
  local INSPECT_DIR="${OUT_DIR}/inspect"
  local INSPECT_IMG="${FINAL_ARTIFACT}"
  local MOUNT_DIR="${OUT_DIR}/mount"
  local BOOT_MNT="${MOUNT_DIR}/boot"
  local ROOT_MNT="${MOUNT_DIR}/root"
  local LOOP_DEV=""
  local RFKILL_PATH=""
  local BLUETOOTHCTL_PATH=""
  local SDPTOOL_PATH=""
  local IW_PATH=""
  local DNSMASQ_PATH=""
  local GPSD_PATH=""
  local OPENBLAS_LIB=""
  local ROOTFS_PYPROJECT=""
  local PYTHON_RUNTIME_INFO_PATH=""
  local RECORDED_SYSTEM_PYTHON=""
  local RECORDED_SYSTEM_PYTHON_VERSION=""
  local RECORDED_VENV_PYTHON=""
  local RECORDED_VENV_PYTHON_VERSION=""
  local RECORDED_SUPPORTED_PYTHON_FLOOR=""
  local ACTUAL_SUPPORTED_PYTHON_FLOOR=""
  local ACTUAL_VENV_PYTHON_VERSION=""
  local SHADOW_LINE=""
  local SHADOW_HASH=""

  VALIDATED_IMAGE_PYTHON_VERSION=""
  VALIDATED_IMAGE_PYTHON_FLOOR=""

  mkdir -p "${INSPECT_DIR}"

  case "${FINAL_ARTIFACT}" in
    *.img)
      ;;
    *.img.xz)
      require_cmd xz
      INSPECT_IMG="${FINAL_ARTIFACT%.xz}"
      xz -dkf "${FINAL_ARTIFACT}"
      ;;
    *.zip)
      require_cmd unzip
      unzip -o "${FINAL_ARTIFACT}" -d "${INSPECT_DIR}" >/dev/null
      INSPECT_IMG="$(find "${INSPECT_DIR}" -maxdepth 1 -type f -name "*.img" | sort -r | head -n 1 || true)"
      if [ -z "${INSPECT_IMG}" ]; then
        echo "ZIP artifact did not contain an .img file: ${FINAL_ARTIFACT}"
        exit 1
      fi
      ;;
    *)
      echo "Unsupported artifact format: ${FINAL_ARTIFACT}"
      exit 1
      ;;
  esac

  if [ ! -f "${INSPECT_IMG}" ]; then
    echo "Inspection image does not exist: ${INSPECT_IMG}"
    exit 1
  fi

  mkdir -p "${BOOT_MNT}" "${ROOT_MNT}"

  cleanup_mounts() {
    set +e
    if mountpoint -q "${ROOT_MNT}"; then
      sudo umount "${ROOT_MNT}"
    fi
    if mountpoint -q "${BOOT_MNT}"; then
      sudo umount "${BOOT_MNT}"
    fi
    if [ -n "${LOOP_DEV}" ]; then
      sudo losetup -d "${LOOP_DEV}"
    fi
  }
  trap cleanup_mounts EXIT

  LOOP_DEV="$(sudo losetup -Pf --show "${INSPECT_IMG}")"
  sudo mount "${LOOP_DEV}p1" "${BOOT_MNT}"
  sudo mount "${LOOP_DEV}p2" "${ROOT_MNT}"

  if [ ! -d "${ROOT_MNT}/opt/VibeSensor" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/opt/VibeSensor"
    exit 1
  fi

  if [ ! -x "${ROOT_MNT}/usr/bin/nmcli" ]; then
    echo "Validation failed: missing executable ${ROOT_MNT}/usr/bin/nmcli"
    exit 1
  fi

  assert_rootfs_binary() {
    local name="$1"
    local path=""
    for candidate in "/usr/bin/${name}" "/usr/sbin/${name}" "/bin/${name}" "/sbin/${name}"; do
      if [ -x "${ROOT_MNT}${candidate}" ]; then
        path="${candidate}"
        break
      fi
    done
    if [ -z "${path}" ]; then
      echo "Validation failed: missing executable '${name}' in rootfs PATH locations"
      exit 1
    fi
    printf '%s\n' "${path}"
  }

  assert_rootfs_package() {
    local pkg="$1"
    if ! awk -v pkg="${pkg}" '
      BEGIN {in_pkg=0; ok=0}
      $0 == "Package: " pkg {in_pkg=1; next}
      /^Package: / && in_pkg {exit}
      in_pkg && $0 == "Status: install ok installed" {ok=1}
      END {exit(ok ? 0 : 1)}
    ' "${ROOT_MNT}/var/lib/dpkg/status"; then
      echo "Validation failed: package '${pkg}' is not installed in image rootfs"
      exit 1
    fi
  }

  RFKILL_PATH="$(assert_rootfs_binary rfkill)"
  BLUETOOTHCTL_PATH="$(assert_rootfs_binary bluetoothctl)"
  SDPTOOL_PATH="$(assert_rootfs_binary sdptool)"
  IW_PATH="$(assert_rootfs_binary iw)"
  DNSMASQ_PATH="$(assert_rootfs_binary dnsmasq)"
  GPSD_PATH="$(assert_rootfs_binary gpsd)"
  USBMUXD_PATH="$(assert_rootfs_binary usbmuxd)"

  if [ ! -f "${ROOT_MNT}/etc/systemd/system/vibesensor-hotspot.service" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/etc/systemd/system/vibesensor-hotspot.service"
    exit 1
  fi

  if [ ! -f "${ROOT_MNT}/etc/systemd/system/vibesensor-rfkill-unblock.service" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/etc/systemd/system/vibesensor-rfkill-unblock.service"
    exit 1
  fi

  if [ ! -f "${ROOT_MNT}/usr/lib/systemd/system/bluetooth.service" ] && \
    [ ! -f "${ROOT_MNT}/lib/systemd/system/bluetooth.service" ]; then
    echo "Validation failed: missing bluetooth.service systemd unit in the image rootfs"
    exit 1
  fi

  if [ ! -x "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/vibesensor_obd_admin.py" ]; then
    echo "Validation failed: missing executable ${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/vibesensor_obd_admin.py"
    exit 1
  fi

  if [ ! -f "${ROOT_MNT}/etc/sudoers.d/vibesensor-update" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/etc/sudoers.d/vibesensor-update"
    exit 1
  fi

  if ! sudo grep -Fq '/opt/VibeSensor/apps/server/scripts/vibesensor_obd_admin.py' \
    "${ROOT_MNT}/etc/sudoers.d/vibesensor-update"; then
    echo "Validation failed: OBD helper sudoers entry missing from ${ROOT_MNT}/etc/sudoers.d/vibesensor-update"
    exit 1
  fi

  if ! grep -Fq 'rfkill unblock bluetooth' "${ROOT_MNT}/etc/systemd/system/vibesensor-rfkill-unblock.service"; then
    echo "Validation failed: rfkill unblock service does not explicitly unblock Bluetooth"
    exit 1
  fi

  if [ ! -L "${ROOT_MNT}/etc/systemd/system/bluetooth.service.wants/vibesensor-rfkill-unblock.service" ]; then
    echo "Validation failed: bluetooth.service is not wired to start vibesensor-rfkill-unblock.service"
    exit 1
  fi

  if [ ! -f "${ROOT_MNT}/etc/systemd/system/vibesensor-hotspot-self-heal.service" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/etc/systemd/system/vibesensor-hotspot-self-heal.service"
    exit 1
  fi

  if [ ! -f "${ROOT_MNT}/usr/lib/systemd/system/usbmuxd.service" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/usr/lib/systemd/system/usbmuxd.service"
    exit 1
  fi

  if [ ! -f "${ROOT_MNT}/usr/lib/udev/rules.d/39-usbmuxd.rules" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/usr/lib/udev/rules.d/39-usbmuxd.rules"
    exit 1
  fi

  if ! grep -Eq '^ExecStart=/opt/VibeSensor/apps/server/\.venv/bin/(python|vibesensor-hotspot-self-heal)([[:space:]]|$)' \
    "${ROOT_MNT}/etc/systemd/system/vibesensor-hotspot-self-heal.service"; then
    echo "Validation failed: hotspot self-heal service ExecStart does not reference the apps/server venv bin dir"
    exit 1
  fi

  if [ ! -d "${ROOT_MNT}/etc/vibesensor" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/etc/vibesensor"
    exit 1
  fi

  # Static data ships inside the installed `vibesensor` package wheel
  # (site-packages/vibesensor/data/*). The source tree under
  # /opt/VibeSensor/apps/server/vibesensor is intentionally removed after install,
  # so check the wheel-install path instead. `shopt -s nullglob` avoids literal
  # glob strings when the path is missing; the explicit -f check then fails.
  local venv_site_packages_glob="${ROOT_MNT}/opt/VibeSensor/apps/server/.venv/lib/python*/site-packages/vibesensor/data"
  local venv_data_dir=""
  for candidate in ${venv_site_packages_glob}; do
    if [ -d "${candidate}" ]; then
      venv_data_dir="${candidate}"
      break
    fi
  done
  if [ -z "${venv_data_dir}" ]; then
    echo "Validation failed: missing site-packages/vibesensor/data directory under ${ROOT_MNT}/opt/VibeSensor/apps/server/.venv"
    exit 1
  fi

  if [ ! -f "${venv_data_dir}/report_i18n.json" ]; then
    echo "Validation failed: missing ${venv_data_dir}/report_i18n.json"
    exit 1
  fi

  if [ ! -f "${venv_data_dir}/car_library.json" ]; then
    echo "Validation failed: missing ${venv_data_dir}/car_library.json"
    exit 1
  fi

  ROOTFS_PYPROJECT="${ROOT_MNT}/opt/VibeSensor/apps/server/pyproject.toml"
  if [ ! -f "${ROOTFS_PYPROJECT}" ]; then
    echo "Validation failed: missing ${ROOTFS_PYPROJECT}"
    exit 1
  fi

  if [ -d "${ROOT_MNT}/opt/VibeSensor/apps/server/vibesensor" ]; then
    echo "Validation failed: source tree still present at ${ROOT_MNT}/opt/VibeSensor/apps/server/vibesensor"
    exit 1
  fi

  if [ ! -d "${ROOT_MNT}/var/log/wifi" ] && [ ! -f "${ROOT_MNT}/etc/tmpfiles.d/vibesensor-wifi.conf" ]; then
    echo "Validation failed: missing /var/log/wifi and /etc/tmpfiles.d/vibesensor-wifi.conf"
    exit 1
  fi

  if [ ! -f "${ROOT_MNT}/opt/VibeSensor/apps/server/.venv/bin/python3" ] && \
    [ ! -f "${ROOT_MNT}/opt/VibeSensor/apps/server/.venv/bin/python" ]; then
    echo "Validation failed: Python venv not built at ${ROOT_MNT}/opt/VibeSensor/apps/server/.venv/bin"
    exit 1
  fi

  if [ -d "${ROOT_MNT}/var/lib/vibesensor/firmware/baseline" ]; then
    if [ ! -f "${ROOT_MNT}/var/lib/vibesensor/firmware/baseline/flash.json" ]; then
      echo "WARNING: Baseline firmware directory exists but flash.json manifest is missing"
    else
      echo "Firmware baseline bundle validated OK"
    fi
  else
    echo "WARNING: No embedded baseline firmware bundle (first-boot flash requires online updater)"
  fi

  assert_rootfs_package gpsd
  assert_rootfs_package bluez
  assert_rootfs_package pi-bluetooth
  assert_rootfs_package openssh-server
  assert_rootfs_package libopenblas0-pthread
  assert_rootfs_package libgfortran5
  assert_rootfs_package usbmuxd
  assert_rootfs_package libimobiledevice-1.0-6

  if ! grep -R -n "ipheth" "${ROOT_MNT}/lib/modules"/*/modules.alias* "${ROOT_MNT}/lib/modules"/*/modules.builtin* >/dev/null 2>&1; then
    echo "Validation failed: kernel metadata does not advertise ipheth support"
    exit 1
  fi

  OPENBLAS_LIB="$(find "${ROOT_MNT}/usr/lib" -type f -name 'libopenblas*.so*' | head -n 1 || true)"
  if [ -z "${OPENBLAS_LIB}" ]; then
    echo "Validation failed: OpenBLAS runtime library not found in rootfs"
    exit 1
  fi

  run_qemu_chroot() {
    sudo cp /usr/bin/qemu-arm-static "${ROOT_MNT}/usr/bin/"
    sudo chroot "${ROOT_MNT}" /usr/bin/qemu-arm-static "$@"
  }

  PYTHON_RUNTIME_INFO_PATH="${ROOT_MNT}/opt/VibeSensor/apps/server/.venv/.vibesensor-python-runtime.env"
  if [ ! -f "${PYTHON_RUNTIME_INFO_PATH}" ]; then
    echo "Validation failed: missing ${PYTHON_RUNTIME_INFO_PATH}"
    exit 1
  fi

  RECORDED_SYSTEM_PYTHON="$(read_env_file_value "${PYTHON_RUNTIME_INFO_PATH}" "system_python" || true)"
  RECORDED_SYSTEM_PYTHON_VERSION="$(read_env_file_value "${PYTHON_RUNTIME_INFO_PATH}" "system_python_version" || true)"
  RECORDED_VENV_PYTHON="$(read_env_file_value "${PYTHON_RUNTIME_INFO_PATH}" "venv_python" || true)"
  RECORDED_VENV_PYTHON_VERSION="$(read_env_file_value "${PYTHON_RUNTIME_INFO_PATH}" "venv_python_version" || true)"
  RECORDED_SUPPORTED_PYTHON_FLOOR="$(read_env_file_value "${PYTHON_RUNTIME_INFO_PATH}" "supported_python_floor" || true)"

  if [ -z "${RECORDED_SYSTEM_PYTHON}" ] || [ -z "${RECORDED_SYSTEM_PYTHON_VERSION}" ] || \
    [ -z "${RECORDED_VENV_PYTHON}" ] || [ -z "${RECORDED_VENV_PYTHON_VERSION}" ] || \
    [ -z "${RECORDED_SUPPORTED_PYTHON_FLOOR}" ]; then
    echo "Validation failed: Python runtime metadata file is incomplete at ${PYTHON_RUNTIME_INFO_PATH}"
    exit 1
  fi

  ACTUAL_SUPPORTED_PYTHON_FLOOR="$(read_supported_python_floor_from_pyproject "${ROOTFS_PYPROJECT}" || true)"
  if [ -z "${ACTUAL_SUPPORTED_PYTHON_FLOOR}" ]; then
    echo "Validation failed: Could not determine supported Python floor from ${ROOTFS_PYPROJECT}"
    exit 1
  fi

  ACTUAL_VENV_PYTHON_VERSION="$(
    run_qemu_chroot /opt/VibeSensor/apps/server/.venv/bin/python -c '
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
'
  )"

  if [ "${RECORDED_VENV_PYTHON}" != "/opt/VibeSensor/apps/server/.venv/bin/python" ]; then
    echo "Validation failed: recorded venv Python path ${RECORDED_VENV_PYTHON} does not match /opt/VibeSensor/apps/server/.venv/bin/python"
    exit 1
  fi

  if [ "${RECORDED_VENV_PYTHON_VERSION}" != "${ACTUAL_VENV_PYTHON_VERSION}" ]; then
    echo "Validation failed: recorded image Python version ${RECORDED_VENV_PYTHON_VERSION} does not match actual venv version ${ACTUAL_VENV_PYTHON_VERSION}"
    exit 1
  fi

  if [ "${RECORDED_SUPPORTED_PYTHON_FLOOR}" != "${ACTUAL_SUPPORTED_PYTHON_FLOOR}" ]; then
    echo "Validation failed: recorded Python floor ${RECORDED_SUPPORTED_PYTHON_FLOOR} does not match pyproject floor ${ACTUAL_SUPPORTED_PYTHON_FLOOR}"
    exit 1
  fi

  if ! python_version_meets_floor "${ACTUAL_VENV_PYTHON_VERSION}" "${ACTUAL_SUPPORTED_PYTHON_FLOOR}"; then
    echo "Validation failed: image runtime Python ${ACTUAL_VENV_PYTHON_VERSION} does not satisfy supported floor >=${ACTUAL_SUPPORTED_PYTHON_FLOOR}"
    exit 1
  fi

  VALIDATED_IMAGE_PYTHON_VERSION="${ACTUAL_VENV_PYTHON_VERSION}"
  VALIDATED_IMAGE_PYTHON_FLOOR="${ACTUAL_SUPPORTED_PYTHON_FLOOR}"

  if ! run_qemu_chroot /opt/VibeSensor/apps/server/.venv/bin/python -c '
import vibesensor.use_cases.updates.firmware.firmware_cache
print("FIRMWARE_CACHE_MODULE_OK")
'; then
    echo "Validation failed: firmware_cache module not importable in target rootfs"
    exit 1
  fi

  if ! run_qemu_chroot /opt/VibeSensor/apps/server/.venv/bin/python - <<'PY'
import importlib
mods = [
    "numpy",
    "pyfftw",
    "yaml",
    "reportlab",
    "fastapi",
    "granian",
    "vibesensor",
    "vibesensor.vibration_strength",
]
for mod in mods:
    importlib.import_module(mod)
print("IMPORT_VALIDATION_OK")
PY
  then
    echo "Validation failed: Python import smoke test failed in ARM chroot"
    exit 1
  fi

  if ! run_qemu_chroot /opt/VibeSensor/apps/server/.venv/bin/python - <<'PY'
import pathlib
import vibesensor
module_path = pathlib.Path(vibesensor.__file__).resolve()
if "/site-packages/" not in str(module_path):
    raise SystemExit(f"vibesensor imported from unexpected path: {module_path}")
print("WHEEL_INSTALL_PATH_OK")
PY
  then
    echo "Validation failed: vibesensor is not imported from site-packages wheel install"
    exit 1
  fi

  if run_qemu_chroot /bin/bash -lc '
ls /opt/VibeSensor/apps/server/.venv/lib/python*/site-packages/__editable__.vibesensor-*.pth >/dev/null 2>&1
'; then
    echo "Validation failed: editable install marker found; expected wheel-first runtime"
    exit 1
  fi

  if ! run_qemu_chroot /bin/bash -lc '
set -e
pkill -f "vibesensor-server" >/dev/null 2>&1 || true
cp /etc/vibesensor/config.yaml /tmp/vibesensor-smoke-config.yaml
/opt/VibeSensor/apps/server/.venv/bin/python - <<'PY'
from pathlib import Path

import yaml

path = Path("/tmp/vibesensor-smoke-config.yaml")
config = yaml.safe_load(path.read_text())
server = config.setdefault("server", {})
udp = config.setdefault("udp", {})
server["port"] = 18080
udp["data_host"] = "0.0.0.0"
udp["data_port"] = 19000
udp["control_host"] = "0.0.0.0"
udp["control_port"] = 19001
path.write_text(yaml.safe_dump(config, sort_keys=False))
PY
set +e
timeout 10s /opt/VibeSensor/apps/server/.venv/bin/vibesensor-server --config /tmp/vibesensor-smoke-config.yaml >/tmp/vibesensor-smoke.log 2>&1
code=$?
set -e
if [ "$code" -ne 0 ] && [ "$code" -ne 124 ]; then
  echo "Server startup smoke command failed with code=${code}"
  tail -n 80 /tmp/vibesensor-smoke.log || true
  exit 1
fi
if ! grep -q "Listening at:" /tmp/vibesensor-smoke.log; then
  echo "Server startup smoke did not reach successful startup"
  tail -n 80 /tmp/vibesensor-smoke.log || true
  exit 1
fi
echo "SERVER_STARTUP_SMOKE_OK"
'; then
    echo "Validation failed: vibesensor-server startup smoke failed in ARM chroot"
    exit 1
  fi

  if ! run_qemu_chroot /bin/bash -lc '
set -e
rm -f /etc/ssh/ssh_host_*_key*
mkdir -p /run/sshd
chmod 0755 /run/sshd
if ! ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1; then
  /usr/bin/ssh-keygen -A
fi
/usr/sbin/sshd -t
echo "SSHD_FIRST_BOOT_READINESS_OK"
'; then
    echo "Validation failed: sshd first-boot readiness test failed"
    exit 1
  fi

  if grep -n "apt-get" "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/hotspot_nmcli.sh" >/dev/null 2>&1; then
    echo "Validation failed: hotspot script still contains apt-get"
    exit 1
  fi

  if ! grep -n "/var/log/wifi" "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/hotspot_nmcli.sh" >/dev/null 2>&1; then
    echo "Validation failed: hotspot script does not reference /var/log/wifi"
    exit 1
  fi

  if [ ! -f "${ROOT_MNT}/etc/NetworkManager/conf.d/99-vibesensor-dnsmasq.conf" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/etc/NetworkManager/conf.d/99-vibesensor-dnsmasq.conf"
    exit 1
  fi

  if [ -f "${ROOT_MNT}/etc/xdg/autostart/piwiz.desktop" ]; then
    echo "Validation failed: first-boot user wizard still present (${ROOT_MNT}/etc/xdg/autostart/piwiz.desktop)"
    exit 1
  fi

  if ! grep -E "^${VS_FIRST_USER_NAME}:" "${ROOT_MNT}/etc/passwd" >/dev/null 2>&1; then
    echo "Validation failed: expected user '${VS_FIRST_USER_NAME}' missing from /etc/passwd"
    exit 1
  fi

  if [ ! -f "${ROOT_MNT}/etc/ssh/sshd_config.d/99-vibesensor-password-auth.conf" ]; then
    echo "Validation failed: missing SSH password-auth drop-in"
    exit 1
  fi

  if ! grep -Eq '^PasswordAuthentication[[:space:]]+yes$' "${ROOT_MNT}/etc/ssh/sshd_config.d/99-vibesensor-password-auth.conf"; then
    echo "Validation failed: SSH password auth drop-in does not enable PasswordAuthentication"
    exit 1
  fi

  if [ ! -L "${ROOT_MNT}/etc/systemd/system/multi-user.target.wants/ssh.service" ]; then
    echo "Validation failed: ssh.service is not enabled in multi-user.target"
    exit 1
  fi

  if [ -L "${ROOT_MNT}/etc/systemd/system/ssh.service" ] && \
    [ "$(readlink "${ROOT_MNT}/etc/systemd/system/ssh.service")" = "/dev/null" ]; then
    echo "Validation failed: ssh.service is masked"
    exit 1
  fi

  # The supported contract is ssh.service enablement plus the drop-in below.
  # Trixie no longer guarantees a standalone regenerate_ssh_host_keys symlink.
  if [ ! -f "${ROOT_MNT}/etc/systemd/system/ssh.service.d/10-vibesensor-hostkeys.conf" ]; then
    echo "Validation failed: missing ssh host-key bootstrap drop-in"
    exit 1
  fi

  if ! grep -Fq 'ssh-keygen -A' "${ROOT_MNT}/etc/systemd/system/ssh.service.d/10-vibesensor-hostkeys.conf"; then
    echo "Validation failed: ssh host-key bootstrap drop-in does not generate host keys"
    exit 1
  fi

  SHADOW_LINE="$(sudo grep -E "^${VS_FIRST_USER_NAME}:" "${ROOT_MNT}/etc/shadow" || true)"
  SHADOW_HASH="$(printf '%s\n' "${SHADOW_LINE}" | cut -d: -f2)"
  if [ -z "${SHADOW_HASH}" ] || [ "${SHADOW_HASH}" = "*" ] || [ "${SHADOW_HASH}" = "!" ]; then
    echo "Validation failed: first user '${VS_FIRST_USER_NAME}' has no usable password hash"
    exit 1
  fi

  require_cmd perl
  if ! perl -e '
my ($plain, $shadow_hash) = @ARGV;
exit(crypt($plain, $shadow_hash) eq $shadow_hash ? 0 : 1);
' "${VS_FIRST_USER_PASS}" "${SHADOW_HASH}"
  then
    echo "Validation failed: first user password hash does not match VS_FIRST_USER_PASS"
    exit 1
  fi

  echo "=== Validation: /opt/VibeSensor exists ==="
  ls -la "${ROOT_MNT}/opt/VibeSensor" | head -n 20

  echo "=== Validation: nmcli + rfkill + bluetoothctl + sdptool + iw + dnsmasq + gpsd + usbmuxd binaries ==="
  ls -l "${ROOT_MNT}/usr/bin/nmcli" "${ROOT_MNT}${RFKILL_PATH}" "${ROOT_MNT}${BLUETOOTHCTL_PATH}" "${ROOT_MNT}${SDPTOOL_PATH}" "${ROOT_MNT}${IW_PATH}" "${ROOT_MNT}${DNSMASQ_PATH}" "${ROOT_MNT}${GPSD_PATH}" "${ROOT_MNT}${USBMUXD_PATH}"

  echo "=== Validation: usbmuxd service + udev rule ==="
  ls -l "${ROOT_MNT}/usr/lib/systemd/system/usbmuxd.service" "${ROOT_MNT}/usr/lib/udev/rules.d/39-usbmuxd.rules"

  echo "=== Validation: Bluetooth helper + sudoers ==="
  ls -l "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/vibesensor_obd_admin.py" "${ROOT_MNT}/etc/sudoers.d/vibesensor-update"
  sudo grep -n 'vibesensor_.*sudo\|vibesensor_obd_admin.py' "${ROOT_MNT}/etc/sudoers.d/vibesensor-update"

  echo "=== Validation: vibesensor systemd units ==="
  ls -la "${ROOT_MNT}/etc/systemd/system" | grep -i vibesensor || true

  echo "=== Validation: first user preconfigured, wizard disabled ==="
  grep -n "^${VS_FIRST_USER_NAME}:" "${ROOT_MNT}/etc/passwd"
  if [ -f "${ROOT_MNT}/etc/xdg/autostart/piwiz.desktop" ]; then
    echo "ERROR: piwiz.desktop present"
    exit 1
  else
    echo "OK: piwiz.desktop absent"
  fi

  echo "=== Validation: /etc/vibesensor ==="
  ls -la "${ROOT_MNT}/etc/vibesensor"

  echo "=== Validation: SSH auth configuration ==="
  cat "${ROOT_MNT}/etc/ssh/sshd_config.d/99-vibesensor-password-auth.conf"

  echo "=== Validation: /var/log/wifi or tmpfiles ==="
  if [ -d "${ROOT_MNT}/var/log/wifi" ]; then
    ls -ld "${ROOT_MNT}/var/log/wifi"
  fi
  if [ -f "${ROOT_MNT}/etc/tmpfiles.d/vibesensor-wifi.conf" ]; then
    cat "${ROOT_MNT}/etc/tmpfiles.d/vibesensor-wifi.conf"
  fi

  echo "=== Validation: NetworkManager conf.d drop-in ==="
  cat "${ROOT_MNT}/etc/NetworkManager/conf.d/99-vibesensor-dnsmasq.conf"

  echo "=== Validation: Python venv ==="
  ls -la "${ROOT_MNT}/opt/VibeSensor/apps/server/.venv/bin/python"* || true

  echo "=== Validation: embedded Python runtime ==="
  cat "${PYTHON_RUNTIME_INFO_PATH}"
  echo "validated_venv_python_version=${VALIDATED_IMAGE_PYTHON_VERSION}"
  echo "validated_supported_python_floor=>=${VALIDATED_IMAGE_PYTHON_FLOOR}"

  echo "=== Validation: OpenBLAS runtime ==="
  echo "${OPENBLAS_LIB}"

  echo "=== Validation: hotspot script has no apt-get ==="
  if grep -n "apt-get" "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/hotspot_nmcli.sh"; then
    echo "ERROR: found apt-get in hotspot script"
    exit 1
  else
    echo "OK: no apt-get found"
  fi

  echo "=== Validation: hotspot script references /var/log/wifi ==="
  grep -n "/var/log/wifi" "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/hotspot_nmcli.sh"

  cleanup_mounts
  trap - EXIT
}
