#!/bin/sh
# Optional archive source. Default Docker builds copy the pinned official OCI image.
set -eu

version=${XRAY_VERSION:-26.9.9}
arch=${TARGETARCH:-$(dpkg --print-architecture)}
cache=${XRAY_CACHE_DIR:-/var/cache/dbot-xray}
local_dir=${XRAY_LOCAL_DIR:-/tmp/dbot-xray-local}
destination=${XRAY_INSTALL_PATH:-/usr/local/bin/xray}
case "$version" in ''|*[!0-9.]*|.*) echo '[dbot-xray] Invalid release version.' >&2; exit 1 ;; esac
case "$arch" in
    amd64) asset=64 ;;
    arm64) asset=arm64-v8a ;;
    arm) asset=arm32-v7a ;;
    *) echo "[dbot-xray] Unsupported architecture: $arch" >&2; exit 1 ;;
esac
mkdir -p "$cache/$version" "$(dirname "$destination")"
work=$(mktemp -d "$cache/$version/.install-XXXXXX")
trap 'rm -rf "$work"' EXIT
archive="$cache/$version/Xray-linux-$asset.zip"
local_archive="$local_dir/$version/Xray-linux-$asset.zip"

install_archive() {
    unzip -tq "$1" >/dev/null 2>&1 || return 1
    unzip -p "$1" xray >"$work/xray" || return 1
    test -s "$work/xray" || return 1
    chmod 0755 "$work/xray" || return 1
    output=$(timeout 10 "$work/xray" version) || return 1
    case "$output" in
        "Xray $version "*|"Xray $version") ;;
        *) echo "[dbot-xray] Archive is not the expected Xray $version binary." >&2; return 1 ;;
    esac
    install -m 0755 "$work/xray" "$destination" || return 1
    printf '%s\n' "$output"
}

if [ -f "$local_archive" ]; then
    echo "[dbot-xray] Installing local archive: $version / $arch (no network)."
    install_archive "$local_archive" || { echo '[dbot-xray] Local archive is invalid or incompatible.' >&2; exit 1; }
    exit 0
fi
if [ -f "$archive" ]; then
    if install_archive "$archive"; then
        echo "[dbot-xray] Reused cached archive: $version / $arch (no download)."
        exit 0
    fi
    echo '[dbot-xray] Discarding invalid cached archive.' >&2
    rm -f "$archive"
fi

url="https://github.com/XTLS/Xray-core/releases/download/v$version/Xray-linux-$asset.zip"
attempt=1
while [ "$attempt" -le 2 ]; do
    echo "[dbot-xray] Download attempt $attempt/2: $version / $arch; maximum 60 seconds."
    if curl --fail --location --silent --show-error --retry 0 \
        --proto '=https' --proto-redir '=https' --max-redirs 5 \
        --connect-timeout 8 --max-time 60 --speed-limit 1024 --speed-time 15 \
        "$url" --output "$work/download.zip"; then
        if install_archive "$work/download.zip"; then
            mv "$work/download.zip" "$archive"
            exit 0
        fi
        echo '[dbot-xray] Downloaded archive failed validation.' >&2
    fi
    rm -f "$work/download.zip"
    if [ "$attempt" -lt 2 ]; then sleep 2; fi
    attempt=$((attempt + 1))
done
echo '[dbot-xray] Download failed. Use the default XRAY_SOURCE=image, or place the official ZIP in build/xray/VERSION/ and use XRAY_SOURCE=archive. Existing services were not stopped by this download step.' >&2
exit 1
