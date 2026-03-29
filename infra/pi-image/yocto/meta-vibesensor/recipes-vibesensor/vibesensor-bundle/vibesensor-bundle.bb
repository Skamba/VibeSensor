SUMMARY = "VibeSensor runtime tree, services, and prebuilt wheelhouse"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${EXTERNALSRC}/LICENSE;md5=27740f2316885c4337403671072ad5b5"

inherit externalsrc systemd

EXTERNALSRC = "${VIBESENSOR_SOURCE_TREE}"
S = "${EXTERNALSRC}"
B = "${WORKDIR}/build"

SYSTEMD_SERVICE:${PN} = "vibesensor.service vibesensor-hotspot.service vibesensor-hotspot-self-heal.timer vibesensor-rfkill-unblock.service vibesensor-ssh-hostkeys.service"
SYSTEMD_AUTO_ENABLE = "enable"

RDEPENDS:${PN} += " \
    bash \
    networkmanager \
    python3 \
    python3-pip \
    python3-venv \
    shadow \
    sudo \
"

FILES:${PN} += " \
    /etc/NetworkManager/conf.d \
    /etc/ssh/sshd_config.d \
    /etc/sudoers.d \
    /etc/systemd/system/sshd.service.d \
    /etc/tmpfiles.d \
    /etc/vibesensor \
    /opt/VibeSensor \
    /opt/vibesensor-artifacts \
    /usr/lib/systemd/system \
    /var/lib/vibesensor \
    /var/log/vibesensor \
    /var/log/wifi \
"

VIBESENSOR_SERVICE_USER ?= "${VIBESENSOR_FIRST_USER_NAME}"

python __anonymous() {
    for var in ("VIBESENSOR_SOURCE_TREE", "VIBESENSOR_WHEELHOUSE_DIR"):
        value = d.getVar(var)
        if not value:
            bb.fatal(f"{var} must be set before building vibesensor-bundle")
}

do_install() {
    install -d ${D}/opt/VibeSensor
    cp -a ${EXTERNALSRC}/. ${D}/opt/VibeSensor/

    install -d ${D}/opt/vibesensor-artifacts/wheels
    cp -a ${VIBESENSOR_WHEELHOUSE_DIR}/. ${D}/opt/vibesensor-artifacts/wheels/
    if [ -n "${VIBESENSOR_ARTIFACTS_MANIFEST}" ] && [ -f "${VIBESENSOR_ARTIFACTS_MANIFEST}" ]; then
        install -m 0644 ${VIBESENSOR_ARTIFACTS_MANIFEST} ${D}/opt/vibesensor-artifacts/build-manifest.json
    fi

    install -d ${D}/etc/vibesensor
    install -d ${D}/etc/tmpfiles.d
    install -d ${D}/etc/sudoers.d
    install -d ${D}/etc/NetworkManager/conf.d
    install -d ${D}/etc/ssh/sshd_config.d
    install -d ${D}/etc/systemd/system/sshd.service.d
    install -d ${D}${systemd_system_unitdir}
    install -d ${D}/var/lib/vibesensor/rollback
    install -d ${D}/var/lib/vibesensor/firmware
    install -d ${D}/var/log/vibesensor
    install -d ${D}/var/log/wifi

    if [ -d ${VIBESENSOR_FIRMWARE_CACHE_DIR}/baseline ]; then
        cp -a ${VIBESENSOR_FIRMWARE_CACHE_DIR}/baseline ${D}/var/lib/vibesensor/firmware/
    fi

    install -m 0644 ${S}/apps/server/config.pi.yaml ${D}/etc/vibesensor/config.yaml

    cat > ${D}/etc/tmpfiles.d/vibesensor-wifi.conf <<'TMPFILES_EOF'
d /var/log/wifi 0755 root root -
TMPFILES_EOF

    cat > ${D}/etc/NetworkManager/conf.d/99-vibesensor-dnsmasq.conf <<'NMCONF_EOF'
[main]
dns=dnsmasq
NMCONF_EOF

    cat > ${D}/etc/ssh/sshd_config.d/99-vibesensor-password-auth.conf <<'SSHCONF_EOF'
PasswordAuthentication yes
KbdInteractiveAuthentication no
UsePAM yes
SSHCONF_EOF

    printf '%s ALL=(root) NOPASSWD: /opt/VibeSensor/apps/server/scripts/vibesensor_update_sudo.sh\n' \
        '${VIBESENSOR_SERVICE_USER}' > ${D}/etc/sudoers.d/vibesensor-update
    chmod 0440 ${D}/etc/sudoers.d/vibesensor-update

    cat > ${D}/etc/systemd/system/sshd.service.d/10-vibesensor-hostkeys.conf <<'SSHD_DROPIN_EOF'
[Unit]
Wants=vibesensor-ssh-hostkeys.service
After=vibesensor-ssh-hostkeys.service
SSHD_DROPIN_EOF

    cat > ${D}${systemd_system_unitdir}/vibesensor-ssh-hostkeys.service <<'SSH_HOSTKEYS_EOF'
[Unit]
Description=Generate VibeSensor SSH host keys before sshd starts
DefaultDependencies=no
Before=sshd.service
ConditionPathExistsGlob=!/etc/ssh/ssh_host_*_key

[Service]
Type=oneshot
ExecStart=/usr/bin/ssh-keygen -A

[Install]
WantedBy=multi-user.target
SSH_HOSTKEYS_EOF

    sed \
        -e 's#__PI_DIR__#/opt/VibeSensor/apps/server#g' \
        -e 's#__VENV_DIR__#/opt/VibeSensor/apps/server/.venv#g' \
        -e 's#__SERVICE_USER__#${VIBESENSOR_SERVICE_USER}#g' \
        ${S}/apps/server/systemd/vibesensor.service > ${D}${systemd_system_unitdir}/vibesensor.service

    sed \
        -e 's#__PI_DIR__#/opt/VibeSensor/apps/server#g' \
        -e 's#__VENV_DIR__#/opt/VibeSensor/apps/server/.venv#g' \
        ${S}/apps/server/systemd/vibesensor-hotspot.service > ${D}${systemd_system_unitdir}/vibesensor-hotspot.service

    sed \
        -e 's#__VENV_DIR__#/opt/VibeSensor/apps/server/.venv#g' \
        ${S}/apps/server/systemd/vibesensor-hotspot-self-heal.service > ${D}${systemd_system_unitdir}/vibesensor-hotspot-self-heal.service

    install -m 0644 ${S}/apps/server/systemd/vibesensor-hotspot-self-heal.timer ${D}${systemd_system_unitdir}/vibesensor-hotspot-self-heal.timer
    install -m 0644 ${S}/apps/server/systemd/vibesensor-rfkill-unblock.service ${D}${systemd_system_unitdir}/vibesensor-rfkill-unblock.service
}
