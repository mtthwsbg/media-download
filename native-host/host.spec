# -*- mode: python ; coding: utf-8 -*-
#
# What goes into host.exe. Run it through make-release.py, not by hand.
#
# Everything the downloader imports has to be named here, because PyInstaller
# finds imports by reading the code and none of these are reachable that way:
# download/bundle/transcribe are imported from the project root rather than
# beside host.py, and both yt-dlp and gallery-dl pick their extractor for a
# site at runtime, by name. Miss one and the frozen build fails on exactly the
# site whose extractor didn't come along.
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['download', 'bundle', 'transcribe']
hiddenimports += collect_submodules('yt_dlp')
hiddenimports += collect_submodules('gallery_dl')


a = Analysis(
    ['host.py'],
    pathex=['..'],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Pillow's Tk bridge pulls in the whole of tkinter for nothing - we only
    # ever open, resize and save.
    excludes=['tkinter', 'PIL.ImageTk', 'PIL.ImageQt'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='host',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='host',
)
