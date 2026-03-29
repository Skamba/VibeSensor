SUMMARY = "VibeSensor Raspberry Pi runtime package set"
LICENSE = "MIT"
PR = "r0"

inherit packagegroup

RDEPENDS:${PN} = " \
    bash \
    bzip2 \
    ca-certificates \
    coreutils \
    curl \
    dnsmasq \
    gpsd \
    iproute2 \
    iw \
    networkmanager \
    procps \
    psmisc \
    python3 \
    python3-core \
    python3-modules \
    python3-pip \
    python3-setuptools \
    python3-venv \
    python3-wheel \
    rfkill \
    shadow \
    sudo \
    usbmuxd \
    util-linux \
    wpa-supplicant \
"
