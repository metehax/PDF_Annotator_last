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
| `models.py`      | Annotation ailesi (Text/Ink/Line/Shape/Highlight/Redaction/Number/**Image**/**Blur**/**Note**), `WatermarkConfig`, `ToolState`, `DocumentSession`, **QUndoCommand** alt sınıfları |
| `pdf_engine.py`  | `PDFDocument` (PyMuPDF sarmalayıcı): **LRU önbellekli + asenkron (QThreadPool) render**, arama, İçindekiler, sayfa yönetimi/döndürme, PDF & görsel dışa aktarım, **filigran motoru**, JSON proje kaydı |
| `gizmo.py`       | Seçili nesneler için **8 noktalı boyutlandırma kulpları** |
| `views.py`       | `PDFView` (canvas etkileşimleri, **Bézier/Catmull-Rom ink yumuşatma**, arama vurguları), `ComparePane` (karşılaştırma modu) |
| `ui/theme.py`    | Renk sistemi (açık/koyu tema belirteçleri), QPalette + stil dosyası, Windows temasını izleme |
| `ui/icons.py`    | Uygulamanın kendi SVG ikon seti; renk temadan ve düğme durumundan çizim anında seçilir |
| `ui/overlays.py` | Çalışma alanında yüzen gölgeli çubuklar (araç kapsülü, özellik/seçim/sayfa çubukları) |
| `ui/sidepanel.py`| Sol ikon şeridi + animasyonla açılıp kapanan panel |
| `ui/welcome.py`  | Açılış ekranı: sürükle-bırak alanı, son açılan dosyalar |
| `ui/toast.py`    | Köşede beliren ve kendiliğinden kaybolan bildirimler |
| `ui/palette.py`  | Ctrl+K komut paleti (Türkçe karakterlere duyarsız arama) |
| `docsec.py`      | Parola/izinler, sıkıştırma seviyeleri, güvenlik taraması ve temizliği, belge bilgileri |
| `ui/docdialogs.py` | Parola, sıkıştırma, belge bilgileri ve güvenlik denetimi pencereleri |
| `pii.py`         | Kişisel veri bulucu (TC, IBAN, telefon, e-posta, plaka, kart); kontrol haneli doğrulama |
| `ui/kvkk.py`     | "Kişisel verileri bul ve karart" penceresi |
| `headfoot.py`    | Sayfa numarası / üstbilgi / altbilgi / Bates motoru (`HeadFootConfig`, `apply_header_footer`) |
| `ui/pagetools.py`| Üstbilgi/Bates ve sayfa kırpma pencereleri |
| `ui/comments.py` | Yorumlar paneli (yapışkan notlar, yanıtlar, çözüldü) |
| `forms.py`       | PDF formları (AcroForm): alanları okuma, doldurma, sıfırlama, hesaplama, alan oluşturma/silme |
| `ui/formui.py`   | Formlar paneli, alan özellikleri penceresi, sayfa üstündeki alan düzenleyicisi |
| `ui/signatures.py` | Elektronik imza (çiz/yaz/görsel), imza kütüphanesi, dijital imza ve doğrulama pencereleri |
| `digisign.py`    | Dijital imza (pyhanko): .pfx ile imzalama, doğrulama, sonradan değişiklik denetimi |
| `workflow.py`   | **Görsel iş akışı çekirdeği:** adım türleri (OCR, döndür, filigran, sayfa numarası, KVKK, erişilebilirlik düzeltmesi, sıkıştır, parola, Word'e dönüştür, kaydet), şablon kütüphanesi, çalıştırıcı (tek dosya / toplu), sonuç raporu |
| `ui/workflow.py` | İş akışı penceresi: adım paleti, sürükleyerek sıralanan zincir, ayar paneli, şablon, hedef seçimi, ilerleme/durdurma, sonuç tablosu |
| `textdiff.py`   | **Metin farkı çekirdeği:** iki belgenin metnini satır + kelime düzeyinde karşılaştırır (eklenen / silinen / değişen, sayfa konumlarıyla) ve `report_html` karşılaştırma raporu |
| `ui/compare.py` | Karşılaştırma modunun "Değişiklikler" paneli: sayfa sayfa liste, tür süzgeci, önceki/sonraki |
| `convert.py`    | **PDF → Word** (pdf2docx) ve **PDF → Excel** (PyMuPDF `find_tables` + openpyxl) çekirdeği |
| `a11y.py`       | **Erişilebilirlik denetimi** çekirdeği: 8 kontrol, rapor (HTML/TXT), dil/başlık/yer imi düzeltmeleri, OCR ile sayfa değiştirme |
| `scan.py`       | **Belge tarama** çekirdeği (OpenCV, arayüzsüz): fotoğraftan kâğıt köşelerini bulma, perspektif düzeltme, döndürme, **eğim (deskew)**, 6 filtre + gölge düzleştirme anahtarı, temizleme fırçası, sayfaları PDF'e aktarma. Arayüzü G2'de |
| `ui/flatten.py` | **Düzleştir ve kaydet** penceresi: işaret/yorum/form alanlarını sayfaya gömme, isteğe bağlı resme çevirme |
| `ui/scanner.py` | **Belge tara** penceresi: köşe kulpları (otomatik + elle), filtre kartları, parlaklık/kontrast, döndür, sayfa şeridi, PDF/OCR üretimi |
| `ui/imgpdf.py`  | **Görselleri PDF'e çevir** penceresi: sürükle-bırak, sıralama, sayfa boyutu/yön/kenar boşluğu/kalite, tek ya da ayrı PDF |
| `workspace.py`  | **Çalışma klasörü + otomatik kurtarma çekirdeği:** kök/alt klasörler (Gelen, Taramalar, Donusturulenler, Projeler, Yedekler, IsAkisi), çıktı tercihleri, son klasör, eski gelen klasörü taşıma, kurtarma taslakları |
| `ui/preferences.py` | **Tercihler** penceresi (Düzenle → Tercihler…, Ctrl+,) |
| `sharing.py`    | **Paylaşım yardımcıları:** yerel bulut klasörü algılama (OneDrive/Google Drive/Dropbox), e-posta (Outlook ekli ya da klasör + mailto), konumu aç |
| `qrshare.py`    | **QR ile telefon aktarımı** çekirdeği: anahtarlı yerel HTTP sunucusu (yükleme/indirme), telefon sayfası, QR (segno), isteğe bağlı 6 haneli PIN + kilit |
| `ui/share.py`   | "Telefonla aktar (QR)" penceresi: QR, gelenler listesi, belgeyi telefona sunma |
| `ui/convert.py` | Dönüştürme penceresi + arka plan iş sınıfı (`BackgroundJob`) |
| `ui/a11y.py`    | Erişilebilirlik raporu penceresi: kontrol listesi, tek tıkla düzeltme, rapor kaydı |
| `ui/stamps.py`   | Damga çizici, hazır damgalar, kendi damgalarınız (logolu) ve kütüphane penceresi |
| `ui/widgets.py`  | Tema uyumlu parçalar (ör. küçük resim çizici) |
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

## Yeni: Arayüz yerleşimi

* **Üst çubuk:** Dosya / Düzenle / Görünüm / Belge / Yardım menüleri, ortada
  belge sekmeleri, sağda Geri al/Yinele, Dışa Aktar ve Kaydet.
* **Araç kapsülü:** Sayfanın üstünde yüzen araç çubuğu. Seçilen aracın
  ayarları hemen altındaki **özellik çubuğunda** çıkar (ipuçları (i) simgesinde).
* **Sol şerit:** Sayfalar, İçindekiler, Ara ve İşaretler panelleri; aynı simgeye
  tekrar tıklamak paneli kapatır (Ctrl+B).
* **Seçim çubuğu:** Seçili işaretin üstünde: öne/arkaya al, sil.
  **Sayfa çubuğu:** Seç aracındayken imlecin altındaki sayfanın sağ üstünde:
  döndür, sayfa ekle/kopyala/sil. Sayfaya sağ tıklamak da aynı menüyü açar.
* **Durum çubuğu:** Sayfa numarası kutusu (yazıp Enter), sığdırma, zoom
  (yüzdeye tıklayınca hazır değerler), gece modu, karşılaştırma.
* **Açılış ekranı ve sürükle-bırak:** Dosyaları pencereye bırakmak yeterli;
  son açılanlar hem açılış ekranında hem Dosya menüsünde listelenir.
* Klavye kısayollarının tamamı: Yardım → Klavye kısayolları (F1).

## Yeni: Hızlı kullanım

* **Ctrl+K komut paleti:** Yazarak her komuta ulaşın ("döndür", "filigran",
  "ocr", "kalem", "sayfa 12"…). Türkçe karakter yazmanız gerekmez.
* **Tek harfli araç kısayolları:** V Seç, T Metin, E Metin Düzenle, P Kalem,
  H Fosforlu, L Çizgi, R Dörtgen, O Oval, X Gizle, B Bulanıklaştır, I Resim, N Numarala, S Damga, M Not, G İmza, C Kırp/Yakala, F Form Alanı.
  Esc seç aracına döner. Yazı alanlarındayken devreye girmez.
* **Bildirimler:** Kaydetme vb. sonuçlar köşede kısa bir bildirimle gösterilir
  ("Klasörde göster" bağlantısıyla). Hatalar yine pencere olarak çıkar.
* **Kaydedilmemiş değişiklikler:** Sekme adında `●` görünür; sekme ya da
  uygulama kapatılırken Kaydet / Kaydetme / İptal sorulur. PDF, resim ya da
  proje olarak kaydetmek belgeyi "kaydedildi" sayar.
* **Birlikte aç:** `main_window.py dosya.pdf` ile açılabilir; uygulama açıkken
  yeni dosyalar mevcut pencereye gönderilir. Yardım menüsündeki
  "Windows'ta 'Birlikte aç' listesine ekle" yalnızca kullanıcı hesabınız için
  kayıt yapar (HKCU), varsayılan uygulamanızı değiştirmez; aynı menüden kaldırılabilir.
* Pencere boyutu/konumu ve kenar paneli durumu bir sonraki açılışta hatırlanır.

## Yeni: Kişisel veri karartma (KVKK) ve damgalar

* **Belge → Kişisel verileri bul ve karart (Ctrl+Shift+K):** TC kimlik no, IBAN,
  telefon, e-posta, araç plakası ve kart numaralarını bulur. TC/IBAN/kart
  numaraları kontrol haneleriyle doğrulanır, böylece fatura no, tutar gibi
  sayılar yanlışlıkla seçilmez. Taranmış sayfalar OCR ile okunur. Bulunanlar
  sayfada vurgulanır; istediklerinizi seçip tek tıkla karartırsınız (tek Ctrl+Z
  ile geri alınır). Dışa aktarırken altındaki metin PDF'ten kalıcı silinir.
* **Damga aracı (S):** ONAYLANDI, REDDEDİLDİ, GÖRÜLDÜ, ASLI GİBİDİR … ve kendi
  damgalarınız. İsteğe bağlı ad + tarih satırı ve eğik görünüm. Basılan damga
  taşınabilir/boyutlandırılabilir. **Belge → Damga kütüphanesi** ya da özellik
  çubuğundaki "Kütüphane…" ile logolu özel damgalar oluşturulur.

## Yeni: Belge güvenliği ve bilgileri

* **Parolalı PDF açma:** Parola sorulur; kaydederken aynı açma parolası korunur.
* **Belge → Parola koruması:** Açma parolası ve izinler (yazdırma, kopyalama,
  düzenleme, yorum, form doldurma, sayfa düzenleme, ekran okuyucu). 256-bit AES.
* **Dosya → Sıkıştırarak kaydet:** Hafif / Dengeli / Güçlü; sonuçta kaç MB'tan
  kaça indiği gösterilir.
* **Belge → Belge bilgileri (Ctrl+D):** Başlık, yazar, konu, anahtar kelimeler;
  dosya bilgileri; gömülü dosyaları ekleme, dışarı kaydetme, silme.
* **Belge → Güvenlik denetimi:** JavaScript, otomatik eylemler, program çalıştırma,
  veri gönderme, gömülü dosyalar, çoklu ortam, dış bağlantılar, gizli katmanlar ve
  metadata listelenir; seçilenler tek tıkla temizlenir.

## Yeni: Numaralandırma, kırpma, bulanıklaştırma ve notlar

* **Belge → Sayfa numarası, üstbilgi ve altbilgi:** Üst ve altta sol / orta / sağ
  olmak üzere altı alana metin yazılır. Yer tutucular: `{sayfa}`, `{toplam}`,
  `{tarih}`, `{dosya}`, `{bates}`. Hazır düzenler, ilk sayfa numarası, sayfa aralığı,
  "kapağa yazma" ve yazı rengi/boyutu seçilebilir; pencerede canlı önizleme metni
  görünür. Döndürülmüş ve kırpılmış sayfalarda da düz yazılır. Sonuç yeni bir PDF
  olarak kaydedilir, açık belgeniz değişmez.
* **Belge → Bates numaralandır:** `ÖNEK-000001` biçiminde ardışık, benzersiz sayfa
  tanıtıcısı (önek, hane sayısı, başlangıç değeri, sonek). Başlangıç değerini
  değiştirerek ikinci bir seti kaldığınız yerden sürdürebilirsiniz.
* **Belge → Sayfaları kırp:** Dört kenardan mm cinsinden kırpma, "içeriğe göre
  otomatik" (beyaz kenarları algılar) ve bu sayfa / tüm sayfalar / aralık seçimi.
  Mevcut işaretler yeni köşeye göre kayar; **Ctrl+Z** her şeyi geri alır. Yakala
  aracıyla (C) bir alan seçince açılan pencerede "Sayfayı bu alana kırp" da vardır.
  Kırpma sayfanın görünen alanını (CropBox) küçültür, içerik silinmez.
* **Bulanıklaştır aracı (B):** Alanı sürükleyin; biçim **Bulanık** ya da **Mozaik**,
  güç kaydırıcıyla ayarlanır. Dışa aktarırken alan görüntü olarak işlenir ve
  altındaki metin PDF'ten kalıcı silinir (kopyalanıp okunamaz). Düzenleme
  sırasında mavi taralı kutu görünür. Kesin gizlilik gereken veriler için yine
  "Gizle" aracı önerilir. Bulanıklık, kendisinden sonra eklenen işaretleri etkilemez.
* **Yapışkan Not aracı (M) ve Yorumlar paneli (Ctrl+Shift+M):** Sayfaya tıklayıp not
  yazın; çift tıklayarak düzenleyin, taşıyın. Sol şeritteki **Yorumlar** paneli tüm
  notları sayfa sırasıyla listeler; tıklayınca sayfaya gider. **Yanıtla**,
  **Çözüldü / Yeniden aç**, **Düzenle**, **Sil**, açık/çözüldü süzgeci, arama ve
  "Yorumları metin olarak kaydet" vardır. Her değişiklik geri alınabilir. Notlar
  PDF'e gerçek "Not" açıklaması olarak yazılır (yanıtlar içeriğine eklenir), böylece
  başka PDF okuyucularında da görünür; proje (JSON) dosyasına yanıtlarıyla kaydedilir.
  Bu sürümde PDF'in içinde zaten bulunan eski notlar panele alınmaz.

## Yeni: PDF formları

* **Mevcut formu doldurma:** Seç aracıyla (V) bir alana tıklayın. Metin, tarih
  (takvimli) ve açılır liste alanları sayfanın üstünde açılır; **Enter** kaydeder,
  **Tab / Shift+Tab** sonraki / önceki alana geçer, **Esc** vazgeçer. Onay kutusu ve
  radyo düğmesi tek tıkla işaretlenir. Türkçe karakterler (ş, ğ, ı, İ) doğru görünür.
  Her değişiklik **Ctrl+Z** ile geri alınır; kaydedilen PDF başka okuyucularda da dolu açılır.
* **Formlar paneli** (sol şerit / Form menüsü): tüm alanlar sayfa sırasıyla adı, türü ve
  değeriyle listelenir. Çift tıklama alana gider ve düzenler. **Sıfırla** tüm alanları
  boşaltır (geri alınabilir), **Hesapla** hesaplanan alanları günceller, **Özellikler** ve
  **Sil** seçili alan içindir. "Alanları vurgula" alanları açık maviyle gösterir (yalnızca ekranda).
* **Kendi formunu oluşturma — Form Alanı aracı (F):** Özellik çubuğundan alan türünü seçin,
  sayfada bir kutu çizin (onay/radyo için tıklamak yeter). Türler: **metin alanı**, **onay
  kutusu**, **radyo düğmesi** (aynı grup adındakilerden yalnızca biri seçilir), **açılır
  liste** (seçenekler satır satır), **tarih** (gg.aa.yyyy vb.) ve **hesaplanan alan**
  (seçilen alanların toplamı, çarpımı, ortalaması, en küçüğü ya da en büyüğü; "1.234,5" ve
  "2,5" gibi yazımları anlar). Mevcut bir alana Form Alanı aracıyla tıklamak özelliklerini açar.
  Alanlar Acrobat uyumlu yazılır: tarih ve hesaplama betikleri diğer okuyucularda da çalışır.
* **Yazdır (Ctrl+P):** Windows yazdırma penceresi; tüm sayfalar, sayfa aralığı ya da geçerli
  sayfa. Çıktıya işaretler ve form değerleri dahildir; yatay sayfalar yatay basılır.
* Sınırlamalar: imza ve düğme alanları listelenir ama düzenlenmez; çok satırlı alanlarda
  Türkçe karakterli metin basit sözcük kaydırmayla çizilir; proje (JSON) dosyası form
  değerlerini taşımaz — değerler PDF olarak kaydedilince korunur.

## Yeni: Elektronik ve dijital imza

* **Elektronik imza — İmza aracı (G):** "Yeni imza…" ile imzanızı fareyle **çizin**, adınızı el
  yazısı yazı tipiyle **yazın** ya da taranmış **görselden** alın (beyaz arka plan saydamlaştırılır).
  İmzalar kaydedilir; sonra sayfada tıkladığınız yere tek tıkla basılır ("Tarih ekle" isteğe bağlı).
  Bu görsel bir imzadır; Seç aracıyla taşınıp boyutlandırılabilir.
* **İmza alanı oluştur** (İmza menüsü ya da Form Alanı aracında "İmza alanı"): başkalarının
  dijital imzalaması için boş imza kutusu ekler.
* **Dijital olarak imzala (.pfx/.p12):** sertifika + parola, yer (boş imza alanı, görünür kutu ya da
  görünmez), neden ve konum seçilir; imzalı kopya ayrı dosyaya yazılır. Değişiklik yapılmamış
  PDF artımlı imzalanır, önceki imzalar bozulmaz. Deneme için "Oluştur…" kendinden imzalı
  sertifika üretir.
* **İmzaları doğrula:** her imza için imzalayan, zaman, bütünlük, kriptografik geçerlilik,
  sertifika güveni ve **imzadan sonra değişiklik** (yok / form / açıklama / içerik) raporlanır.
  Not: imzalı bir belgeyi işaretleyip yeniden kaydetmek mevcut imzaları geçersiz kılar.

## Yeni: Görsel iş akışı (adım zinciri)

**Belge → Görsel iş akışı (Ctrl+Shift+W)** kod yazmadan adım zinciri kurar; belge açık olmasa da çalışır.

* **Adımlar:** OCR · Döndür · Filigran · Sayfa numarası/üstbilgi (Bates dahil) · KVKK karartma · Sıkıştır ·
  Erişilebilirlik düzeltmeleri (dil, başlık, yer imleri) · Parola/izinler · Word'e dönüştür · Kaydet. Çift tıklayarak ya da zincire sürükleyerek eklenir; zincirdeki kartlar sürüklenerek
  yeniden sıralanır, onay kutusu adımı atlar, çöp kutusu siler. Seçili adımın ayarları sağda açılır.
  Hazır motorlar yeniden kullanılır (ocr, headfoot, pii, docsec, filigran) — ayrı bir uygulama yolu yoktur.
* **Sıra kuralı:** sayfaları değiştiren adımlar yazıldığı sırayla çalışır; **Sıkıştır, Parola, Word'e dönüştür ve Kaydet** sırası ne olursa
  olsun en sonda, tek kayıtta uygulanır. Zincir olası sıra hatalarını önceden uyarır (örn. filigran OCR'dan önceyse
  metinli sayılan sayfalarda OCR atlanabilir; KVKK ya da yer imi üretimi OCR'dan önceyse taranmış sayfada veri/başlık bulunamaz).
  **Word'e dönüştür** sonucu PDF yerine `.docx` yazar (özgün PDF'in üstüne asla yazılmaz; sıkıştırma/parola uygulanmaz,
  zincir bunu uyarır). **Erişilebilirlik düzeltmeleri** boş bırakılan başlıkta mevcut anlamlı başlığı korur, yoksa dosya adını yazar;
  var olan yer imlerine dokunmaz.
* **Şablonlar:** Kaydet / Farklı kaydet / Sil, JSON olarak dışa-içe aktarma. 6 hazır şablon var
  (Taranmış belgeyi düzenle, KVKK paylaşım kopyası, Arşiv paketi, Dosya hazırlığı/Bates, Erişilebilir PDF, Word'e aktar); hazırların üstüne yazılmaz.
  Parola adımında "çalıştırırken sor" açıkken parola şablona ya da ayarlara **yazılmaz**.
* **Hedef:** açık belge (işaretleriyle birlikte işlenir; özgün belge değişmez), seçilen dosyalar (PDF ve resimler) ya da
  bütün klasör (alt klasörler dahil; çıktı ekini taşıyan dosyalar tekrar işlenmez).
* **Çalıştırma:** arka planda, ilerleme çubuğu + **Durdur**. Bir dosyadaki hata diğerlerini durdurmaz; durdurulunca yarım
  dosya bırakılmaz (çıktı geçici dosyaya yazılıp atomik yerine konur). Sonuç tablosunda dosya başına durum, sayfa, boyut
  değişimi, süre ve ayrıntı görünür; çift tıklamak sonucu açar, **Raporu kaydet** CSV/TXT yazar.
* **Kaydet adımı:** aynı klasöre ada ek getirerek (varsayılan `_islendi`), seçilen klasöre (alt klasör yapısı korunabilir) ya da
  özgün dosyanın üstüne (`.yedek.pdf` kopyasıyla). Açık belge için üstüne yazma kapalıdır; güvenli yola düşer.

## Yeni: Metin farkı (iki sürümü karşılaştırma)

**Görünüm → Metin farkını göster** (ya da karşılaştırma modunu açmak) iki belgenin metnini otomatik karşılaştırır.

* **Vurgu:** sol panelde (eski sürüm) silinen/değişen metin **kırmızı**, sağ panelde (yeni sürüm) eklenen/değişen metin **yeşil**
  boyanır. Konumlar sayfanın görünen yönüne göre hesaplanır; döndürülmüş sayfalarda da doğru oturur.
* **Değişiklikler paneli:** sağda, sayfa sayfa gruplanmış liste (`+` eklenen, `−` silinen, `≠` değişen: eski → yeni).
  Eklenen / Silinen / Değişen süzgeçleri vardır; süzgeç vurguları da günceller.
* **Listeden git:** bir satıra tıklamak iki paneli de ilgili sayfaya götürür ve değişikliği mavi halkayla işaretler.
  Eklemede eski belgede, silmede yeni belgede karşılık gelen nokta gösterilir. **F8 / Shift+F8** sonraki / önceki değişikliğe geçer.
* **Rapor:** panelin altındaki **Raporu kaydet…** sayfa sayfa *eski | yeni* tablosunu HTML ya da PDF olarak yazar (eklenen yeşil,
  silinen kırmızı çizgili; değişen parçada yalnızca farklı kelimeler vurgulanır; belge metni kaçışlanır). Süzgeçten bağımsız tüm değişiklikler girer.
* **Nasıl çalışır:** önce satır, sonra değişen satırların içinde kelime düzeyinde fark alınır (arka planda, arayüz donmaz).
  Sol/sağ belge ya da "Büyük/küçük harfi yoksay" değişince otomatik yeniden hesaplanır.
* **Sınırlar:** yalnızca metin katmanı karşılaştırılır; taranmış (metinsiz) belge için önce OCR gerekir (panel uyarır).
  Görsel/çizim farkı ve henüz kaydedilmemiş işaretler karşılaştırmaya girmez.

## Yeni: Word / Excel'e dönüştürme

**Belge → Word'e dönüştür (.docx)** ve **Excel'e dönüştür (tablolar, .xlsx)**. Dönüştürme belgenin işaretli kopyasından,
arka planda yapılır; kapsam tüm belge ya da yalnız geçerli sayfadır. Çıktı geçici dosyaya yazılıp yerine konur (yarım dosya kalmaz).

* **Word:** `pdf2docx` ile metin, tablo, görsel ve yazı biçimi korunmaya çalışılır. Karmaşık düzenlerde küçük kaymalar olabilir.
  Metinsiz (taranmış) sayfalar resim olarak kalır; pencere bunu uyarır, önce OCR çalıştırın.
* **Excel:** sayfalardaki tablolar algılanır (çizgili tablolar en iyi sonucu verir); her tablo ayrı sayfaya (`S3-T1`) yazılır,
  ilk satır kalın başlıktır. Sayılar hücrede **sayı** olur (`1.250,50` → 1250,5); ondalık biçimi seçilir. Baştaki sıfırlı kodlar
  (`007`) ve 15 haneden uzun sayılar metin kalır. Tablo bulunamazsa dosya yazılmaz, nedeni söylenir.

## Yeni: Erişilebilirlik denetimi

**Belge → Erişilebilirlik denetimi…** sekiz kontrolü çalıştırır (✓ geçti · ⚠ uyarı · ✕ sorun · ℹ bilgi):

| Kontrol | Ne bakar | Düzeltme |
|---|---|---|
| Etiketli PDF | Yapı ağacı + "etiketli" işareti | Yok (kaynak uygulamadan etiketli dışa aktarın) |
| Belge dili | `/Lang` | **Tek tık** (metinden önerilir: tr-TR, en-US…) |
| Belge başlığı | Başlık dolu mu, dosya adına benziyor mu, pencere başlığında gösteriliyor mu | **Tek tık** (ilk sayfadaki en büyük satır önerilir) |
| Başlık yapısı | Etiket ağacında H/H1–H6 ya da yer imleri | **Tek tık:** görsel başlıklardan yer imi üretir |
| Alternatif metin | Etiket ağacındaki `Figure` öğelerinde `Alt`; etiketsiz belgede görsel sayısı | Yok (alt metin içerik bilgisi ister) |
| Okuma sırası | Etiketliyse bilgi; etiketsizde içerik akışı görsel sıraya uyuyor mu (sezgisel) | Yok |
| Gömülü yazı tipleri | Gömülü olmayan yazı tipleri | Yok |
| Taranmış sayfalar | Yalnızca resimden oluşan sayfalar | **Tek tık:** OCR (arka planda, sayfa metinli sürümüyle değişir) |

Düzeltilebilenler onay kutularıyla seçilir; dil ve başlık yerinde düzenlenebilir. Düzeltmeler açık belgeye uygulanır
(Ctrl+Z ile geri alınmaz) ve kaydedince PDF'e yansır. OCR, taranmış sayfanın görüntüsünü yeniden kodlar ve o sayfadaki
özgün bağlantı/form alanlarını taşımaz. **Raporu kaydet…** HTML ya da TXT yazar. Denetim belgenin kopyasında çalışır, arayüz donmaz.

## Yeni: Telefonla aktar (QR)

**Dosya → Telefonla aktar (QR)…** yerel ağda geçici bir web sayfası açar ve QR'ını gösterir; ek uygulama gerekmez.

* **Telefondan bilgisayara:** QR'ı telefonun kamerasıyla okutun; açılan sayfada **Dosya veya fotoğraf seç** ya da **Kamerayla çek**
  düğmesi vardır (birden çok dosya, ilerleme çubuğu). Gelen dosya `Belgelerim\PDF Annotator Gelen` klasörüne kaydedilir
  (**Klasör…** ile değişir) ve uygulamada açılır ("Gelen dosyaları otomatik aç" kapatılabilir; listeden çift tıklayınca da açılır).
* **Bilgisayardan telefona:** **Açık belgeyi telefona sun**, açık belgeyi işaretleriyle birlikte PDF olarak sunar; telefondaki
  sayfanın "Bilgisayardan indir" bölümünde birkaç saniye içinde görünür. Belgeyi değiştirdiyseniz yeniden sunun.
* **Güvenlik:** adresin içinde her açılışta yeni, rastgele (128 bit) bir anahtar vardır; anahtarsız ya da yanlış istek 404 alır.
  Sunucu yalnızca seçili yerel adrese bağlanır (birden çok ağ varsa pencereden seçilir). Yalnızca **PDF ve resim** kabul edilir
  (uzantı + dosya imzası denetlenir; `.exe` vb. reddedilir), dosya adı temizlenir (yol geçişi, Windows'ta yasak adlar),
  dosya başına 200 MB, oturum başına 100 dosya / 1 GB sınırı vardır; yarım yüklemeler kaydedilmez.
* **Durma:** pencere kapanınca, uygulama kapanınca ya da 15 dk boşta kalınca sunucu durur; sunulan geçici dosyalar silinir.
* **Notlar:** telefon ve bilgisayar aynı Wi‑Fi ağında olmalı; bağlanamazsa Windows Güvenlik Duvarı'nda "özel ağlar"a izin verin.
  Bağlantı şifrelenmez (HTTP), bu yüzden yalnızca güvendiğiniz ağda kullanın. iPhone'da HEIC yerine "En uyumlu" (JPEG) biçimi gerekir.

## Yeni: Belge tarama
**Dosya → Belge tara (görsellerden)…** fotoğrafları (ya da PDF'leri), **Belge → Bu belgeyi tara/kırp…** açık belgenin sayfalarını (200 dpi) tarama penceresinde açar.

* **Köşeler:** kâğıt otomatik bulunur; 4 kulpu sürükleyerek ayarlayın (**Otomatik algıla**, **Tüm görsel**). **Sonuç** sekmesi düzeltilmiş görüntüyü gösterir.
* **Filtre:** orijinal, otomatik, belge (gölgesiz siyah-beyaz), gri, canlı, gölgesiz renkli; parlaklık/kontrast ve ↺ ↻ döndürme. Her sayfanın ayarı ayrıdır.
* **Sayfa şeridi:** sayfa ekle/sil, ◀ ▶ ya da sürükleyerek sırala.
* **PDF oluştur…:** A4 / Letter / orijinal oran, JPEG kalitesi, isteğe bağlı **Aranabilir yap (OCR)**; iş arka planda çalışır, **Durdur** ile iptal edilir, sonuç yeni sekmede açılır.

## Yeni: Görselleri PDF'e çevir ve telefondan taramaya aktarma
* **Dosya → Görselleri PDF'e çevir…:** görselleri (ya da klasörü) pencereye sürükleyin/ekleyin, sırayı düzenleyin; sayfa boyutu (A4/Letter/orijinal), yön, kenar boşluğu ve JPEG kalitesi seçin. **Tek PDF** ya da **her görsel ayrı PDF** (var olan ad bozulmaz); sonuç uygulamada açılır (ayrıda en çok 10 sekme).
* **Telefonla aktar (QR) → "Gelen fotoğrafları tarayıcıda aç":** gelen fotoğraflar belge olarak açılmaz, birikir; **Taramayı bitir (N)** hepsini Belge tara penceresinde açar. PDF'ler eskisi gibi açılır.

## Yeni: Tercihler, çalışma klasörü ve otomatik kurtarma
**Düzenle → Tercihler… (Ctrl+,)** değişiklikleri anında kaydeder.

* **Çalışma klasörü:** varsayılan `Belgeler\PDF Annotator`; Seç / Aç / Sıfırla. Altında `Gelen` (QR ile gelenler), `Taramalar`,
  `Donusturulenler` (Word/Excel), `Projeler`, `Yedekler`, `IsAkisi`. Her tür için "çalışma klasörüne kaydet" kutusu vardır;
  açıkken ilgili pencere (QR gelenleri, Belge tara, Word/Excel dönüştür, proje kaydet/aç, iş akışı varsayılan hedefi)
  varsayılan yol olarak orayı önerir, kapalıyken eski davranışa (belgenin yanı) döner. Pencerede elle seçtiğiniz yol her zaman önceliklidir.
  Eski `Belgeler\PDF Annotator Gelen` klasöründe dosya varsa açılışta **taşıma önerilir** (dosyalar silinmez, aynı ad ezilmez).
* **Otomatik kurtarma:** açıkken (1–10 dk, varsayılan 3) değişmiş belgelerin taslağı `Yedekler\kurtarma`'ya yazılır (belge + işaretler).
  Uygulama beklenmedik kapanırsa sonraki açılışta *Kurtar / Şimdilik değil / Sil* sorulur; kurtarılan belge değişmiş sayılır, özgün
  yoluyla açılır. Kaydetme ve normal kapanış taslağı siler. **Parolalı belgeler düz metin yedeklenmesin diye yedeklenmez.**
* **Genel:** tema (sistem/açık/koyu), son kullanılan klasörü hatırlama (Aç penceresi).
* Çalışma klasörünü `PDF_ANNOTATOR_WORKSPACE` ortam değişkeniyle de belirleyebilirsiniz (ayarı geçersiz kılar).

## Yeni: Daha nazik sansür görünümü
* **Düzenlerken yumuşak:** sansür kutusu yarı saydam (~%55) dolgu, ince açık kenar ve yuvarlatılmış köşeyle görünür; altındaki metin
  hâlâ seçilip kontrol edilebilir. **Görünüm → Sansürün nihai görünümü** (ya da araç çubuğundaki kutu) ekranda da çıktıdaki gibi
  tam dolgu/kenarsız gösterir. Bu yalnız ekran görünümüdür: **dışa aktarılan PDF her zaman dikdörtgen + tam dolgudur** ve kaydedince
  altındaki metin ve resim PDF'ten **kalıcı silinir** (sansür aracı ilk seçildiğinde ve araç ipucunda hatırlatılır).
* **Dolgu ve etiket:** özellik çubuğunda Siyah / Koyu gri / Beyaz hazırları (+ özel renk) ve isteğe bağlı **etiket metni**
  ("GİZLİ", "[KARARTILDI]" ya da kendi metniniz; Türkçe harfler desteklenir). Etiket kutunun ortasına, dolguya göre beyaz ya da siyah
  yazılır; kutuya sığmıyorsa yazılmaz (silme yine olur). KVKK penceresi aynı seçenekleri kullanır.
* **Eski projeler** (etiket alanı olmayan JSON) olduğu gibi açılır.
* **Düzeltme:** döndürülmüş sayfalarda sansür kutusu artık görünen konuma göre uygulanır (önceden altındaki metin silinmeyebiliyordu).

## Yeni: Tarama sonrası müdahale ve PDF düzleştirme
* **Belge tara → Düzeltme:** **Otomatik eğim düzelt** metin satırlarının eğimini bulup kaydırıcıya yazar (elle ±15°, 0,1° adım; belirgin metin yoksa
  dokunmaz). **Gölge düzleştir** her filtrede açılıp kapatılabilir (Belge ve Gölgesiz renkli'de varsayılan açık). **Temizle fırçası** Sonuç
  görünümünde leke/parmak izini beyaza boyar (geri alınabilir; yalnız bu taramada, çıktıya pişer; köşe/döndürme/eğim değişince sıfırlanır).
  **Bu sayfayı sıfırla** yalnız seçili sayfanın tüm ayarlarını başa alır; her sayfanın ayarı ayrıdır.
* **Belge → Düzleştir ve kaydet…:** işaretleri, yorumları, vurguları ve **form alanlarını** sayfa içeriğine gömer (artık düzenlenebilir nesne kalmaz,
  görünüm aynı; metin kalır). **Sayfaları resme çevir** seçeneği (150/200/300 dpi, JPEG kalitesi) metni de kaldırır: kopyalanamaz/aranamaz.
  Açık belge değişmez, sonuç `*_duzlestirilmis.pdf` olarak kaydedilip yeni sekmede açılır; iş arka planda çalışır, durdurulabilir.
  Sansür kutuları önce gerçekten uygulanır (altındaki metin silinir), sonra gömülür.

## Yeni: Paylaşım seçenekleri (yerel ağ dışında)
* **Aynı ağda değil misiniz?** (QR penceresi): telefonun **mobil sıcak noktasına** bilgisayarı bağlayın (internet gerekmez), *Ağ adresi*
  listesinden yeni adresi seçip QR'ı yeniden okutun; **Wi‑Fi ayarlarını aç** düğmesi vardır. Aktarım yine doğrudan telefon ile bilgisayar arasındadır.
* **Dosya → Paylaş:** **E-postayla gönder** (Outlook varsa dosya ekli yeni ileti; yoksa dosyanın klasörü açılır + boş e-posta, dosyayı sürükleyin),
  **Bulut klasörüne kaydet** (bilgisayarınızda bulunan OneDrive / Google Drive / Dropbox klasörlerinden birine kopya; eşitlemeyi o uygulama yapar),
  **Dosya konumunu aç**. Kaydedilmemiş değişiklik varsa özgün dosya yerine işaretli kopya kullanılır.
* **Deneysel — kendi internet tünelim:** QR penceresinde *Gelişmiş* kutusu. cloudflared/ngrok gibi **kendi kurduğunuz** tünelin adresini girin, tüneli gösterilen
  yerel bağlantı noktasına yönlendirin. Sunucu yalnız `127.0.0.1`'de dinler ve **6 haneli PIN** ister (telefon önce PIN sayfasını görür); **5 yanlış denemede kilitlenir**
  (doğru PIN de kabul edilmez; *Kilidi aç* ya da *Yeni PIN*). Uygulama tünel servisiyle **kendisi bağlanmaz**; yalnızca adresi QR'a yazar. Dosyalar o servisten geçer.
  Güvenlik kuralları aynıdır (anahtarlı adres, yalnız PDF/resim, boyut/adet sınırı).
