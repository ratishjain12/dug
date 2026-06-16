#!/bin/sh
# dug installer — https://github.com/ratishjain12/dug
set -e

REPO="ratishjain12/dug"
BIN_DIR="${DUG_INSTALL_DIR:-/usr/local/bin}"

# --------------------------------------------------------------------------
# Detect OS and architecture
# --------------------------------------------------------------------------
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

case "$OS" in
  linux)  PLATFORM="linux" ;;
  darwin) PLATFORM="macos" ;;
  *)
    echo "Unsupported OS: $OS"
    echo "Install manually: pip install dug-cli"
    exit 1
    ;;
esac

case "$ARCH" in
  x86_64|amd64) ARCH_LABEL="amd64" ;;
  arm64|aarch64) ARCH_LABEL="arm64" ;;
  *)
    echo "Unsupported architecture: $ARCH"
    echo "Install manually: pip install dug-cli"
    exit 1
    ;;
esac

TARGET="${PLATFORM}-${ARCH_LABEL}"

# --------------------------------------------------------------------------
# Prefer pipx if Python is available (smaller download, always up to date)
# --------------------------------------------------------------------------
if command -v pipx >/dev/null 2>&1; then
  echo "Found pipx — installing dug-cli from PyPI..."
  pipx install dug-cli
  echo ""
  echo "✓ dug installed via pipx. Run: dug --help"
  exit 0
fi

if command -v pip3 >/dev/null 2>&1 || command -v pip >/dev/null 2>&1; then
  PIP=$(command -v pip3 || command -v pip)
  echo "Found pip — installing pipx then dug-cli..."
  $PIP install --user pipx
  python3 -m pipx install dug-cli
  echo ""
  echo "✓ dug installed. Run: dug --help"
  exit 0
fi

# --------------------------------------------------------------------------
# Fallback: download standalone binary from GitHub Releases
# --------------------------------------------------------------------------
LATEST=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
  | grep '"tag_name"' | sed 's/.*"tag_name": "\(.*\)".*/\1/')

if [ -z "$LATEST" ]; then
  echo "Could not determine latest release."
  echo "Visit: https://github.com/${REPO}/releases"
  exit 1
fi

BIN_URL="https://github.com/${REPO}/releases/download/${LATEST}/dug-${TARGET}"
TMP="$(mktemp)"

echo "Downloading dug ${LATEST} for ${TARGET}..."
curl -fsSL "$BIN_URL" -o "$TMP"
chmod +x "$TMP"

# Install to BIN_DIR (may need sudo)
if [ -w "$BIN_DIR" ]; then
  mv "$TMP" "${BIN_DIR}/dug"
else
  echo "Installing to ${BIN_DIR} (requires sudo)..."
  sudo mv "$TMP" "${BIN_DIR}/dug"
fi

echo ""
echo "✓ dug ${LATEST} installed to ${BIN_DIR}/dug"
echo "Run: dug --help"
