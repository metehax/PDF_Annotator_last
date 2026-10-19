"""Uygulama kimliği — sürüm, ad, yayıncı için TEK kaynak (arayüz, spec, kurucu buradan okur)."""
import os
import sys

APP_NAME = "PDF Annotator"
APP_TITLE = "PDF İşaretleme Aracı"          # pencere başlığında görünen Türkçe ad
VERSION = "1.1.0"
PUBLISHER = "PDF Annotator"
APP_ID = "{8E5C7A41-3B9D-4F26-A1C0-6D2B94E7F315}"   # sabit GUID: kurucu ve güncelleme aynısını kullanır
UPDATE_URL = "https://api.github.com/repos/metehax/PDF_Annotator_last/releases/latest"   # herkese açık depo gerekir
DESCRIPTION = "PDF ve resimler için işaretleme, düzenleme, OCR, filigran ve karşılaştırma aracı"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """Kaynak klasörü (`src/`); PyInstaller'da paket içi `_internal`."""
    if frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir() -> str:
    """`tessdata/` ve `fonts/` klasörlerinin üst klasörü: kaynakta `<depo>/resources`, PyInstaller'da `_internal`."""
    if frozen():
        return app_dir()
    return os.path.join(os.path.dirname(app_dir()), "resources")


def version_tuple():
    p = [int(x) for x in VERSION.split(".")[:4]]
    return tuple(p + [0] * (4 - len(p)))
