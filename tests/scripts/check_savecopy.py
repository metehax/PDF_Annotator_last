"""Kaydet/Farklı kaydet/Tümünü kaydet/otomatik kaydet, aynı konuma toplu işaretleme ve Metin Seç + otomatik OCR."""
import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
import pymupdf as fitz
from PySide6.QtCore import QPointF, QRectF, QSettings
from PySide6.QtGui import QColor, QImage, QPainter, QFont
from PySide6.QtWidgets import QApplication

tmp = tempfile.mkdtemp(prefix="sc_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


app = QApplication.instance() or QApplication(sys.argv)
import main_window as mw
import workspace, ocr
from models import RedactionAnnotation
from ui.savedlg import parse_pages
from mw_textcopy import words_to_text


def make(name, pages=5, w=595):
    p = os.path.join(tmp, name)
    d = fitz.open()
    for i in range(pages):
        pg = d.new_page(width=w, height=842)
        pg.insert_text((100, 120), f"TC: 1234567890{i}  sayfa {i + 1}")
    d.save(p); d.close()
    return p


def pump(cond, secs=60):
    t = time.time()
    while not cond() and time.time() - t < secs:
        app.processEvents(); time.sleep(0.02)
    return cond()


a = make("a.pdf"); b = make("b.pdf", 3)
w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
w.stamp_lib.settings = w.settings; w.sig_lib.settings = w.settings
workspace.configure(w.settings)
w.resize(1200, 800); w.show()
w.open_paths([a, b]); app.processEvents()
sa, sb = w.sessions

check("aralık ayrıştırma", parse_pages("2-3, 5", 5) == [1, 2, 4] and parse_pages("9", 5) is None)

# --- tüm sayfalara aynı konum
w.switch_session(0); app.processEvents()
w.state.repeat_pages = True
w.add_annotation(RedactionAnnotation(QRectF(100, 100, 250, 30), QColor("black")))
check("5 sayfada kutu", all(len(sa.annotations[i]) == 1 for i in range(5)))
sa.undo_stack.undo()
check("tek geri al hepsini siler", all(len(sa.annotations[i]) == 0 for i in range(5)))
sa.undo_stack.redo()
w.state.repeat_pages = False
sb.annotations[0].append(RedactionAnnotation(QRectF(50, 50, 100, 20), QColor("black")))
w.switch_session(1); app.processEvents()
w.ask_page_scope = lambda s: [1]
g = next(iter(w.view.item_ann_map)); g.setSelected(True)
w.apply_selected_to_pages()
check("seçili işaret sayfa 2'ye", len(sb.annotations[1]) == 1 and len(sb.annotations[2]) == 0)

# --- Kaydet = özgün dosyanın üzerine
w._ask_redaction_summary = lambda n, pages: "save"
w.switch_session(0); app.processEvents()
w.save_document()
d = fitz.open(a)
check("üzerine yazıldı, sansürlü metin yok", "1234567890" not in d[2].get_text())
d.close()
check("temiz, işaret bellekte, geri alınabilir",
      not w._is_dirty(sa) and len(sa.annotations[0]) == 1 and sa.undo_stack.canUndo())
check("geçici dosya kalmadı", not os.path.exists(a + ".kaydediliyor"))
check("özgün b.pdf dokunulmadı", "1234567890" in fitz.open(b)[2].get_text())

# --- otomatik kaydet
w.act_autosave.setChecked(True)
check("ayar yazıldı", workspace.autosave_overwrite())
sa.undo_stack.undo()
w._autosave_tick()
check("autosave temizledi", not w._is_dirty(sa))
w.act_autosave.setChecked(False)
check("ayar kapandı", not workspace.autosave_overwrite())

# --- farklı kaydet
w.switch_session(1); app.processEvents()
newp = os.path.join(tmp, "b_yeni.pdf")
import PySide6.QtWidgets as W
W.QFileDialog.getSaveFileName = staticmethod(lambda *a_, **k: (newp, ""))
w.save_pdf_as()
check("yol değişti", sb.path == newp and sb.title == "b_yeni.pdf" and os.path.exists(newp))

# --- tümünü kaydet
w._mark_dirty(sa); w._mark_dirty(sb)
w.ask_save_all = lambda dirty: ("copy", dirty, "")
check("kopya modu", w.save_all() and os.path.exists(os.path.join(tmp, "a_isaretli.pdf"))
      and os.path.exists(os.path.join(tmp, "b_yeni_isaretli.pdf")))
w._mark_dirty(sa)
w.ask_save_all = lambda dirty: ("dir", dirty, tmp)
w.save_all()
check("ikinci kopya ayrı ad", os.path.exists(os.path.join(tmp, "a_isaretli2.pdf")))
w._mark_dirty(sa); w._mark_dirty(sb)
w.ask_save_all = lambda dirty: ("over", dirty, "")
check("üzerine yaz modu", w.save_all() and not w._is_dirty(sa) and not w._is_dirty(sb))

# --- imzalı dosyada autosave atlar
import digisign
pfx = os.path.join(tmp, "t.pfx"); digisign.create_self_signed(pfx, "T", "1")
signed = os.path.join(tmp, "s.pdf"); digisign.sign_pdf(a, signed, pfx, "1")
w.open_paths([signed]); app.processEvents()
ss = w.sessions[-1]; w._mark_dirty(ss)
check("imzalıda autosave atlar", w.save_in_place(ss, auto=True) is False and w._is_dirty(ss))
for s in w.sessions:
    s.dirty = False; s.undo_stack.setClean()

# --- Metin Seç: gerçek metin
t1 = make("t1.pdf", 2)
w.open_paths([t1]); app.processEvents()
st = w.sessions[-1]
w.switch_session(len(w.sessions) - 1); app.processEvents()
got = {}
w.ensure_words(st, 0, then=lambda e: got.setdefault("e", e), user=True)
check("native kelimeler", pump(lambda: "e" in got) and got["e"]["source"] == "native")
txt = words_to_text(got["e"]["words"], QRectF(90, 100, 400, 30))
check("alan metni", "1234567890" in txt and "sayfa 1" in txt, txt)
w.on_text_rect_requested(QRectF(90, 100, 400, 30)); app.processEvents()
check("panoya kopyalandı", "sayfa 1" in QApplication.clipboard().text())

# --- taranmış (yalnızca resim) sayfa: otomatik OCR
if ocr.find_tessdata():
    src = fitz.open()
    pg = src.new_page(width=400, height=200)
    pg.insert_text((30, 100), "Merhaba Dunya 2026", fontsize=28)
    pix = pg.get_pixmap(dpi=200)
    img_pdf = os.path.join(tmp, "taranmis.pdf")
    d2 = fitz.open(); p2 = d2.new_page(width=400, height=200)
    p2.insert_image(p2.rect, pixmap=pix); d2.save(img_pdf); d2.close(); src.close()
    w.open_paths([img_pdf]); app.processEvents()
    sc = w.sessions[-1]
    w.switch_session(len(w.sessions) - 1)           # auto_ocr_kick arka planda başlatır
    check("otomatik OCR önbelleğe yazdı", pump(lambda: 0 in w._words_cache(sc), 90))
    ent = w._words_cache(sc).get(0)
    check("OCR kaynağı", ent is not None and ent["source"] == "ocr")
    check("OCR metni", ent is not None and "Merhaba" in words_to_text(ent["words"]),
          words_to_text(ent["words"]) if ent else "")
    w.on_text_rect_requested(QRectF(0, 0, 400, 200)); app.processEvents()
    check("OCR metni panoda", "Merhaba" in QApplication.clipboard().text())
    workspace.set_auto_ocr_enabled(False)
    img2 = os.path.join(tmp, "t2.pdf"); d3 = fitz.open(); p3 = d3.new_page(width=400, height=200)
    p3.insert_image(p3.rect, pixmap=pix); d3.save(img2); d3.close()
    w.open_paths([img2]); app.processEvents(); s3 = w.sessions[-1]
    w.switch_session(len(w.sessions) - 1)
    pump(lambda: False, 1.0)
    check("otomatik OCR kapalıyken çalışmaz", 0 not in w._words_cache(s3))
else:
    print("ATLA  OCR dil verisi yok")

for s in w.sessions:
    s.dirty = False; s.undo_stack.setClean()
print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
os._exit(0)
