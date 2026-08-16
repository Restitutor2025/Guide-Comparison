# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


project_root = Path(SPECPATH).parent

analysis = Analysis(
    [str(project_root / "packaging" / "windows_launcher.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(project_root / "THIRD_PARTY_NOTICES.md"), ".")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="GuideComparison",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-packed executables are disproportionately flagged by heuristic AV
    # engines. The modest size saving is not worth the distribution risk.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(project_root / "packaging" / "windows_version_info.txt"),
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GuideComparison",
)
