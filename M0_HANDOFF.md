# M0 Handoff — Phase 3 Walking Skeleton (CLOSED · approved 2026-07-07)

**Branch:** `phase3/m0-walking-skeleton` @ `13434f5` — **LOCAL-ONLY, not merged, not pushed.**
Merging to `main` and pushing to GitHub happen only on Elias's explicit call.
Baseline underneath: `v3-baseline-phase0` (`399e775`). Engine bytes untouched since.

## Exit criteria — all PASS

| Criterion | Result |
|---|---|
| Frozen non-Tk .app launches on macOS 26.5 | ✅ both smoke probes, incl. `open -n` (the no-tty LaunchServices path that SIGABRT'd v2); zero new crash reports |
| Real drag-and-drop → full analysis in the frozen app | ✅ injected QDropEvent → 140.22 BPM on the synthetic drill WAV, honestly flagged ambiguous |
| Audio from the frozen bundle (decision D3 spike) | ✅ `audio_ok: true` via **sounddevice** — D3 confirmed, QtMultimedia stays excluded |
| Commit stamp integrity | ✅ smoke JSON `commit` == git HEAD (both probes) |
| Test matrix | ✅ v3 venv 346 passed (offscreen); engine venv 327 passed + 3 skipped (Qt modules skip cleanly → engine CI job unaffected) |
| Acceptance gate | ✅ `python -m validation` **byte-identical** to `docs/baselines/gate-reference-v3baseline.txt` |
| Engine untouched | ✅ all new code in `rai_ui/`, `tools/`, `build/`, `tests/ui/`; `rai_analyzer/` + `validation/` diff-empty vs baseline |
| Clean-tree, no-Homebrew build discipline | ✅ enforced by `build/build_macos_v3.sh` guards |

**The demo:** `dist-v3/RAI Audio Analyzer.app` (255 MB, arm64, ad-hoc signed — first launch: right-click → Open). Drop a WAV; the classic report renders under the real theme. Tempo/Overview/Signal/Compare are designed placeholders until M1/M2.

## Landmines (verified this milestone — treat as house rules)

1. **PySide6 6.11.1 / Python 3.14.5:** never `thread.finished.connect(worker.deleteLater)` — hard SIGSEGV (deferred delete inside the dying QThread). Workers are Python-owned; free at prune/close.
2. **Cross-thread signal connections:** functor/`lambda`/`partial` connections silently misdeliver across threads in this pairing. Use bound-method connections + `QMetaObject.invokeMethod(worker, "run", Qt.QueuedConnection, Q_ARG(...))` + `sender()._generation` gating (pattern lives in `rai_ui/services/worker.py` / `main_window.py`).
3. **uv interpreter resolution:** `uv venv --python 3.14` happily resolves to **Homebrew** Python. Always `--python-preference only-managed` (`.venv-v3` is correct; verify with `sys.base_prefix` — the build script asserts it).
4. **`QFontDatabase.addApplicationFont` silently fails on relative paths** — absolute paths only (handled in `rai_ui/theme/fonts.py`).
5. **numba in a signed .app:** cache dir is read-only → silent recompile every launch. `build/hooks/rthook_numba_cache.py` sets `NUMBA_CACHE_DIR` to `~/Library/Caches/RAIAudioAnalyzer`; first frozen analysis ~4 s (cold JIT), faster after.
6. **QSS realities:** `border-radius` > half box height is ignored (generator caps at 24 and computes pill radii); app-wide `QWidget { font-size }` outranks `QFont` (widget-level pins in nav/header are deliberate); heights are content-box (48px header renders 49px with its hairline — `setFixedHeight` where it matters).
7. **Theme drift gate:** edit `rai_ui/theme/rai.tokens.json` → run `.venv-v3/bin/python tools/gen_theme.py` → commit regenerated `_tokens_gen.py` + `app.qss`, or `test_theme.py` fails CI. Never hand-edit generated files.

## Environment quick reference

```bash
# dev app (unfrozen)
QT_QPA_PLATFORM=offscreen .venv-v3/bin/python -m rai_ui --smoke   # headless check
.venv-v3/bin/python -m rai_ui                                     # real window

# full matrix
QT_QPA_PLATFORM=offscreen .venv-v3/bin/python -m pytest tests/ -q  # 346 expected
.venv/bin/python -m pytest tests/ -q                               # 327 + 3 skipped
.venv/bin/python -m validation                                     # gate, byte-compare vs docs/baselines/

# freeze + both smoke probes (clean tree required)
bash build/build_macos_v3.sh
```

Lockfile: `requirements-v3.lock.txt` (uv-managed CPython 3.14.5 · PySide6-Essentials 6.11.1 · pyqtgraph 0.14.0 · sounddevice 0.5.5 · pyinstaller 6.20.0). Fonts vendored under `rai_ui/resources/fonts/` (OFL).

## Next milestone — M1: Tempo section (NOT started; do not start without Elias's go)

Scope per `~/Desktop/RAI v3 — Phase 3 Implementation Plan (2026-07-06).md` §4: pyqtgraph tempogram per component C-16 (band region, amber/violet markers, label-flip ≥72%, no legend ever), candidate table (QTableView + model + delegates, computed chips from `rai_ui/state/formatters.py`), persistent rail + bridge collapsed mode, verdict block with reasons, recents polish. Exit = v2 GUI functionally superseded on the Tempo lane; gate byte-identical; frozen smoke green.

**To begin:** Elias says **"start M1"** in a session with this repo. First command a fresh session should run:

```bash
cd ~/Projects/rai-audio-analyzer-v2 && git switch phase3/m0-walking-skeleton && git log --oneline -3 && QT_QPA_PLATFORM=offscreen .venv-v3/bin/python -m rai_ui --smoke
```

(expect: `13434f5` at HEAD, smoke exit 0 — then M1 work may begin on this branch or a new `phase3/m1-tempo` branched from it, per Elias's merge decision.)
