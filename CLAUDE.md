# PDF Annotator — çalışma notları

PySide6 + PyMuPDF masaüstü PDF/resim işaretleme aracı (Windows). Kullanıcı Türkçe konuşur;
**arayüz metinleri, yorumlar ve commit mesajları Türkçe**. Çerçeve değiştirilmez (PySide6 kalır).

## Yapı
| Dosya | Görev |
|---|---|
| `main_window.py` | `MainWindow`: menüler, üst çubuk, yüzen araç kapsülü + özellik çubuğu, sol panel, durum çubuğu, tüm eylemler |
| `views.py` | `PDFView` sürekli kaydırmalı görünüm (`PageItem`; işaretler sayfanın çocuk öğesi, koordinatlar sayfa pt), `ComparePane` |
| `models.py` | Annotation sınıfları + `QUndoCommand`'lar, `DocumentSession` |
| `pdf_engine.py` | `PDFDocument` (render, dışa aktarım `export_pdf(..., security, compress)`), filigran |
| `docsec.py` | Parola/izin, sıkıştırma, güvenlik taraması/temizliği, belge bilgileri |
| `pii.py` | KVKK kişisel veri bulucu |
| `ocr.py`, `fonts.py`, `gizmo.py` | OCR (Tesseract, `tessdata/`), yazı tipleri, boyutlandırma kulpları |
| `ui/theme.py` | Renk belirteçleri (`current()`, `qcolor()`), QSS — yeni objectName stillerini buraya ekle |
| `ui/icons.py` | Kendi SVG ikon seti: `icon(name, role)`; yeni ikon = `_PATHS`'e 24×24 çizgi SVG |
| `ui/*.py` | overlays, sidepanel, welcome, toast, palette, kvkk, stamps, docdialogs, widgets |

## Kurallar
- Yeni eylem: `_build_menus()` içinde `A(menu, ikon, "Metin", slot, "Kısayol")` — komut paletine (Ctrl+K) otomatik girer.
- Yeni araç: `TOOLS` + `TOOL_KEYS` + `_build_properties_stack()` sayfası (+ gerekiyorsa `PDFView` sinyali).
- İşaret değişikliği her zaman `session.undo_stack.push(...Command)`; çoklu değişiklik `beginMacro/endMacro`.
- Sayfa yapısı değişince `pdf._invalidate()` ve `self._mark_dirty()`.
- Bilgi mesajları `self.toasts.show(...)`; yalnızca hatalar `QMessageBox`.
- Uzun işler arka planda (`_OcrTask`), arayüz donmaz.

## Test
- Testler repoda değil; geçici betikle: `QT_QPA_PLATFORM=windows .venv/Scripts/python test.py`.
- Pencereyi oluşturduktan hemen sonra `w.settings = QSettings(<geçici>.ini, IniFormat)` ve
  `w.stamp_lib.settings = w.settings` — yoksa kullanıcının gerçek ayarları (son açılanlar) kirlenir.
- Lint: `pip install pyflakes` → `python -m pyflakes ...` → işi bitince `pip uninstall -y pyflakes`.
- Ekran görüntüsünü yalnızca aşama sonunda bir kez al (maliyet).

## Yol haritası (kalan)
B: sayfa numarası/üstbilgi/altbilgi/Bates, kırpma + bulanıklaştırma aracı, yapışkan notlar + yorum paneli ·
C: form doldurma/oluşturma, elektronik imza, dijital imza (pyhanko) · E: görsel iş akışı + toplu işlem ·
F: QR ile telefondan dosya alma (yerel ağ, segno) · D: sürüm karşılaştırma, Word/Excel (pdf2docx, openpyxl),
erişilebilirlik denetimi. Onaylı yeni paketler: segno, pyhanko, pdf2docx, openpyxl (`requirements.txt`'e ekle).
