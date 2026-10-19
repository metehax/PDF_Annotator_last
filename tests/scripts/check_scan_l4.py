import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
import numpy as np
import cv2
import pymupdf as fitz

tmp = tempfile.mkdtemp(prefix="l4_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


import scan

# ---- sentetik sayfa: gölgeli zemin + yazı satırları
rng = np.random.default_rng(3)
H, W = 400, 300
page = np.full((H, W, 3), 240, np.uint8)
for y in range(30, H - 30, 22):
    for x in range(25, W - 40, 50):
        cv2.rectangle(page, (x, y), (x + int(rng.integers(20, 40)), y + 8), (25, 25, 25), -1)
page = (page * np.linspace(1.0, 0.6, W, dtype=np.float32)[None, :, None]).astype(np.uint8)
noisy = np.clip(page + rng.normal(0, 14, page.shape), 0, 255).astype(np.uint8)

NEW = ["keskin metin", "gri germe", "mürekkep tasarrufu", "sepya", "negatif"]
check("yeni filtreler listede", all(f in scan.FILTERS for f in NEW) and "canlı" in scan.FILTERS)
for f in scan.FILTERS:
    a = scan.apply_filter(page, f)
    b = scan.apply_filter(page, f)
    check(f"{f}: boyut/dtype/determinizm", a.shape == page.shape and a.dtype == np.uint8 and np.array_equal(a, b))
g = scan.apply_filter(page, "gri germe")
check("gri germe: gri ve geniş aralık", np.array_equal(g[:, :, 0], g[:, :, 1]) and int(g.max()) - int(g.min()) > 200)
ink = scan.apply_filter(page, "mürekkep tasarrufu")
check("mürekkep tasarrufu: arka plan açık, metin koyu", np.percentile(ink, 60) > 235 and ink.min() < 80)
check("sepya: sıcak ton (R>G>B)", (lambda s: s[0] > s[1] > s[2])(scan.apply_filter(page, "sepya").reshape(-1, 3).mean(0)))
check("negatif: tersi", np.array_equal(scan.apply_filter(page, "negatif"), 255 - page))
ks = scan.apply_filter(page, "keskin metin")
check("keskin metin: kenar kontrastı artar", cv2.Laplacian(ks, cv2.CV_32F).var() > cv2.Laplacian(page, cv2.CV_32F).var())

# ---- gürültü azaltma / leke gücü / kenar
dn = scan.apply_filter(noisy, "orijinal", gurultu=80)
check("gürültü azaltma: sapma düşer", dn.astype(float).std() <= noisy.astype(float).std() and
      np.abs(np.diff(dn.astype(float), axis=1)).mean() < np.abs(np.diff(noisy.astype(float), axis=1)).mean())
check("gürültü 0 = dokunmaz", np.array_equal(scan.apply_filter(noisy, "orijinal", gurultu=0), noisy))
s0 = scan.apply_filter(page, "orijinal", golge=True, golge_guc=0)
s50 = scan.apply_filter(page, "orijinal", golge=True, golge_guc=50)
s100 = scan.apply_filter(page, "orijinal", golge=True, golge_guc=100)


def spread(a):                                  # soldan sağa aydınlık farkı
    m = a.mean(axis=(0, 2))
    return float(m[:40].mean() - m[-40:].mean())


check("leke/gölge gücü: 0 > 50 > 100 (gölge farkı azalır)", spread(s0) > spread(s50) > spread(s100) and np.array_equal(s0, page), (spread(s0), spread(s50), spread(s100)))
cm = scan.crop_margin(page, 5)
check("kenar kırpma: her kenardan %5", cm.shape == (H - 2 * 20, W - 2 * 15, 3), cm.shape)
check("kenar kırpma 0 = aynı, üst sınır", scan.crop_margin(page, 0).shape == page.shape
      and scan.crop_margin(page, 99).shape == scan.crop_margin(page, scan.MAX_MARGIN).shape)

# ---- yön tahmini
check("yön: dik metne dokunma", scan.estimate_orientation(page) == 0)
side = np.ascontiguousarray(np.rot90(page))
check("yön: yatık metin 90° önerir", scan.estimate_orientation(side) == 90)
blank = np.full((200, 200, 3), 255, np.uint8)
check("yön: boş/güvenilmez sayfaya dokunma", scan.estimate_orientation(blank) == 0)
check("yön: gürültüde dokunma", scan.estimate_orientation(rng.integers(0, 255, (300, 300, 3), dtype=np.uint8)) == 0)

# ================= UI =================
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import main_window as mw
from ui.scanner import ScanDialog
from ui.scansource import ScanSourceDialog

app = QApplication.instance() or QApplication(sys.argv)
w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
w.stamp_lib.settings = w.settings
w.sig_lib.settings = w.settings
w.resize(1300, 850)
w.show()


def pump(until=None, limit=60000, ms=100):
    t0 = time.time()
    while (time.time() - t0) * 1000 < (limit if until else ms):
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.01)
    return False


from PySide6.QtGui import QAction
texts = [a.text() for a in w.findChildren(QAction)]
check("menü: Tara…", "Tara…" in texts)
check("üst çubukta Tara düğmesi", w.btn_scan.text() == "Tara")

# kaynak seçici
d0 = ScanSourceDialog(w, 0, 0)
check("belge yokken 'Açık belge' pasif", not d0.r_doc.isEnabled())
d5 = ScanSourceDialog(w, 6, 2)
d5.r_doc.setChecked(True)
check("kapsam: tüm belge", d5.pages() == list(range(6)) and d5.replace())
d5.r_page.setChecked(True)
check("kapsam: yalnız bu sayfa", d5.pages() == [2])
d5.r_range.setChecked(True)
d5.ed_range.setText("1-2, 6")
check("kapsam: aralık", d5.pages() == [0, 1, 5] and d5.btn_ok.isEnabled())
d5.ed_range.setText("9")
check("kapsam: hatalı aralık engellenir", d5.pages() is None and not d5.btn_ok.isEnabled() and bool(d5.lbl_err.text()))
d5.r_new.setChecked(True)
check("sonuç: yeni PDF seçeneği", not d5.replace())

# ---- 6 sayfalık belge
src = os.path.join(tmp, "belge.pdf")
doc = fitz.open()
for i in range(6):
    pg = doc.new_page()
    pg.insert_text((72, 100), f"SAYFA {i + 1}", fontsize=40)
doc.save(src)
w.open_paths([src])
pump(ms=400)
s = w.active_session
check("oturum açıldı", s is not None and s.pdf.page_count == 6)
s.current_page = 2


def finish(dlg):
    out = os.path.join(tmp, f"o_{time.time_ns()}.pdf")
    dlg.start_export(out)
    return pump(until=lambda: dlg.result_path is not None or dlg._job is None, limit=120000)


# tek sayfa yerinde
dlg = w.scan_document([2], True)
pump(ms=500)
check("tarayıcı yalnız seçili sayfayla açıldı", dlg is not None and len(dlg.pages) == 1)
dlg.apply_to_all()
dlg.cur.filt = "gri germe"
finish(dlg)
pump(ms=800)
check("tek sayfa yerinde: sayfa sayısı aynı", s.pdf.page_count == 6, s.pdf.page_count)
check("yerinde: o sayfa görüntüye döndü, diğerleri metin", not s.pdf.doc[2].get_text().strip() and "SAYFA 1" in s.pdf.doc[0].get_text()
      and "SAYFA 6" in s.pdf.doc[5].get_text())
check("yerinde: geri alınabilir komut", s.undo_stack.count() >= 1)
s.undo_stack.undo()
pump(ms=300)
check("geri al: özgün sayfa geri geldi", "SAYFA 3" in s.pdf.doc[2].get_text() and s.pdf.page_count == 6)
s.undo_stack.redo()
pump(ms=300)
check("yinele: tarama sürümü", not s.pdf.doc[2].get_text().strip())
s.undo_stack.undo()
pump(ms=300)

# aralık yerinde (kopuk sayfalar) + işaretler
dlg = w.scan_document([0, 4], True)
pump(ms=500)
check("aralık: iki sayfa", len(dlg.pages) == 2)
finish(dlg)
pump(ms=800)
check("aralık yerinde: 1 ve 5 değişti, diğerleri aynı", not s.pdf.doc[0].get_text().strip() and not s.pdf.doc[4].get_text().strip()
      and "SAYFA 2" in s.pdf.doc[1].get_text() and "SAYFA 6" in s.pdf.doc[5].get_text() and s.pdf.page_count == 6)
s.undo_stack.undo()
pump(ms=300)

# tüm belge yeni PDF (belge değişmez)
n_before = len(w.sessions)
dlg = w.scan_document(None, False)
pump(ms=600)
check("tüm belge: 6 sayfa", len(dlg.pages) == 6)
finish(dlg)
check("yeni PDF olarak açıldı, özgün değişmedi", pump(until=lambda: len(w.sessions) == n_before + 1)
      and "SAYFA 3" in s.pdf.doc[2].get_text())
w.switch_session(0)
pump(ms=200)

# ---- toplu uygula, son ayarlar, yeni sayfa kontrolleri
photo = os.path.join(tmp, "a.png")
cv2.imwrite(photo, cv2.cvtColor(page, cv2.COLOR_RGB2BGR))
dlg = ScanDialog(w, [photo, photo, photo])
dlg.show()
pump(ms=500)
dlg.strip.setCurrentRow(0)
pump(ms=300)
f_idx = list(scan.FILTERS).index("sepya")
dlg.filters.setCurrentRow(f_idx)
dlg.sl_denoise.setValue(40)
dlg.sl_stain.setValue(60)
dlg.sl_margin.setValue(4)
check("ayarlar sayfaya yazıldı", dlg.cur.filt == "sepya" and dlg.cur.denoise == 40 and dlg.cur.stain == 60 and dlg.cur.margin == 4.0)
check("kontroller var (yön tahmini, toplu uygula)", dlg.btn_orient.isEnabled() and dlg.btn_apply_all.isEnabled())
n = dlg.apply_to_all()
check("tüm sayfalara uygula: 2 sayfa", n == 2 and all(p.filt == "sepya" and p.denoise == 40 and p.stain == 60 and p.margin == 4.0 for p in dlg.pages))
pump(ms=300)
shape_full = scan.apply_filter(page, "orijinal").shape
check("kenar kırpma çıktıya yansır", dlg.preview_array.shape[0] < page.shape[0] - 10, dlg.preview_array.shape)
check("son kullanılan kaydedildi (scan/last)", "sepya" in str(w.settings.value("scan/last")))
dlg.close()
dlg2 = ScanDialog(w, [photo])
dlg2.show()
pump(ms=400)
check("yeni pencere son ayarla başlar", dlg2.pages[0].filt == "sepya" and dlg2.pages[0].denoise == 40 and dlg2.pages[0].margin == 4.0)
dlg2.reset_page()
check("sayfa sıfırla yeni ayarları da sıfırlar", dlg2.cur.denoise == 0 and dlg2.cur.stain == 100 and dlg2.cur.margin == 0)
d_before = dlg2.cur.rot
check("yön tahmini dik sayfaya dokunmaz", dlg2.auto_orient() == 0 and dlg2.cur.rot == d_before)
outp = os.path.join(tmp, "son.pdf")
dlg2.start_export(outp)
check("dışa aktarım çalışır (12'li spec)", pump(until=lambda: dlg2.result_path is not None or dlg2._job is None, limit=60000)
      and os.path.exists(outp))
dlg2.close()

# Tara komutu: kaynak -> pencere
calls = []
w.scan_images = lambda *a, **k: calls.append("files")
w.open_share = lambda: type("D", (), {"tabs": type("T", (), {"setCurrentIndex": lambda self, i: calls.append("phone")})()})()
orig = ScanSourceDialog.exec
for which in ("files", "phone"):
    ScanSourceDialog.exec = lambda self, wh=which: (getattr(self, "r_" + wh).setChecked(True), True)[1]
    w.scan_command()
check("Tara komutu: Dosyalar / Telefondan yönlendirir", calls == ["files", "phone"], str(calls))
ScanSourceDialog.exec = lambda self: False
check("Tara komutu: vazgeç", w.scan_command() is None)
ScanSourceDialog.exec = orig

print(f"OZET: {sum(ok)}/{len(ok)} gecti")
sys.exit(0 if all(ok) else 1)
