# Sağlamlık raporu (S1)

Yöntem: `tests/scripts/check_robustness.py` uç durumları zorlar; yakalanmamış istisna/donma/çökme olanlar aşağıda.
Günlükler: `<çalışma klasörü>\Gunlukler\pdfannotator.log` (dönen, ~1 MB x 3) ve `yerel_cokme.log` (C seviyesi çökme izi).

## Bulgular
| # | Önem | Bulgu | Tekrar adımı | Durum |
|---|---|---|---|---|
| 1 | Kritik | Dışa aktarma doğrudan hedefe yazıyordu: disk dolu/yazma hatasında yarım dosya kalır, var olan dosya bozulurdu | Var olan dosyanın üstüne kaydet, yazma sırasında hata | Düzeltildi (`export_pdf` → `.part` + `os.replace`, hatada silinir) |
| 2 | Orta | 0 sayfalı PDF açılınca `IndexError` (render) | 0 sayfalı PDF'i aç | Düzeltildi (açılışta "Belgede hiç sayfa yok." hatası, oturum açılmaz) |
| 3 | Orta | Çok büyük sayfa (14000x14000 pt) `FzErrorLimit: Overly large image` | Dev sayfalı PDF aç / yakınlaştır / küçük resim / içerik sınırı | Düzeltildi (`clamp_scale`, 60 Mpx sınırı: render, küçük resim, resim dışa aktarma, içerik sınırı) |
| 4 | Orta | Karşılaştırma modunda sekme kapanınca panel kapanmış belgeyi çizmeye çalışıp `ValueError: document closed` veriyordu (tekrarlı hata) | Karşılaştırma açıkken iki belgeyi kapat | Düzeltildi (`ComparePane._render` kapanmış oturumu bırakır, sayfa sınırlanır) |
| 5 | Orta | Kapanışta QR sunucusu, gizli/hiç gösterilmemiş pencerede `closeEvent` gelmediği için durmayabilir; çıkışta iş parçacığı çökmesi riski | Paylaş penceresini aç, uygulamayı kapat | Düzeltildi (`closeEvent` doğrudan `stop()`; zamanlayıcılar durur, havuz beklenir) |
| 6 | Orta | Yakalanmamış hata günlüğe yazılmıyor, kullanıcı bilgilenmiyordu | Herhangi bir slotta hata | Düzeltildi (`crashguard.py`) |
| 7 | Düşük | Filigran metni/resmi yazılamazsa sessizce atlanıyordu | Bozuk yazı tipi/resim ile filigran | Düzeltildi (atlanır ama günlüğe yazılır) |
| 8 | Düşük | Çıkışta `os._exit` ile 0xC0000005 (test sürecinde) | Test betiği sonu | Test artefaktı: normal yorumlayıcı çıkışı temiz; robustness betiği normal çıkar |

Sorunsuz çıkanlar: boş/bozuk/yanlış uzantılı dosya, bozuk/0 baytlık resim, parolalı (yanlış/iptal/doğru), 320 sayfa, döndürülmüş+kırpılmış sayfa, Unicode ve >260 karakter yol, salt-okunur dosya, aynı dosyayı iki kez açma, açıkken silinen/bozulan dosya, belge yokken tüm menü eylemleri, boş seçimle sil/yapıştır, geri al/yinele sınırları, sayfa işleminden hemen sonra geri alma, hızlı sekme değiştirme, render/küçük resim/metin farkı/arka plan işi sürerken kapatma, kapanmış `PDFDocument` erişimi.

## Açık (düzeltilmedi)
- **Orta:** Diskte gerçek "disk dolu" koşulu doğrudan sınanamadı (yalnız hedef yazılamaz durumu); dönüştürme (Word/Excel), tarama PDF'i ve iş akışı çıktıları `.part` kullanıyor mu tek tek doğrulanmadı (tarama/düzleştirme kullanıyor).
- **Orta:** Açık dosya Windows'ta kilitli olduğundan "açıkken diskten silinme" gerçek koşulda sınanamadı; dışarıdan değiştirilen dosya için uyarı yok.
- **Düşük:** Aynı hata 60 sn içinde yeniden uyarı üretmez, yalnız günlüğe yazılır. Bazı `except Exception: pass` bloğu (`models.py` not rengi, `ui/*` açma sonrası toast) zararsız ama günlüğe yazmıyor.
- **Düşük:** İş parçacığındaki OCR/tarama işleri kapanışta en çok 3 sn beklenir; daha uzun işler beklenmeden süreç sonlanır.
