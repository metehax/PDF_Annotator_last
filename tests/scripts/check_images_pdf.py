import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
SP = tempfile.gettempdir()
import numpy as np
import pymupdf as fitz
from PIL import Image

tmp = tempfile.mkdtemp(prefix="g3_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


# --- gorseller: dikey jpg, yatay png, EXIF yonlu jpg (gorunum dikey), buyuk gurultulu png
A = os.path.join(tmp, "a.jpg")
B = os.path.join(tmp, "b.png")
C = os.path.join(tmp, "c.jpg")
BIG = os.path.join(tmp, "buyuk.png")
Image.new("RGB", (400, 800), (200, 30, 30)).save(A)
Image.new("RGB", (800, 400), (30, 160, 60)).save(B)
exif = Image.Exif()
exif[0x0112] = 6
Image.new("RGB", (200, 100), (30, 60, 200)).save(C, exif=exif)
Image.fromarray(np.random.default_rng(0).integers(0, 255, (3000, 4500, 3), dtype=np.uint8)).save(BIG)
NOTIMG = os.path.join(tmp, "not.txt")
open(NOTIMG, "w").write("x")

import scan
from convert import Cancelled


def sizes(path):
    with fitz.open(path) as d:
        return [(round(p.rect.width), round(p.rect.height)) for p in d]


# ---- cekirdek: tek PDF
calls = []
out = os.path.join(tmp, "tek.pdf")
res = scan.images_to_pdfs([A, B, C], out, progress=lambda i, n: calls.append((i, n)))
check("tek PDF: dosya + sayfa sayisi", res == [out] and len(sizes(out)) == 3 and not os.path.exists(out + ".part"))
sz = sizes(out)
check("tek PDF: A4, yon otomatik (dikey, yatay, dikey[EXIF])", sz == [(595, 842), (842, 595), (595, 842)], str(sz))
check("ilerleme (0..n)", calls[0] == (0, 3) and calls[-1] == (3, 3), str(calls))

for yon, exp in (("dikey", (595, 842)), ("yatay", (842, 595)), ("Yatay", (842, 595))):
    p = os.path.join(tmp, f"y_{yon}.pdf")
    scan.images_to_pdfs([A, B], p, yon=yon)
    check(f"yon {yon}", all(s == exp for s in sizes(p)), str(sizes(p)))
p = os.path.join(tmp, "letter.pdf")
scan.images_to_pdfs([A], p, sayfa_boyutu="letter")
check("letter", sizes(p) == [(612, 792)])
p = os.path.join(tmp, "orj.pdf")
scan.images_to_pdfs([A, B], p, sayfa_boyutu="orijinal", yon="yatay")
s0, s1 = sizes(p)
check("orijinal oran (yon yok sayilir)", abs(s0[0] / s0[1] - 0.5) < 0.01 and abs(s1[0] / s1[1] - 2.0) < 0.01, str(sizes(p)))
p = os.path.join(tmp, "marj.pdf")
scan.images_to_pdfs([A], p, kenar_bosluk_pt=50)
with fitz.open(p) as d:
    bb = d[0].get_image_info()[0]["bbox"]
check("kenar boslugu", bb[0] >= 49.9 and bb[1] >= 49.9 and bb[2] <= 595.3 - 49.9 and bb[3] <= 841.9 - 49.9, str(bb))
q_lo = os.path.getsize(scan.images_to_pdfs([BIG], os.path.join(tmp, "q30.pdf"), jpeg_kalite=30)[0])
q_hi = os.path.getsize(scan.images_to_pdfs([BIG], os.path.join(tmp, "q95.pdf"), jpeg_kalite=95)[0])
check("kalite boyutu etkiler", q_lo < q_hi, f"{q_lo} {q_hi}")
with fitz.open(os.path.join(tmp, "q95.pdf")) as d:
    info = d.extract_image(d[0].get_images()[0][0])
check("buyuk gorsel 4000 px ile sinirli (3000 degil)", max(info["width"], info["height"]) == 4000, f"{info['width']}x{info['height']}")

# ---- ayri PDF'ler
odir = os.path.join(tmp, "ayri")
res = scan.images_to_pdfs([A, B, C], odir, ayri=True)
check("ayri: 3 dosya, adlar gorsel adi", sorted(os.path.basename(r) for r in res) == ["a.pdf", "b.pdf", "c.pdf"]
      and all(len(sizes(r)) == 1 for r in res))
res2 = scan.images_to_pdfs([A], odir, ayri=True)
check("ayri: var olan bozulmaz, (2) eklenir", os.path.basename(res2[0]) == "a (2).pdf" and os.path.exists(os.path.join(odir, "a.pdf")))

# ---- iptal / hata
n = {"i": 0}


def cancel_after(k):
    def f():
        n["i"] += 1
        return n["i"] > k
    return f


for mode, tgt in ((False, os.path.join(tmp, "iptal.pdf")), (True, os.path.join(tmp, "iptal_dir"))):
    n["i"] = 0
    try:
        scan.images_to_pdfs([A, B, C, BIG], tgt, ayri=mode, cancelled=cancel_after(2))
        raised = False
    except Cancelled:
        raised = True
    left = [f for f in (os.listdir(tgt) if mode and os.path.isdir(tgt) else [])]
    check(f"iptal ({'ayri' if mode else 'tek'}): Cancelled, dosya kalmadi",
          raised and not os.path.exists(tgt + ".part") and (not mode and not os.path.exists(tgt) or mode and left == []), str(left))
bad = os.path.join(tmp, "hata.pdf")
try:
    scan.images_to_pdfs([A, NOTIMG], bad)
    err = False
except Exception:
    err = True
check("gecersiz girdi: hata + yarim dosya yok", err and not os.path.exists(bad) and not os.path.exists(bad + ".part"))
for bad_call, nm in ((lambda: scan.images_to_pdfs([], os.path.join(tmp, "x.pdf")), "bos liste"),
                     (lambda: scan.to_pdf([A], yon="capraz"), "yon")):
    try:
        bad_call()
        raised = False
    except ValueError:
        raised = True
    check(f"gecersiz {nm}: ValueError", raised)

# ====================== pencere ======================
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QAction
import main_window as mw
from ui.imgpdf import ImagesPdfDialog

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
check("menü: Görselleri PDF'e çevir…", "Görselleri PDF'e çevir…" in texts)

dlg = ImagesPdfDialog(w, [B, A, C])
dlg.resize(780, 660)
dlg.show()
pump(ms=300)
names = lambda: [os.path.basename(p) for p in dlg.paths]
check("3 gorsel, sirayla, kucuk resimli", names() == ["b.png", "a.jpg", "c.jpg"] and all(not dlg.list.item(i).icon().isNull() for i in range(3)))
dlg.sort_by_name()
check("ada gore sirala", names() == ["a.jpg", "b.png", "c.jpg"])
dlg.list.item(0).setSelected(True)
dlg.move_selected(1)
check("secileni sona tasi", names() == ["b.png", "a.jpg", "c.jpg"], str(names()))
dlg.move_selected(-1)
check("secileni one tasi", names() == ["a.jpg", "b.png", "c.jpg"])
dlg.list.clearSelection()
dlg.list.item(2).setSelected(True)
dlg.move_selected(1)
check("sona tasima sinirda degismez", names() == ["a.jpg", "b.png", "c.jpg"])
dlg.list.clearSelection()
dlg.list.item(1).setSelected(True)
dlg.remove_selected()
check("kaldir", names() == ["a.jpg", "c.jpg"])
n_add = dlg.add_files([B, NOTIMG])
check("ekle: gorsel eklenir, gorsel olmayan atlanir", n_add == 1 and names() == ["a.jpg", "c.jpg", "b.png"] and "not.txt" in dlg.status.text())
dlg.list.filesDropped.emit([BIG])
check("surukle-birak yolu (filesDropped)", names()[-1] == "buyuk.png")
dlg.remove_selected()
dlg.list.clearSelection()
dlg.list.item(3).setSelected(True)
dlg.remove_selected()
folder = os.path.join(tmp, "klasor")
os.makedirs(folder)
for nm, src in (("1.jpg", A), ("2.png", B)):
    Image.open(src).save(os.path.join(folder, nm))
open(os.path.join(folder, "oku.txt"), "w").write("x")
check("klasor eklenir (yalniz gorseller)", dlg.add_files([folder]) == 2 and names()[-2:] == ["1.jpg", "2.png"])
for _ in range(2):
    dlg.list.clearSelection()
    dlg.list.item(dlg.list.count() - 1).setSelected(True)
    dlg.remove_selected()
check("orijinalde yon/kenar pasif", (dlg.cb_size.setCurrentIndex(2), dlg.cb_orient.isEnabled() or dlg.sp_margin.isEnabled())[1] is False)
dlg.cb_size.setCurrentIndex(0)
check("A4'te yon/kenar etkin", dlg.cb_orient.isEnabled() and dlg.sp_margin.isEnabled())

# -- tek PDF uret -> uygulamada acilir
OUT1 = os.path.join(tmp, "uygulama_tek.pdf")
ns = len(w.sessions)
dlg.cb_orient.setCurrentIndex(1)
dlg.sp_margin.setValue(20)
dlg.start_export(OUT1)
check("tek: bitti", pump(until=lambda: bool(dlg.results), limit=60000), dlg.status.text())
check("tek: 3 dikey A4 sayfa", sizes(OUT1) == [(595, 842)] * 3, str(sizes(OUT1)))
check("tek: uygulamada acildi, pencere kapandi", len(w.sessions) == ns + 1 and not dlg.isVisible())

# -- her biri ayri
d2 = ImagesPdfDialog(w, [A, B, C])
d2.show()
pump(ms=200)
d2.r_sep.setChecked(True)
ODIR = os.path.join(tmp, "ayri_ui")
ns = len(w.sessions)
d2.start_export(ODIR)
check("ayri: bitti", pump(until=lambda: bool(d2.results), limit=60000), d2.status.text())
check("ayri: 3 PDF, 3 sekme", sorted(os.listdir(ODIR)) == ["a.pdf", "b.pdf", "c.pdf"] and len(w.sessions) == ns + 3, str(os.listdir(ODIR)))

# -- iptal
d3 = ImagesPdfDialog(w, [BIG] * 6)
d3.show()
pump(ms=300)
OUT3 = os.path.join(tmp, "ui_iptal.pdf")
d3.start_export(OUT3)
check("iptal: calisirken dugmeler", d3.btn_stop.isVisible() and not d3.btn_run.isVisible() and not d3.btn_add.isEnabled())
d3.stop()
check("iptal: is bitti", pump(until=lambda: d3._job is None, limit=120000), d3.status.text())
check("iptal: dosya yok, pencere acik", not os.path.exists(OUT3) and not os.path.exists(OUT3 + ".part") and d3.isVisible() and d3.btn_run.isEnabled())
d3.close()

# -- bos pencere
d4 = ImagesPdfDialog(w)
d4.show()
pump(ms=100)
check("bos: PDF olustur pasif", not d4.btn_run.isEnabled() and d4.generate() is None)
d4.close()

shot = os.path.join(SP, "g3_images.png")
d5 = ImagesPdfDialog(w, [A, B, C, BIG])
d5.resize(780, 660)
d5.show()
pump(ms=500)
d5.grab().save(shot)

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
print("ekran:", shot)
sys.stdout.flush()
from PySide6.QtCore import QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
os._exit(0 if all(ok) else 1)
