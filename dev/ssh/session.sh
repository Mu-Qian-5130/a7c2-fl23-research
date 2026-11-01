#!/bin/sh
# One RAM-only session. No startup edits, remounts, Wi-Fi changes or firmware writes.
set -eu
session=${1:?session path required}
case "$session" in /tmp_wbshd/a7c2-ssh-????????????????) ;; *) exit 64;; esac
cd "$session"
umask 077
case "${2:-}" in
start)
    test "$(/bin/busybox uname -m)" = aarch64 || exit 65
    test ! -e started || exit 66
    test -s hostkey && test -s authorized_keys && test -x dropbear
    # -F retains this private working directory. Relative -D uses its root-owned
    # 0700 directory without requiring changes to the parent tmpfs permissions.
    # A marker prevents a lost acknowledgement from causing a second launch.
    : > started
    exec ./dropbear -F -p "${3:?IPv4 bind address required}:2222" \
        -r "$session/hostkey" -D . -P "$session/dropbear.pid" \
        -K 30 -I 600
    ;;
*) exit 64;;
esac
