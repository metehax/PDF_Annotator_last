# -*- mode: python ; coding: utf-8 -*-
# PyInstaller (onedir): pyinstaller --noconfirm pdfannotator.spec  →  dist\PDF Annotator\
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo)

HERE = os.path.abspath(SPECPATH)            # packaging/
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
import appinfo

v = appinfo.version_tuple()
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=v, prodvers=v, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
    kids=[
        StringFileInfo([StringTable("041f04b0", [
            StringStruct("CompanyName", appinfo.PUBLISHER),
            StringStruct("FileDescription", appinfo.APP_TITLE),
            StringStruct("FileVersion", appinfo.VERSION),
            StringStruct("InternalName", appinfo.APP_NAME),
            StringStruct("OriginalFilename", appinfo.APP_NAME + ".exe"),
            StringStruct("ProductName", appinfo.APP_NAME),
            StringStruct("ProductVersion", appinfo.VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x041F, 1200])]),
    ])

datas = [
    (os.path.join(ROOT, "resources", "tessdata"), "tessdata"),
    (os.path.join(ROOT, "resources", "fonts"), "fonts"),
]
datas += collect_data_files("pdf2docx")
datas += collect_data_files("pyhanko")
datas += collect_data_files("pyhanko_certvalidator")
datas += collect_data_files("segno")
datas += collect_data_files("openpyxl")

# serbest iş parçacıklı/abi3t Python'da eklentiler (cryptography _rust vb.) python3t.dll ister; PyInstaller bulmaz
binaries = []
for _n in ("python3t.dll",):
    _p = os.path.join(sys.base_prefix, _n)
    if os.path.exists(_p):
        binaries.append((_p, "."))

hiddenimports = ["pdf2docx", "pyhanko", "segno", "openpyxl", "cv2", "pymupdf", "fitz", "numpy", "PIL",
                 "PySide6.QtSvg", "PySide6.QtPrintSupport", "PySide6.QtNetwork"]
for pkg in ("pyhanko", "pyhanko_certvalidator", "pdf2docx", "openpyxl", "segno"):
    hiddenimports += collect_submodules(pkg)
# uygulama modülleri açıkça içe aktarılmayanlar (ör. selftest) de gelsin
hiddenimports += ["selftest", "appinfo"] + collect_submodules("ui")

excludes = ["pymupdf.layout", "pymupdf4llm", "onnxruntime", "tkinter", "matplotlib", "pytest", "_pytest", "pyflakes", "IPython", "notebook", "unittest",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
            "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization"]

a = Analysis([os.path.join(SRC, "main_window.py")], pathex=[SRC], binaries=binaries, hookspath=[os.path.join(HERE, "pyi_hooks")], datas=datas, hiddenimports=hiddenimports,
             excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=appinfo.APP_NAME, console=False,
          icon=os.path.join(HERE, "app.ico"), version=version_info, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=appinfo.APP_NAME)
