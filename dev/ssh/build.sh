#!/bin/sh
# Reproducible host build; never opens a camera. Run on Linux/WSL.
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_dir=${1:?usage: build.sh BUILD_DIRECTORY OUTPUT_DIRECTORY}
output_dir=${2:?output directory required}
mkdir -p "$task_dir" "$output_dir"
task_dir=$(cd "$task_dir" && pwd)
output_dir=$(cd "$output_dir" && pwd)
cd "$task_dir"
release=dropbear-2025.89
archive=$release.tar.bz2
if [ ! -f "$archive" ]; then
    curl -fL --connect-timeout 20 --max-time 180 \
        "https://dropbear.nl/mirror/releases/$archive" -o "$archive.download"
    mv "$archive.download" "$archive"
fi
printf '%s  %s\n' 0d1f7ca711cfc336dc8a85e672cab9cfd8223a02fe2da0a4a7aeb58c9e113634 "$archive" | sha256sum -c -
if [ ! -d "$release" ]; then tar -xf "$archive"; fi
zig_path=${A7C2_SSH_ZIG:?set A7C2_SSH_ZIG to a Linux Zig 0.13.0 executable}
test "$("$zig_path" version)" = 0.13.0
printf '#!/bin/sh\nexec "%s" cc -target aarch64-linux-musl "$@"\n' "$zig_path" > "$task_dir/aarch64-cc"
chmod 755 "$task_dir/aarch64-cc"
mkdir -p build-aarch64
cd build-aarch64
"$task_dir/aarch64-cc" -Os -c "$source_dir/debug_account.c" -o "$task_dir/debug-account.o"
cat > localoptions.h <<'OPTIONS'
#define DROPBEAR_SVR_PASSWORD_AUTH 0
#define DROPBEAR_SVR_PAM_AUTH 0
#define DROPBEAR_SVR_PUBKEY_AUTH 1
#define DROPBEAR_SVR_LOCALTCPFWD 0
#define DROPBEAR_SVR_REMOTETCPFWD 0
#define DROPBEAR_SVR_LOCALSTREAMFWD 0
#define DROPBEAR_SVR_AGENTFWD 0
#define DROPBEAR_X11FWD 0
#define DROPBEAR_SFTPSERVER 0
#define DROPBEAR_REEXEC 0
#define DO_MOTD 0
#define DROPBEAR_DSS 0
#define DROPBEAR_DEFPORT "2222"
OPTIONS
CC="$task_dir/aarch64-cc" CFLAGS='-Os -Dgetpwnam=a7c2_debug_getpwnam -Dgetpwuid=a7c2_debug_getpwuid' \
    LDFLAGS="$task_dir/debug-account.o" \
    "$task_dir/$release/configure" --host=aarch64-linux-musl \
    --enable-static --disable-zlib --disable-syslog --disable-lastlog \
    --disable-utmp --disable-utmpx --disable-wtmp --disable-wtmpx \
    > configure.log 2>&1
make clean > clean.log 2>&1
make -j2 PROGRAMS='dropbear dropbearkey' > build.log 2>&1
cp dropbear dropbearkey localoptions.h "$output_dir/"
"$zig_path" objcopy --strip-all "$output_dir/dropbear" "$output_dir/dropbear.stripped"
"$zig_path" objcopy --strip-all "$output_dir/dropbearkey" "$output_dir/dropbearkey.stripped"
mv "$output_dir/dropbear.stripped" "$output_dir/dropbear"
mv "$output_dir/dropbearkey.stripped" "$output_dir/dropbearkey"
cp "$task_dir/$release/LICENSE" "$output_dir/dropbear-LICENSE.txt"
printf '%s\n' "$release" 'aarch64-linux-musl static; Zig 0.13.0' > "$output_dir/build-info.txt"
printf '%s\n' 'Process-local root account mapping: shell=/bin/sh; public-key only; no system account edits.' >> "$output_dir/build-info.txt"
cp "$source_dir/debug_account.c" "$output_dir/a7c2-debug-account.c"
sha256sum "$output_dir/dropbear" "$output_dir/dropbearkey"
