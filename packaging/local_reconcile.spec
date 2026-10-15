# Build output and workpath are supplied by build_windows.ps1.
from pathlib import Path
import os,sys
root=Path(SPECPATH).parent
a=Analysis([str(root/"packaging"/"entrypoint.py")],pathex=[str(root/"src")],
    binaries=[],datas=[(str(root/"src"/"local_reconcile"/"resources"),"local_reconcile/resources"),(str(root/"src"/"local_reconcile"/"ui"/"style.qss"),"local_reconcile/ui")],
    hiddenimports=["defusedxml"],hookspath=[],hooksconfig={},
    excludes=["tkinter","matplotlib","pandas","numpy","PySide6.QtQml","PySide6.QtQuick","PySide6.QtWebEngineCore","PySide6.QtWebEngineWidgets","PySide6.QtSql","PySide6.QtMultimedia","PySide6.QtTest"],
    noarchive=False,optimize=0)
sys.path.insert(0,str(root/"scripts"))
from packaging_policy import filter_windows_system_icu
a.binaries=filter_windows_system_icu(a.binaries)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name="LocalReconcile",debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=bool(os.environ.get("LOCAL_RECONCILE_CONSOLE")))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name="LocalReconcile")

