# Yol haritası — sıradaki aşamalar

Sıra (tamamlananlar I…K3). **Sıradaki: L1 → L2 → L3 → L4 (sürüm 1.1.0, aşağıda).** Her aşama ayrı sohbette, ayrı commit'te yapılır (J bölünmesi bitti: kod mw_*.py dosyalarında, küçük okumalar yeter).
Tamamlananlar: B, C1, C2, D1, D2, E, F, G1–G3, H1, H2, J1–J3, testler. Eski G1–J3 bölümleri yalnızca kayıt içindir; yeniden okumaya gerek yok.

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

## I1 — Tercihler penceresi + çalışma klasörü + otomatik kurtarma
**Mevcut durum:** Tercihler penceresi yok; ayarlar `QSettings`'te dağınık (`recent`, `qrReceiveDir`, geometri…). QR gelenleri `Belgeler\PDF Annotator Gelen`'e, diğer çıktılar her diyalogda ayrı yola gider. Otomatik kurtarma yok.
**Yapılacak**
- `workspace.py` (arayüzsüz): `root()` (varsayılan `Belgeler\PDF Annotator`, ayardan okunur), `sub(ad)` → alt klasörü oluşturup döndürür (`Gelen`, `Taramalar`, `Donusturulenler`, `Projeler`, `Yedekler`, `IsAkisi`), `migrate_old_inbox()` (eski `PDF Annotator Gelen` varsa taşımayı öner, sessizce silme).
- `ui/preferences.py` `PreferencesDialog` (Düzenle → Tercihler…, Ctrl+,): **Çalışma klasörü** (seç/aç/sıfırla), "Çıktıları buraya kaydet" kutuları (QR gelenleri, tarama PDF'leri, Word/Excel dönüşümleri, iş akışı varsayılan hedefi, proje JSON), **Otomatik kurtarma** (aç/kapa, süre: 1–10 dk), tema, "Son klasörü hatırla". Güncelleme bölümü K3'te eklenecek (şimdilik yer tutucu bırakma).
- Otomatik kurtarma: değişmiş (`dirty`) oturumlar için `Yedekler\kurtarma\<id>.json/.pdf` taslağı (işaretler + belge baytları); açılışta "Kapanmayan belgeler bulundu, kurtarılsın mı?"; normal kapanış/kaydetme taslağı siler.
- Mevcut diyalogların varsayılan klasörlerini `workspace.sub()`'a bağla (ScanDialog, ConvertDialog, ShareDialog, WorkflowDialog "Kaydet" adımı, proje kaydet/aç).
**Yeniden kullan:** `QSettings` (`self.settings`), `ui/share.default_receive_dir`, `mw_*` içindeki kaydet diyalogları (Grep `getSaveFileName`), `ui/theme`.
**Bitti ölçütü:** `check_workspace.py` — klasör oluşturma/ayar kalıcılığı, taşıma, kurtarma taslağı yazma/okuma/silme; pencere açılır, değişiklik ayara yansır (geçici `QSettings`).

## I2 — Daha "nazik" sansür görünümü (+ gerçek silme güvencesi)
**Mevcut durum:** `models.RedactionAnnotation`: düz dolgu + kırmızı kesikli 1,5 px kenar (`create_item`). Dışa aktarırken `pdf_engine._annotated_copy` → `add_redact_annot` + `apply_redactions` ile alttaki **metin/resim PDF'ten kalıcı silinir** (yalnız kaydet/dışa aktarmada; özgün dosya siz kaydedene kadar değişmez, çalışırken geri alınabilir). Metin düzenle ("quiet") ve KVKK da aynı sınıfı kullanır.
**Yapılacak**
- Düzenleme sırasında yumuşak görünüm: hafif saydam dolgu (alpha ~%55) + ince, açık kenar (kesikli kırmızı yerine tema vurgusu), yuvarlatılmış köşe (yalnız ekranda); "Nihai görünüm" anahtarı (dolgu %100, kenarsız) — çıktı değişmez (dikdörtgen, tam dolgu).
- Özellik çubuğunda: dolgu rengi (siyah / koyu gri / beyaz / özel), isteğe bağlı **etiket metni** ("GİZLİ", "[KARARTILDI]"; PyMuPDF `add_redact_annot(text=…, fill=…)`), KVKK'da aynı seçenekler.
- Araç ipucu/ilk kullanım metni: "Kaydedince altındaki metin ve resim PDF'ten KALICI silinir."
**Yeniden kullan:** `models.py` (RedactionAnnotation, `to_dict/_from_dict` — yeni alanlar geriye uyumlu: eski projeler açılmalı), `mw_annot.py`/özellik çubuğu (Grep `redact`), `ui/kvkk.py`, `pdf_engine._annotated_copy`.
**Bitti ölçütü:** `check_redaction.py` — dışa aktarılan PDF'te sansürlenen metin `get_text()`'te YOK ve görüntüde dolgu rengi var; etiketli sansür; eski JSON proje yüklenir; nihai-görünüm anahtarı sahne öğesini değiştirir.

## I3 — Tarama sonrası müdahale + düzleştirme (eğim/gölge/PDF)
**Mevcut durum:** `scan.py`: perspektif düzeltme (`warp`), `rotate(derece)`, filtreler (`belge` filtresindeki `_flatten` gölge/aydınlatma düzleştirir); **eğim (deskew) yok**. `ui/scanner.py`: köşe sürükleme, filtre, parlaklık/kontrast, döndür, sayfa şeridi. PDF "düzleştirme" (işaret/form gömme) seçeneği yok.
**Yapılacak**
- `scan.deskew(img, max_derece=15)` → (görüntü, bulunan açı) (metin satırı eğimi: eşik → `minAreaRect`/Hough, güvenilmezse 0); `ScanDialog`'a "Otomatik eğim düzelt" + **eğim açısı kaydırıcısı** (±15°, elle); "Gölge düzleştir" her filtrede açılıp kapanır; **sayfa başına** geri alma ("Bu sayfayı sıfırla").
- İsteğe bağlı: "Temizle" fırçası (beyaz boyama; leke/parmak) — yalnız taramada, kalıcı değil önizlemeden pişirilir.
- **PDF düzleştirme:** Belge → "Düzleştir ve kaydet…": işaretleri, yorumları ve form alanlarını sayfa içeriğine gömer (PyMuPDF `Document.bake` varsa onu kullan, yoksa alan/işaret tek tek içeriğe yaz); ek seçenek "Sayfaları resme çevir (metin kopyalanamaz)".
**Yeniden kullan:** `scan.py`, `ui/scanner.py`, `ui/convert.BackgroundJob`, `pdf_engine.export_pdf/_annotated_copy`, `forms.py`.
**Bitti ölçütü:** `check_scan.py`'ye deskew (sentetik 5° eğik metin → ≤0,5° kalır, eğimsizde dokunmaz) ve `check_flatten.py` (düzleştirilmiş PDF'te işaret/alan nesnesi yok ama görünüm var, resme çevirmede metin yok).

## I4 — Paylaşım seçenekleri (yerel ağ dışında)
**Mevcut durum:** QR aktarımı yalnızca **aynı yerel ağda** çalışır (`qrshare.py`, `ui/share.py`).
**Yapılacak**
- QR penceresine "Aynı ağda değil misiniz?" yardımı: telefonun **mobil sıcak noktasına** bilgisayarı bağlamak (internet gerekmez, QR aynı çalışır); ağ adresi seçimi zaten var.
- **Paylaş** menüsü (Dosya): e-postayla gönder (varsayılan posta istemcisi; Outlook varsa eklentili, yoksa dosyayı seçili klasörde aç + boş e-posta), **bulut klasörüne kaydet** (OneDrive / Google Drive / Dropbox yerel klasörünü algıla; senkronu o uygulama yapar), dosya konumunu aç.
- Deneysel/isteğe bağlı: internet üzerinden QR için **kullanıcının kendi kurduğu tünel** (cloudflared/ngrok) adresini girme alanı; bu durumda sunucu **6 haneli PIN** ister (5 yanlış denemede kilit). Uygulama üçüncü taraf bir servisle kendisi konuşmaz; uyarı metni: dosyalar o servisten geçer.
**Yeniden kullan:** `qrshare.ShareServer` (PIN için `token` yanında `pin` ekle), `ui/share.py`, `workspace.py` (I1), `os.startfile`/`QDesktopServices`.
**Bitti ölçütü:** `check_qrshare_*`'a PIN kontrolleri (yanlış PIN reddi, kilit, doğru PIN geçer); bulut klasörü algılama (sahte ortam değişkeni/klasör), e-posta/konum açma çağrıları (sahte `QDesktopServices`).

## I5 — Kullanılabilirlik denetimi ve iyileştirme (iki adım, ayrı sohbetler)
**Not:** "Arayüz kullanışlı mı?" sorusuna denemeden dürüst cevap verilemez; bu aşama ölçer, sonra düzeltir.
**I5a (yalnız denetim, kod yok):** pencereyi temiz ayarlarla açıp 8 temel durumun **tek seferde** ekran görüntüsünü al (boş açılış, PDF açık, araç seçili, sansür, karşılaştırma, tarama, Tercihler, Belge menüsü); sezgisel değerlendirme (görünürlük, tutarlılık, hata önleme, kısayollar, boş durumlar), menü yoğunluğu sayımı (Belge menüsü 20+ eylem), kısayol çakışmaları, Türkçe/ikon tutarlılığı, geri alınamayan işlemler (a11y düzeltmeleri, sansür). Çıktı: `UX_RAPOR.md` — kritik/orta/düşük öncelikli, her madde için tahmini efor. Ayrıca 10 görevlik **kullanıcı deneme listesi** (ör. "bir PDF'i aç, bir paragrafı sansürle, kaydet") — kullanıcı kendisi dener, takıldığı yerleri yazar.
**I5b (uygulama):** kullanıcının onayladığı en yüksek 5–8 madde (olası örnekler: alt menülere gruplama, boş durum ipuçları/ilk kullanım turu, araç ipuçlarında kısayol, durum çubuğu geri bildirimi, geri alınabilir düzeltmeler, klavye erişimi, yüksek DPI/kontrast).
**Bitti ölçütü:** I5a: rapor + deneme listesi commit'li; I5b: seçilen maddeler + ilgili check betikleri + tam pytest; tek ekran görüntüsü (sonda).

## S1 — Sağlamlık (çökme avı; K1'den önce)
**Amaç:** davranış değişmeden çökme/donma/veri kaybı riskini azalt.
- `crashguard.py`: `sys.excepthook` + `threading.excepthook` + Qt ileti işleyicisi + `faulthandler`; günlük `<çalışma klasörü>\Gunlukler\pdfannotator.log` (dönen, ~1 MB x 3); yakalanmamış hata uygulamayı kapatmaz → Türkçe uyarı (toast + "Günlüğü aç"), aynı hata 60 sn içinde tekrar uyarmaz, taslak hemen yazılır.
- `tests/scripts/check_robustness.py`: bozuk/boş/parolalı/dev dosyalar, kapanışta arka plan işleri, belgesiz eylemler, geri al sınırları, yazma hataları.
- Çıktı: `SAGLAMLIK_RAPOR.md` (kritik/orta/düşük, tekrar adımı, durum); kritik+orta düzeltilir (≤~15), her biri için regresyon kontrolü.
**Bitti ölçütü:** tam pytest yeşil; README ve CLAUDE.md'de günlük konumu notu.

## K1 — Sürüm 1.0.0, PyInstaller derlemesi, kendi kendini sınama
**Başlangıç:** bu aşamada yayın sürümü **1.0.0** olur.
**Yapılacak**
- `appinfo.py`: `APP_NAME="PDF Annotator"`, `VERSION="1.0.0"`, `PUBLISHER`, `APP_ID` (sabit GUID; kurucu ve güncelleme aynısını kullanır), `UPDATE_URL=""` (K3). Hakkında penceresi, pencere başlığı ve exe sürüm bilgisi buradan okunur (tek kaynak).
- `pdfannotator.spec` (**onedir**; onefile yavaş açılır): `datas`: `tessdata/` (tur+eng), `fonts/`, `ui` varlıkları; `hiddenimports`: pdf2docx, pyhanko, segno, openpyxl, cv2, pymupdf; gereksizleri hariç tut (tkinter, matplotlib, test paketleri); simge (`app.ico`; yoksa SVG'den üret); çıktı `dist\PDF Annotator\`. `build.bat`: temiz `venv` kurar, `pip install -r requirements.txt pyinstaller`, derler.
- `--selftest` bayrağı: uygulamayı açmadan tüm modülleri içe aktarır, tessdata/fonts/ikonları bulur, küçük PDF'i render eder + OCR + Word/Excel/QR/tarama çekirdeğini bir kez çalıştırır, `selftest.txt` yazar, hata varsa çıkış kodu 1.
**Bitti ölçütü:** `build.bat` çalışır; `dist` içindeki exe, **Python'un PATH'te olmadığı** ortamda `--selftest` ile geçer; eksik dosya/DLL varsa spec düzeltilir (kaynak dosyalar). Kullanıcı bir PDF açıp OCR/kaydet dener (tek elle deneme).

## K2 — Profesyonel kurucu (setup.exe, Denetim Masası kaydı)
**Araç:** Inno Setup 6 (ücretsiz; derleyici `ISCC.exe` gerekir — `winget install JRSoftware.InnoSetup`; kurmadan önce kullanıcıya sor).
**Yapılacak**
- `kurulum.iss`: `AppId={APP_ID}` (güncellemede aynı uygulama olarak üzerine kurulsun), `AppName/AppVersion/AppPublisher/AppPublisherURL`, `DefaultDirName={autopf}\PDF Annotator`, `PrivilegesRequiredOverridesAllowed=dialog` (kullanıcı başına ya da tüm kullanıcılar), `UninstallDisplayIcon`/`UninstallDisplayName` → **Ayarlar/Denetim Masası "Program Ekle/Kaldır" listesinde görünür ve oradan kaldırılır** (Inno bunu otomatik yazar), Başlat menüsü + isteğe bağlı masaüstü kısayolu, isteğe bağlı ".pdf dosyalarını PDF Annotator ile aç" ilişkilendirmesi, `CloseApplications=yes`, Türkçe + İngilizce sihirbaz dili, lisans/README sayfası, kaldırırken "Ayarlar ve çalışma klasörü silinsin mi?" (varsayılan: hayır; kullanıcının belgelerine dokunma).
- Çalışma zamanı: PyInstaller çıktısı VC++ çalışma zamanı DLL'lerini içerir; yine de yoksa `vc_redist.x64.exe`'yi (sessiz) kuran isteğe bağlı bölüm.
- `build.bat` sonunda `ISCC kurulum.iss` → `dist\PDF-Annotator-Setup-1.0.0.exe`; SHA-256 yazdır.
- **İmza notu:** imzasız kurucuda Windows SmartScreen "bilinmeyen yayıncı" uyarısı verir (profesyonellik için kod imzalama sertifikası gerekir; ayrı karar). README'ye "Daha fazla bilgi → Yine de çalıştır" açıklaması ekle.
**Temiz makine doğrulaması:** Windows 11 **Home**'da Windows Sandbox yoktur. Sırayla: (1) yeni bir yerel kullanıcı hesabında kur-çalıştır-kaldır, (2) mümkünse VirtualBox VM, (3) **kullanıcı başka bir bilgisayarda kontrol listesiyle dener** (kurulum, başlat menüsü, PDF aç, OCR, Word dönüştürme, QR, kaldırma → Program Ekle/Kaldır'dan gittiğini doğrula). Liste `README`'de.
**Bitti ölçütü:** setup.exe üretilir; kurucu sessiz modda (`/VERYSILENT`) temiz bir kullanıcı profilinde kurulur, `--selftest` geçer, kayıt defterinde Uninstall girdisi vardır, kaldırınca klasör ve girdi gider (otomatik script; kullanıcı verisi korunur).

## K3 — Otomatik güncelleme (yayınladığınızda)
**Önkoşul:** K1 (`appinfo.py`) ve K2 (kurucu). Güncelleme adresi ayarlanana kadar özellik "adres tanımlı değil" diyerek kapalı kalır.
**Yapılacak**
- `updater.py` (arayüzsüz): `check(url)` → `latest.json` (`{"version","url","sha256","notes","size"}`; GitHub Releases `releases/latest` yanıtını da ayrıştır), sürüm karşılaştırma (kendi `1.2.10 > 1.2.9` mantığı, ek paket yok), `download(info, progress, cancelled)` (geçici dosya + ilerleme), **SHA-256 doğrulaması zorunlu** (uyuşmazsa sil ve reddet), yalnızca **HTTPS**, `install(path)` → `setup.exe /SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS` başlatıp uygulamayı kapatır.
- Arayüz: Tercihler → **Güncelleme** bölümü ("Şimdi denetle", "Açılışta denetle" varsayılan açık, "Sürüm notları"), Yardım → Güncellemeleri denetle, yeni sürüm varsa toast + "İndir ve kur" diyaloğu (notlar, boyut). Ağ hatası sessiz (uygulama kullanımı engellenmez).
- `tools/make_release.py`: sürümü `appinfo.py`'den okur, kurucunun SHA-256'sını ve `latest.json`'u üretir; `YAYIN.md`: yayın adımları (sürüm artır → `build.bat` → `make_release.py` → GitHub Release'e kurucu + `latest.json` yükle).
- Kullanıcıdan alınacak: yayın yeri (GitHub deposu mu, kendi sitesi mi) ve adres → `appinfo.UPDATE_URL`.
**Bitti ölçütü:** `check_updater.py` — yerel sahte HTTP sunucusuyla: yeni sürüm bulunur, eski/aynı sürümde "güncel", bozuk SHA-256 reddedilir, HTTP (https değil) reddedilir, indirme iptali; kurulum çağrısı sahte (komut satırı doğrulanır).


---

# Sürüm 1.1.0 — kullanılabilirlik güncellemesi (L1 → L4)
Kaynak: kullanıcı geri bildirimi. **Sıra L1 → L2 → L3 → L4**, her biri ayrı sohbet/commit. Sürüm numarası `appinfo.VERSION`'u **yalnızca L4 sonunda** `1.1.0` yap, `build.bat` + `tools/make_release.py` + GitHub Release (`docs/YAYIN.md`).
Ortak ilkeler: yeni ayar = `QSettings` anahtarı + Tercihler'de görünür; yeni eylem komut paletine otomatik girer (`A(...)`); yeni ikon `ui/icons._PATHS`; kod `src/` altında; testler `tests/scripts/check_<ad>.py` (+ `check_ux.py` menü beklentileri bilerek güncellenir).

## L1 — Arayüz: Ayarlar, komut paleti, sekmeler, Paylaş, e-postayı kaldırma (TAMAM)
**Yapılacak**
- **Ayarlar düğmesi:** üst çubukta görünür ⚙ **Ayarlar** (Dışa aktar'ın yanında). `PreferencesDialog` soldan kategori listesi (Genel · Görünüm · Çalışma klasörü · Tarama · Telefon aktarımı · Güncelleme · Kısayollar) olsun; mevcut bölümleri kategorilere dağıt, davranışı değiştirme.
- **Komut paleti (`ui/palette.py`):** ayarlar da aranabilir ("tema", "çalışma klasörü" → ilgili kategori açılır); en üstte **son kullanılan** komutlar (ayar `palette/recent`, ≤5); her komutta kısayol ve menü yolu gri yazı.
- **Paylaş düğmesi:** Dışa aktar'ın yanında **Paylaş** menü düğmesi: Telefona gönder (L3'teki pencerenin "Gönder" sekmesi), Bulut klasörüne kaydet, Dosya konumunu aç. Telefona gönder için şimdilik mevcut `open_share` yeter.
- **E-posta kaldırılır:** `share_email`, `sharing.compose_email/find_outlook` ve menü/palet girdisi, ilgili testler ve README/CLAUDE.md anlatımı silinir (ölü kod bırakma).
- **Son açılanlar:** her girdinin yanında **×**; tıklayınca o girdi *görünümden* gizlenir (ayar `recent_hidden`, yol listesi); dosya silinmez, `recent` listesinde kalır. Uygulama kapanıp açılınca gizlenenler yeniden görünür (açılışta `recent_hidden` temizlenir). Hem Dosya → Son açılanlar menüsünde hem karşılama ekranında; "Listeyi temizle" kalsın.
- **Sekme başlığı:** uzun ad ortadan kısalmasın; ad başı + sonu (uzantı) görünsün, tam ad ipucunda; kapat düğmesi belirgin; değişmiş belge noktası net. Sekme genişliği ayarlanabilir (Görünüm).
- **Görünürlük:** sık araç çubuğu düğmelerine yazı etiketi seçeneği (Ayar: "Düğmelerde yazı göster"), daha yüksek kontrast ve büyük tıklama alanı; boş karşılama ekranında kartlar: Aç · Tara · Telefondan al · Birleştir · Böl.
- **Hata düzeltme:** `ui/share.py` içindeki "Telefon aktarımı boşta kaldığı için durduruldu" bildirimi pencere kapatılsa/× ile kapansa bile tekrar tekrar çıkıyor (`share.py:375` civarı): sunucu kapanınca zamanlayıcıyı durdur, bildirimi bir kez göster, pencere kapanınca (`close`/`done`) göstermeden temizle. Regresyon testi.
- **Şekil çizimi (dikdörtgen/elips/çizgi):** kenarlar tırtıklı/kaba görünüyor: `views.py`/`overlays` içinde ilgili `QGraphicsItem`'larda `Antialiasing`, `QPen` `RoundJoin/RoundCap`, ince çizgide kozmetik kalem yerine ölçekli kalem; yazılan PDF çıktısında da (`models.py` ilgili `apply_to_page`) aynı kalınlık/uç tipi. Önce ilgili kodu `Grep` ile bul, ekran görüntüsünü yalnızca sonda al.
**Bitti ölçütü:** `check_ux.py` güncel ve geçer; yeni `check_ui_l1.py`: Ayarlar kategorileri/arama, palet son kullanılanlar, son açılan × gizleme + yeniden başlatınca geri gelme, e-posta izi yok (grep), boşta bildirimi tek kez.

## L2 — Birleştir / Böl: sayfa aralığı, çoklu işlem, önizleme (TAMAM)
**Önce oku:** `mw_export.py` (birleştir/böl), `pdf_engine.py` ilgili işlevler. Çekirdek arayüzsüz yeni modül `pdfops.py` (test edilebilir), UI `ui/mergesplit.py`.
**Yapılacak**
- **Birleştir penceresi:** dosya listesi (sürükle-bırak sırala, ekle/çıkar); her dosya için **sayfa aralığı** ("1-3, 5, 8-"); sağda **küçük resim önizleme** (seçili sayfalar; ilk ve son sayfa büyükçe, yanlış sayfa kolay fark edilsin; tembel render, `MAX_PIXELS` sınırı); çıktı adı/konumu (`workspace.join_out`); **klasörden tümünü ekle**.
- **Böl penceresi:** modlar: aralıklarla ("1-3, 5, 8-10" → her aralık ayrı dosya ya da hepsi tek), **her N sayfada bir**, **yer imine göre**, her sayfa ayrı. Seçilen sayfaların önizleme şeridi; çıktı adları şablonu (`{ad}_{n}`), çakışmada otomatik numara.
- **Çoklu işlem:** birden çok PDF'i aynı kuralla böl; birleştirmede birden çok klasör/dosya grubu.
- `pdfops.py`: `parse_ranges(metin, sayfa_sayisi)` (geçersizde `ValueError` ve Türkçe ileti), `merge(kaynaklar[(yol, aralık)], out)`, `split(...)`; çıktı `.part` + `os.replace`; iptal/ilerleme (`BackgroundJob`).
**Bitti ölçütü:** `check_pdfops.py`: aralık ayrıştırma (hatalı girdiler), merge/split sayfa sayıları ve sırası, yer imine göre bölme, iptalde dosya kalmaz; UI testi: önizleme sayfa sayısı seçimle eşleşir.

## L3 — Telefon aktarımı: Al / Gönder sekmeleri, telefon web arayüzü, otomatik tarama (TAMAM)
**Önce oku:** `ui/share.py` (`ShareDialog`), `qrshare.py` (`PAGE`, yollar). Güvenlik kuralları (anahtar, PIN, uzantı+imza, boyut sınırı) **değişmez**.
**Yapılacak**
- `ShareDialog`: iki sekme **Telefondan al** / **Telefona gönder**. *Al:* büyük QR + adres; gelenler küçük resimli liste; her satırda **Tara · Aç · PDF'e çevir · Klasörde göster**; seçenek "Gelen fotoğraflar gelince tarayıcıyı otomatik aç" (ayar; varsayılan açık) ve ilk fotoğrafta pencere kendiliğinden açılır, sonrakiler aynı pencereye eklenir. *Gönder:* açık belge ya da seçilen birden çok dosya; telefonda indirme listesi.
- **Telefon sayfası (`qrshare.PAGE`):** hangi işlem yapılacağı seçilebilsin: "Belge tara (köşe düzeltmeli)" / "Fotoğraf olarak gönder" / "PDF olarak gönder"; birden çok dosya seçimi, ilerleme çubuğu, gönderilenlerin listesi, Türkçe ve büyük dokunma alanları. Seçim yükleme isteğinde `X-Action` başlığıyla gider (yeni değer = `ALLOWED_ACTIONS` beyaz listesi; bilinmeyen reddedilir).
- Ayarlar → "Telefon aktarımı": boşta süresi, boyut sınırı, PIN varsayılanı, otomatik açma.
- Boşta durma bildirimi L1'deki düzeltmeyle uyumlu.
**Bitti ölçütü:** `check_qrshare_*` geçer + yeni testler: sekmeler, `X-Action` beyaz listesi, otomatik tarama kuyruğu, gönder sekmesinde çoklu dosya listesi.

## L4 — Tarama: daha çok filtre/özellik, tek sayfa mı tüm PDF mi, doğrudan Tara komutu
**Önce oku:** `scan.py` (`FILTERS`, `apply_filter`), `ui/scanner.py`, `mw_doctools.py` `scan_images/scan_document`.
**Yapılacak**
- **Doğrudan "Tara" komutu** (komut paleti + üst çubuk + karşılama kartı): tek kaynak seçici penceresi (Dosyalar · Telefondan · Açık belge); *Tara ve içe aktar* menüsündeki ayrı adımlar buna iner. Son kullanılan filtre/ayarlar hatırlanır (`scan/last`).
- **Kapsam seçeneği:** açık PDF'i tararken **Yalnız bu sayfa / Sayfa aralığı / Tüm belge**; sonuç **aynı PDF'te o sayfaların yerine** (geri alınabilir, `DocContentCommand`) ya da **yeni PDF** (ikisi seçenek).
- **Yeni filtreler** (`scan.FILTERS`, her biri saf numpy/OpenCV): Canlı renk, Keskin metin (unsharp), Gri tonlama + kontrast germe, Mürekkep tasarrufu (açık arka plan, ince koyu metin), Eski belge/sepya, Negatif; ayarlar: **gürültü azaltma**, **leke/gölge temizleme gücü**, **kenar boşluğu kırpma**, **otomatik döndürme (yön tahmini, güvenilmezse dokunma)**; toplu: "bu ayarı tüm sayfalara uygula".
- Filtre önizlemesi küçük kartlarla (aynı görüntüde yan yana) seçilir.
**Bitti ölçütü:** `check_scan.py`/`check_scan_ui.py` güncel + yeni filtreler için boyut/dtype/determinizm testleri; kapsam seçeneği testi (tek sayfa yerinde değişir, undo çalışır, tüm belge/yeni PDF); sürümü `1.1.0` yap, README/CLAUDE.md kısa not, tam pytest, `build.bat`, yayın.
