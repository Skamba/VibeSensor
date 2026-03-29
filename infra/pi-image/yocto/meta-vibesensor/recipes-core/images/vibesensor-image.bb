SUMMARY = "Universal VibeSensor Raspberry Pi image"
LICENSE = "MIT"

inherit core-image extrausers

SRC_URI = "file://vibesensor-rootfs-finalize.sh"

IMAGE_FEATURES += "ssh-server-openssh"
IMAGE_INSTALL:append = " packagegroup-vibesensor vibesensor-bundle"
IMAGE_ROOTFS_EXTRA_SPACE = "524288"
EXTRA_USERS_PARAMS = "useradd -m -G dialout,video,audio -p '${VIBESENSOR_FIRST_USER_PASS_HASH}' ${VIBESENSOR_FIRST_USER_NAME};"

ROOTFS_POSTPROCESS_COMMAND += " vibesensor_finalize_rootfs; "

vibesensor_finalize_rootfs() {
    export IMAGE_ROOTFS='${IMAGE_ROOTFS}'
    export HOST_QEMU_AARCH64='${@bb.utils.which(d.getVar("PATH"), "qemu-aarch64-static") or ""}'
    export VIBESENSOR_SERVICE_USER='${VIBESENSOR_FIRST_USER_NAME}'
    ${WORKDIR}/vibesensor-rootfs-finalize.sh
}
