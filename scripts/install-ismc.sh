#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="$ROOT_DIR/vendor/ismc"
VERSION="v0.13.5"
ARCHIVE_URL="https://github.com/dkorunic/iSMC/releases/download/${VERSION}/iSMC_Darwin_all.tar.gz"
ARCHIVE_SHA256="c7e5472f16466dc2fbc8a9edf0264b920151efa7eb3851b58f64f2dee12d2d35"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/swiftbar-ismc.XXXXXX")"

cleanup() {
  rm -rf "$TMP_DIR"
}

trap cleanup EXIT

mkdir -p "$INSTALL_DIR"

echo "Downloading iSMC ${VERSION}..."
curl -L "$ARCHIVE_URL" -o "$TMP_DIR/iSMC_Darwin_all.tar.gz"

actual_sha256="$(shasum -a 256 "$TMP_DIR/iSMC_Darwin_all.tar.gz" | awk '{print $1}')"

if [[ "$actual_sha256" != "$ARCHIVE_SHA256" ]]; then
  echo "Checksum mismatch for iSMC archive." >&2
  echo "Expected: $ARCHIVE_SHA256" >&2
  echo "Actual:   $actual_sha256" >&2
  exit 1
fi

tar -xzf "$TMP_DIR/iSMC_Darwin_all.tar.gz" -C "$TMP_DIR"
install -m 0755 "$TMP_DIR/iSMC" "$INSTALL_DIR/iSMC"
printf '%s\n' "$VERSION" > "$INSTALL_DIR/version.txt"

echo "Installed iSMC ${VERSION} to $INSTALL_DIR/iSMC"
