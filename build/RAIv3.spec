# -*- mode: python ; coding: utf-8 -*-
#
# RAI Audio Analyzer v3 — PyInstaller spec for the PySide6 macOS .app
#
# USAGE (on a Mac, from the repo root — the build script is the ONLY
# supported path because it stamps build provenance and smoke-tests):
#   bash build/build_macos_v3.sh
#
# Lineage: derived from build/RAIAudioAnalyzer.spec (v2, tkinter era).
# KEPT   — librosa/numba/llvmlite/audioread collects + importlib metadata,
#          fingerprint JSON datas, the _ROOT-from-SPEC path pattern.
# DROPPED — everything tkinter (tkdnd datas, tkinterdnd2, matplotlib
#          backends), sklearn collects/metadata (unused by the engine; it is
#          merely present in the venv as a transitive install), UPX, and
#          argv_emulation (v3 has no Apple-Events file-open path in M0, and
#          argv_emulation has a history of eating real argv on macOS).
#
# NOTE ON LINTING: PyInstaller injects globals (Analysis, EXE, BUNDLE, SPEC,
# ...) at spec-execution time, so this file cannot be *executed* outside
# pyinstaller. It parses as plain Python (ast/py_compile-clean); anything
# smarter has to wait for a real freeze run.

import os as _os
import sys as _sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

# ---------------------------------------------------------------------------
# 0. Repo-root path resolution
# ---------------------------------------------------------------------------
# PyInstaller resolves relative paths in a spec file relative to the SPEC
# file's own directory (build/), NOT the current working directory. Every
# repo-root-relative path below is therefore joined onto _ROOT, computed from
# the SPEC global PyInstaller injects at spec-execution time.
_HERE = _os.path.dirname(_os.path.abspath(SPEC))
_ROOT = _os.path.dirname(_HERE)

# collect_submodules() imports the target package in a helper process that
# inherits this sys.path — our own top-level packages live at the repo root,
# which is not otherwise guaranteed to be importable at spec-exec time.
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

# ---------------------------------------------------------------------------
# 1. Data files
# ---------------------------------------------------------------------------

# librosa ships YAML/JSON data blobs; audioread similarly. Collect their
# package trees wholesale (v2 pattern — proven in the shipped 2.0.0).
librosa_datas = collect_data_files('librosa', include_py_files=False)
audioread_datas = collect_data_files('audioread', include_py_files=False)

# copy_metadata keeps the dist-info directories some packages query at
# runtime via importlib.metadata (lazy_loader does this for librosa).
librosa_meta = copy_metadata('librosa')
numpy_meta = copy_metadata('numpy')
scipy_meta = copy_metadata('scipy')

# Our own bundled data: genre fingerprint profiles + the v3 theme (QSS,
# design tokens, IBM Plex fonts — tokens are law, the app refuses to
# improvise without them).
rai_datas = [
    (_os.path.join(_ROOT, 'rai_analyzer/fingerprints/*.json'), 'rai_analyzer/fingerprints'),
    (_os.path.join(_ROOT, 'rai_ui/theme/app.qss'), 'rai_ui/theme'),
    (_os.path.join(_ROOT, 'rai_ui/theme/rai.tokens.json'), 'rai_ui/theme'),
    (_os.path.join(_ROOT, 'rai_ui/resources/fonts/*'), 'rai_ui/resources/fonts'),
]

all_datas = (
    librosa_datas
    + audioread_datas
    + librosa_meta
    + numpy_meta
    + scipy_meta
    + rai_datas
)

# ---------------------------------------------------------------------------
# 2. Hidden imports
# ---------------------------------------------------------------------------
# PyInstaller's static analysis misses dynamic imports triggered by librosa,
# numba, scipy, and soundfile (v2 list, minus sklearn/matplotlib/tkinterdnd2).
# Our own packages are collected wholesale as cheap insurance against any
# lazy/function-level imports in the engine or UI.

librosa_hidden = collect_submodules('librosa')
numba_hidden = collect_submodules('numba')
llvmlite_hidden = collect_submodules('llvmlite')
rai_hidden = collect_submodules('rai_analyzer') + collect_submodules('rai_ui')

extra_hidden = [
    # soundfile loads its CFFI extension dynamically
    'soundfile',
    '_soundfile_data',
    'cffi',
    # scipy sub-packages loaded on demand
    'scipy.signal',
    'scipy.signal.windows',
    'scipy.signal._upfirdn_apply',
    'scipy.ndimage',
    'scipy.special',
    'scipy.fft',
    'scipy._lib.messagestream',
    # audioread backends
    'audioread.rawread',
    'audioread.maddec',
    'audioread.gstdec',
    'audioread.mediafoundation',
    # pyloudnorm
    'pyloudnorm',
    # Qt: the three modules the UI is allowed to touch in M0
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    # audio playback (hooks-contrib bundles the portaudio binary for this)
    'sounddevice',
    '_sounddevice_data',
]

all_hidden = (
    librosa_hidden
    + numba_hidden
    + llvmlite_hidden
    + rai_hidden
    + extra_hidden
)

# ---------------------------------------------------------------------------
# 3. Analysis
# ---------------------------------------------------------------------------

a = Analysis(
    [_os.path.join(_ROOT, 'build/rai_v3_entry.py')],
    pathex=[_ROOT],
    binaries=[],
    datas=all_datas,
    hiddenimports=all_hidden,
    hookspath=[],
    hooksconfig={},
    # Numba writes its JIT cache next to the owning source file by default —
    # inside the signed bundle. The hook redirects it to ~/Library/Caches
    # BEFORE any application import runs.
    runtime_hooks=[_os.path.join(_HERE, 'hooks/rthook_numba_cache.py')],
    excludes=[
        # The entire v2 GUI stack must stay out of the v3 bundle (the Tcl/Tk 9
        # poison documented in docs/ENVIRONMENT.md rode in through these).
        'tkinter',
        '_tkinter',
        'tkinterdnd2',
        'matplotlib',
        'PIL',
        # Installed in the venv as a transitive package but unused by the
        # engine; the build script's bloat assert enforces this exclusion.
        'sklearn',
        # Qt modules the M0 app must not ship. QtOpenGL / QtOpenGLWidgets /
        # QtSvg / QtDBus are deliberately NOT excluded: pyqtgraph and the
        # cocoa platform plugin reach for them.
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuickControls2',
        'PySide6.QtNetwork',
        'PySide6.QtSql',
        'PySide6.QtPdf',
        'PySide6.QtTest',
        'PySide6.QtPrintSupport',
        'PySide6.QtConcurrent',
        'PySide6.QtDesigner',
        'PySide6.QtHelp',
        # Dev tooling (v2 list)
        'IPython',
        'jupyter',
        'notebook',
        'sphinx',
        'pytest',
        'black',
        'mypy',
        'ruff',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# 4. EXE (the Unix executable inside the .app bundle)
# ---------------------------------------------------------------------------

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # binaries go into COLLECT, not the exe
    name='RAIAudioAnalyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,             # strip=True can break numba/llvmlite on macOS
    upx=False,               # UPX dropped in v3: zero benefit on signed macOS bundles
    console=False,           # no terminal window — GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,    # v3: real argv only (see header)
    target_arch='arm64',
    codesign_identity=None,  # ad-hoc re-sign happens in build_macos_v3.sh
    entitlements_file=_os.path.join(_ROOT, 'build/entitlements.plist'),
)

# ---------------------------------------------------------------------------
# 5. COLLECT (gathers all binaries / dylibs alongside the exe)
# ---------------------------------------------------------------------------

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='RAIAudioAnalyzer',
)

# ---------------------------------------------------------------------------
# 6. BUNDLE — the macOS .app
# ---------------------------------------------------------------------------

app = BUNDLE(
    coll,
    name='RAI Audio Analyzer.app',
    icon=_os.path.join(_ROOT, 'build/RAIAudioAnalyzer.icns'),
    bundle_identifier='com.siliconclick.rai-audio-analyzer',
    info_plist={
        'CFBundleName': 'RAI Audio Analyzer',
        'CFBundleDisplayName': 'RAI Audio Analyzer',
        # CFBundleVersion must be a period-separated number list; the
        # marketing string carries the milestone tag.
        'CFBundleVersion': '3.0.0',
        'CFBundleShortVersionString': '3.0.0-m0',

        'LSApplicationCategoryType': 'public.app-category.music',
        'NSHighResolutionCapable': True,

        # Qt 6.8+ officially supports macOS 13+; v2's 10.15 floor was a
        # tkinter-era claim.
        'LSMinimumSystemVersion': '13.0',

        # Allow the app to open audio files from the Finder.
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'Audio File',
                'CFBundleTypeRole': 'Viewer',
                'LSItemContentTypes': [
                    'public.audio',
                    'com.microsoft.waveform-audio',
                    'public.aiff-audio',
                ],
            }
        ],

        # Build provenance: replaced with the real commit hash by
        # build_macos_v3.sh (PlistBuddy) before signing. If you see the
        # placeholder in a shipped bundle, the build bypassed the script.
        'RAIBuildCommit': 'RAI_BUILD_COMMIT_PLACEHOLDER',

        # sounddevice only ever OPENS OUTPUT streams here, but keep the
        # usage string so a future input feature cannot crash on a missing
        # plist key.
        'NSMicrophoneUsageDescription': 'RAI Audio Analyzer does not use the microphone.',
    },
)
