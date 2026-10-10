#!/bin/bash -e

# VibeSensor runs headless: no HDMI display and no camera. Without the KMS
# display driver the 256 MB CMA pool shrinks to 64 MB, and gpu_mem=16 hands the
# rest of the GPU split to Linux (a Pi 3 A+ goes from ~425 MB to ~473 MB of
# usable RAM). camera_auto_detect=0 keeps the camera stack from loading and
# logging errors against the minimal GPU firmware.
# lib/image_validation.sh (assert_headless_boot_config) enforces this.
CONFIG_TXT="${ROOTFS_DIR}/boot/firmware/config.txt"

sed -i -E \
  -e 's/^(dtoverlay=vc4-(f)?kms-v3d.*)$/#\1/' \
  -e 's/^(max_framebuffers=.*)$/#\1/' \
  -e 's/^camera_auto_detect=1$/camera_auto_detect=0/' \
  "${CONFIG_TXT}"

cat >>"${CONFIG_TXT}" <<'EOF'

[all]
# VibeSensor is headless: give the GPU the 16 MB minimum (no HDMI, no camera).
gpu_mem=16
EOF
