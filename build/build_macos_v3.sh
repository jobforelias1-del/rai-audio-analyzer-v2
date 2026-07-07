#!/usr/bin/env bash
# build/build_macos_v3.sh — Build RAI Audio Analyzer v3 (PySide6) as a macOS .app
#
# Usage, from anywhere (the script cd's to the repo root):
#   bash build/build_macos_v3.sh [--allow-dirty]
#
# WHY this script is strict (docs/ENVIRONMENT.md, the two 2026 incidents):
#   • Never freeze from Homebrew Python — the Tcl/Tk 9 poison class. v3 is
#     PySide6, but the "interpreter upgraded behind your back" failure mode
#     is interpreter-level, so the guard stays.
#   • Never freeze from a dirty tree — the bundle stamps its commit hash, and
#     a stamp that doesn't describe the bytes is worse than no stamp.
#   • Never trust a terminal run — the built .app itself is smoke-tested
#     (build/smoke_frozen.sh) or the build FAILS.
#
# Outputs: dist-v3/RAI Audio Analyzer.app   (work dir: build/RAIv3-work)
# Both paths are regenerable and must be gitignored.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV_PY="$ROOT/.venv-v3/bin/python"
PYINSTALLER="$ROOT/.venv-v3/bin/pyinstaller"
SPEC_FILE="build/RAIv3.spec"
DIST_DIR="dist-v3"
WORK_DIR="build/RAIv3-work"
BUILDINFO="rai_ui/_buildinfo.py"
APP_NAME="RAI Audio Analyzer.app"

red()   { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }
info()  { printf '==> %s\n' "$*"; }
die()   { red "ERROR: $*"; exit 1; }

# ── Flags ────────────────────────────────────────────────────────────────────
ALLOW_DIRTY=0
for arg in "$@"; do
    case "$arg" in
        --allow-dirty) ALLOW_DIRTY=1 ;;
        *) die "unknown argument: $arg (only --allow-dirty is supported)" ;;
    esac
done

# ── Environment guards ───────────────────────────────────────────────────────
[[ -x "$VENV_PY" ]] || die ".venv-v3 missing or broken ($VENV_PY not executable) — \
create the uv-managed v3 venv first (see requirements-v3.lock.txt)."
[[ -x "$PYINSTALLER" ]] || die "pyinstaller not installed in .venv-v3."

BASE_PREFIX="$("$VENV_PY" -c 'import sys; print(sys.base_prefix)')"
case "$BASE_PREFIX" in
    *[Hh]omebrew*|*Cellar*)
        die "refusing to build from a Homebrew-based interpreter ($BASE_PREFIX). \
Use the uv-managed .venv-v3 (docs/ENVIRONMENT.md: the one rule that matters)."
        ;;
esac

# ── Clean-tree guard + provenance ────────────────────────────────────────────
DIRTY_STATUS="$(git status --porcelain)"
DIRTY_SUFFIX=""
if [[ -n "$DIRTY_STATUS" ]]; then
    if [[ "$ALLOW_DIRTY" -eq 1 ]]; then
        red "╔══════════════════════════════════════════════════════════════╗"
        red "║  DIRTY-TREE BUILD (--allow-dirty)                            ║"
        red "║  The commit stamp will carry a +dirty marker. This bundle    ║"
        red "║  is NOT reproducible from the stamped commit. Do not ship.  ║"
        red "╚══════════════════════════════════════════════════════════════╝"
        DIRTY_SUFFIX="+dirty"
    else
        red "Working tree is not clean:"
        printf '%s\n' "$DIRTY_STATUS" >&2
        die "commit or stash first, or pass --allow-dirty for a local throwaway build."
    fi
fi

COMMIT="$(git rev-parse HEAD)${DIRTY_SUFFIX}"
TAG="$(git describe --tags --exact-match HEAD 2>/dev/null || true)"
BUILD_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# ── Stamp _buildinfo.py (restored afterwards, success or failure) ───────────
# Primary restore is git checkout (the dev stub is committed); the cp backup
# covers the not-yet-committed case so the tree is never left stamped.
BUILDINFO_BACKUP="$(mktemp)"
cp "$BUILDINFO" "$BUILDINFO_BACKUP"
restore_buildinfo() {
    git checkout --quiet -- "$BUILDINFO" 2>/dev/null \
        || cp "$BUILDINFO_BACKUP" "$BUILDINFO"
    rm -f "$BUILDINFO_BACKUP"
}
trap restore_buildinfo EXIT

info "Stamping $BUILDINFO  (commit=$COMMIT tag=${TAG:-<none>} utc=$BUILD_UTC)"
cat > "$BUILDINFO" <<EOF
"""Build provenance constants — MACHINE-STAMPED by build/build_macos_v3.sh.

If you are reading this in a checkout, a build crashed before restoring the
dev stub: run  git checkout -- rai_ui/_buildinfo.py
"""

from __future__ import annotations

COMMIT = "$COMMIT"
TAG = "$TAG"
BUILD_UTC = "$BUILD_UTC"
EOF

# ── Freeze ───────────────────────────────────────────────────────────────────
info "Running PyInstaller ($SPEC_FILE)"
"$PYINSTALLER" "$SPEC_FILE" --noconfirm --distpath "$DIST_DIR" --workpath "$WORK_DIR"

APP="$DIST_DIR/$APP_NAME"
[[ -d "$APP" ]] || die "expected bundle not found: $APP"

# ── Provenance into Info.plist ───────────────────────────────────────────────
PLIST="$APP/Contents/Info.plist"
info "Writing RAIBuildCommit=$COMMIT into Info.plist"
if ! /usr/libexec/PlistBuddy -c "Set :RAIBuildCommit $COMMIT" "$PLIST" 2>/dev/null; then
    /usr/libexec/PlistBuddy -c "Add :RAIBuildCommit string $COMMIT" "$PLIST"
fi

# ── Bloat assert ─────────────────────────────────────────────────────────────
# The excludes in the spec are only requests; hooks and transitive imports can
# smuggle frameworks back in. Fail the build rather than ship a 700 MB app.
info "Bloat assert (QtQml/QtQuick/QtWebEngine/qml/sklearn must be absent)"
BLOAT_HITS="$(find "$APP" \
    -name 'QtQml*' -print \
    -o -name 'QtQuick*' -print \
    -o -name 'QtWebEngine*' -print \
    -o -type d -name 'qml' -print \
    -o -name 'sklearn*' -print \
    -o -name 'scikit_learn*' -print \
    2>/dev/null || true)"
if [[ -n "$BLOAT_HITS" ]]; then
    red "Forbidden payload found inside $APP:"
    printf '%s\n' "$BLOAT_HITS" >&2
    die "bloat assert failed — fix the spec excludes before shipping."
fi

# ── Sign ─────────────────────────────────────────────────────────────────────
info "Stripping quarantine bits (xattr -cr)"
xattr -cr "$APP"

info "Ad-hoc codesigning with JIT entitlements (numba needs MAP_JIT)"
codesign --force --deep --sign - \
    --entitlements build/entitlements.plist \
    "$APP"

# ── Smoke-test the actual bundle ─────────────────────────────────────────────
# Non-negotiable: terminal runs of the same stack passed while the shipped v2
# .app was dead on arrival. The frozen bundle itself must prove it works.
info "Running frozen-app smoke test"
bash build/smoke_frozen.sh

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  BUILD + SMOKE COMPLETE"
echo ""
echo "  App:     $APP"
echo "  Commit:  $COMMIT"
echo "  Tag:     ${TAG:-<none>}"
echo "  Built:   $BUILD_UTC"
echo ""
echo "  First launch of an ad-hoc-signed app: right-click → Open."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
