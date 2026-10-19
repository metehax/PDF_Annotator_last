"""L1: Ayarlar kategorileri/arama, palet son kullanılanlar, son açılan × gizleme, e-posta izi yok, boşta bildirimi tek kez."""
import os, re, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
tmp = tempfile.mkdtemp(prefix="l1_")
os.environ["PDF_ANNOTATOR_WORKSPACE"] = os.path.join(tmp, "calisma")
import pymupdf as fitz
from PySide6.QtCore import QSettings, QRectF
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QApplication, QWidgetAction, QMenu, QPushButton, QToolButton

ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


app = QApplication.instance() or QApplication(sys.argv)
import workspace as ws
import main_window as mw
import sharing
from ui import preferences as prefs
from ui.share import ShareDialog
from mw_common import short_tab_name

INI = os.path.join(tmp, "ayar.ini")


def new_settings():
    return QSettings(INI, QSettings.Format.IniFormat)


def pump(ms=150, until=None, limit=8000):
    t0 = time.time()
    while (time.time() - t0) * 1000 < (limit if until else ms):
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.01)
    return False


def setup_window():
    w = mw.MainWindow()
    w.settings = new_settings()
    w.stamp_lib.settings = w.settings
    w.sig_lib.settings = w.settings
    ws.configure(w.settings)
    w.resize(1300, 850)
    w.show()
    pump(200)
    return w


def mkpdf(name, text="x"):
    p = os.path.join(tmp, name)
    d = fitz.open()
    d.new_page().insert_text((72, 100), text, fontsize=14)
    d.save(p)
    d.close()
    return p


w = setup_window()

# ---------------- Ayarlar düğmesi + kategoriler ----------------
check("üst çubukta Ayarlar düğmesi", w.btn_settings.text() == "Ayarlar" and w.btn_settings.isVisible())
dlg = w.open_preferences()
pump(100)
check("kategoriler: 7 sayfa soldaki listede", [dlg.nav.item(i).text() for i in range(dlg.nav.count())] == list(prefs.CATEGORIES) == [
    "Genel", "Görünüm", "Çalışma klasörü", "Tarama", "Telefon aktarımı", "Güncelleme", "Kısayollar"])
check("her kategori bir sayfa", dlg.stack.count() == 7)
dlg.show_category("Görünüm")
check("show_category sayfayı değiştirir", dlg.stack.currentIndex() == 1 and dlg.current_category() == "Görünüm")
check("mevcut denetimler yerinde (tema, çalışma klasörü, güncelleme)", all(hasattr(dlg, a) for a in ("cb_theme", "root_edit", "chk_upd", "chk_rec", "chk_last", "keys")))
check("Kısayollar sayfası dolu", dlg.keys.topLevelItemCount() > 10)
dlg.chk_labels.setChecked(True)
check("Düğmelerde yazı: undo/redo yazı alır", w.btn_undo.text() == "Geri al" and w.btn_redo.text() == "Yinele")
dlg.chk_labels.setChecked(False)
check("Düğmelerde yazı kapanınca kalkar", w.btn_undo.text() == "")
dlg.cb_tabw.setCurrentIndex(dlg.cb_tabw.findData("compact"))
check("sekme genişliği ayarı kalıcı", str(w.settings.value("ui/tab_width")) == "compact")
dlg.cb_tabw.setCurrentIndex(dlg.cb_tabw.findData("normal"))
dlg.accept()

# ---------------- Paylaş menüsü ----------------
check("Paylaş düğmesi: Telefona gönder · Bulut · Konum", [a.text() for a in w.btn_share.menu().actions()] == [
    "Telefona gönder…", "Bulut klasörüne kaydet…", "Dosya konumunu aç"])
check("Paylaş: belge yokken bulut/konum pasif", not any(a.isEnabled() for a in w.btn_share.menu().actions()[1:]))

# ---------------- e-posta izi yok ----------------
hits = []
for base in ("src", "tests", "README.md", "CLAUDE.md"):
    path = os.path.join(ROOT, base)
    files = [path] if os.path.isfile(path) else [os.path.join(d, f) for d, _, fs in os.walk(path) for f in fs if f.endswith((".py", ".md"))]
    for f in files:
        if f.endswith(("check_ui_l1.py", "check_qrshare_share.py")) or "__pycache__" in f:
            continue
        txt = open(f, encoding="utf-8", errors="ignore").read()
        if re.search(r"share_email|compose_email|find_outlook|mailto_url|E-postayla gönder", txt):
            hits.append(f)
check("e-posta izi yok (kod, test, belge)", not hits, str(hits))
check("sharing/MainWindow'da e-posta yöntemi yok", not hasattr(sharing, "compose_email") and not hasattr(w, "share_email"))

# ---------------- komut paleti ----------------
cmds = w._palette_commands("tema")
check("palet: 'tema' ayarı bulur ve kategoriyi açar", any(c.title.startswith("Ayar: Tema") for c in cmds))
c = next(c for c in cmds if c.title.startswith("Ayar: Çalışma klasörü") ) if any(c.title.startswith("Ayar: Çalışma klasörü") for c in cmds) else None
w.palette.open()
w.palette.edit.setText("çalışma klasörü")
pump(100)
check("palet: arama ayar satırı gösterir", any(cm.title.startswith("Ayar: Çalışma klasörü") for cm in w.palette._commands))
idx = next(i for i, cm in enumerate(w.palette._commands) if cm.title.startswith("Ayar: Çalışma klasörü"))
w.palette._run_item(w.palette.list.item(idx))
pump(100)
check("palet: ayar seçilince Ayarlar ilgili kategoriyle açılır", w._prefs_dialog.isVisible() and w._prefs_dialog.current_category() == "Çalışma klasörü")
w._prefs_dialog.accept()

check("palet: menü yolu alt menüyü içerir", any(cm.category == "Dosya › Tara ve içe aktar" for cm in w._palette_commands("")))
check("palet: komutlarda kısayol gri yazı alanı", any(cm.shortcut for cm in w._palette_commands("")))
# son kullanılanlar
for title in ("Ayarlar", "A", "B", "C", "D", "E", "F"):
    w._palette_ran(title)
rec = w._palette_recent()
check("palet: son kullanılan en çok 5, en yeni önce", rec == ["F", "E", "D", "C", "B"], str(rec))
w.settings.setValue("palette/recent", [])
w.palette.open()
w.palette.edit.setText("")
pump(50)
w.palette.edit.setText("ayar: tema")
pump(50)
target = next(i for i, cm in enumerate(w.palette._commands) if cm.title.startswith("Ayar: Tema"))
w.palette._run_item(w.palette.list.item(target))
pump(100)
w._prefs_dialog.accept()
saved_title = w._palette_recent()[0] if w._palette_recent() else ""
check("palet: çalıştırılan komut ayara yazılır", saved_title.startswith("Ayar: Tema"), saved_title)
w.palette.open()
w.palette.edit.setText("")
pump(50)
check("palet: boş aramada son kullanılan en üstte", w.palette._commands and w.palette._commands[0].title == saved_title)
w.palette.close_palette()

# ---------------- son açılanlar ×  ----------------
A1, A2, A3 = mkpdf("a1.pdf"), mkpdf("a2.pdf"), mkpdf("a3.pdf")
for p in (A1, A2, A3):
    w._add_recent(p)
vis = w._recent_paths(visible=True)
check("son açılanlar: 3 görünür", [os.path.basename(p) for p in vis[:3]] == ["a3.pdf", "a2.pdf", "a1.pdf"])
rows = w.welcome.recent_box.count()
check("karşılama: her girdide × düğmesi", rows >= 3 and all(w.welcome.recent_box.itemAt(i).widget().hide_btn.text() == "×" for i in range(rows)))
w.welcome.recent_box.itemAt(0).widget().hide_btn.click()
pump(100)
check("× girdiyi görünümden gizler", os.path.normcase(os.path.abspath(A3)) not in [os.path.normcase(p) for p in w._recent_paths(visible=True)]
      and w.welcome.recent_box.count() == rows - 1)
check("gizlenen dosya 'recent' listesinde kalır, dosya silinmedi", any(os.path.basename(p) == "a3.pdf" for p in w._recent_paths()) and os.path.exists(A3))
menu_rows = [a for a in w.recent_menu.actions() if isinstance(a, QWidgetAction)]
check("Son açılanlar menüsünde gizlenen yok, kalanlar × ile", len(menu_rows) == rows - 1 and all(m.defaultWidget().hide_btn.text() == "×" for m in menu_rows))
check("palette 'Aç:' girdisi gizleneni göstermez", not any(c.title == "Aç: a3.pdf" for c in w._palette_commands("")))
check("Listeyi temizle menüde duruyor", any(a.text() == "Listeyi temizle" for a in w.recent_menu.actions()))
menu_rows[0].defaultWidget().hide_btn.click()
pump(50)
check("menüdeki × da gizler", len(w._recent_paths(visible=True)) == len(menu_rows) - 1)
check("recent_hidden ayarda tutulur", len(w._hidden_recent()) >= 2)
# açılışta gizlenenler yeniden görünür: kurucu recent_hidden'ı sıfırlar
src = open(os.path.join(ROOT, "src", "main_window.py"), encoding="utf-8").read()
init = src[src.index("def __init__"):src.index("def _build_ui") if "def _build_ui" in src else None]
check("açılışta recent_hidden temizlenir (MainWindow.__init__)", 'setValue("recent_hidden", [])' in init)
w.close()
pump(100)
w = setup_window()
for p in (A1, A2, A3):
    w._add_recent(p)
w.hide_recent(A1)
check("hide_recent: yeniden _add_recent görünür yapar", os.path.normcase(os.path.abspath(A1)) not in [os.path.normcase(p) for p in w._recent_paths(visible=True)])
w._add_recent(A1)
check("dosya yeniden açılınca görünür olur", os.path.normcase(os.path.abspath(A1)) in [os.path.normcase(p) for p in w._recent_paths(visible=True)])
w.clear_recent()
check("Listeyi temizle: liste boşalır", w._recent_paths() == [])

# ---------------- karşılama kartları ----------------
check("karşılama: Aç · Tara · Telefondan al · Birleştir · Böl", [w.welcome.cards[k].text() for k in ("open", "scan", "phone", "merge", "split")] == [
    "Aç", "Tara", "Telefondan al", "Birleştir", "Böl"])
calls = []
w.open_pdf = lambda: calls.append("open")
w.scan_images = lambda *a, **k: calls.append("scan")
w.open_share = lambda: calls.append("phone")
w.merge_pdfs = lambda: calls.append("merge")
for k in ("open", "scan", "phone", "merge"):
    w.welcome.cards[k].click()
check("kartlar ilgili eylemi çağırır", calls == ["open", "scan", "phone", "merge"], str(calls))

# ---------------- sekme başlığı ----------------
long_name = "Cok_uzun_bir_sozlesme_taslagi_son_surum_final_v7.pdf"
sh = short_tab_name(long_name, 30)
check("sekme adı: başı + sonu + uzantı görünür", sh.endswith("v7.pdf") and sh.startswith("Cok_uzun") and "…" in sh and len(sh) <= 31, sh)
check("kısa ad olduğu gibi", short_tab_name("a.pdf") == "a.pdf")
LP = mkpdf(long_name)
w.open_paths([LP])
pump(500, until=lambda: bool(w.sessions))
check("sekme: tam ad ipucunda, görünen ad kısaltılmış", w.sessions and long_name in w.doc_tabbar.tabToolTip(0) and w.doc_tabbar.tabText(0) != long_name)
w.add_annotation(__import__("models").TextAnnotation(QRectF(72, 200, 100, 30), "DEGISTI", QColor("#c0392b"), 14))
w._mark_dirty()
check("değişmiş belge: ● işareti", w.doc_tabbar.tabText(0).startswith("● "))

# ---------------- şekil çizimi ----------------
from models import ShapeAnnotation
from PySide6.QtCore import Qt
sa = ShapeAnnotation(QRectF(100, 300, 120, 80), "rect", None, QColor("#1d3557"), 2.0, 1.0)
it = sa.create_item()
check("şekil kalemi: yuvarlak köşe/uç", it.pen().joinStyle() == Qt.PenJoinStyle.RoundJoin and it.pen().capStyle() == Qt.PenCapStyle.RoundCap)
check("şekil: görünüm anti-aliasing açık", bool(w.view.renderHints() & __import__("PySide6.QtGui", fromlist=["QPainter"]).QPainter.RenderHint.Antialiasing))
d = fitz.open()
pg = d.new_page()
sa.apply_to_page(pg, w.font_ctx)
cont = pg.read_contents().decode("latin1")
check("PDF çıktısı: lineCap/lineJoin yuvarlak (1 J / 1 j)", re.search(r"\b1 J\b", cont) and re.search(r"\b1 j\b", cont), cont[:200])
d.close()

# ---------------- boşta bildirimi tek kez ----------------
RD = os.path.join(tmp, "alinan")
os.makedirs(RD, exist_ok=True)
shown = []
w.toasts.show = lambda *a, **k: shown.append(a[0])
dlg = ShareDialog(w, host="127.0.0.1", receive_dir=RD)
dlg.show()
pump(150)
dlg._server._last = time.monotonic() - 10_000          # boşta sayacı eşiği aştı
dlg._check_idle()
dlg._check_idle()
pump(100)
idle_msgs = [m for m in shown if "boşta" in m]
check("boşta: sunucu durunca bildirim bir kez", len(idle_msgs) == 1 and dlg._server is None and not dlg._idle.isActive(), str(shown))
dlg2 = ShareDialog(w, host="127.0.0.1", receive_dir=RD)
dlg2.show()
pump(150)
srv = dlg2._server
dlg2.reject()                                           # Esc/× ile kapanış: zamanlayıcı ve sunucu durur
pump(100)
shown.clear()
srv._last = time.monotonic() - 10_000
dlg2._check_idle()
dlg2._check_idle()
check("kapatılan pencerede bildirim hiç çıkmaz, zamanlayıcı durur", shown == [] and not dlg2._idle.isActive() and dlg2._server is None, str(shown))
dlg3 = ShareDialog(w, host="127.0.0.1", receive_dir=RD)
dlg3.show()
pump(150)
dlg3.close()
pump(100)
check("close(): zamanlayıcı ve sunucu durmuş", not dlg3._idle.isActive() and dlg3._server is None)

for s in w.sessions:
    s.dirty = False
    s.undo_stack.setClean()
w.close()
pump(200)
print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
from PySide6.QtCore import QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
os._exit(0 if all(ok) else 1)
