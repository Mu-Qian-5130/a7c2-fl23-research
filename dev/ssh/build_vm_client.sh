#!/bin/sh
# Companion client for isolated firmware-VM loopback tests, not a camera installer.
set -eu
task_dir=${1:?usage: build_vm_client.sh EXISTING_BUILD_DIRECTORY OUTPUT_FILE}
output=${2:?output file required}
task_dir=$(cd "$task_dir" && pwd)
zig_path=${A7C2_SSH_ZIG:?set A7C2_SSH_ZIG to Linux Zig 0.13.0}
test "$("$zig_path" version)" = 0.13.0
printf '%s  %s\n' 0d1f7ca711cfc336dc8a85e672cab9cfd8223a02fe2da0a4a7aeb58c9e113634 \
    "$task_dir/dropbear-2025.89.tar.bz2" | sha256sum -c -
test -x "$task_dir/aarch64-cc"
mkdir -p "$task_dir/build-client-vm"
cd "$task_dir/build-client-vm"
cp "$task_dir/build-aarch64/localoptions.h" localoptions.h
CC="$task_dir/aarch64-cc" CFLAGS='-Os -Dgetpwnam=a7c2_debug_getpwnam -Dgetpwuid=a7c2_debug_getpwuid' \
    LDFLAGS="$task_dir/debug-account.o" \
    "$task_dir/dropbear-2025.89/configure" --host=aarch64-linux-musl \
    --enable-static --disable-zlib --disable-syslog --disable-lastlog \
    --disable-utmp --disable-utmpx --disable-wtmp --disable-wtmpx \
    > configure.log 2>&1
# PROGRAMS changes compilation flags for common objects. Reusing objects built
# for the server can produce a client that crashes before authentication.
make clean > clean.log 2>&1
make -j2 PROGRAMS=dbclient > build.log 2>&1
"$zig_path" objcopy --strip-all dbclient "$output"
sha256sum "$output"
