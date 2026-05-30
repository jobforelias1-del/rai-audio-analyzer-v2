# -*- mode: python ; coding: utf-8 -*-
#
# RAI Audio Analyzer v2 — PyInstaller spec for macOS .app
#
# USAGE (on a Mac, from the repo root):
#   bash build/build_macos.sh
# or manually:
#   pyinstaller build/RAIAudioAnalyzer.spec --noconfirm
#
# NOTE: This spec targets macOS only.  PyInstaller produces a .app for the
# OS on which it is run, so this must be built on a Mac.  Running it on Linux
# or Windows will NOT produce a valid macOS .app.
#
# GLOBALS injected by PyInstaller at spec-execution time (not importable via
# py_compile, but valid at runtime):
#   Analysis, EXE, COLLECT, BUNDLE, Tree, TOC, SPEC, specnm, ...
#
# The collect_data_files / collect_submodules helpers are imported here
# (before the PyInstaller globals are used) so that py_compile can check
# the import/syntax without needing PyInstaller installed.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

# ---------------------------------------------------------------------------
# 0. Repo-root path resolution
# ---------------------------------------------------------------------------
# PyInstaller resolves relative paths in a spec file relative to the SPEC
# file's own directory (build/), NOT the current working directory.  Every
# repo-root-relative path below is therefore joined onto _ROOT, computed from
# the SPEC global PyInstaller injects at spec-execution time.
import os as _dispatch_os
_HERE = _dispatch_os.path.dirname(_dispatch_os.path.abspath(SPEC))
_ROOT = _dispatch_os.path.dirname(_HERE)

# ---------------------------------------------------------------------------
# 1. Data files
# ---------------------------------------------------------------------------

# librosa ships YAML/JSON classifier data (e.g. genre_map.json) and numba
# caches; collect everything under its package tree.
librosa_datas = collect_data_files('librosa', include_py_files=False)

# librosa depends on audioread, resampy, and lazy_loader data blobs.
audioread_datas = collect_data_files('audioread', include_py_files=False)

# copy_metadata keeps the METADATA / dist-info directories that some packages
# (notably librosa and sklearn) query at runtime via importlib.metadata.
librosa_meta    = copy_metadata('librosa')
numpy_meta      = copy_metadata('numpy')
scipy_meta      = copy_metadata('scipy')
sklearn_meta    = copy_metadata('scikit-learn')  # llvmlite/numba may need it

# tkinterdnd2 ships a 'tkdnd' directory holding the tkdnd shared libraries for
# every platform (osx-x64, osx-arm64, linux-*, win-*).  Bundle ONLY the
# host-matching macOS subdirectory: Tcl's `package require tkdnd` (no version
# pinned) otherwise picks the highest version it finds — the wrong-arch osx-x64
# build (2.9.4 > arm64's 2.9.3) — and crashes at launch on Apple Silicon.  The
# Linux/Windows binaries are dead weight in a macOS .app regardless.
import tkinterdnd2 as _tkdnd2_mod
import os as _os
import platform as _dispatch_platform
_tkdnd2_dir = _os.path.dirname(_tkdnd2_mod.__file__)
_mac_arch = _dispatch_platform.machine()
_tkdnd_platform_dir = 'osx-arm64' if _mac_arch == 'arm64' else 'osx-x64'
tkdnd_datas = [
    (
        _os.path.join(_tkdnd2_dir, 'tkdnd', _tkdnd_platform_dir),
        f'tkinterdnd2/tkdnd/{_tkdnd_platform_dir}',
    ),
]

# Our own fingerprint profiles (bundled genre JSON files).
# The glob '*.json' ensures any file produced by fit_prior is included.
fingerprints_datas = [
    (_dispatch_os.path.join(_ROOT, 'rai_analyzer/fingerprints/*.json'), 'rai_analyzer/fingerprints'),
]

# Combine all data sources.
all_datas = (
    librosa_datas
    + audioread_datas
    + librosa_meta
    + numpy_meta
    + scipy_meta
    + sklearn_meta
    + tkdnd_datas
    + fingerprints_datas
)

# ---------------------------------------------------------------------------
# 2. Hidden imports
# ---------------------------------------------------------------------------
# PyInstaller's static analysis misses dynamic imports triggered by librosa,
# numba, scipy, sklearn, and soundfile.  We list the most common ones here.
# If you hit an ImportError inside the .app, add the missing module to this
# list and rebuild.

librosa_hidden   = collect_submodules('librosa')
sklearn_hidden   = collect_submodules('sklearn')
numba_hidden     = collect_submodules('numba')
llvmlite_hidden  = collect_submodules('llvmlite')

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
    # matplotlib (for waveform display in GUI)
    'matplotlib.backends.backend_tkagg',
    'matplotlib.backends.backend_agg',
    # tkinterdnd2
    'tkinterdnd2',
]

all_hidden = (
    librosa_hidden
    + sklearn_hidden
    + numba_hidden
    + llvmlite_hidden
    + extra_hidden
)

# ---------------------------------------------------------------------------
# 3. Analysis
# ---------------------------------------------------------------------------

a = Analysis(
    # Entry point: the GUI main() — the CLI can still be invoked from the
    # terminal via the raw interpreter, but the .app launches the GUI.
    [_dispatch_os.path.join(_ROOT, 'rai_analyzer/gui.py')],
    pathex=[_ROOT],
    binaries=[],
    datas=all_datas,
    hiddenimports=all_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Exclude modules we know are not needed; this reduces .app size.
    excludes=[
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
    upx=True,
    console=False,           # no terminal window — GUI app
    disable_windowed_traceback=False,
    argv_emulation=True,     # macOS: open(file) events forwarded to sys.argv
    target_arch=None,        # None = build for the host arch (arm64 on M-series)
    codesign_identity=None,  # overridden at signing time; see build_macos.sh
    entitlements_file=_dispatch_os.path.join(_ROOT, 'build/entitlements.plist'),
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
    upx=True,
    upx_exclude=[
        'vcruntime140.dll',   # Windows — harmless on macOS
        'libssl*',
        'libcrypto*',
    ],
    name='RAIAudioAnalyzer',
)

# ---------------------------------------------------------------------------
# 6. BUNDLE — the macOS .app
# ---------------------------------------------------------------------------

app = BUNDLE(
    coll,
    name='RAI Audio Analyzer.app',
    icon=_dispatch_os.path.join(_ROOT, 'build/RAIAudioAnalyzer.icns'),
    bundle_identifier='com.siliconclick.rai-audio-analyzer',
    info_plist={
        # Human-readable product name shown in Finder and the menu bar.
        'CFBundleName': 'RAI Audio Analyzer',
        'CFBundleDisplayName': 'RAI Audio Analyzer',
        'CFBundleVersion': '2.0.0',
        'CFBundleShortVersionString': '2.0.0',

        # The LSApplicationCategoryType governs App Store placement (unused for
        # direct distribution, but harmless to set).
        'LSApplicationCategoryType': 'public.app-category.music',

        # Required for a GUI app on Retina displays.
        'NSHighResolutionCapable': True,

        # Hide the "Opened from Internet" quarantine warning for files dragged
        # onto the app window (does NOT bypass Gatekeeper on first launch).
        'LSFileQuarantineEnabled': False,

        # Allow the app to open audio files from the Finder via drag/double-click.
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

        # Minimum macOS version.  10.15 (Catalina) is the earliest that ships
        # a Python capable of running this stack.
        'LSMinimumSystemVersion': '10.15',

        # Privacy usage strings — required if the app ever accesses the
        # microphone (not used in v2, but keeps the plist forward-compatible).
        'NSMicrophoneUsageDescription': 'RAI Audio Analyzer does not use the microphone.',
    },
)
