# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

import PyQt6

# Obce katalogi PATH mogą zawierać niezgodne biblioteki o nazwach systemowych.
# Budowanie korzysta wyłącznie z bieżącego środowiska oraz bibliotek Windows.
if sys.platform == 'win32':
    windows = Path(os.environ['SystemRoot'])
    paths = [Path(PyQt6.__file__).parent / 'Qt6' / 'bin',
             Path(sys.executable).parent, Path(sys.base_prefix),
             windows / 'System32', windows]
    os.environ['PATH'] = os.pathsep.join(str(path) for path in paths)

a = Analysis(['run_emulator.py'], pathex=[], binaries=[], datas=[], hiddenimports=[],
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='OpenModbusSlaveEmulator',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
