#!/bin/bash -e

on_chroot << 'CHROOT_EOF'
set -e
rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /var/cache/apt/archives/partial/*
CHROOT_EOF
