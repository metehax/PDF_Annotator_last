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
| `headfoot.py` | Sayfa numarası/üstbilgi/altbilgi/Bates motoru (`export_pdf(..., headfoot=cfg)`) |
| `forms.py` | AcroForm: `list_fields`, `set_value/apply_values/snapshot_values`, `reset_values`, `recalculate`, `add_field/field_spec/delete_field` |
| `digisign.py` | pyhanko: `sign_pdf` (artımlı; alan/yeni kutu/görünmez), `verify_pdf` → `SigReport`, `create_self_signed` |
| `workflow.py` | Görsel iş akışı çekirdeği (arayüzsüz): `STEP_TYPES` (ocr/rotate/watermark/headfoot/kvkk/compress/password/save), `Workflow`/`Step`, `WorkflowLibrary` (QSettings'te JSON şablon + hazır şablonlar), `run_file`/`run_batch`/`collect_files`, `BatchReport` |
| `textdiff.py` | Metin farkı çekirdeği (arayüzsüz): `compare(pdf_a, pdf_b, ignore_case, check, progress)` → `DiffResult` (`Change`: kind add/del/mod, `a_rects`/`b_rects` sayfa pt + görünen yön, `focus_a/focus_b`, `page`), `extract_lines` |
| `convert.py` | PDF→Word/Excel çekirdeği (arayüzsüz): `to_docx(bytes, out, pages, cancelled)` (pdf2docx), `find_tables` + `write_xlsx` + `to_xlsx(..., numbers, decimal)` (PyMuPDF `find_tables` + openpyxl), `parse_number`; hata `ConvertError`, iptal `Cancelled`, sonuç `ConvertResult` |
| `a11y.py` | Erişilebilirlik çekirdeği (arayüzsüz): `audit(doc, path, cancelled)` → `A11yReport` (`Check`: key/status pass·warn·fail·info/`fix`/`data`), `apply_fixes(doc, ['lang','title','bookmarks'], ...)`, `ocr_replace_pages`, `detect_headings`, `report_text/html` |
| `ocr.py`, `fonts.py`, `gizmo.py` | OCR (Tesseract, `tessdata/`), yazı tipleri, boyutlandırma kulpları |
| `ui/theme.py` | Renk belirteçleri (`current()`, `qcolor()`), QSS — yeni objectName stillerini buraya ekle |
| `ui/icons.py` | Kendi SVG ikon seti: `icon(name, role)`; yeni ikon = `_PATHS`'e 24×24 çizgi SVG |
| `ui/*.py` | overlays, sidepanel, welcome, toast, palette, kvkk, stamps, docdialogs, widgets, pagetools (üstbilgi/Bates + sayfa kırpma), comments (Yorumlar paneli + `ask_note_text`), signatures (`SignatureLibrary`, imza/dijital imza/rapor pencereleri), formui (Formlar paneli, `FormFieldDialog`, satır içi `FormFieldEditor`), workflow (`WorkflowDialog`: palet + sürüklenebilir zincir + `ParamForm` + şablon + hedef + ilerleme/rapor), compare (`CompareDiffPanel`: sayfa sayfa değişiklik listesi + süzgeç + önceki/sonraki), convert (`ConvertDialog` + `BackgroundJob`: `job(progress, cancelled)` havuzda, `done/failed` sinyali), a11y (`A11yDialog`: rapor + tek tıkla düzelt) |

## Kurallar
- Yeni eylem: `_build_menus()` içinde `A(menu, ikon, "Metin", slot, "Kısayol")` — komut paletine (Ctrl+K) otomatik girer.
- Yeni araç: `TOOLS` + `TOOL_KEYS` + `_build_properties_stack()` sayfası (+ gerekiyorsa `PDFView` sinyali).
- İşaret değişikliği her zaman `session.undo_stack.push(...Command)`; çoklu değişiklik `beginMacro/endMacro`.
- Sayfa yapısı değişince `pdf._invalidate()` ve `self._mark_dirty()`.
- Bilgi mesajları `self.toasts.show(...)`; yalnızca hatalar `QMessageBox`.
- Uzun işler arka planda (`_OcrTask`), arayüz donmaz.
- Sayfa kırpma `PDFDocument.crop_page` (CropBox; döndürme + önceki kırpma dikkate alınır) ve `CropPagesCommand` ile; işaretler kaydırılır.
- Bulanıklaştırma dışa aktarımda `_annotated_copy` içinde: önce görüntü hazırlanır, alttaki içerik redact edilir, görüntü eklenir (döndürülmüş sayfa için derotation şart).
- Diyalog içeren akışlar için test betiğinde `mw.ask_note_text` gibi yardımcıları sahte fonksiyonla değiştir (exec bloklar).
- Form alanları işaret DEĞİL, doğrudan `pdf.doc` içinde yaşar. Değer: `FormValuesCommand` (ada göre),
  yapı: `FormFieldCommand(eski_spec, yeni_spec)`; parçacık kimliği `/NM` (xref yeniden oluşturmada değişir).
  Sonra `_forms_changed(pages)` sayfaları geçersiz kılar ve `_refresh_forms()` paneli/vurguyu tazeler.
- PyMuPDF 1.28 tuzakları: yeni radyo `field_value=False` ile eklenmeli ve ortak üst alana `forms._join_radio_group`
  bağlar; `add_widget` sonrası xref sayfadan geri okunur; boş metin değeri ve Türkçe harfler için görünüm akışını
  `forms._write_text_ap` yazar (cp1254 kodlamalı /PaTr Helvetica, AcroForm/DR'de).
- Tarih = `AFDate_FormatEx` betikli metin, hesaplanan = `AFSimple_Calculate` betikli salt okunur metin (Acrobat uyumlu).
- İmza: elektronik imza = `ImageAnnotation(source_path="sign:")`; imza alanı = forms türü `signature`.
  Testte `mw.ask_signature`, `mw.ask_digital_sign`, `mw.show_report` sahtelenir; `w.sig_lib.settings` da
  geçici ayara bağlanıp `load()` çağrılır. Değişmemiş PDF özgün dosyadan artımlı, değilse geçici dışa aktarımdan imzalanır.
- Testte özellik penceresi yerine `mw.ask_form_field` sahte fonksiyonla; yazdırma `mw.print_to(QPrinter PdfFormat)`.
- İş akışı: yeni adım = `workflow.STEP_TYPES`'a `StepType` (+`Param` şeması; arayüz formu şemadan üretilir, ayrıca arayüz kodu gerekmez) ve `STEP_ORDER`'a anahtar. Sayfaları değiştiren adım `_PAGE`, kaydederken uygulanan `_FINAL` (sona alınır). Adım `StepError` fırlatırsa dosya 'hata' olur, toplu iş sürer; uzun döngülerde `ctx.check()` + `ctx.inner(oran, ileti)` çağır (durdurma/ilerleme).
- İş akışı çıktısı geçici dosya + `os.replace`; Windows'ta açık dosyanın üstüne taşınmaz → özgün belge `save` öncesi kapatılır. Açık belge `Source(protect_original=True)` ile işlenir (işaretli kopya bayt olarak), üstüne yazma kapalıdır.
- Parola adımında `ask=True` iken parola şablona/ayara yazılmaz; `run_batch(..., overrides={'user_password': ...})` ile gelir. Testte `dlg.ask_passwords`, `dlg.ask_name` sahtelenir (exec bloklar).
- Görünür bir pencereye sonradan eklenen widget'a `show()` çağır (aksi halde panel boş kalır; `ParamForm` böyle yakalandı).
- Metin farkı: `MainWindow._run_diff` `_OcrTask` ile arka planda `textdiff.compare` çalıştırır; `_diff_token` bayat sonucu eler, sol/sağ combo ya da "harf yoksay" değişince `_schedule_diff` (350 ms) yeniden hesaplar. Vurgu `ComparePane.set_marks({sayfa: [(x0,y0,x1,y1,"add"|"del")]})`, listeden gitme `ComparePane.goto(sayfa, rect)` (odak halkası). Konumlar `page.rotation_matrix` ile görünen yöne çevrilir; birleştirme yalnızca aynı satırdaki kelimeleri kapsar. Testte iki belge `w.open_paths([a, b])` + `w.compare_documents()`, sonucu `w._diff is not None` ile bekle.
- Word/Excel: dönüştürme `s.pdf._annotated_copy(...).write()` baytlarıyla `BackgroundJob`'da çalışır, ana belgeye dokunmaz. Excel yalnızca çizgili/algılanabilir tabloları alır; `numbers` yalnız 2. satırdan itibaren sayıya çevirir (1. satır başlık), `decimal` TR=`,` varsayılan. Yeni dönüştürme biçimi = `convert.py`'ye işlev + `ConvertDialog`'a seçenek.
- Erişilebilirlik: yeni kontrol = `a11y.audit`'e `rep.checks.append(Check(...))`; düzeltilebiliyorsa `fix=<anahtar>` + `apply_fixes` dalı + `FIX_LABEL` + `A11yDialog.chk`. Denetim `ocr.open_snapshot` kopyasında çalışır; düzeltmeler `pdf.doc`'a doğrudan yazılır (geri alınmaz) ve `changed()` (`_invalidate` + `_mark_dirty` + küçük resim/İçindekiler yenileme) çağrılır. OCR düzeltmesi sayfayı `new_page` + `show_pdf_page` ile değiştirir (boyut sabit, sayfa sayısı aynı). `QTreeWidget` satır kaydırması için `setTextElideMode(ElideNone)` + yatay kaydırma kapalı gerekir. Testte iletişim kutularını `exec()` ile değil doğrudan oluşturup `pump` ile bekle; dosya diyaloglarını `QFileDialog.getSaveFileName` sahtesiyle değiştir.
- Heredoc ile `'''` içeren betik yazma (araç ayrıştırması bozuluyor): betiği Write ile dosyaya yaz, sonra çalıştır.

## Test
- Testler repoda değil; geçici betikle: `QT_QPA_PLATFORM=windows .venv/Scripts/python test.py`.
- Pencereyi oluşturduktan hemen sonra `w.settings = QSettings(<geçici>.ini, IniFormat)` ve
  `w.stamp_lib.settings = w.settings` (+ `w.sig_lib`) — yoksa kullanıcının gerçek ayarları (son açılanlar) kirlenir.
- Lint: `pip install pyflakes` → `python -m pyflakes ...` → işi bitince `pip uninstall -y pyflakes`.
- Ekran görüntüsünü yalnızca aşama sonunda bir kez al (maliyet).
- `.venv` başka bilgisayardan (OneDrive) gelmişse çalışmaz (pyvenv.cfg başka kullanıcı yolu): repoya dokunmadan geçici klasörde `py -3.12 -m venv` + `pip install -r requirements.txt pyflakes` ile test ortamı kur. Çıktı borulanırsa `python -u` kullan (`os._exit` tamponu yutar).

## Yol haritası (kalan)
B tamam (sayfa no/üstbilgi/Bates, sayfa kırpma, bulanıklaştırma, yapışkan not + yorumlar) ·
C1 tamam (form doldurma/sıfırlama/oluşturma, hesaplanan alan, Ctrl+P yazdırma) ·
C2 tamam (elektronik imza + kütüphane, imza alanı, pyhanko dijital imza/doğrulama) · E tamam (görsel iş akışı: adım zinciri + şablon + açık belge/dosyalar/klasör, ilerleme/durdurma/rapor) ·
D1 tamam (iki sürümün metin farkı: yeşil/kırmızı vurgu, sayfa sayfa liste, listeden git) ·
D2 tamam (Word/Excel dönüştürme, erişilebilirlik denetimi + tek tıkla düzeltme; pdf2docx ve openpyxl `requirements.txt`'te) ·
F: QR ile telefondan dosya alma (yerel ağ, segno). Onaylı yeni paket: segno (`requirements.txt`'e ekle).
