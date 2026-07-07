#!/usr/bin/env bash
# build/smoke_frozen.sh — smoke-test the FROZEN v3 .app (not the source tree)
#
# WHY two probes (docs/ENVIRONMENT.md): the v2 SIGABRT only fired in a frozen,
# no-tty launch — terminal runs of the same stack passed. So:
#   Probe 1  exec the bundle's Mach-O directly (exit code + JSON visible)
#   Probe 2  `open -n` through LaunchServices (the real double-click path;
#            no exit code, so we poll for the JSON and diff crash reports)
#
# Runs standalone (bash build/smoke_frozen.sh) or as the last stage of
# build/build_macos_v3.sh. Exit 0 = both probes passed.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DIST_DIR="dist-v3"
APP="$DIST_DIR/RAI Audio Analyzer.app"
EXE="$APP/Contents/MacOS/RAIAudioAnalyzer"
JSON1="/tmp/rai_smoke1.json"
JSON2="/tmp/rai_smoke2.json"
CRASH_DIR="$HOME/Library/Logs/DiagnosticReports"
POLL_SECONDS=90
# Crash reports are written asynchronously by ReportCrash after process death.
CRASH_SETTLE_SECONDS=5

PYBIN="$ROOT/.venv-v3/bin/python"
[[ -x "$PYBIN" ]] || PYBIN="$(command -v python3)"

red()  { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }
info() { printf '==> %s\n' "$*"; }

[[ -d "$APP" ]] || { red "no bundle at $APP — run build/build_macos_v3.sh first"; exit 1; }
[[ -x "$EXE" ]] || { red "bundle executable missing: $EXE"; exit 1; }

HEAD_SHA="$(git rev-parse HEAD)"

# check_json <path> <require_dnd:0|1> — asserts the smoke JSON is healthy.
# commit must START WITH HEAD (a +dirty suffix is legal, a stale sha is not).
check_json() {
    "$PYBIN" - "$1" "$HEAD_SHA" "$2" <<'PYEOF'
import json, sys

path, head, require_dnd = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
data = json.load(open(path))
errs = []

commit = str(data.get("commit", ""))
if not commit.startswith(head):
    errs.append(f"commit {commit!r} does not match HEAD {head} (unstamped or stale build)")
if data.get("window_shown") is not True:
    errs.append("window_shown is not true")
if data.get("accepts_drops") is not True:
    errs.append("accepts_drops is not true")
if require_dnd and data.get("dnd_delivered") is not True:
    errs.append("dnd_delivered is not true (the v2 dead-DnD class)")
if data.get("analysis_ok") is not True:
    errs.append(f"analysis_ok is not true (error: {data.get('analysis_error')!r})")
bpm = data.get("bpm")
if not isinstance(bpm, (int, float)) or not 60.0 <= float(bpm) <= 200.0:
    errs.append(f"bpm not sane: {bpm!r}")

if errs:
    print(f"smoke JSON {path} FAILED:", file=sys.stderr)
    for e in errs:
        print(f"  - {e}", file=sys.stderr)
    sys.exit(1)
print(f"    json ok: bpm={bpm} ambiguous={data.get('ambiguous')} "
      f"seconds={data.get('seconds')} audio_ok={data.get('audio_ok')} qt={data.get('qt')}")
PYEOF
}

# ── Probe 1: direct exec ─────────────────────────────────────────────────────
probe1() {
    info "PROBE 1: direct exec of $EXE"
    rm -f "$JSON1"
    local rc=0
    "$EXE" --smoke --smoke-json "$JSON1" --smoke-audio || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        red "probe 1: smoke run exited $rc (2 = analysis timeout)"
        [[ -f "$JSON1" ]] && cat "$JSON1" >&2
        return 1
    fi
    [[ -f "$JSON1" ]] || { red "probe 1: exit 0 but no JSON at $JSON1"; return 1; }
    check_json "$JSON1" 1
}

# ── Probe 2: LaunchServices launch (the real double-click path) ─────────────
probe2() {
    info "PROBE 2: open -n via LaunchServices (crash-report diff)"
    local baseline after new_reports waited
    baseline="$(ls "$CRASH_DIR" 2>/dev/null | grep -i 'RAIAudioAnalyzer' || true)"
    rm -f "$JSON2"

    open -n "$APP" --args --smoke --smoke-json "$JSON2"

    waited=0
    while [[ ! -f "$JSON2" && "$waited" -lt "$POLL_SECONDS" ]]; do
        sleep 1
        waited=$((waited + 1))
    done
    if [[ ! -f "$JSON2" ]]; then
        red "probe 2: no JSON after ${POLL_SECONDS}s — app hung or died before reporting"
    else
        info "probe 2: JSON appeared after ${waited}s"
    fi

    sleep "$CRASH_SETTLE_SECONDS"
    after="$(ls "$CRASH_DIR" 2>/dev/null | grep -i 'RAIAudioAnalyzer' || true)"
    new_reports="$(comm -13 <(sort <<<"$baseline") <(sort <<<"$after") | grep -v '^$' || true)"
    if [[ -n "$new_reports" ]]; then
        red "probe 2: NEW crash report(s) — the v2 dead-on-arrival class:"
        printf '%s\n' "$new_reports" >&2
        return 1
    fi

    [[ -f "$JSON2" ]] || return 1
    check_json "$JSON2" 1
}

P1=FAIL
P2=FAIL
if probe1; then P1=PASS; fi
if probe2; then P2=PASS; fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━ FROZEN SMOKE SUMMARY ━━━━━━━━━━━━━━━━━━━━"
echo "  probe 1 (direct exec)      : $P1"
echo "  probe 2 (open -n + crash)  : $P2"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
[[ "$P1" == PASS && "$P2" == PASS ]] || exit 1
echo "  FROZEN SMOKE: PASS"
