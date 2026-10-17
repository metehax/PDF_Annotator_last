# Yol haritası — sıradaki aşamalar

Sıra: **G1 → G2 → G3 → H1 → H2 → J1 → J2 → J3 → K**. Her aşama ayrı sohbette, ayrı commit'te yapılır.
Tamamlananlar: B, C1, C2, D1, D2, E, F, testlerin repoya alınması (bkz. `CLAUDE.md`).

## Token tasarrufu kuralları (her sohbette geçerli)
1. `CLAUDE.md` zaten yüklenir. Bu dosyadan **yalnızca ilgili aşama bölümünü** oku (`Grep "^## G2" -A 40`); dosyayı bütün okuma.
2. Kodu `Grep` ile konumla, `Read`'i `offset/limit` ile kullan. `main_window.py` (4500+ satır) ve `views.py`'ı asla bütün okuma.
3. Çok satırlı taşıma/ekleme işlerini küçük bir Python/PowerShell betiğiyle yap (satır aralığı kesip yapıştır); dosyayı baştan yazma.
4. Test: geliştirirken yalnızca ilgili betik (`pytest -k scan`), aşama sonunda tam `pytest`. Çıktıda yalnızca `OZET`/`FAIL`.
5. Tek ekran görüntüsü, yalnızca sonda. Alt ajan/araştırma açma. Açıklamalar kısa.
6. Test ortamı: `py -3.12 -m venv <geçici>` + `pip install -r requirements-dev.txt` (bir kez; sonraki aşamada aynı ortamı kullan).
7. Mekanik aşamalarda (H2, J1–J3, K) daha hafif model yeterli; tasarım yoğun G1/G2'de güçlü model.
8. Aşama sonu: ilgili `tests/scripts/check_*.py`, tam pytest, README + CLAUDE.md'ye **kısa** not, commit (mesaj dosyadan: `git commit -F`).

**İstem şablonu** (yeni sohbette ilk mesaj; `<A>` yerine aşama kodu):
> PDF Annotator, aşama `<A>`. CLAUDE.md'yi ve YOLHARITASI.md'nin yalnızca `<A>` bölümünü oku. Bölümdeki "Yapılacak / Yeniden kullan / Bitti ölçütü"ne uy. Kurallar: dosyaları bütün değil gereken kısmıyla oku, test çıktısının yalnızca özetine bak, ekran görüntüsünü yalnızca sonda bir kez al, açıklamaları kısa tut. Bitince test et (ilgili check betiği + tam pytest), README ve CLAUDE.md'yi kısaca güncelle, git'e kaydet.

---

## G1 — Belge tarama çekirdeği (`scan.py`, arayüzsüz)
**Amaç:** fotoğraftan kâğıdı bulup düzeltmek ve filtre uygulamak (Adobe Scan benzeri), UI'siz ve test edilebilir.
**Yapılacak**
- `scan.py`: `load_image(path)` (Pillow `ImageOps.exif_transpose`, çok büyükse ≤3000 px'e küçült), `detect_corners(img)` → sıralı 4 köşe (SÖ, SaÖ, SaA, SA) ya da `None`
  (küçült → gri → blur → Canny → genişlet → en büyük dörtgen kontur, alan ≥ %20; bulunamazsa tüm görüntü), `order_points`, `warp(img, corners)` (çıktı boyutu kenar uzunluklarından),
  `rotate(img, derece)`, `apply_filter(img, ad, parlaklik=0, kontrast=0)` — filtreler: `orijinal`, `otomatik` (otomatik kontrast + hafif keskinleştirme), `belge` (gölge kaldır + adaptif eşik → siyah-beyaz), `gri`, `canli` (CLAHE + doygunluk), `gölgesiz renkli`.
- `to_pdf(sayfalar, out_path=None, sayfa_boyutu="a4"|"letter"|"orijinal", kenar_bosluk_pt=0, jpeg_kalite=85)` → fitz belgesi/dosya (sayfa görüntüye sığdırılır, yön otomatik).
- `requirements.txt`: `opencv-python-headless`, `numpy` (şu an pdf2docx ile dolaylı geliyor; açık yaz).
**Yeniden kullan:** `pdf_engine.image_to_pdf_document` ve `IMAGE_EXTS` (aynı uzantı kümesi), Pillow.
**Bitti ölçütü:** `tests/scripts/check_scan.py` — sentetik fotoğraf (koyu zemin + perspektifli beyaz kâğıt, `cv2.warpPerspective`) üretip köşeleri ±%3 doğrular, `warp` çıktı oranı, her filtrenin şekil/tür korunumu, `belge` filtresi çıktısının ≥%95'i 0/255, `to_pdf` sayfa sayısı/boyutu, köşe bulunamayınca geri dönüş.

## G2 — Tarayıcı penceresi (`ui/scanner.py`)
**Amaç:** köşeleri otomatik bul + elle ayarlat, filtre seç, çok sayfalı PDF üret. Kaynak: görsel dosyalar **veya** açık/seçili PDF'in sayfaları (taranmış PDF'i kırp/temizle).
**Yapılacak**
- `ScanDialog(main, kaynaklar)`: ortada büyük görüntü + 4 **sürüklenebilir köşe kulpu** (`QGraphicsView`, kulpların arasında yarı saydam alan, büyüteç yok), "Otomatik algıla" / "Tüm görsel" düğmeleri;
  sağda filtre kartları (küçük önizleme) + parlaklık/kontrast kaydırıcıları + döndür (↺ ↻); altta sayfa şeridi (ekle, sil, sürükleyerek sırala; her sayfanın köşe/filtre/dönüşü ayrı saklanır);
  seçenekler: sayfa boyutu, kalite, "Aranabilir yap (OCR)"; **PDF oluştur…** → kaydet ve uygulamada aç. Ağır işler `ui.convert.BackgroundJob`'da.
- Menü: Dosya → "Belge tara (görsellerden)…" (`needs_doc=False`), PDF sekmesinde "Bu belgeyi tara/kırp…" (sayfalar 200 dpi görüntü olarak alınır). Komut paletine otomatik girer.
**Yeniden kullan:** `scan.py` (G1), `ocr.make_searchable_pdf/ocr_pages/find_tessdata/pick_language`, `ui.convert.BackgroundJob`, `ui/icons.py` (yeni ikon gerekirse `_PATHS`), `ui/theme.py` (yeni objectName stilleri buraya).
**Bitti ölçütü:** `check_scan_ui.py` — pencereyi sentetik fotoğraflarla aç, otomatik köşe → kulp konumları, köşe değiştirince önizleme değişir, filtre değişir, 2 sayfa ekle/sırala, PDF üret (sayfa sayısı, OCR'lı sürümde metin), iptal.

## G3 — Telefondan taramaya bağlantı + "Görselleri PDF'e çevir"
**Yapılacak**
- `ShareDialog`: "Gelen fotoğrafları tarayıcıda aç" seçeneği; birden çok foto birikir, "Taramayı bitir" tarayıcıyı bu sayfalarla açar (`ShareDialog._on_received` kancası).
- Dosya → "Görselleri PDF'e çevir…": çoklu seçim/sürükle-bırak, sıralama, sayfa boyutu/yön/kenar boşluğu/kalite, tek PDF ya da her görsel ayrı PDF; sonuç uygulamada açılır. (Tek görsel zaten belge olarak açılıp PDF kaydedilebiliyor; bu, toplu ve ayarlı yol.)
**Yeniden kullan:** `scan.to_pdf`, `ui.convert.BackgroundJob`, `qrshare.ShareServer` (değişmez), `ui/share.py`.
**Bitti ölçütü:** `check_images_pdf.py` (çekirdek + pencere), `check_qrshare_ui.py`'ye "foto → tarayıcı kuyruğu" kontrolü.

## H1 — İş akışına yeni adımlar (+ iş akışı testi)
**Yapılacak**
- `workflow.STEP_TYPES`'a `a11y_fix` (dil/başlık/yer imi; `a11y.apply_fixes`, `Param` şeması: dil, başlık ata/ata) ve `to_word` (`convert.to_docx`; çıktı `.docx`, `_FINAL`) adımları; `STEP_ORDER`'a anahtar.
- E aşaması için hiç test yok: `check_workflow.py` (mevcut adımlar: rotate, watermark, compress, password; hazır şablon; `run_batch` hata/iptal) ve yeni adımlar.
**Yeniden kullan:** `workflow.py` adım deseni (CLAUDE.md "İş akışı" maddeleri), `a11y.py`, `convert.py`.
**Bitti ölçütü:** `check_workflow.py` geçer; arayüz formu şemadan otomatik üretilir (ek UI kodu yok).

## H2 — Karşılaştırma raporu (HTML/PDF)
**Yapılacak:** `textdiff.report_html(sonuc, ad_a, ad_b)` (özet + sayfa sayfa eski | yeni tablosu, eklenen yeşil / silinen kırmızı, kelime düzeyinde vurgu); `CompareDiffPanel`'e "Raporu kaydet…" (HTML ya da PDF — PDF için `QTextDocument` + `QPrinter(PdfFormat)`, yeni paket yok).
**Yeniden kullan:** `textdiff.DiffResult/Change`, `a11y.report_html` desenindeki kaçışlama, `ui/compare.py`.
**Bitti ölçütü:** `check_textdiff.py`'ye rapor kontrolleri (HTML'de kaçışlı metin, sayfa başlıkları, PDF dosyası açılır ve ≥1 sayfa).

## J1–J3 — `main_window.py` bölünmesi (davranış değişmez)
**Kural:** yalnızca taşı, mantığa dokunma; her adımdan sonra tam `pytest`, ayrı commit. Taşımayı elle yeniden yazarak değil, `ast` ile satır aralığı çıkaran küçük betikle yap (token tasarrufu).
- **J1:** dosya içindeki bağımsız sınıfları (`OcrDialog`, `_OcrTask`, `_OcrSignals` vb.) `ui/` altına taşı; `main_window` içe aktarsın.
- **J2:** yöntem gruplarını mixin sınıflarına ayır (`CompareMixin`, `OcrMixin`, `FormsMixin`, `SignMixin`, `DocToolsMixin` …; dosyalar `mw_*.py`), `MainWindow` hepsini miras alsın.
- **J3:** kalan büyük bloklar (menü kurulumu, dışa aktarma) ve `CLAUDE.md` yapı tablosunu güncelle; `main_window.py` hedef < 1500 satır.
**Bitti ölçütü:** pytest yeşil, `pyflakes` temiz, uygulama açılır (tek elle deneme).

## K — Paketleme (PyInstaller)
**Yapılacak:** `pdfannotator.spec` (one-folder), `build.bat`; `datas`: `tessdata/`, `fonts/`, `ui` varlıkları; `hiddenimports`: pdf2docx, pyhanko, segno, openpyxl, cv2; gereksizleri hariç tut (tkinter, matplotlib…); uygulama simgesi; çıktıyı `dist/PDF Annotator/`. İsteğe bağlı: Inno Setup betiği (kurucu + masaüstü kısayolu).
**Notlar:** boyut büyük olacak (PySide6 + OpenCV; yüzlerce MB), antivirüs yanlış alarmı olabilir (kodu imzalamak ayrı konu), `onefile` yavaş açılır — `onedir` öner.
**Bitti ölçütü:** `build.bat` çalışır, `dist` içindeki exe temiz bir klasörde açılır, bir PDF açıp OCR/kaydet denenir (tek elle deneme); `README`'de "Kurulum (exe)" bölümü.
