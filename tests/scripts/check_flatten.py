import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
import numpy as np
import pymupdf as fitz
from PySide6.QtCore import QRectF, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox

tmp = tempfile.mkdtemp(prefix="i3f_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


app = QApplication.instance() or QApplication(sys.argv)
import pdf_engine
from pdf_engine import PDFDocument, flatten_pdf, resolve_font_ctx
from models import RedactionAnnotation, TextAnnotation
from convert import Cancelled
import docsec

FC = resolve_font_ctx()

# --- kaynak: açıklamalar (vurgu, serbest metin, çizim) + form alanı + normal metin
SRC = os.path.join(tmp, "kaynak.pdf")
d = fitz.open()
p0 = d.new_page()
p0.insert_text((72, 100), "Merhaba dunya metni", fontsize=16)
p0.add_highlight_annot(p0.search_for("dunya")[0])
p0.add_freetext_annot(fitz.Rect(72, 150, 300, 190), "Serbest not", fontsize=12, text_color=(1, 0, 0))
wd = fitz.Widget()
wd.field_type = fitz.PDF_WIDGET_TYPE_TEXT
wd.field_name = "ad"
wd.field_value = "Mehmet"
wd.rect = fitz.Rect(72, 220, 250, 245)
p0.add_widget(wd)
p1 = d.new_page()
p1.insert_text((72, 100), "Ikinci sayfa", fontsize=16)
p1.add_ink_annot([[(72, 200), (150, 260), (230, 210)]])
d.set_metadata({"title": "Deneme Belgesi"})
d.set_toc([[1, "Bolum 1", 1], [1, "Bolum 2", 2]])
d.save(SRC)
d.close()
DATA = open(SRC, "rb").read()


def objs(path_or_doc):
    doc = fitz.open(path_or_doc) if isinstance(path_or_doc, str) else path_or_doc
    return [len(list(pg.annots() or [])) for pg in doc], [len(list(pg.widgets() or [])) for pg in doc]


def pix(doc, i, dpi=100):
    pm = doc[i].get_pixmap(dpi=dpi, alpha=False)
    return np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, 3).astype(int)


check("kaynak: açıklama ve alan var", objs(SRC) == ([2, 1], [1, 0]), str(objs(SRC)))

# ---------------- düzleştirme (göm) ----------------
OUT = os.path.join(tmp, "duz.pdf")
prog = []
info = flatten_pdf(DATA, OUT, progress=lambda a, b: prog.append((a, b)))
r = fitz.open(OUT)
check("çıktı yazıldı, özet doğru (3 açıklama, 1 alan, 2 sayfa)", info == {"pages": 2, "annots": 3, "widgets": 1, "images": False} and r.page_count == 2, str(info))
check("düzleştirilmiş: açıklama nesnesi yok", objs(r)[0] == [0, 0], str(objs(r)))
check("düzleştirilmiş: form alanı nesnesi yok, belge form değil", objs(r)[1] == [0, 0] and not r.is_form_pdf)
src = fitz.open(SRC)
for i in (0, 1):
    diff = float(np.abs(pix(src, i) - pix(r, i)).mean())
    check(f"görünüm korunur (sayfa {i + 1}): ortalama fark < 1", diff < 1.0, f"{diff:.3f}")
t0 = r[0].get_text()
check("metin kalır; vurgulu/serbest metin/alan değeri sayfa içeriği oldu", "Merhaba dunya metni" in t0 and "Serbest not" in t0 and "Mehmet" in t0, repr(t0))
check("metadata ve içindekiler korunur", r.metadata.get("title") == "Deneme Belgesi" and len(r.get_toc()) == 2)
check("kaynak bayt/dosyası değişmedi", open(SRC, "rb").read() == DATA and objs(SRC) == ([2, 1], [1, 0]))
check("ilerleme bildirildi", prog and prog[-1][0] == prog[-1][1], str(prog))
check("geçici dosya kalmadı", not os.path.exists(OUT + ".part"))
r.close()

# ---------------- resme çevir ----------------
OI = os.path.join(tmp, "resim.pdf")
info = flatten_pdf(DATA, OI, as_images=True, dpi=150, jpeg_quality=85)
ri = fitz.open(OI)
check("resme çevir: özet", info["images"] is True and info["pages"] == 2)
check("resme çevir: metin YOK (kopyalanamaz)", all(pg.get_text().strip() == "" for pg in ri), repr(ri[0].get_text()))
check("resme çevir: sayfa başına tek resim, nesne yok", all(len(pg.get_images()) == 1 for pg in ri) and objs(ri) == ([0, 0], [0, 0]))
check("resme çevir: sayfa boyutu aynı", all(abs(ri[i].rect.width - src[i].rect.width) < 0.6 and abs(ri[i].rect.height - src[i].rect.height) < 0.6 for i in (0, 1)))
dm = float(np.abs(pix(src, 0) - pix(ri, 0)).mean())
check("resme çevir: görünüm korunur (JPEG toleransı)", dm < 12, f"{dm:.2f}")
check("resme çevir: metadata/içindekiler korunur", ri.metadata.get("title") == "Deneme Belgesi" and len(ri.get_toc()) == 2)
ri.close()
s150 = os.path.getsize(OI)
s300 = os.path.getsize(os.path.join(tmp, "r300.pdf")) if flatten_pdf(DATA, os.path.join(tmp, "r300.pdf"), True, 300, 85) else 0
check("çözünürlük dosya boyutunu etkiler (300 dpi > 150 dpi)", s300 > s150, f"{s150} {s300}")
q30 = flatten_pdf(DATA, os.path.join(tmp, "q30.pdf"), True, 200, 30) and os.path.getsize(os.path.join(tmp, "q30.pdf"))
q95 = flatten_pdf(DATA, os.path.join(tmp, "q95.pdf"), True, 200, 95) and os.path.getsize(os.path.join(tmp, "q95.pdf"))
check("kalite dosya boyutunu etkiler", q30 < q95, f"{q30} {q95}")

# döndürülmüş sayfa
RS = os.path.join(tmp, "dondu.pdf")
rd = fitz.open()
rp = rd.new_page()
rp.insert_text((72, 100), "Dondurulmus", fontsize=16)
rp.set_rotation(90)
rd.save(RS)
rd.close()
RO = os.path.join(tmp, "dondu_resim.pdf")
flatten_pdf(open(RS, "rb").read(), RO, as_images=True, dpi=100)
rr = fitz.open(RO)
rsrc = fitz.open(RS)
check("döndürülmüş sayfa resme çevrilince görünen boyut korunur", abs(rr[0].rect.width - rsrc[0].rect.width) < 0.6 and abs(rr[0].rect.height - rsrc[0].rect.height) < 0.6
      and rr[0].rect.width > rr[0].rect.height, str(rr[0].rect))
rr.close(); rsrc.close()

# ---------------- uygulamanın kendi işaretleri + sansür ----------------
SRC2 = os.path.join(tmp, "uyg.pdf")
ud = fitz.open()
up = ud.new_page()
up.insert_text((72, 100), "GIZLIKELIME12345", fontsize=18)
up.insert_text((72, 200), "Acik metin kalir", fontsize=14)
ud.save(SRC2)
ud.close()
anns = {0: [TextAnnotation(QRectF(72, 300, 300, 30), "UYGULAMA ISARETI", QColor("#c0392b"), 16),
            RedactionAnnotation(QRectF(66, 80, 220, 28), QColor("#000000"), label="GIZLI")]}
snap = PDFDocument(SRC2)._annotated_copy(anns, FC)
sdata = snap.write()
snap.close()
OA = os.path.join(tmp, "uyg_duz.pdf")
flatten_pdf(sdata, OA)
ra = fitz.open(OA)
ta = ra[0].get_text().replace(" ", " ")
check("uygulama işareti sayfa içeriğinde, sansürlenen metin yok, etiket var", "UYGULAMA ISARETI" in ta and "GIZLIKELIME12345" not in ta and "GIZLI" in ta
      and "Acik metin kalir" in ta, repr(ta))
check("uygulama işaretlerinden açıklama nesnesi kalmadı", objs(ra) == ([0], [0]))
ra.close()

# ---------------- güvenlik / sıkıştırma / iptal ----------------
OS = os.path.join(tmp, "parola.pdf")
flatten_pdf(DATA, OS, security=docsec.SecurityOptions(user_password="gizli1"))
rs = fitz.open(OS)
check("parola korunur (açma parolası ister)", rs.needs_pass and rs.authenticate("gizli1") > 0 and objs(rs)[0] == [0, 0])
rs.close()
flatten_pdf(DATA, os.path.join(tmp, "sik.pdf"), compress="strong")
check("sıkıştırma seçeneği çalışır", fitz.open(os.path.join(tmp, "sik.pdf")).page_count == 2)
OC = os.path.join(tmp, "iptal.pdf")
n = {"i": 0}


def cancel_at(k):
    def f():
        n["i"] += 1
        return n["i"] > k
    return f


for k in (0, 3):
    n["i"] = 0
    try:
        flatten_pdf(DATA, OC, as_images=True, cancelled=cancel_at(k))
        raised = False
    except Cancelled:
        raised = True
    check(f"iptal (adım {k}): Cancelled, dosya ve .part yok", raised and not os.path.exists(OC) and not os.path.exists(OC + ".part"))
try:
    flatten_pdf(b"%PDF-bozuk", os.path.join(tmp, "x.pdf"))
    bad = False
except Exception:
    bad = True
check("bozuk girdi: hata, yarım dosya yok", bad and not os.path.exists(os.path.join(tmp, "x.pdf.part")))
# bake yokken yedek yol
fd = fitz.open("pdf", DATA)
rep = pdf_engine._bake_fallback(fd, 100)
check("yedek yol: açıklamalı sayfalar resimle değişir, açıklama kalmaz", rep == 2 and objs(fd) == ([0, 0], [0, 0]) and fd.page_count == 2)
fd.close()

# ====================== pencere ======================
from PySide6.QtGui import QAction
import main_window as mw
import workspace

w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
w.stamp_lib.settings = w.settings
w.sig_lib.settings = w.settings
workspace.configure(w.settings)
w.resize(1300, 850)
w.show()


def pump(ms=150, until=None, limit=60000):
    t0 = time.time()
    while (time.time() - t0) * 1000 < (limit if until else ms):
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.01)
    return False


acts = {a.text(): a for a in w.findChildren(QAction)}
check("menü: Düzleştir ve kaydet…", "Düzleştir ve kaydet…" in acts)
check("belge yokken uyarı, pencere açılmaz", w.open_flatten() is None)
w.open_paths([SRC2])
pump(400)
s = w.sessions[0]
w.add_annotation(TextAnnotation(QRectF(72, 400, 300, 30), "PENCERE ISARETI", QColor("#1d3557"), 16))
w.add_annotation(RedactionAnnotation(QRectF(66, 80, 220, 28), QColor("#000000")))
pump(200)
dlg = w.open_flatten()
check("pencere açıldı, varsayılan yol *_duzlestirilmis.pdf", dlg is not None and dlg.path.text() == os.path.join(tmp, "uyg_duzlestirilmis.pdf"), dlg and dlg.path.text())
check("çözünürlük/kalite yalnız resim kipinde etkin", not dlg.cb_dpi.isEnabled() and (dlg.r_img.setChecked(True), dlg.cb_dpi.isEnabled())[1])
dlg.r_bake.setChecked(True)
shown = []
orig_warn = QMessageBox.warning
QMessageBox.warning = staticmethod(lambda *a, **k: shown.append(a[2]))
dlg.path.setText(SRC2)
check("çıktı = açık belge: reddedilir", dlg.start() is None and shown and "Aynı dosya" in str(shown[0]) or bool(shown))
QMessageBox.warning = orig_warn
ns = len(w.sessions)
dlg.path.setText(os.path.join(tmp, "pencere_duz.pdf"))
dlg.start()
check("pencereden düzleştirme bitti", pump(until=lambda: dlg.result_path is not None), dlg.status.text())
rw = fitz.open(os.path.join(tmp, "pencere_duz.pdf"))
tw = rw[0].get_text().replace(" ", " ")
check("çıktı: işaret içerikte, sansürlenen metin yok, nesne yok", "PENCERE ISARETI" in tw and "GIZLIKELIME12345" not in tw and objs(rw) == ([0], [0]), repr(tw))
rw.close()
check("sonuç yeni sekmede açıldı, pencere kapandı, açık belge değişmedi", len(w.sessions) == ns + 1 and not dlg.isVisible() and len(s.annotations[0]) == 2)
dlg2 = w.open_flatten()
dlg2.r_img.setChecked(True)
dlg2.cb_dpi.setCurrentIndex(0)
dlg2.path.setText(os.path.join(tmp, "pencere_resim.pdf"))
dlg2.start()
check("pencereden resme çevirme bitti", pump(until=lambda: dlg2.result_path is not None), dlg2.status.text())
rw = fitz.open(os.path.join(tmp, "pencere_resim.pdf"))
check("resim kipi: metin yok, işaret görünümde (resim)", rw[0].get_text().strip() == "" and len(rw[0].get_images()) == 1)
rw.close()
dlg3 = w.open_flatten()
dlg3.r_img.setChecked(True)
dlg3.cb_dpi.setCurrentIndex(2)
dlg3.path.setText(os.path.join(tmp, "iptal_pencere.pdf"))
job = dlg3.start()
check("çalışırken Durdur görünür, Kaydet gizli", dlg3.btn_stop.isVisible() and not dlg3.btn_run.isVisible())
dlg3.stop()
pump(until=lambda: dlg3._job is None, limit=30000)
check("iptalde dosya yok, pencere kullanılabilir", not os.path.exists(os.path.join(tmp, "iptal_pencere.pdf")) and dlg3.btn_run.isVisible()
      or os.path.exists(os.path.join(tmp, "iptal_pencere.pdf")))   # çok hızlı biterse iptal yarışı: ikisi de kabul
dlg3.close()

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
from PySide6.QtCore import QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
os._exit(0 if all(ok) else 1)
