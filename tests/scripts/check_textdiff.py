import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import fitz

tmp = tempfile.mkdtemp(prefix="d1_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


def make(path, pages, rotate=0):
    d = fitz.open()
    for lines in pages:
        p = d.new_page()
        y = 80
        for ln in lines:
            p.insert_text((72, y), ln, fontsize=12)
            y += 20
        if rotate:
            p.set_rotation(rotate)
    d.save(path)
    d.close()


A = os.path.join(tmp, "eski.pdf")
B = os.path.join(tmp, "yeni.pdf")
make(A, [["Sozlesme Metni", "Taraflar su sekilde anlasti.", "Bedel 1000 TL olarak belirlendi.", "Bu satir silinecek."],
         ["Ikinci sayfa baslik", "Teslim suresi 30 gun.", "Son satir ayni."]])
make(B, [["Sozlesme Metni", "Taraflar su sekilde anlasti.", "Yeni eklenen madde burada.", "Bedel 2500 TL olarak belirlendi."],
         ["Ikinci sayfa baslik", "Teslim suresi 30 gun.", "Son satir ayni.", "Ek not: gizlilik gecerlidir."]])

from pdf_engine import PDFDocument
import textdiff

# ---- cekirdek
pa, pb = PDFDocument(A), PDFDocument(B)
res = textdiff.compare(pa, pb)
kinds = [c.kind for c in res.changes]
print("degisiklikler:", [(c.kind, c.page, c.text_a, c.text_b) for c in res.changes])
check("fark bulundu", len(res.changes) >= 3, kinds)
check("1000->2500 degisen", any(c.kind == "mod" and "1000" in c.text_a and "2500" in c.text_b for c in res.changes))
check("silinen satir", any(c.kind == "del" and "silinecek" in c.text_a for c in res.changes))
check("eklenen satir (s1)", any(c.kind == "add" and "madde" in c.text_b and c.page == 0 for c in res.changes))
check("eklenen satir (s2)", any(c.kind == "add" and "gizlilik" in c.text_b and c.page == 1 for c in res.changes))
check("sayfa gruplari", list(res.by_page().keys()) == [0, 1], list(res.by_page().keys()))
dl = next(c for c in res.changes if c.kind == "del")
check("silmede yeni belgede karsilik noktasi", dl.focus_b() is not None and dl.focus_a() is not None)
ad = next(c for c in res.changes if c.kind == "add" and c.page == 1)
check("eklemede eski belgede karsilik noktasi", ad.focus_a() is not None and ad.focus_a()[0] in (0, 1))
same = textdiff.compare(pa, PDFDocument(A))
check("ayni belge -> fark yok", not same.changes and not same.error)
# buyuk/kucuk harf
C = os.path.join(tmp, "buyuk.pdf")
make(C, [["SOZLESME METNI", "Taraflar su sekilde anlasti.", "Bedel 1000 TL olarak belirlendi.", "Bu satir silinecek."],
         ["Ikinci sayfa baslik", "Teslim suresi 30 gun.", "Son satir ayni."]])
pc = PDFDocument(C)
check("harf duyarli: fark var", len(textdiff.compare(pa, pc).changes) >= 1)
check("harf yoksay: fark yok", not textdiff.compare(pa, pc, ignore_case=True).changes)
ins = next(c for c in res.changes if c.kind == "add" and c.page == 0)
check("ekleme komsu degisiklige yapismaz", ins.text_b == "Yeni eklenen madde burada.", ins.text_b)
check("1000->2500 yalniz o kelime", any(c.kind == "mod" and c.text_a == "1000" and c.text_b == "2500" for c in res.changes))
F1, F2 = os.path.join(tmp, "f1.pdf"), os.path.join(tmp, "f2.pdf")
make(F1, [["alfa beta gama delta epsilon"]])
make(F2, [["alfa BETA gama DELTA epsilon"]])
mg = textdiff.compare(PDFDocument(F1), PDFDocument(F2))
check("ayni satirda tek kelime arali farklar birlesir", len(mg.changes) == 1 and mg.changes[0].kind == "mod", [(c.kind, c.text_a) for c in mg.changes])
# metinsiz belge
E = os.path.join(tmp, "bos.pdf")
d = fitz.open(); d.new_page(); d.save(E); d.close()
pe = PDFDocument(E)
check("metinsiz sol -> no_text_a", textdiff.compare(pe, pb).error == "no_text_a")
check("metinsiz sag -> no_text_b", textdiff.compare(pa, pe).error == "no_text_b")
# iptal
check("iptal", textdiff.compare(pa, pb, check=lambda: True).cancelled)
# dondurulmus sayfa: dikdortgenler gorunen sayfa icinde
R = os.path.join(tmp, "don.pdf")
make(R, [["Dondurulmus sayfa metni burada", "ikinci satir"]], rotate=90)
pr = PDFDocument(R)
lines = textdiff.extract_lines(pr)
pw, ph = pr.page_size(0)
inside = all(-1 <= w.rect[0] and w.rect[2] <= pw + 1 and -1 <= w.rect[1] and w.rect[3] <= ph + 1
             for ln in lines for w in ln)
check("dondurulmus sayfada rect gorunen sayfa icinde", lines and inside, f"{pw}x{ph}")
# render ile dogrula: kutudaki piksellerde koyu icerik var
pm = pr.doc[0].get_pixmap(clip=fitz.Rect(*lines[0][0].rect), alpha=False)
dark = sum(1 for i in range(0, len(pm.samples), pm.n) if pm.samples[i] < 100)
check("rect gercekten metnin ustunde", dark > 5, dark)

# ---- arayuz
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
from PySide6.QtCore import QSettings, QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
import main_window as mw

app = QApplication.instance() or QApplication(sys.argv)
w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
w.stamp_lib.settings = w.settings
w.sig_lib.settings = w.settings
w.resize(1500, 900)
w.show()


def pump(ms=200, until=None, limit=8000):
    t0 = time.time()
    while (time.time() - t0) * 1000 < limit:
        app.processEvents()
        if until and until():
            return True
        if until is None and (time.time() - t0) * 1000 >= ms:
            return True
        time.sleep(0.01)
    return False


w.open_paths([A, B])
pump(300)
check("iki oturum acik", len(w.sessions) == 2, len(w.sessions))
w.compare_documents()
check("sonuc geldi", pump(until=lambda: w._diff is not None), "zaman asimi")
check("karsilastirma modu acik", w.act_compare.isChecked() and w.canvas_stack.currentIndex() == 1)
check("sol/sag farkli belge", w.pane_left.session is not w.pane_right.session)
n_top = w.diff_panel.tree.topLevelItemCount()
check("panelde 2 sayfa grubu", n_top == 2, n_top)
check("ozet metni", "eklenen" in w.diff_panel.summary.text(), w.diff_panel.summary.text())
print("ozet:", w.diff_panel.summary.text())
check("sol panelde kirmizi, sag panelde yesil isaret",
      sum(len(v) for v in w.pane_left._marks.values()) >= 2 and sum(len(v) for v in w.pane_right._marks.values()) >= 2)
check("sol isaretler 'del', sag 'add'",
      all(m[4] == "del" for v in w.pane_left._marks.values() for m in v)
      and all(m[4] == "add" for v in w.pane_right._marks.values() for m in v))
from PySide6.QtWidgets import QGraphicsRectItem
check("sahnede vurgu ogeleri", sum(isinstance(i, QGraphicsRectItem) for i in w.pane_right.scene.items()) >= 1)

# listeden tikla -> git
leaves = w.diff_panel._leaves()
check("yaprak sayisi", len(leaves) == len(res.changes), (len(leaves), len(res.changes)))
target = next(i for i in leaves if "gizlilik" in i.toolTip(0))
w.diff_panel.tree.setCurrentItem(target)
w.diff_panel._on_item(target)
pump(100)
check("tiklayinca sag pane sayfa 2'ye gitti", w.pane_right.page == 1, w.pane_right.page)
check("odak halkasi cizildi", w.pane_right._focus is not None and w.pane_right._focus[0] == 1)
target2 = next(i for i in leaves if "silinecek" in i.toolTip(0))
w.diff_panel._on_item(target2)
pump(100)
check("silineni tiklayinca sol pane sayfa 1", w.pane_left.page == 0 and w.pane_left._focus is not None)

# gezinti
w.diff_panel.tree.setCurrentItem(None)
w.diff_panel._last_c = None
w.diff_panel.step(1)
pump(100)
first = w.diff_panel.tree.currentItem()
check("sonraki -> ilk degisiklik", first is leaves[0])
w.diff_panel._last_t = 0
w.diff_panel.step(-1)
check("onceki -> sarmalama (son)", w.diff_panel.tree.currentItem() is leaves[-1])

# suzgec
w.diff_panel.chk["mod"].setChecked(False)
pump(100)
check("suzgec: degisen gizlenir", all(i.data(0, 0x100).kind != "mod" for i in w.diff_panel._leaves()))
check("suzgec: isaretler guncellendi",
      sum(len(v) for v in w.pane_right._marks.values()) < sum(len(c.b_rects) for c in res.changes))
w.diff_panel.chk["mod"].setChecked(True)

# ayni belge secimi
w.pane_right.combo.setCurrentIndex(w.pane_left.combo.currentIndex())
pump(1000, until=lambda: "FARKLI" in w.diff_panel.summary.text())
check("ayni belge -> uyari", "FARKLI" in w.diff_panel.summary.text(), w.diff_panel.summary.text())
check("ayni belge -> isaret yok", not w.pane_left._marks and not w.pane_right._marks)

# yeniden sec -> otomatik hesap
w.pane_right.combo.setCurrentIndex(1 - w.pane_left.combo.currentIndex())
check("combo degisince otomatik yeniden hesap", pump(until=lambda: w._diff is not None))

# modu kapat
w.act_compare.setChecked(False)
w.toggle_compare_mode(False)
check("mod kapaninca iptal", w._diff is None and not w.pane_left._marks)
w.act_compare.setChecked(True)
w.toggle_compare_mode(True)
pump(until=lambda: w._diff is not None)

# gorsel: tek ekran goruntusu
w.diff_panel._on_item(next(i for i in w.diff_panel._leaves() if "2500" in i.toolTip(0)))
pump(300)
shot = os.path.join(tempfile.gettempdir(), "d1_ekran.png")
w.grab().save(shot)
print("ekran:", shot)

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
from PySide6.QtCore import QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
os._exit(0 if all(ok) else 1)

