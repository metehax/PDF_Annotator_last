# PDF İşaretleme Aracı — Profesyonel Mimari

Tek dosyalık prototipin (`pdf_annotator.py`) modüler, performanslı bir
PySide6 + PyMuPDF masaüstü uygulamasına dönüştürülmüş hâli.

## Kurulum ve çalıştırma

**Windows (önerilen):** `kur.bat` dosyasına çift tıklayın (bir kez). Sanal ortam
kurar, gereksinimleri yükler, OCR için `tur` + `eng` dil dosyalarını
`tessdata/` klasörüne indirir ve masaüstüne "PDF Annotator" kısayolu koyar.
Sonra uygulamayı `calistir.bat` ya da masaüstü kısayoluyla açın
(hata görmek için `calistir_konsol.bat`).

Elle kurulum:

```bash
pip install -r requirements.txt
python main_window.py
```

Windows'ta Türkçe karakterler için `pdf_engine.find_unicode_font()`
sistemde bulduğu ilk TrueType fontu (Arial/Segoe UI/Tahoma/Calibri) otomatik
kullanır; bulunamazsa PyMuPDF'in yerleşik `helv` fontuna düşer (bu durumda
Türkçe karakterler PDF çıktısında görünmeyebilir).

## Dosya yapısı

| Dosya            | Sorumluluk                                                            |
|------------------|------------------------------------------------------------------------|
| `models.py`      | Annotation ailesi (Text/Ink/Line/Shape/Highlight/Redaction/Number/**Image**), `WatermarkConfig`, `ToolState`, `DocumentSession`, **QUndoCommand** alt sınıfları |
| `pdf_engine.py`  | `PDFDocument` (PyMuPDF sarmalayıcı): **LRU önbellekli + asenkron (QThreadPool) render**, arama, İçindekiler, sayfa yönetimi/döndürme, PDF & görsel dışa aktarım, **filigran motoru**, JSON proje kaydı |
| `gizmo.py`       | Seçili nesneler için **8 noktalı boyutlandırma kulpları** |
| `views.py`       | `PDFView` (canvas etkileşimleri, **Bézier/Catmull-Rom ink yumuşatma**, arama vurguları), `ComparePane` (karşılaştırma modu) |
| `main_window.py` | `MainWindow`: üst araç çubuğu, **QTabBar** sekmeli belge yönetimi, **QDockWidget** paneller (sol: Küçük Resimler/İçindekiler/Ara — sağ: Özellikler/Katmanlar), yakınlaştırma/durum çubuğu, **QUndoStack/QUndoGroup**, filigran & resim ekleme diyalogları |

## Öne çıkan mimari kararlar

* **Sürekli kaydırma** (`views.PDFView`): tüm sayfalar alt alta `PageItem`
  olarak dizilir; işaretler ilgili sayfanın çocuk öğesidir (koordinatlar sayfa
  birimi). Yalnızca görünen sayfalar + komşuları, o anki zoom'a uygun
  çözünürlükte arka planda render edilir; uzaktakiler bellekten atılır.
  Ctrl+tekerlek yumuşak zoom, Boşluk/orta tuş ile sürükleme, Home/End/PgUp/PgDn.
* **LRU önbellek** (`pdf_engine.LRUCache`, `collections.OrderedDict` tabanlı)
  son 10 sayfanın render'ını tutar; daha eskisi otomatik atılır.
* **Asenkron render**: `PDFDocument.make_render_task()` bir `QRunnable`
  döner; `QThreadPool` üzerinde çalışır, sonucu `QImage` olarak sinyalle
  ana iş parçacığına taşır (QPixmap yalnızca orada oluşturulur).
* **QUndoStack / QUndoGroup**: her `DocumentSession` kendi `QUndoStack`'ine
  sahiptir; `MainWindow.undo_group` sekmeler arası aktif yığını yönetir.
  Ekleme/silme/taşıma/boyutlandırma/katman-sırası hepsi `QUndoCommand`.
* **Bézier/Catmull-Rom yumuşatma**: serbest çizim noktaları
  `models.catmull_rom_to_beziers()` ile kübik Bézier segmentlerine
  çevrilir; hem ekran önizlemesi hem PDF çıktısı (`page.draw_bezier`)
  AYNI eğriyi kullanır.
* **8 noktalı gizmo**: `gizmo.SelectionGizmo`, `Annotation.get_rect()` /
  `set_rect()` arayüzünü kullanır (Şekil, Metin kutusu, Resim). Resimlerde
  varsayılan en-boy kilidi AÇIK, Shift ile serbest; diğerlerinde tersi.
* **Filigran motoru** (`pdf_engine.apply_watermark_to_pages`): metin ya da
  resim, tekli/döşenmiş yerleşim, -90°/+90° döndürme (`fitz.Matrix` + PIL
  görüntü döndürme), saydamlık (Pillow ile alfa kanalına gömülür), kapsam
  seçimi (aktif sayfa/aralık/tüm belge).
* **JSON proje formatı**: `DocumentSession.to_project_dict()` /
  `load_project_dict()` + `pdf_engine.save_project_json/load_project_json`
  — tüm vektörel işaretleri (resimler dâhil, base64 gömülü) kaydeder;
  kaynak PDF'e ayrıca ihtiyaç duyar.
* **Sayfa döndürme**: `fitz.Page.set_rotation` doğrudan kullanılır — MuPDF
  `page.rect` ve `get_pixmap()` çıktısını otomatik olarak döndürülmüş
  boyuta göre üretir, bu sayede önizleme/dışa aktarım için ekstra bir
  koordinat dönüşümüne gerek kalmaz.
* **Kaynak temizliği**: `PDFDocument.close()` / `DocumentSession.close()`
  dosyayı açıkça kapatır; `MainWindow.closeEvent` ve `close_session` bunu
  çağırır.

## Korunan özellikler

* **Altın açı numaralandırma** (`models.number_to_color`) — iki belgede
  aynı numara her zaman aynı rengi alır.
* **Karşılaştırma modu** (`views.ComparePane`) — salt okunur, bağımsız
  belge/sayfa seçimi, "Eşleştir modu" ile iki belge arasında numara
  eşleştirme.

## Bilinen sınırlamalar / genişletme noktaları

* SVG filigran/resim girişleri Qt'nin `QSvgRenderer`'ı ile rasterize
  edilir (vektörel olarak PDF'e gömülmez).
* Bir sayfa zaten işaretlenmişken döndürülürse, eski işaretlerin
  konumu yeni eksen takımına göre kayabilir (uygulama bu durumda
  kullanıcıyı uyarır).
* Çok büyük (yüzlerce sayfalık) belgelerde tam-belge arama senkron
  bir döngüyle yapılır ama `QRunnable` üzerinden arka planda çalışır;
  UI donmaz.


## Yeni: Yazı tipi seçimi ve OCR

* **Metin aracı**: sayfaya tıklayınca açılan pencerede yazı, **yazı tipi**
  (Arial, Calibri, Times New Roman, Roboto), **renk** ve **punto** seçilir.
  Son seçimler bir sonraki metin için hatırlanır; sağ paneldeki "Metin"
  sayfasından da değiştirilebilir. Seçilen font hem ekranda hem PDF çıktısında
  ve JSON projede saklanır. Roboto `fonts/` klasöründen yüklenir
  (Apache 2.0); diğerleri Windows font klasöründen alınır (`fonts.py`).
* **OCR** (üst çubuk → 🔍 OCR): bu sayfanın ya da tüm belgenin metnini okur
  (kopyala / TXT kaydet), ayrıca işaretlerinizle birlikte **aranabilir PDF**
  üretir. İşlem arka planda çalışır. Gerekli: Tesseract dil verisi
  (`tur` + `eng`). Ya Tesseract'ı kurun (Turkish seçili) ya da
  `tur.traineddata` ve `eng.traineddata` dosyalarını `tessdata/` klasörüne koyun
  (`ocr.py`).

### Metin Düzenle aracı (✏)

Sol araç sütunundan "Metin Düzenle"yi seçin; sayfadaki okunabilen satırlar mavi
kutularla işaretlenir (sağ panelden "Paragraf" seçimine de geçilebilir).
Bir kutuya tıklayınca metin, font, punto ve renk (gerçek metinde PDF'teki
değerler, taranmış sayfada OCR + renk örnekleme) hazır gelir. Tamam'a basınca
eski metin **kalıcı silinir** (arka plan rengiyle kapatılır) ve yenisi yazılır;
Ctrl+Z tek adımda geri alır. Metni boşaltırsanız yalnızca silinir.
Sayfada gerçek metin yoksa OCR otomatik devreye girer (Türkçe + İngilizce,
yüklü dil verisine göre); "Taranmış sayfa (OCR kullan)" ile zorlanabilir.

## Yeni: Resim dosyalarını düzenleme

"📂 Aç" artık PDF'in yanında PNG, JPG/JPEG, BMP, GIF, TIFF (çok sayfalı dahil)
ve WEBP dosyalarını da açar. Resim, `pdf_engine.image_to_pdf_document()` ile
bellekte bir PDF sayfasına çevrilir (EXIF yönü uygulanır); tüm araçlar
(metin, çizim, şekil, karartma, filigran, OCR…) aynı şekilde çalışır.

* **Ctrl+S**: resim açıldıysa resim olarak (varsayılan: orijinal uzantı),
  PDF açıldıysa PDF olarak kaydeder.
* **Dışa Aktar → Resim olarak kaydet**: orijinal piksel çözünürlüğünde
  PNG/JPEG/BMP/TIFF/WEBP çıktı. Çok sayfalı belgelerde her sayfa ayrı dosya olur.
* İstenirse resim **PDF olarak** da kaydedilebilir; **Birleştir** resimleri de
  kabul eder.
