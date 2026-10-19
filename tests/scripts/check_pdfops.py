import os, shutil, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
import pymupdf as fitz

tmp = tempfile.mkdtemp(prefix="l2_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


def make(name, n, toc=None):
    d = fitz.open()
    for i in range(n):
        d.new_page().insert_text((72, 72), f"{name}{i + 1}")
    if toc:
        d.set_toc(toc)
    p = os.path.join(tmp, name + ".pdf")
    d.save(p)
    d.close()
    return p


def texts(p):
    with fitz.open(p) as d:
        return [pg.get_text().strip() for pg in d]


import pdfops
from convert import Cancelled

A = make("A", 10, [[1, "Giris bolumu", 1], [1, "Orta", 4], [2, "Alt", 5], [1, "Son", 8]])
B = make("B", 4)

# --- aralik ayristirma
check("aralik: karma", pdfops.parse_ranges("1-3, 5, 8-", 10) == [0, 1, 2, 4, 7, 8, 9])
check("aralik: bos = hepsi", pdfops.parse_ranges("", 3) == [0, 1, 2])
check("aralik: -3 = 1-3", pdfops.parse_ranges("-3", 10) == [0, 1, 2])
for bad in ("0", "11", "3-1", "a", "1,,2", "1-2-3", "x-3", ","):
    try:
        pdfops.parse_ranges(bad, 10)
        check("aralik hatali: " + bad, False)
    except ValueError as ex:
        check("aralik hatali: " + bad, bool(str(ex)))
check("aralik: grup", pdfops.parse_groups("1-2, 5", 10) == [[0, 1], [4]])
check("aralik bicim", pdfops.format_ranges([0, 1, 2, 4]) == "1-3, 5")

# --- merge
out = os.path.join(tmp, "m.pdf")
pdfops.merge([(A, "2-3"), (B, ""), (A, "10")], out)
check("merge: sayfa sirasi", texts(out) == ["A2", "A3", "B1", "B2", "B3", "B4", "A10"], str(texts(out)))
check("merge: .part kalmadi", not os.path.exists(out + ".part"))
try:
    pdfops.merge([(A, "99")], os.path.join(tmp, "x.pdf"))
    check("merge: hatali aralik", False)
except ValueError as ex:
    check("merge: hatali aralik", "A.pdf" in str(ex) and not os.path.exists(os.path.join(tmp, "x.pdf")))
cancel_out = os.path.join(tmp, "c.pdf")
try:
    pdfops.merge([(A, ""), (B, "")], cancel_out, cancelled=lambda: True)
    check("merge: iptal", False)
except Cancelled:
    check("merge: iptal dosya birakmaz", not os.path.exists(cancel_out) and not os.path.exists(cancel_out + ".part"))

# --- split
d = os.path.join(tmp, "s1")
f = pdfops.split(A, d, "ranges", "1-3, 5, 8-10")
check("split aralik: 3 dosya", [len(texts(p)) for p in f] == [3, 1, 3] and texts(f[2]) == ["A8", "A9", "A10"], str(f))
check("split ad sablonu", os.path.basename(f[0]) == "A_1.pdf")
f2 = pdfops.split(A, d, "ranges", "1-3")
check("split cakismada numara", os.path.basename(f2[0]) == "A_1 (2).pdf" and len(os.listdir(d)) == 4)
f = pdfops.split(A, os.path.join(tmp, "s2"), "ranges_one", "1-2, 9-")
check("split tek dosya", len(f) == 1 and texts(f[0]) == ["A1", "A2", "A9", "A10"])
f = pdfops.split(A, os.path.join(tmp, "s3"), "every", every=4)
check("split N: 4+4+2", [len(texts(p)) for p in f] == [4, 4, 2], str([len(texts(p)) for p in f]))
f = pdfops.split(A, os.path.join(tmp, "s4"), "bookmarks", template="{n}_{aralik}")
check("split yer imi: 3+4+3", [len(texts(p)) for p in f] == [3, 4, 3], str([len(texts(p)) for p in f]))
check("split yer imi: ad baslik", os.path.basename(f[1]) == "2_Orta.pdf", os.path.basename(f[1]))
f = pdfops.split(A, os.path.join(tmp, "s5"), "pages", template="{ad}_s{aralik}")
check("split her sayfa", len(f) == 10 and os.path.basename(f[9]) == "A_s10.pdf")
try:
    pdfops.split(B, os.path.join(tmp, "s6"), "bookmarks")
    check("split yer imi yok", False)
except ValueError:
    check("split yer imi yok: hata + dosya yok", not os.path.isdir(os.path.join(tmp, "s6")) or not os.listdir(os.path.join(tmp, "s6")))
try:
    pdfops.split(A, os.path.join(tmp, "s7"), "pages", template="{yok}")
    check("split hatali sablon", False)
except ValueError:
    check("split hatali sablon", True)
n = [0]


def cancel_after_three():
    n[0] += 1
    return n[0] > 3


try:
    pdfops.split(A, os.path.join(tmp, "s8"), "pages", cancelled=cancel_after_three)
    check("split iptal", False)
except Cancelled:
    check("split iptalde dosya kalmaz", os.listdir(os.path.join(tmp, "s8")) == [])
f = pdfops.split_many([A, B], os.path.join(tmp, "s9"), per_file_dir=True, mode="every", every=2)
check("split coklu: 5+2 dosya, alt klasor", len(f) == 7 and os.path.isdir(os.path.join(tmp, "s9", "A")))
try:
    pdfops.split_many([B, A], os.path.join(tmp, "s10"), per_file_dir=True, mode="ranges", ranges="6-8")
    check("split coklu hata", False)
except ValueError as ex:
    check("split coklu hata: hicbir dosya kalmaz", "B.pdf" in str(ex) and not any(
        fn.endswith(".pdf") for _, _, fs in os.walk(os.path.join(tmp, "s10")) for fn in fs))

# --- UI
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import main_window as mw
from ui.mergesplit import MergeDialog, SplitDialog, PREVIEW_MAX

app = QApplication.instance() or QApplication(sys.argv)
w = mw.MainWindow()
w.sig_lib.settings = QSettings(os.path.join(tmp, 't2.ini'), QSettings.Format.IniFormat)
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
w.stamp_lib.settings = w.settings


def pump(until=None, limit=30000, ms=50):
    t = time.time()
    while (time.time() - t) * 1000 < limit:
        QApplication.processEvents()
        if until is None:
            if (time.time() - t) * 1000 > ms:
                return True
        elif until():
            return True
        time.sleep(0.01)
    return False


opened = []
w.open_paths = lambda ps: opened.append(ps)
dm = MergeDialog(w, [A, B])
dm.show()
check("birlestir: liste 2 dosya", dm.list.count() == 2)
dm.list.setCurrentRow(0)
dm.ed_range.setText("1-3, 5")
dm.preview.settle()
check("onizleme sayisi = secilen sayfa (4)", dm.preview.count() == 4, str(dm.preview.count()))
check("onizleme kucuk resim cizildi", not dm.preview.item(0).icon().isNull())
dm.ed_range.setText("20")
check("hatali aralikta ileti", bool(dm.lbl_err.text()) and dm.preview.count() == 0)
dm.ed_range.setText("")
check("bos aralik = tum sayfalar (10)", dm.preview.count() == 10)
dm.ed_range.setText("2-3")
dm.list.setCurrentRow(1)
check("dosya basina aralik korunur", dm.sources() == [(A, "2-3"), (B, "")], str(dm.sources()))
dm._move(-1)
check("one tasima sirayi degistirir", [os.path.basename(p) for p, _ in dm.sources()] == ["B.pdf", "A.pdf"])
mo = os.path.join(tmp, "ui_merge.pdf")
dm.start_merge(mo)
check("birlestir: bitti", pump(until=lambda: bool(dm.results)), dm.status.text())
check("birlestir ciktisi", texts(mo) == ["B1", "B2", "B3", "B4", "A2", "A3"], str(texts(mo)))
dm2 = MergeDialog(w, [])
fold = os.path.join(tmp, "klasor")
os.makedirs(fold)
shutil.copy(A, fold)
shutil.copy(B, fold)
open(os.path.join(fold, "x.txt"), "w").write("x")
check("klasorden ekle: yalniz PDF/resim", dm2.add_files([fold]) == 2)

big = make("BIG", PREVIEW_MAX + 40)
dm3 = MergeDialog(w, [big])
check("onizleme siniri", dm3.preview.count() == PREVIEW_MAX, str(dm3.preview.count()))

ds = SplitDialog(w, [A])
ds.show()
ds.cb_mode.setCurrentIndex(2)
ds.sp_every.setValue(3)
check("bol onizleme: 4 parca", ds.preview.count() == 4, str(ds.preview.count()))
ds.cb_mode.setCurrentIndex(3)
check("bol onizleme: yer imi 3 parca", ds.preview.count() == 3, str(ds.preview.count()))
ds.cb_mode.setCurrentIndex(0)
ds.ed_range.setText("1-2, 9")
check("bol onizleme: aralik 2 parca", ds.preview.count() == 2)
ds.ed_range.setText("40")
check("bol hatali aralik ileti", bool(ds.lbl_err.text()))
ds.add_files([B])
od = os.path.join(tmp, "ui_split")
ds.ed_range.setText("1-2")
ds.start_split(od)
check("bol: coklu bitti", pump(until=lambda: bool(ds.results)), ds.status.text())
check("bol: 2 PDF x 1 aralik", len(ds.results) == 2 and all(len(texts(p)) == 2 for p in ds.results), str(ds.results))
ds5 = SplitDialog(w, [big])
ds5.cb_mode.setCurrentIndex(4)
ds5.start_split(os.path.join(tmp, "ui_split2"))
pump(ms=1)
ds5.stop()
pump(until=lambda: ds5._job is None, limit=60000)
left = [f for _, _, fs in os.walk(os.path.join(tmp, "ui_split2")) for f in fs]
check("bol iptal/bitis tutarli (yarim dosya yok)",
      not any(f.endswith(".part") for f in left) and len(left) in (0, PREVIEW_MAX + 40), str(len(left)))

print(f"OZET: {sum(ok)}/{len(ok)} gecti")
sys.exit(0 if all(ok) else 1)
