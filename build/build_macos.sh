#!/usr/bin/env bash
# build/build_macos.sh — Build RAI Audio Analyzer v2 as a macOS .app
#
# Run this script from the repository root on a Mac:
#
#   bash build/build_macos.sh
#
# The finished .app lands in dist/RAI\ Audio\ Analyzer.app and can be
# drag-installed into /Applications.
#
# Requirements:
#   • macOS 10.15+ (Catalina or later)
#   • Python 3.10+ on PATH  (python3)
#   • Internet access for the initial pip install
#
# ─────────────────────────────────────────────────────────────────────────────
# GATEKEEPER / CODESIGNING NOTES
# ─────────────────────────────────────────────────────────────────────────────
# macOS Gatekeeper blocks un-notarized apps from running.  There are two
# practical options for direct distribution (no App Store):
#
# Option A — Ad-hoc signing (free; works on your own Mac and for trusted
#             recipients who follow the "right-click → Open" workaround):
#
#   codesign --force --deep --sign - "dist/RAI Audio Analyzer.app"
#
#   This script applies ad-hoc signing automatically after the PyInstaller
#   build.  Recipients need to right-click → Open on FIRST LAUNCH to dismiss
#   the "unidentified developer" alert; subsequent launches work normally.
#   xattr -cr is run first to strip the quarantine bit from all bundled files.
#
# Option B — Full Developer ID notarization (required for mass distribution;
#             allows double-click on any Mac without the workaround):
#
#   1.  Enrol in the Apple Developer Program ($99/year).
#   2.  Create a "Developer ID Application" certificate in Xcode / keychain.
#   3.  Sign with your identity:
#         codesign --force --deep --options runtime \
#                  --entitlements build/entitlements.plist \
#                  --sign "Developer ID Application: Your Name (TEAMID)" \
#                  "dist/RAI Audio Analyzer.app"
#   4.  Notarize:
#         xcrun notarytool submit "dist/RAI Audio Analyzer.zip" \
#                  --apple-id you@example.com \
#                  --team-id TEAMID --wait
#   5.  Staple:
#         xcrun stapler staple "dist/RAI Audio Analyzer.app"
#
#   build/entitlements.plist (included in this repo) grants the hardened-runtime
#   entitlements needed by numba's JIT compiler.  Pass it to codesign via
#   --entitlements when doing a real Developer-ID sign.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
VENV_DIR=".venv-build"
REQUIREMENTS="requirements.txt"
SPEC_FILE="build/RAIAudioAnalyzer.spec"
APP_NAME="RAI Audio Analyzer.app"
DIST_DIR="dist"
# ─────────────────────────────────────────────────────────────────────────────

# Ensure we are running from the repository root.
if [[ ! -f pyproject.toml ]]; then
    echo "ERROR: run this script from the repository root (where pyproject.toml lives)." >&2
    exit 1
fi

echo "==> Creating build virtual environment: ${VENV_DIR}"
python3 -m venv "${VENV_DIR}"

# Activate the venv for this shell.
# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"

echo "==> Upgrading pip / setuptools / wheel"
pip install --quiet --upgrade pip setuptools wheel

echo "==> Installing project requirements (${REQUIREMENTS})"
pip install --quiet -r "${REQUIREMENTS}"

# Ensure PyInstaller is present (requirements.txt includes it, but be explicit).
echo "==> Ensuring PyInstaller is installed"
pip install --quiet "pyinstaller>=6.0"

echo "==> Running PyInstaller"
pyinstaller "${SPEC_FILE}" --noconfirm

echo ""
echo "==> Stripping quarantine bits from bundled files (required before signing)"
xattr -cr "${DIST_DIR}/${APP_NAME}"

echo "==> Applying ad-hoc code signature (Option A — see script header for notarization)"
# '-' means ad-hoc identity (no certificate required).
# --deep recurses into all Frameworks and helpers inside the bundle.
codesign --force --deep --sign - "${DIST_DIR}/${APP_NAME}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  BUILD COMPLETE"
echo ""
echo "  App:  ${DIST_DIR}/${APP_NAME}"
echo ""
echo "  First-launch (ad-hoc signed):"
echo "    Right-click the .app → Open → Open in the Gatekeeper dialog."
echo "    Subsequent launches work with a normal double-click."
echo ""
echo "  For mass distribution without that workaround, see the"
echo "  'Option B — Full Developer ID notarization' notes in this script."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
