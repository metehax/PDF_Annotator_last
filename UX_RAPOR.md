# UX raporu — I5a (yalnız denetim, kod değişikliği yok)

Tarih: 2026-10-17 · Sürüm: `ebc49fa` sonrası ana dal (I4 dâhil) · Pencere 1500×950, koyu tema, geçici ayar/çalışma klasörü.

## 1. Yöntem ve sınırları
* **Ekran görüntüleri (tek çalıştırmada):** boş açılış, PDF açık, araç seçili (fosforlu), sansür, karşılaştırma, tarama penceresi, Tercihler, Belge menüsü.
  (Ek olarak "son açılanlarla açılış".) Görüntüler depoda **tutulmadı**; betik geçici klasörde çalıştı.
* **Sayımlar kaynaktan/çalışan pencereden:** menü öğeleri, kısayollar (`QAction` + `QShortcut`), ikon/ad tutarlılığı, ipucusuz düğmeler.
* **Sezgisel değerlendirme:** Nielsen ilkeleri (görünürlük, tutarlılık, hata önleme, kısayollar, boş durumlar, geri bildirim) + geri alınamaz işlem taraması.
* **Yapılmadı / doğrulanamadı:** gerçek kullanıcıyla deneme (bunun için `UX_GOREVLER.md`), ekran okuyucu, yalnız klavyeyle gezinme (Tab sırası, menü
  mnemonics), yüksek DPI / %150–200 ölçek, yüksek kontrast, küçük ekran (≤1366×768) tam taraması, açık tema görünümü.
* **Yanlış alarm notu:** ilk denemede açılış ekranında "hayalet" bir son-açılan satırı gördüm; nedeni test düzeneğimizde `deleteLater`'ın işlenmemesiydi
  (gerçek olay döngüsünde yok). Gerçek hata değil, rapora alınmadı.
* **Eforlar:** S ≤ 0,5 gün (≈ 1–4 sa) · M 0,5–1,5 gün · L > 1,5 gün. Tahminler test yazımı dâhil, kullanıcı denemesi hariç.

## 2. Özet

| Öncelik | Adet | Toplam efor (yaklaşık) |
|---|---|---|
| Kritik | 2 | S + L (≈ 2,5–4 gün; K1'in hızlı hafifletmesi 2 sa) |
| Orta | 8 | ≈ 5–7 gün |
| Düşük | 6 | ≈ 1,5–2 gün |

Güçlü yönler: boş durum (01) net ve eyleme yönelik (başlık, sürükle-bırak alanı, **Dosya aç**, Ctrl+O ipucu, son açılanlar); tüm görünür düğmelerin
metni ya da ipucu var (ipucusuz düğme **0**); tema/renk tutarlı; kısayol **çakışması yok** (48 kısayolda 0 tekrar); sansür/KVKK/düzleştirme gibi tehlikeli
işlemlerde "özgün dosya değişmez, yeni dosya yazılır" modeli güvenli; araç ipuçlarında kısayol harfi var.

## 3. Kritik

### K1 — Sayfa işlemleri geri alınamıyor ve "Sayfayı sil" onaysız  · Efor: S (hızlı önlem) + L (gerçek geri alma)
* **Kanıt:** `mw_pages.py` `_delete_page/_insert_blank_page/_duplicate_page/_move_page/_rotate_page` doğrudan `pdf` üzerinde çalışır, `undo_stack`'e komut
  yazmaz (yalnız `CropPagesCommand` var). Belge menüsü, küçük resim sağ tık menüsü ve sayfa çubuğundaki çöp kutusu tek tıkla siler. Onay yalnızca döndürmede
  ve yalnız o sayfada işaret varsa soruluyor. Ctrl+Z işaretleri geri alırken sayfa silmeyi sessizce atlıyor → kullanıcı "geri aldım" sanır.
* **Risk:** Kaydetmeden önce yanlış sayfa silinirse kurtarma yolu yok (ancak belgeyi kapatıp yeniden açmak; bu da diğer değişiklikleri götürür).
* **Öneri:** (a) hemen: silmede onay (ya da 5 sn'lik "Geri al" toast'ı + belgeyi o ana kadar kopyalama); (b) kalıcı: sayfa işlemlerini `QUndoCommand` yap
  (belge baytlarının anlık görüntüsü ya da ters işlem; büyük belgelerde bellek sınırı); (c) Düzenle menüsündeki Geri al etiketi ne yapılacağını söylesin
  ("Sayfa silmeyi geri al").
* **Efor:** onay/toast **S (2 sa)**; tam geri alma **L (2–3 gün; ters işlem + işaret yeniden indeksleme + test)**.

### K2 — "Kaydet" / "PDF olarak kaydet…" / "Dışa Aktar": özgün dosya hiçbir yoldan güncellenmiyor, kavram karışık  · Efor: M
* **Kanıt:** `save_document` = `save_pdf`; varsayılan ad `<ad>_isaretli.pdf`. Dosya menüsünde "Kaydet" ile "PDF olarak kaydet…" **aynı davranış** (aynı
  pencere). Üst çubukta öne çıkan mavi **Kaydet** özgün PDF'i değiştirmez; "Dışa Aktar" ayrı menü. Kaydedince başlıktaki ● kalkıyor ama özgün dosya aynı.
* **Risk:** kullanıcı "kaydettim" sanıp özgün dosyayı bulur, işaretlerin olmadığını görür; ya da tersine, sansürün özgün dosyaya uygulandığını sanır.
  Temel görevin (aç → işaretle → kaydet) en çok takılacağı yer.
* **Öneri:** (1) "Kaydet" etiketini sonucu söyleyecek biçimde değiştir ("Kopya olarak kaydet" / "İşaretli PDF kaydet"); (2) menüde yinelenen girişi kaldır;
  (3) iletişim kutusunda ya da toast'ta "Özgün dosya değişmedi" notu; (4) isteğe bağlı: "Özgün dosyanın üzerine yaz (yedekli)" seçeneği (iş akışındaki
  `.yedek.pdf` mantığı hazır).
* **Efor:** M (1 gün: etiketler, iletişim notu, isteğe bağlı üzerine yazma + test).

## 4. Orta

| # | Bulgu | Kanıt / ekran | Öneri | Efor |
|---|---|---|---|---|
| O1 | **Menü yoğunluğu**: Belge 21, Dosya 20 doğrudan öğe (alt menüler dâhil toplam 84); mantıksal gruplar karışık (sayfa işlemleri, güvenlik, dönüştürme, tarama, erişilebilirlik tek düz liste) | 08 | Belge → alt menüler: **Sayfa ▸** (ekle/kopyala/sil/döndür/kırp), **Üstbilgi ve numara ▸** (sayfa no, Bates, filigran), **Dönüştür ▸** (Word, Excel, düzleştir), **Güvenlik ▸** (parola, güvenlik denetimi, KVKK); Dosya → "Tara/İçe aktar ▸" (Belge tara, Görselleri PDF'e çevir, Telefonla aktar), "Kaydet ▸" | M |
| O2 | **Durum çubuğu bayat/zayıf geri bildirim**: belge açıkken "Tüm belgeler kapatıldı." (03), karşılaştırmada "İşaret eklendi." (05) kalıyor; mesajlar küçük gri, zaman aşımı yok | 03, 05 | Mesaja kısa ömür (4–6 sn) + belge değişince temizle; başarılı işlemler için toast, durum çubuğunda kalıcı bilgi (sayfa/yakınlaştırma/seçili araç) | S |
| O3 | **Sansür görünürlüğü**: yumuşak görünümde altındaki metin okunuyor, **etiket ekranda görünmüyor** (yalnız çıktıda); ⚠ uyarı yalnız ikon/tooltip; "Nihai görünüm" varsayılan kapalı | 04 | Etiketi ekranda soluk önizle; ⚠ yerine görünür tek satırlık metin ("Kaydedince altındaki metin silinir"); **Kaydetmeden önce özet** ("2 sansür kutusu uygulanacak" + "Nihai görünüme bak") | M |
| O4 | **Özellik çubuğu sayfa üstünü örtüyor**: araç kapsülü + özellik çubuğu birlikte ≈ 110 px; sayfanın ilk satırları/üst kenarı kapanıyor (başlık yarım) | 03, 04 | Sayfa üst boşluğunu çubuk yüksekliğine göre ayarla (`CANVAS_TOP_INSET` dinamik) ya da çubuğu sayfanın üstünde değil yanında/altında göster | M |
| O5 | **Karşılaştırma modunda araç kapsülü**: soluk ama "Numarala" simgesi mavi (etkin gibi), ne işe yaradığı belirsiz; sağ panel özeti küçük gri | 05 | Kapsülü gizle ya da net devre dışı yap; özet satırını büyüt/renkli (örn. "+1 −0 ≠0"); modun nasıl kapatılacağını göster (sağ alttaki simge belirsiz) | S |
| O6 | **Erişilebilirlik düzeltmeleri ve OCR geri alınamıyor** (pencere notu "Ctrl+Z ile geri alınamaz" diyor ama çare sunmuyor) | `ui/a11y.py:82` | Düzeltme öncesi anlık görüntü + "Düzeltmeleri geri al" düğmesi; ya da düzeltmeleri yeni kopyaya uygula | M |
| O7 | **Tarama penceresi sığmıyor**: sağ panelde iç içe kaydırma (filtre listesi kendi çubuğu + panel çubuğu); 820 px yükseklikte "Bu sayfayı sıfırla" kesik; 768 px'lik dizüstünde büyük bölüm erişilemez | 06 | Filtre kartlarını kaydırmasız 3×2 yap; Düzeltme bölümünü katlanır yap; pencereyi ekrana göre boyutlandır | M |
| O8 | **Yinelenen/benzer adlar**: Kaydet = PDF olarak kaydet…; "Bu belgeyi tara/kırp…" ≠ "Sayfaları kırp…" ≠ "Belge tara (görsellerden)…"; "Metin farkını göster" ile "Karşılaştırma modu"; "Telefonla aktar" ile "Paylaş" | 08 + döküm | Tek amaçlı, fiil+nesne adlar ("Belge sayfalarını yeniden tara", "Kenarlardan kırp"); karşılaştırma tek girişte | S |
| O9 | **Kısayol boşlukları**: Ctrl+C/V/A (işaretleri kopyala/yapıştır/tümünü seç) yok; Ctrl+Shift+Z yok (yalnız Ctrl+Y); F11 tam ekran, Ctrl+Tab belge sekmesi yok; F1 yardım yerine "Klavye kısayolları" | döküm | İşaret kopyala/yapıştır (en çok beklenen), Ctrl+Shift+Z, F11, Ctrl+Tab; F1 → Yardım penceresi | M (kopyala/yapıştır 0,5–1 gün; diğerleri S) |

## 5. Düşük

| # | Bulgu | Öneri | Efor |
|---|---|---|---|
| D1 | **İkon tutarlılığı**: "Çıkış" ve "Gerçek boyut (%100)" ikonsuz; aynı ikon farklı anlamda: `images` ×3 (PNG'ler / Görselleri PDF'e çevir / ayrı PDF), `folder` ×3 (bulut / konum aç / proje aç), `trash` ×3, `sliders` ×3 (Komut paleti / Tercihler / Alan özellikleri), `file` ×3, `headfoot` ×2 (Sayfa no ve Bates), Düzleştir `layers` (Katmanlar paneliyle aynı), Word'e dönüştür `download` (Dışa aktar ile aynı) | Menü başına benzersiz ikon; eksikleri tamamla | S |
| D2 | **Etiket tutarlılığı**: "…" 77 eylemin 40'ında; ölçüt belirsiz (ek pencere açmayan "Dosya konumunu aç", "Sayfayı sil" gibi öğelerde yok; "Seçili alanın özellikleri…" gibi pencere açanlarda var), 46 karakterlik "Metin farkını göster (iki sürümü karşılaştır)" ve "Windows'ta 'Birlikte aç' listesine ekle…" çok uzun | Kural: pencere/ek bilgi isteyen → "…"; en çok ~32 karakter; yönetim işlerini (Birlikte aç) Tercihler'e taşı | S |
| D3 | **Yanlış yerleşim**: "Damga kütüphanesi…" Belge'de, imza/damga ise ayrı **İmza** menüsünde; "Formlar paneli/Yeni alan" gibi iki-üç öğeli Form ve İmza menüleri | Damga kütüphanesini İmza'ya taşı; Form+İmza'yı "Form ve imza" altında birleştirmeyi değerlendir | S |
| D4 | **Yardım/öğrenme yok**: Yardım menüsünde yalnız kısayol listesi, Birlikte aç yönetimi, Hakkında; ilk kullanım turu/örnek belge/ipucu yok; belge açıkken tek ipucu kaynağı araç kapsülü | İlk açılışta 3 adımlı tur ya da "ipucu" bandı; Yardım → "Başlarken" | M |
| D5 | **Tercihler**: değişiklikler anında uygulanıyor ama bunu söyleyen metin yok; "Kapat" tek düğme; çalışma klasörü yolu uzun yollarda baştan kesik | "Değişiklikler anında kaydedilir" notu; yolu ortadan kısalt (elided) | S |
| D6 | **Kısayol keşfedilebilirliği**: tek harfli 17 araç tuşu (V, T, E, P, H, L, R, O, X, I, N, S, C, B, M, F, G) yalnızca araç ipucunda; menüde yok; sol/sağ ok sayfa değiştirir (listelerde ok tuşuyla çakışabilir) | Kısayol penceresinde tek harfliler bölümü; ok tuşlarını yalnız tuval odaktayken işle | S–M |

## 6. Ayrıntılı ölçümler

### 6.1 Menü yoğunluğu (çalışan pencereden)
| Menü | Doğrudan öğe | Ayraç | Not |
|---|---|---|---|
| Dosya | 20 | 5 | + 3 alt menü (Son açılanlar, Dışa aktar, Paylaş) |
| Düzenle | 6 | 2 | |
| Görünüm | 14 | 2 | 3 işaretli öğe |
| **Belge** | **21** | 5 | düz liste; hedef ≤ 8–10 doğrudan öğe |
| Form | 6 | 1 | |
| İmza | 5 | 1 | |
| Yardım | 4 | 2 | |
| **Toplam (alt menüler dâhil)** | **84** | | komut paleti (Ctrl+K) hepsini aratıyor: iyi bir telafi |

### 6.2 Kısayollar
* Toplam benzersiz kısayol: **48**; **çakışma/tekrar: 0** (QAction + QShortcut birlikte tarandı).
* Standart beklentiler: Ctrl+Z/Y/S/O/P/W/Q/F var; **yok:** Ctrl+C / Ctrl+V / Ctrl+X / Ctrl+A (işaretler için), Ctrl+Shift+Z, Ctrl+N, F11, Ctrl+Tab;
  F1 yardımı değil kısayol listesini açıyor.
* Tek harfli araç tuşları (17) ve sol/sağ ok global; yazı alanlarında devre dışı kalması beklenir (Qt `ShortcutOverride`) — elle doğrulanmadı.

### 6.3 Dil ve ikon tutarlılığı
* Arayüz tamamen Türkçe; yabancı kısaltmalar (PDF, OCR, QR, KVKK, JSON, PNG/JPEG, Bates) alan terimi olarak tutarlı. ASCII "..." kullanımı **yok** (hep "…").
* 77 menü eyleminin 2'si ikonsuz; 6 ikon 3+ kez yeniden kullanılmış (bkz. D1).
* Görünür metinsiz+ipucusuz düğme: **0**.

### 6.4 Geri alınamayan / geri döndürülmesi zor işlemler
| İşlem | Geri alma | Onay / uyarı | Not |
|---|---|---|---|
| Sayfa sil / ekle / kopyala / taşı / döndür | **Yok** (komut yok) | Yalnız döndürmede (işaret varsa) | **K1** |
| Erişilebilirlik düzeltmeleri (dil/başlık/yer imi/OCR) | **Yok** | Pencerede not | O6 |
| OCR (belgeye metin katmanı) | Yok | — | O6 ile birlikte |
| Sansür / KVKK karartma | Var (işaret olarak, Ctrl+Z) | Toast + ipucu; **kalıcı silme yalnız kaydedince** | Özgün dosya değişmez → güvenli; görünürlük O3 |
| Düzleştir ve kaydet / Word / Excel / Tara | Gerekmez (yeni dosya) | Üzerine yazma sorusu var | iyi |
| İş akışı "özgün dosyanın üstüne" | Yedek `.yedek.pdf` | Varsayılan kapalı | iyi |
| Toplu işlemler (iş akışı) | Durdurulabilir, yarım dosya kalmaz | Rapor | iyi |

### 6.5 Boş durumlar
* Açılış (01): çok iyi. Belge yokken eylemler pasif (Kaydet/Dışa Aktar soluk) — neden pasif olduğu söylenmiyor ama bağlamdan anlaşılır.
* Karşılaştırma, Yorumlar, Formlar, Katmanlar panelleri için boş durum metinleri bu turda ayrıca incelenmedi (bkz. 1. bölüm).

## 7. I5b için önerilen sıra (onay bekliyor)
1. K1 (önce S: onay + geri al toast; sonra L)  2. K2  3. O1  4. O2  5. O3  6. O9 (kopyala/yapıştır + Ctrl+Shift+Z)  7. O7  8. O4/O5
Düşük maddeler D1–D3 küçük işler olarak O1 ile aynı pakette yapılabilir.
