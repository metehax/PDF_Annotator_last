"""
mw_common.py
============
MainWindow ve mixin'lerin ortak sabitleri (araç listesi, kısayollar, dosya süzgeçleri) ve küçük istisna sınıfı.
"""

from __future__ import annotations

from pdf_engine import IMAGE_EXTS


CANVAS_TOP_INSET = 66      # araç kapsülü için çizim alanının üstünde bırakılan boşluk (px)
RECENT_MAX = 8
_IMG_PATTERNS = " ".join("*" + e for e in IMAGE_EXTS)
OPEN_FILTER = (f"PDF ve Resimler (*.pdf {_IMG_PATTERNS});;PDF (*.pdf);;"
               f"Resimler ({_IMG_PATTERNS})")

# (anahtar, ad, ikon, açıklama) — None: araç rayında ayraç
TOOLS = [
    ("select", "Seç", "select", "İşaretleri seç, taşı ve boyutlandır"),
    None,
    ("text", "Metin", "text", "Sayfaya yazı ekle"),
    ("edit", "Metin Düzenle", "edit_text", "Sayfadaki mevcut metni değiştir"),
    None,
    ("ink", "Kalem", "ink", "Serbest çizim"),
    ("highlight", "Fosforlu", "highlight", "Satırları vurgula"),
    ("line", "Çizgi / Ok", "line", "Çizgi ya da ok çiz"),
    ("rect", "Dörtgen", "rect", "Dörtgen çiz"),
    ("oval", "Oval", "oval", "Oval çiz"),
    None,
    ("redact", "Gizle (Sansür)", "redact", "Kaydedince altındaki metin ve resim PDF'ten KALICI silinir"),
    ("blur", "Bulanıklaştır", "blur", "Bir alanı bulanıklaştır ya da mozaikle (kalıcı)"),
    ("image", "Resim", "image", "Sayfaya resim yerleştir"),
    ("number", "Numarala", "number", "Sıra numarası koy"),
    ("stamp", "Damga", "stamp", "Hazır ya da kendi damganızı basın"),
    ("sign", "İmza", "sign", "Kayıtlı elektronik imzanızı tek tıkla basın"),
    ("note", "Yapışkan Not", "note", "Sayfaya not ekle; Yorumlar panelinde görünür"),
    ("crop", "Kırp / Yakala", "crop", "Bir alanı görsel olarak yakala"),
    ("form", "Form Alanı", "form", "Doldurulabilir form alanı oluştur (metin, onay, liste, tarih…)"),
]

TOOL_NAMES = {t[0]: t[1] for t in TOOLS if t}

# Tek harfli araç kısayolları (yazı yazılan alanlarda devreye girmez)
TOOL_KEYS = {"select": "V", "text": "T", "edit": "E", "ink": "P", "highlight": "H", "line": "L",
             "rect": "R", "oval": "O", "redact": "X", "image": "I", "number": "N", "stamp": "S", "crop": "C",
             "blur": "B", "note": "M", "form": "F", "sign": "G"}

APP_ID = "PDFAnnotator.Belge"

class _OpenCancelled(Exception):
    """Kullanıcı parola sorusunu iptal etti."""
