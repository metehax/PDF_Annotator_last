import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
SP = tempfile.gettempdir()
import numpy as np
import cv2
import pymupdf as fitz
from PIL import Image

tmp = tempfile.mkdtemp(prefix="g2ui_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


# --- sentetik fotograflar: koyu zemin + perspektifli kagit (okunabilir buyuk yazi)
PW, PH = 900, 1200
W, H = 2000, 1500
rng = np.random.default_rng(3)


def make_photo(path, quad, lines):
    paper = np.full((PH, PW, 3), 244, np.uint8)
    for i, ln in enumerate(lines):
        cv2.putText(paper, ln, (60, 200 + i * 170), cv2.FONT_HERSHEY_SIMPLEX, 2.6, (20, 20, 20), 6, cv2.LINE_AA)
    paper = (paper * np.linspace(1.0, 0.7, PW, dtype=np.float32)[None, :, None]).astype(np.uint8)
    bg = np.clip(np.full((H, W, 3), 45, np.float32) + rng.normal(0, 4, (H, W, 3)), 0, 255).astype(np.uint8)
    q = np.array(quad, np.float32)
    M = cv2.getPerspectiveTransform(np.array([[0, 0], [PW - 1, 0], [PW - 1, PH - 1], [0, PH - 1]], np.float32), q)
    mask = cv2.warpPerspective(np.full((PH, PW), 255, np.uint8), M, (W, H))
    photo = np.where(mask[:, :, None] > 0, cv2.warpPerspective(paper, M, (W, H)), bg)
    Image.fromarray(photo).save(path, quality=92)
    return q


Q1 = [[620, 140], [1380, 120], [1450, 1360], [560, 1340]]
Q2 = [[560, 170], [1330, 160], [1400, 1340], [500, 1350]]
P1 = os.path.join(tmp, "foto1.jpg")
P2 = os.path.join(tmp, "foto2.jpg")
T1 = make_photo(P1, Q1, ["RAPOR", "SOZLESME", "TARAMA"])
T2 = make_photo(P2, Q2, ["FATURA", "ODEME", "TARAMA"])
PDFP = os.path.join(tmp, "iki.pdf")
d = fitz.open()
for k in range(2):
    pg = d.new_page()
    pg.insert_text((72, 100), f"Sayfa {k + 1} metni", fontsize=20)
d.save(PDFP)
d.close()

from PySide6.QtCore import QSettings, QPointF
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtGui import QAction
import main_window as mw
import scan
import ocr
from ui.scanner import ScanDialog, FULL, rotate_corners

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


texts = [a.text() for a in w.findChildren(QAction)]
for t in ("Belge tara (görsellerden)…", "Bu belgeyi tara/kırp…"):
    check(f"menü: {t}", t in texts)

# --- pencere + otomatik kose
dlg = ScanDialog(w, [P1, P2])
dlg.resize(1180, 800)
dlg.show()
pump(ms=300)
check("2 sayfa yuklendi, ilki secili", len(dlg.pages) == 2 and dlg.cur is dlg.pages[0] and dlg.strip.count() == 2)
r = dlg.view.img_rect
pos = np.array([[h.pos().x() / r.width(), h.pos().y() / r.height()] for h in dlg.view.handles])
err = np.abs(pos - T1 / [W, H]).max()
check("otomatik kose -> kulp konumlari (+-%3)", err <= 0.03, f"{err:.3f}")
check("kulp sayisi 4, poligon 4 nokta", len(dlg.view.handles) == 4 and dlg.view.poly.polygon().count() == 4)
check("onizleme uretildi", dlg.preview_array is not None and dlg.preview_array.ndim == 3)
ar = dlg.preview_array.shape[1] / dlg.preview_array.shape[0]
check("onizleme kagit oranina yakin", abs(ar - 0.75) / 0.75 < 0.12, f"{ar:.2f}")

# --- kose degisince onizleme degisir
before = dlg.preview_array.copy()
h0 = dlg.view.handles[0]
h0.setPos(h0.pos() + QPointF(120, 90))
pump(until=lambda: dlg.preview_array.shape != before.shape or not np.array_equal(dlg.preview_array, before), limit=3000)
check("kulp surukleme -> onizleme degisti", dlg.preview_array.shape != before.shape or not np.array_equal(dlg.preview_array, before))
check("kulp surukleme -> sayfa koseleri guncellendi", abs(dlg.cur.corners[0][0] - (pos[0][0] + 120 / r.width())) < 0.01)
h0.setPos(QPointF(-500, -500))
check("kulp goruntu disina cikmaz", h0.pos().x() >= 0 and h0.pos().y() >= 0)
dlg.auto_detect()
back = dlg.preview_array.copy()
check("otomatik algila geri getirir", np.abs(dlg.cur.corners - T1 / [W, H]).max() <= 0.03)
dlg.select_all()
check("tum gorsel: koseler tam kare", np.allclose(dlg.cur.corners, FULL) and dlg.preview_array.shape[:2] == dlg._work.shape[:2])
dlg.auto_detect()

# --- filtre / ayar
names = list(scan.FILTERS)
dlg.filters.setCurrentRow(names.index("belge"))
frac = np.isin(dlg.preview_array, (0, 255)).mean()
check("filtre belge: onizleme 0/255", frac >= 0.95 and dlg.cur.filt == "belge", f"{frac:.3f}")
dlg.filters.setCurrentRow(names.index("gri"))
pa = dlg.preview_array
check("filtre gri: kanallar esit", dlg.cur.filt == "gri" and np.array_equal(pa[:, :, 0], pa[:, :, 2]))
dlg.filters.setCurrentRow(names.index("orijinal"))
m0 = dlg.preview_array.mean()
dlg.sl_br.setValue(40)
pump(until=lambda: dlg.preview_array.mean() > m0 + 5, limit=3000)
check("parlaklik kaydirici -> onizleme aydinlanir", dlg.preview_array.mean() > m0 + 5 and dlg.cur.br == 40)
dlg.btn_reset.click()
check("sifirla", dlg.sl_br.value() == 0 and dlg.sl_ct.value() == 0 and dlg.cur.br == 0)
check("filtre kartlari 6 ve onizlemeli", dlg.filters.count() == 6 and all(not dlg.filters.item(i).icon().isNull() for i in range(6)))
dlg.filters.setCurrentRow(names.index("otomatik"))

# --- dondur
c_before = dlg.cur.corners.copy()
sh_before = dlg._work.shape[:2]
dlg.rotate_page(90)
check("dondur: derece + goruntu boyutu yer degistirdi", dlg.cur.rot == 90 and dlg._work.shape[:2] == sh_before[::-1])
check("dondur: koseler donduruldu", np.allclose(dlg.cur.corners, rotate_corners(c_before, 90), atol=1e-4)
      and np.abs(dlg.view.corners()[:, 0] - dlg.cur.corners[:, 0]).max() < 0.01)
dlg.rotate_page(-90)
check("sola dondur geri alir", dlg.cur.rot == 0 and np.abs(dlg.cur.corners - c_before).max() < 0.01)

# --- sayfa seridi: sirala, sil, ekle
dlg.filters.setCurrentRow(names.index("belge"))          # sayfa 1 ayri filtre
dlg.strip.setCurrentRow(1)
check("sayfa 2'ye gecti, koseler ayri", dlg.cur is dlg.pages[1] and np.abs(dlg.view.corners() - T2 / [W, H]).max() <= 0.03)
check("filtre sayfaya ozgu", dlg.cur.filt == "otomatik" and dlg.pages[0].filt == "belge")
first = dlg.pages[0]
dlg.strip.setCurrentRow(0)
dlg.move_page(1)
check("sayfa saga tasindi", dlg.pages[1] is first and dlg.strip.item(1).data(0x100) is first and dlg.strip.currentRow() == 1)
dlg.move_page(-1)
check("sayfa sola tasindi", dlg.pages[0] is first)
dlg.add_sources([P1])
check("ucuncu sayfa eklendi", len(dlg.pages) == 3 and dlg.strip.count() == 3)
dlg.strip.setCurrentRow(2)
dlg.remove_page()
check("sayfa silindi", len(dlg.pages) == 2 and dlg.strip.count() == 2 and dlg.cur is not None)

# --- PDF kaynagi
dp = ScanDialog(w, [PDFP])
dp.show()
pump(ms=200)
check("pdf kaynagi: 2 sayfa, kose = tum sayfa", len(dp.pages) == 2 and np.allclose(dp.cur.corners, FULL))
check("pdf kaynagi: 200 dpi civari", dp._work.shape[0] > 1100, str(dp._work.shape))
dp.close()
w.open_paths([PDFP])
pump(ms=300)
dd = w.scan_document()
pump(ms=200)
check("Bu belgeyi tara: sayfalar kaynaklandi", dd is not None and len(dd.pages) == 2 and dd.pages[0].src.kind == "pdf")
dd.close()

# --- PDF uret (OCR'siz) -> uygulamada acilir
OUT1 = os.path.join(tmp, "cikti1.pdf")
n_sessions = len(w.sessions)
fake = {"n": 0}


def fake_save(*a, **k):
    fake["n"] += 1
    return (OUT1, "")


orig_save = QFileDialog.getSaveFileName
QFileDialog.getSaveFileName = staticmethod(fake_save)
dlg.cb_size.setCurrentIndex(0)
dlg.chk_ocr.setChecked(False)
dlg.generate()
check("pdf: durum cubugu gorundu", pump(until=lambda: dlg.result_path is not None, limit=60000), dlg.status.text())
QFileDialog.getSaveFileName = orig_save
out_doc = fitz.open(OUT1)
check("pdf: 2 sayfa A4", out_doc.page_count == 2 and abs(out_doc[0].rect.width - 595.276) < 1, str(out_doc.page_count))
check("pdf: kagit boyuta oturdu (siyah-beyaz sayfa 1)", len(out_doc[0].get_images()) == 1)
out_doc.close()
check("pdf: uygulamada acildi", len(w.sessions) == n_sessions + 1)
check("pdf: pencere kapandi", not dlg.isVisible())

# --- OCR'li
OUT2 = os.path.join(tmp, "cikti2.pdf")
d2 = ScanDialog(w, [P1, P2])
d2.show()
pump(ms=200)
for i in range(2):
    d2.strip.setCurrentRow(i)
    d2.filters.setCurrentRow(names.index("belge"))
tess = ocr.find_tessdata()
if tess is None:
    check("OCR kurulu degil: onay kutusu pasif", not d2.chk_ocr.isEnabled())
else:
    d2.chk_ocr.setChecked(True)
    d2.start_export(OUT2)
    check("ocr: bitti", pump(until=lambda: d2.result_path is not None, limit=240000), d2.status.text())
    od = fitz.open(OUT2)
    txt = " ".join(p.get_text().upper() for p in od)
    check("ocr: 2 sayfa", od.page_count == 2)
    check("ocr: metin katmani (RAPOR/FATURA)", "RAPOR" in txt or "FATURA" in txt or "TARAMA" in txt, txt[:80])
    od.close()

# --- iptal
OUT3 = os.path.join(tmp, "iptal.pdf")
d3 = ScanDialog(w, [P1, P2, P1, P2])
d3.show()
pump(ms=200)
if tess is not None:
    d3.chk_ocr.setChecked(True)
job = d3.start_export(OUT3)
check("iptal: calisirken dugmeler", d3.btn_stop.isVisible() and not d3.btn_run.isVisible() and not d3.btn_add.isEnabled())
d3.stop()
check("iptal: is bitti", pump(until=lambda: d3._job is None, limit=120000), d3.status.text())
check("iptal: dosya yazilmadi", not os.path.exists(OUT3) and not os.path.exists(OUT3 + ".part") and not os.path.exists(OUT3 + ".ocr.part"))
check("iptal: pencere acik, tekrar calistirilabilir", d3.isVisible() and d3.btn_run.isEnabled() and d3.result_path is None)
d3.close()

# --- bos / hatali girdi
d4 = ScanDialog(w, [])
d4.show()
pump(ms=100)
check("bos pencere: PDF olustur pasif", not d4.btn_run.isEnabled() and not d4.btn_auto.isEnabled())
d4.close()

shot = os.path.join(SP, "g2_scan.png")
dlg2 = ScanDialog(w, [P1, P2])
dlg2.resize(1180, 800)
dlg2.show()
pump(ms=500)
dlg2.grab().save(shot)

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
print("ekran:", shot)
sys.stdout.flush()
from PySide6.QtCore import QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
os._exit(0 if all(ok) else 1)
