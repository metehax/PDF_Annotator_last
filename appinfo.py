"""Uygulama kimliği — sürüm, ad, yayıncı için TEK kaynak (arayüz, spec, kurucu buradan okur)."""
import os
import sys

APP_NAME = "PDF Annotator"
APP_TITLE = "PDF İşaretleme Aracı"          # pencere başlığında görünen Türkçe ad
VERSION = "1.0.0"
PUBLISHER = "PDF Annotator"
APP_ID = "{8E5C7A41-3B9D-4F26-A1C0-6D2B94E7F315}"   # sabit GUID: kurucu ve güncelleme aynısını kullanır
UPDATE_URL = ""                               # K3'te doldurulur
DESCRIPTION = "PDF ve resimler için işaretleme, düzenleme, OCR, filigran ve karşılaştırma aracı"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """Kaynak dosyaların (tessdata/, fonts/) bulunduğu klasör; PyInstaller'da paket içi `_internal`."""
    if frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def version_tuple():
    p = [int(x) for x in VERSION.split(".")[:4]]
    return tuple(p + [0] * (4 - len(p)))
