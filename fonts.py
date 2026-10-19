"""Metin işaretleri için yazı tipi çözümleme.

Desteklenen aileler: Arial, Calibri, Times New Roman, Roboto.
Windows'ta ilk üçü C:\\Windows\\Fonts içinden bulunur; Roboto uygulamayla
birlikte gelen ``fonts/`` klasöründen yüklenir. Ekranda (Qt) ve PDF çıktısında
(PyMuPDF) aynı font dosyası kullanılır, böylece görüntü ile çıktı eşleşir.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

FONT_FAMILIES: List[str] = ["Arial", "Calibri", "Times New Roman", "Roboto"]
DEFAULT_FAMILY = "Arial"

from appinfo import app_dir

_APP_DIR = app_dir()
_BUNDLED_DIR = os.path.join(_APP_DIR, "fonts")
_WIN_DIRS = [
    r"C:\Windows\Fonts",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Fonts"),
]

# Aile -> (Windows dosya adları, diğer sistemlerdeki yedek yollar)
_CANDIDATES: Dict[str, List[str]] = {
    "Arial": [
        "arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ],
    "Calibri": [
        "calibri.ttf",
        "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    "Times New Roman": [
        "times.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/Library/Fonts/Times New Roman.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    ],
    "Roboto": [
        os.path.join(_BUNDLED_DIR, "Roboto-Regular.ttf"),
        "Roboto-Regular.ttf",
        "/usr/share/fonts/truetype/roboto/Roboto-Regular.ttf",
    ],
}

_cache: Dict[str, Optional[str]] = {}


def resolve_font_file(family: str) -> Optional[str]:
    """Verilen ailenin normal (regular) TTF dosya yolunu döner; yoksa None."""
    if family in _cache:
        return _cache[family]
    found: Optional[str] = None
    for cand in _CANDIDATES.get(family, []):
        paths = [cand] if os.path.isabs(cand) else [os.path.join(d, cand) for d in _WIN_DIRS if d]
        for p in paths:
            if os.path.isfile(p):
                found = p
                break
        if found:
            break
    _cache[family] = found
    return found


def pdf_font_ctx(family: str) -> Optional[Tuple[str, str]]:
    """PyMuPDF için ('benzersiz_ad', dosya_yolu) çifti; bulunamazsa None."""
    path = resolve_font_file(family)
    if not path:
        return None
    safe = "".join(ch for ch in family.lower() if ch.isalnum())
    return (f"pa_{safe}", path)


def register_app_fonts() -> None:
    """Uygulamayla gelen fontları Qt'ye tanıtır (QApplication oluştuktan sonra
    çağrılmalı). Roboto sistemde kurulu olmasa da ekranda doğru görünür."""
    try:
        from PySide6.QtGui import QFontDatabase
    except Exception:
        return
    if not os.path.isdir(_BUNDLED_DIR):
        return
    for name in sorted(os.listdir(_BUNDLED_DIR)):
        if name.lower().endswith((".ttf", ".otf")):
            QFontDatabase.addApplicationFont(os.path.join(_BUNDLED_DIR, name))
