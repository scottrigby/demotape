#!/usr/bin/env bash
# One-time setup for the demo-recorder POC.
# Installs anything that the claudeman profile features don't already cover:
#   - ttyd + dejavu fonts (apt) for VHS rendering
#   - VHS binary from GitHub releases
#   - Python deps (piper-tts, playwright, pyyaml)
#   - Playwright Chromium browser (skipped if the playwright feature already did it)
set -euo pipefail

cd "$(dirname "$0")"

echo "==> apt deps (ttyd, fonts)"
sudo apt-get update
sudo apt-get install -y ttyd fonts-dejavu

echo "==> Python deps"
pip install -r requirements.txt

echo "==> Playwright Chromium"
playwright install chromium || true

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) VHS_ARCH="arm64" ;;
  x86_64)        VHS_ARCH="x86_64" ;;
  *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;;
esac

if ! command -v vhs >/dev/null 2>&1; then
  echo "==> Installing VHS (Linux $VHS_ARCH)"
  TMPDIR="$(mktemp -d)"
  curl -fsSL "https://github.com/charmbracelet/vhs/releases/latest/download/vhs_Linux_${VHS_ARCH}.tar.gz" \
    | tar xz -C "$TMPDIR"
  sudo install -m0755 "$TMPDIR"/vhs*/vhs /usr/local/bin/vhs
  rm -rf "$TMPDIR"
fi

echo "==> Versions"
vhs --version
ttyd --version | head -1
ffmpeg -version | head -1
python -c "import piper, playwright, yaml; print('piper, playwright, yaml: OK')"

echo "==> Setup complete."
