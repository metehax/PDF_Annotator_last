"""
mw_common.py
============
MainWindow ve mixin'lerin ortak sabitleri (araç listesi, kısayollar, dosya süzgeçleri) ve küçük istisna sınıfı.
"""

from __future__ import annotations

import os

from pdf_engine import IMAGE_EXTS


CANVAS_TOP_INSET = 66      # araç kapsülü için çizim alanının üstünde bırakılan boşluk (px)
RECENT_MAX = 8
PALETTE_RECENT_MAX = 5

# Komut paleti eş anlamlıları: (başlıkta geçen küçük harfli parça, aranabilecek kelimeler)
PALETTE_KEYWORDS = (
    ("metin seç", "kopyala metin panoya yazı al seçme copy ocr"),
    ("tüm metni", "kopyala metin ocr yazı çıkar panoya"),
    ("gizle", "sansür karart sakla sil kvkk redact"),
    ("sansür", "gizle karart sakla kvkk redact"),
    ("bulanık", "blur mozaik gizle sansür"),
    ("farklı kaydet", "yeni dosya save as isim"),
    ("kopya olarak", "özgün korunur yedek kopya"),
    ("tümünü kaydet", "hepsi hepsini tüm sekmeler toplu"),
    ("otomatik kaydet", "autosave kendiliğinden üzerine yaz"),
    ("kaydet", "kayıt save yaz"),
    ("imza", "imzala signature el yazısı elektronik"),
    ("dijital", "pfx sertifika imzala doğrula"),
    ("damga", "kaşe mühür stamp"),
    ("tara", "tarayıcı scan telefon kamera fotoğraf"),
    ("ocr", "metin tanıma taranmış okuma"),
    ("filigran", "watermark damga yazı arka plan"),
    ("parola", "şifre kilit güvenlik koruma"),
    ("sıkıştır", "küçült boyut dosya"),
    ("birleştir", "merge ekle pdf"),
    ("böl", "ayır split sayfa parça"),
    ("kırp", "crop kes yakala ekran görüntüsü"),
    ("yazdır", "print yazıcı"),
    ("form", "doldur alan"),
    ("yorum", "not açıklama"),
    ("numara", "sayfa numarası bates"),
    ("döndür", "çevir rotate"),
    ("paylaş", "telefon qr gönder"),
    ("kvkk", "kişisel veri tc gizle karart"),
    ("karşılaştır", "fark compare"),
    ("word", "docx dönüştür"),
    ("excel", "xlsx tablo dönüştür"),
    ("tema", "karanlık gece koyu açık renk"),
    ("kalem", "çiz serbest ink"),
    ("fosforlu", "vurgula işaretle highlight"),
    ("resim", "görsel foto ekle image"),
)
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
    ("copytext", "Metin Seç", "text_select", "Alan sürükleyip metni kopyala (taranmışsa OCR otomatik)"),
    ("crop", "Kırp / Yakala", "crop", "Bir alanı görsel olarak yakala"),
    ("form", "Form Alanı", "form", "Doldurulabilir form alanı oluştur (metin, onay, liste, tarih…)"),
]

TOOL_NAMES = {t[0]: t[1] for t in TOOLS if t}

# Tek harfli araç kısayolları (yazı yazılan alanlarda devreye girmez)
TOOL_KEYS = {"select": "V", "text": "T", "edit": "E", "ink": "P", "highlight": "H", "line": "L",
             "rect": "R", "oval": "O", "redact": "X", "image": "I", "number": "N", "stamp": "S", "crop": "C",
             "blur": "B", "note": "M", "form": "F", "sign": "G", "copytext": "K"}

APP_ID = "PDFAnnotator.Belge"

class _OpenCancelled(Exception):
    """Kullanıcı parola sorusunu iptal etti."""


def short_tab_name(name: str, max_chars: int = 30) -> str:
    """Uzun dosya adını ortadan değil, başı + sonu (uzantı dahil) görünecek biçimde kısaltır: 'uzun_belge…son.pdf'."""
    if len(name) <= max_chars:
        return name
    stem, ext = os.path.splitext(name)
    tail = stem[-4:] if len(stem) > 8 else ""
    keep = max(4, max_chars - len(ext) - len(tail) - 1)
    return stem[:keep].rstrip() + "…" + tail + ext
