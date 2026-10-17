# PDF Annotator — çalışma notları

PySide6 + PyMuPDF masaüstü PDF/resim işaretleme aracı (Windows). Kullanıcı Türkçe konuşur;
**arayüz metinleri, yorumlar ve commit mesajları Türkçe**. Çerçeve değiştirilmez (PySide6 kalır).

## Yapı
| Dosya | Görev |
|---|---|
| `main_window.py` | `MainWindow(…Mixin'ler, QMainWindow)`: yalnızca iskelet (~940 satır) — `__init__`/`_build_ui`, olay işleyicileri (`eventFilter`, `resizeEvent`, sürükle-bırak, `closeEvent`), oturum/sekme yönetimi, komut paleti, "birlikte aç" kaydı; ayrıca `main()` ve tek örnek (QLocalServer) işlevleri |
| `mw_common.py` | Ortak sabitler: `TOOLS`, `TOOL_NAMES`, `TOOL_KEYS`, `CANVAS_TOP_INSET`, `RECENT_MAX`, `OPEN_FILTER`, `APP_ID`, `_OpenCancelled` (mixin'ler `main_window`'dan değil buradan alır: döngü olmasın) |
| `mw_*.py` | `MainWindow` yöntem grupları (mixin; aynı `self`): `mw_build` BuildMixin (menüler, üst çubuk, yan panel, çizim alanı, durum çubuğu, `_build_properties_stack`, satır yardımcıları, `_action`) · `mw_export` ExportMixin (kaydet/dışa aktar/birleştir/böl/proje) · `mw_compare` CompareMixin (metin farkı) · `mw_ocr` OcrMixin (OCR, taranmış sayfada metin düzenleme) · `mw_forms` FormsMixin (AcroForm) · `mw_sign` SignMixin (imza, dijital imza, damga) · `mw_doctools` DocToolsMixin (sıkıştır/parola/güvenlik/tarama/dönüştür/a11y/KVKK/iş akışı/üstbilgi/kırpma/yazdır) · `mw_pages` PagesMixin (sayfa işlemleri) · `mw_nav` NavMixin (küçük resim, içindekiler, yakınlaştırma, arama) · `mw_annot` AnnotMixin (işaret oluşturma/silme, numara, katmanlar) · `mw_notes` NotesMixin (notlar/yorumlar). Yeni yöntemi ilgili mixin'e yaz; mixin'ler `main_window`'dan içe aktarmaz |
| `views.py` | `PDFView` sürekli kaydırmalı görünüm (`PageItem`; işaretler sayfanın çocuk öğesi, koordinatlar sayfa pt), `ComparePane` |
| `models.py` | Annotation sınıfları + `QUndoCommand`'lar, `DocumentSession` |
| `pdf_engine.py` | `PDFDocument` (render, dışa aktarım `export_pdf(..., security, compress)`), filigran |
| `docsec.py` | Parola/izin, sıkıştırma, güvenlik taraması/temizliği, belge bilgileri |
| `pii.py` | KVKK kişisel veri bulucu |
| `headfoot.py` | Sayfa numarası/üstbilgi/altbilgi/Bates motoru (`export_pdf(..., headfoot=cfg)`) |
| `forms.py` | AcroForm: `list_fields`, `set_value/apply_values/snapshot_values`, `reset_values`, `recalculate`, `add_field/field_spec/delete_field` |
| `digisign.py` | pyhanko: `sign_pdf` (artımlı; alan/yeni kutu/görünmez), `verify_pdf` → `SigReport`, `create_self_signed` |
| `workflow.py` | Görsel iş akışı çekirdeği (arayüzsüz): `STEP_TYPES` (ocr/rotate/watermark/headfoot/kvkk/a11y_fix/compress/password/to_word/save), `Workflow`/`Step`, `WorkflowLibrary` (QSettings'te JSON şablon + hazır şablonlar), `run_file`/`run_batch`/`collect_files`, `BatchReport` |
| `textdiff.py` | Metin farkı çekirdeği (arayüzsüz): `compare(pdf_a, pdf_b, ignore_case, check, progress)` → `DiffResult` (`Change`: kind add/del/mod, `a_rects`/`b_rects` sayfa pt + görünen yön, `focus_a/focus_b`, `page`), `extract_lines`, `report_html(sonuc, ad_a, ad_b, ignore_case)` (satır içi stilli, tümü `html.escape`; Qt'siz) |
| `convert.py` | PDF→Word/Excel çekirdeği (arayüzsüz): `to_docx(bytes, out, pages, cancelled)` (pdf2docx), `find_tables` + `write_xlsx` + `to_xlsx(..., numbers, decimal)` (PyMuPDF `find_tables` + openpyxl), `parse_number`; hata `ConvertError`, iptal `Cancelled`, sonuç `ConvertResult` |
| `a11y.py` | Erişilebilirlik çekirdeği (arayüzsüz): `audit(doc, path, cancelled)` → `A11yReport` (`Check`: key/status pass·warn·fail·info/`fix`/`data`), `apply_fixes(doc, ['lang','title','bookmarks'], ...)`, `ocr_replace_pages`, `detect_headings`, `report_text/html` |
| `qrshare.py` | QR/telefon aktarımı çekirdeği (arayüzsüz, yalnız stdlib `http.server` + segno): `ShareServer(receive_dir, on_received, host, port, max_bytes, token)` → `start/stop/url/offer/clear_offers/listing/idle_seconds`, `qr_png(url)`, `lan_addresses()`, `sanitize_filename`, `unique_path`, `PAGE` (telefon sayfası). Yollar: `/<anahtar>/` sayfa, `up` (POST, ham gövde + `X-Filename`), `list`, `d/<i>` |
| `scan.py` | Belge tarama çekirdeği (arayüzsüz, OpenCV+numpy): görüntü = `(h,w,3)` RGB uint8. `load_image` (EXIF, ≤3000 px), `detect_corners(img, fallback=True)` → SÖ,SaÖ,SaA,SA ya da tüm kare/`None`, `order_points`, `warp`, `rotate(img, derece)` (saat yönü), `apply_filter(img, ad, parlaklik, kontrast)` (`FILTERS`; `belge` yalnız 0/255), `to_pdf(sayfalar, out_path, sayfa_boyutu, kenar_bosluk_pt, jpeg_kalite, yon, max_kenar)` (yol → dosya, yoksa `fitz.Document`; dosya girdisi ≤4000 px), `images_to_pdfs(paths, out, ayri, ..., progress, cancelled)` (toplu çevirici; iptalde `convert.Cancelled`, dosya kalmaz) |
| `ocr.py`, `fonts.py`, `gizmo.py` | OCR (Tesseract, `tessdata/`), yazı tipleri, boyutlandırma kulpları |
| `ui/theme.py` | Renk belirteçleri (`current()`, `qcolor()`), QSS — yeni objectName stillerini buraya ekle |
| `ui/icons.py` | Kendi SVG ikon seti: `icon(name, role)`; yeni ikon = `_PATHS`'e 24×24 çizgi SVG |
| `ui/*.py` | overlays, sidepanel, welcome, toast, palette, kvkk, stamps, docdialogs, widgets, pagetools (üstbilgi/Bates + sayfa kırpma), comments (Yorumlar paneli + `ask_note_text`), signatures (`SignatureLibrary`, imza/dijital imza/rapor pencereleri), formui (Formlar paneli, `FormFieldDialog`, satır içi `FormFieldEditor`), workflow (`WorkflowDialog`: palet + sürüklenebilir zincir + `ParamForm` + şablon + hedef + ilerleme/rapor), compare (`CompareDiffPanel`: sayfa sayfa değişiklik listesi + süzgeç + önceki/sonraki), convert (`ConvertDialog` + `BackgroundJob`: `job(progress, cancelled)` havuzda, `done/failed` sinyali), a11y (`A11yDialog`: rapor + tek tıkla düzelt), share (`ShareDialog`: QR + gelenler + belgeyi sunma; sunucuyu `close()` durdurur), imgpdf (`ImagesPdfDialog(main, paths)`: sıralı liste + `start_export(out)`; `out` tek PDF'te dosya, ayrıda klasör), textdialog (`TextDialog`, `ocr_text_width`), ocrdialog (`_OcrTask`/`_OcrSignals` arka plan işçisi + `OcrDialog`), watermark (`WatermarkDialog`), scanner (`ScanDialog(main, kaynaklar, start)`: `CornerView` + `Source`/`ScanPage`/`render_page`) |

## Kurallar
- Yeni eylem: `_build_menus()` (`mw_build.py`) içinde `A(menu, ikon, "Metin", slot, "Kısayol")` — komut paletine (Ctrl+K) otomatik girer.
- Yeni araç: `TOOLS` + `TOOL_KEYS` (`mw_common.py`) + `_build_properties_stack()` sayfası (`mw_build.py`) (+ gerekiyorsa `PDFView` sinyali).
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
- `to_word` adımı `_FINAL`: `ctx.to_word` ayarlar, çıktı `_write_word` ile `.docx` (özgün PDF ezilmez, sıkıştırma/parola yok sayılır); `a11y_fix` `_PAGE`: `a11y.apply_fixes` + `detect_headings` (yer imi düzeyleri `_a11y_toc` ile ≤ önceki+1). Testi `tests/scripts/check_workflow.py` (adım şeması, kaydet kipleri, şablon kütüphanesi, `run_batch` hata/iptal, arayüz formu).
- Parola adımında `ask=True` iken parola şablona/ayara yazılmaz; `run_batch(..., overrides={'user_password': ...})` ile gelir. Testte `dlg.ask_passwords`, `dlg.ask_name` sahtelenir (exec bloklar).
- Görünür bir pencereye sonradan eklenen widget'a `show()` çağır (aksi halde panel boş kalır; `ParamForm` böyle yakalandı).
- Metin farkı: `MainWindow._run_diff` `_OcrTask` ile arka planda `textdiff.compare` çalıştırır; `_diff_token` bayat sonucu eler, sol/sağ combo ya da "harf yoksay" değişince `_schedule_diff` (350 ms) yeniden hesaplar. Vurgu `ComparePane.set_marks({sayfa: [(x0,y0,x1,y1,"add"|"del")]})`, listeden gitme `ComparePane.goto(sayfa, rect)` (odak halkası). Konumlar `page.rotation_matrix` ile görünen yöne çevrilir; birleştirme yalnızca aynı satırdaki kelimeleri kapsar. Rapor: `CompareDiffPanel.write_report(yol)` (`.pdf` → `html_to_pdf`: `QTextDocument`+`QPrinter(PdfFormat)`, yoksa HTML), `save_report()` diyalogla; adlar `set_names` (`_on_diff_done`). Testte iki belge `w.open_paths([a, b])` + `w.compare_documents()`, sonucu `w._diff is not None` ile bekle.
- Word/Excel: dönüştürme `s.pdf._annotated_copy(...).write()` baytlarıyla `BackgroundJob`'da çalışır, ana belgeye dokunmaz. Excel yalnızca çizgili/algılanabilir tabloları alır; `numbers` yalnız 2. satırdan itibaren sayıya çevirir (1. satır başlık), `decimal` TR=`,` varsayılan. Yeni dönüştürme biçimi = `convert.py`'ye işlev + `ConvertDialog`'a seçenek.
- Erişilebilirlik: yeni kontrol = `a11y.audit`'e `rep.checks.append(Check(...))`; düzeltilebiliyorsa `fix=<anahtar>` + `apply_fixes` dalı + `FIX_LABEL` + `A11yDialog.chk`. Denetim `ocr.open_snapshot` kopyasında çalışır; düzeltmeler `pdf.doc`'a doğrudan yazılır (geri alınmaz) ve `changed()` (`_invalidate` + `_mark_dirty` + küçük resim/İçindekiler yenileme) çağrılır. OCR düzeltmesi sayfayı `new_page` + `show_pdf_page` ile değiştirir (boyut sabit, sayfa sayısı aynı). `QTreeWidget` satır kaydırması için `setTextElideMode(ElideNone)` + yatay kaydırma kapalı gerekir. Testte iletişim kutularını `exec()` ile değil doğrudan oluşturup `pump` ile bekle; dosya diyaloglarını `QFileDialog.getSaveFileName` sahtesiyle değiştir.
- QR aktarımı: yükleme `multipart` değil, ham gövde + `X-Filename` (Python 3.13+'da `cgi` yok; ayrıştırıcıya gerek kalmaz). Sunucu `received` sinyaliyle ana iş parçacığına döner (`ShareDialog.received`). Güvenlik kuralları değişmez: anahtar URL'de ve `hmac.compare_digest`; yalnız PDF/resim (uzantı + imza); ad temizliği; boyut/adet sınırı; yarım dosya `.part` silinir; reddedilen küçük gövde `_drain` edilir (tarayıcı yanıtı görsün). Yeni dosya türü = `ALLOWED_EXTS` + `_SIGNATURES`. Pencere/uygulama kapanınca ve 15 dk boşta sunucu durur (`MainWindow.closeEvent` `_share_dialog.close()`). Testte `ShareDialog(w, host="127.0.0.1", receive_dir=<geçici>)` doğrudan oluştur (gerçek LAN adresi ve kullanıcının Belgeler klasörü kullanılmasın); istekleri ayrı iş parçacığından at, ana iş parçacığında `pump` ile bekle.
- Heredoc ile `'''` içeren betik yazma (araç ayrıştırması bozuluyor): betiği Write ile dosyaya yaz, sonra çalıştır.

- Belge tarama penceresi: kaynak `Source(kind image|pdf)`; PDF sayfaları 200 dpi, yükleme tembel (`load_source`), sayfa durumu `ScanPage` (köşe = **kesir** 0…1, döndürülmüş görüntüye göre; `rotate_corners`). Hat: yükle → döndür → köşeden `warp` → filtre (`render_page`, arka plan işi de aynısını çağırır). `_work` ≤1400 px önizleme görüntüsüdür, `preview_array` son önizleme. Çıktı `start_export(yol)` (`generate()` yalnız dosya sorar); OCR'lıda önce `.ocr.part`, sonra `os.replace`. Kapanış `done()` kancasında işi iptal eder. Testte `dlg.start_export` + `pump`; kulp `dlg.view.handles[i].setPos`, sıralama `move_page` (sürükleme `_sync_order`).
- `ShareDialog.chk_scan` açıkken gelen görseller `_scan_queue`'ya biriken (belge olarak açılmaz), `finish_scan()` → `MainWindow.scan_images(yollar)`; PDF'ler `chk_open` kuralına uyar. Testte kuyruğa `post` ile gönder, `dlg.finish_scan()` dönen `ScanDialog`'u kapat.

## Test
- Testler repoda: `tests/` (pytest). `tests/scripts/check_*.py` aşama denetim betikleridir (kendi süreçlerinde çalışır, `OK/FAIL` satırları + `OZET: a/b gecti` yazar); `tests/test_scripts.py` hepsini, `tests/test_lint.py` pyflakes'i çalıştırır.
  Çalıştır: `$env:QT_QPA_PLATFORM="windows"; <venv>\Scripts\python -m pytest` (tek aşama: `-k qrshare`). Çıktıda yalnız `OZET`/`FAIL`'e bak. Yeni özellik = yeni `check_<ad>.py` (en yakın mevcut betikten kopyala: `ROOT`, `check()`, `pump()`, geçici ayar, `OZET`).
- Pencereyi oluşturduktan hemen sonra `w.settings = QSettings(<geçici>.ini, IniFormat)` ve
  `w.stamp_lib.settings = w.settings` (+ `w.sig_lib`) — yoksa kullanıcının gerçek ayarları (son açılanlar) kirlenir.
- Lint `tests/test_lint.py` içinde (pyflakes `requirements-dev.txt`'te).
- Ekran görüntüsünü yalnızca aşama sonunda bir kez al (maliyet).
- `.venv` başka bilgisayardan (OneDrive) gelmişse çalışmaz (pyvenv.cfg başka kullanıcı yolu): repoya dokunmadan geçici klasörde `py -3.12 -m venv` + `pip install -r requirements-dev.txt` ile test ortamı kur (aynı ortam sonraki aşamalarda yeniden kullanılır). Çıktı borulanırsa `python -u` kullan (`os._exit` tamponu yutar).
- Satır sonu LF (`.gitattributes`; `.bat` CRLF). Dosyaları Write/Edit ile yazarken LF bırak.

## Yol haritası (kalan)
B tamam (sayfa no/üstbilgi/Bates, sayfa kırpma, bulanıklaştırma, yapışkan not + yorumlar) ·
C1 tamam (form doldurma/sıfırlama/oluşturma, hesaplanan alan, Ctrl+P yazdırma) ·
C2 tamam (elektronik imza + kütüphane, imza alanı, pyhanko dijital imza/doğrulama) · E tamam (görsel iş akışı: adım zinciri + şablon + açık belge/dosyalar/klasör, ilerleme/durdurma/rapor) ·
D1 tamam (iki sürümün metin farkı: yeşil/kırmızı vurgu, sayfa sayfa liste, listeden git) ·
D2 tamam (Word/Excel dönüştürme, erişilebilirlik denetimi + tek tıkla düzeltme; pdf2docx ve openpyxl `requirements.txt`'te) ·
F tamam (QR ile telefondan dosya alma + açık belgeyi telefona sunma; segno `requirements.txt`'te) ·
G1 tamam (`scan.py` tarama çekirdeği; opencv-python-headless + numpy `requirements.txt`'te) · G2 tamam (`ui/scanner.py` tarayıcı penceresi: görsel/PDF kaynağı, köşe kulpları, filtre, OCR'lı PDF) · G3 tamam (telefon fotoğrafları → tarayıcı kuyruğu; Görselleri PDF'e çevir) · H1 tamam (iş akışı: `a11y_fix`, `to_word` + `check_workflow.py`) · H2 tamam (metin farkı HTML/PDF raporu) · J1 tamam (bağımsız diyaloglar `main_window.py`'dan `ui/`'a taşındı; davranış aynı) · J2 tamam (yöntem grupları `mw_*.py` mixin'lerine taşındı) · J3 tamam (arayüz kurulumu `mw_build.py`, dışa aktarma `mw_export.py`, sabitler `mw_common.py`; `main_window.py` 4622 → ~940 satır).
**Sıradaki aşamalar (G1…K) ve her biri için hazır istem: `YOLHARITASI.md`** — yeni sohbette yalnızca ilgili aşama bölümünü oku.
