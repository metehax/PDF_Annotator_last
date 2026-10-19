import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.pop("PDF_ANNOTATOR_WORKSPACE", None)          # ayar tabanlı davranışı sınarız; env'i aşağıda ayrıca deneriz
import pymupdf as fitz
from PySide6.QtCore import QSettings, QRectF
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

tmp = tempfile.mkdtemp(prefix="i1_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


import workspace as ws

INI = os.path.join(tmp, "ayar.ini")


def new_settings():
    return QSettings(INI, QSettings.Format.IniFormat)


app = QApplication.instance() or QApplication(sys.argv)
st = new_settings()
ws.configure(st)
WS = os.path.join(tmp, "calisma")

# ---------------- kök / alt klasörler ----------------
check("varsayılan kök: Belgeler\\PDF Annotator (oluşturulmaz)", ws.root() == ws.default_root() and os.path.basename(ws.root()) == "PDF Annotator"
      and not ws.is_custom_root())
check("set_root: oluşturur ve yazar", ws.set_root(WS) == os.path.abspath(WS) and os.path.isdir(WS) and ws.root() == os.path.abspath(WS)
      and ws.is_custom_root())
st.sync()
ws.configure(new_settings())
check("kök ayarı yeni QSettings'te kalıcı", ws.root() == os.path.abspath(WS))
made = ws.ensure_all()
check("6 alt klasör oluştu", sorted(os.path.basename(p) for p in made) == sorted(ws.SUBS) and all(os.path.isdir(p) for p in made))
check("sub(): yol kök altında", ws.sub("Taramalar") == os.path.join(os.path.abspath(WS), "Taramalar"))
try:
    ws.sub("../disari")
    bad = False
except ValueError:
    bad = True
check("sub(): bilinmeyen ad reddedilir", bad)
ws.reset_root()
check("reset_root: varsayılana döner", ws.root() == ws.default_root() and not ws.is_custom_root())
ws.set_root(WS)
os.environ[ws.ENV_ROOT] = os.path.join(tmp, "envroot")
check("ortam değişkeni ayarı geçersiz kılar", ws.root() == os.path.abspath(os.path.join(tmp, "envroot")) and ws.is_custom_root())
os.environ.pop(ws.ENV_ROOT)
check("env kalkınca ayar geri gelir", ws.root() == os.path.abspath(WS))

# ---------------- çıktı tercihleri ----------------
check("her tür varsayılan açık", all(ws.use(k) for k in ws.KINDS))
check("out_dir: açıkken alt klasör", ws.out_dir("scans") == ws.sub("Taramalar") and ws.out_dir("inbox") == ws.sub("Gelen"))
ws.set_use("scans", False)
check("out_dir: kapalıyken None", ws.out_dir("scans") is None and ws.use("inbox"))
check("join_out: kapalıyken yedek klasör / yalnız ad", ws.join_out("scans", "a.pdf", tmp) == os.path.join(tmp, "a.pdf")
      and ws.join_out("scans", "a.pdf") == "a.pdf")
check("join_out: açıkken çalışma klasörü", ws.join_out("converted", "a.docx", tmp) == os.path.join(ws.sub("Donusturulenler"), "a.docx"))
st.setValue("workspace/use_projects", "false")
check("bool ayar metin 'false' olarak da okunur", ws.use("projects") is False)
ws.set_use("projects", True)
ws.configure(new_settings())
check("tercih kalıcı", ws.use("scans") is False and ws.use("projects") is True)
ws.set_use("scans", True)
try:
    ws.use("yok")
    bad = False
except ValueError:
    bad = True
check("bilinmeyen tür reddedilir", bad)

# ---------------- son klasör ----------------
d1 = os.path.join(tmp, "son")
os.makedirs(d1)
f1 = os.path.join(d1, "x.pdf")
open(f1, "w").write("x")
check("son klasör başta boş", ws.last_dir() == "")
ws.remember(f1)
check("remember(dosya): klasörü saklar", ws.last_dir() == d1)
ws.remember(tmp)
check("remember(klasör)", ws.last_dir() == tmp)
ws.set_remember_last(False)
check("kapatınca unutulur ve yazılmaz", ws.last_dir() == "" and (ws.remember(d1), ws.last_dir())[1] == "")
ws.set_remember_last(True)
ws.remember(os.path.join(tmp, "yok", "z.pdf"))
check("olmayan klasör saklanmaz", ws.last_dir() == "")

# ---------------- eski gelen klasörü taşıma ----------------
OLD = os.path.join(tmp, "PDF Annotator Gelen")
os.makedirs(OLD)
for nm in ("a.pdf", "b.jpg"):
    open(os.path.join(OLD, nm), "w").write("eski " + nm)
open(os.path.join(ws.sub("Gelen"), "a.pdf"), "w").write("yeni a")
check("taşıma bekliyor (dosya var)", ws.migration_pending(OLD))
mv, errs = ws.migrate_old_inbox(OLD)
gel = sorted(os.listdir(ws.sub("Gelen")))
check("taşındı: aynı ad ezilmez (2)", mv == 2 and errs == [] and gel == ["a (2).pdf", "a.pdf", "b.jpg"], str(gel))
check("mevcut dosya korunur, eskisi içerikle taşındı", open(os.path.join(ws.sub("Gelen"), "a.pdf")).read() == "yeni a"
      and open(os.path.join(ws.sub("Gelen"), "a (2).pdf")).read() == "eski a.pdf")
check("boşalan eski klasör kaldırıldı", not os.path.exists(OLD))
check("klasör yoksa bekleyen yok", not ws.migration_pending(OLD))
os.makedirs(os.path.join(OLD, "alt"))
open(os.path.join(OLD, "c.pdf"), "w").write("c")
ws.migrate_old_inbox(OLD)
check("içinde alt klasör varsa eski klasör silinmez", os.path.isdir(os.path.join(OLD, "alt")) and os.path.exists(os.path.join(ws.sub("Gelen"), "c.pdf")))
os.makedirs(OLD, exist_ok=True)
open(os.path.join(OLD, "d.pdf"), "w").write("d")
ws.decline_migration()
check("'bir daha sorma' sonrası öneri yok", not ws.migration_pending(OLD))
st.setValue("workspace/migration_declined", False)
check("eski klasör = yeni Gelen ise öneri yok", not ws.migration_pending(ws.sub("Gelen")))

# ---------------- kurtarma taslakları ----------------
check("kurtarma: varsayılan açık, 3 dk", ws.recovery_enabled() and ws.recovery_minutes() == 3)
check("süre 1–10'a kırpılır", ws.set_recovery_minutes(99) == 10 and ws.set_recovery_minutes(0) == 1 and ws.recovery_minutes() == 1)
ws.set_recovery_minutes(5)
ws.set_recovery_enabled(False)
ws.configure(new_settings())
check("kurtarma ayarı kalıcı", ws.recovery_enabled() is False and ws.recovery_minutes() == 5)
ws.set_recovery_enabled(True)
check("kurtarma klasörü Yedekler\\kurtarma", ws.recovery_dir() == os.path.join(ws.sub("Yedekler"), "kurtarma"))
d = fitz.open()
d.new_page().insert_text((72, 100), "taslak metni")
pdfb = d.write()
d.close()
proj = {"version": 1, "source_pdf": os.path.join(tmp, "orijinal.pdf"), "title": "orijinal.pdf", "rotations": {}, "annotations": {"0": []}}
dr = ws.write_draft("abc123", pdfb, proj, "orijinal.pdf", 1)
check("taslak yazıldı (pdf + json), yarım dosya yok", os.path.exists(dr.pdf_path) and os.path.exists(dr.json_path)
      and not [f for f in os.listdir(ws.recovery_dir()) if f.endswith(".part")])
lst = ws.list_drafts()
check("taslak listelenir", [x.id for x in lst] == ["abc123"] and lst[0].title == "orijinal.pdf" and lst[0].source == proj["source_pdf"]
      and lst[0].pages == 1 and lst[0].when())
data, p2 = ws.read_draft("abc123")
check("okuma: baytlar ve proje aynı", data == pdfb and p2 == proj)
time.sleep(0.02)
ws.write_draft("zzz999", pdfb, dict(proj, title="ikinci.pdf"), "ikinci.pdf", 1)
check("en yeni üstte", [x.id for x in ws.list_drafts()] == ["zzz999", "abc123"])
ws.write_draft("abc123", pdfb + b"\n", proj, "orijinal.pdf", 1)
check("aynı kimlik üzerine yazılır (tek taslak)", len(ws.list_drafts()) == 2 and ws.read_draft("abc123")[0] == pdfb + b"\n")
os.remove(os.path.join(ws.recovery_dir(), "zzz999.pdf"))
check("pdf'i eksik taslak atlanır", [x.id for x in ws.list_drafts()] == ["abc123"])
open(os.path.join(ws.recovery_dir(), "bozuk.json"), "w").write("{yok")
open(os.path.join(ws.recovery_dir(), "bozuk.pdf"), "wb").write(b"x")
check("bozuk json atlanır", [x.id for x in ws.list_drafts()] == ["abc123"])
for bad_id in ("", "../x", "a/b", ".gizli", "a:b"):
    try:
        ws.write_draft(bad_id, pdfb, proj)
        bad = False
    except ValueError:
        bad = True
    check(f"güvensiz kimlik reddedilir: {bad_id!r}", bad)
check("silme: var olan True, tekrar False, geçersiz False", ws.delete_draft("abc123") is True and ws.delete_draft("abc123") is False
      and ws.delete_draft("../x") is False)
check("silince liste boş", ws.list_drafts() == [])
ws.write_draft("t1", pdfb, proj)
ws.write_draft("t2", pdfb, proj)
check("clear_drafts", ws.clear_drafts() == 2 and ws.list_drafts() == [])
for f in ("bozuk.json", "bozuk.pdf"):
    os.remove(os.path.join(ws.recovery_dir(), f))

# ====================== pencere ======================
import main_window as mw
from models import TextAnnotation
from ui.share import ShareDialog
from ui.convert import ConvertDialog
from ui.scanner import ScanDialog
from PySide6.QtGui import QAction

w = mw.MainWindow()
w.settings = new_settings()
w.stamp_lib.settings = w.settings
w.sig_lib.settings = w.settings
ws.configure(w.settings)
w.resize(1300, 850)
w.show()


def pump(ms=150, until=None, limit=8000):
    t0 = time.time()
    while (time.time() - t0) * 1000 < (limit if until else ms):
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.01)
    return False


acts = {a.text(): a for a in w.findChildren(QAction)}
check("menü: Tercihler… (Ctrl+,)", "Tercihler…" in acts and acts["Tercihler…"].shortcut() == QKeySequence("Ctrl+,"),
      str(acts.get("Tercihler…") and acts["Tercihler…"].shortcut().toString()))

# --- tercihler penceresi
WS2 = os.path.join(tmp, "calisma2")
dlg = w.open_preferences()
pump(200)
check("tercihler açıldı, kök gösteriliyor", dlg.isVisible() and dlg.root_edit.text() == ws.root())
check("tek örnek", w.open_preferences() is dlg)
dlg.set_root(WS2)
check("kök değişti: ayara yazıldı + alt klasörler oluştu", ws.root() == os.path.abspath(WS2) and os.path.isdir(os.path.join(WS2, "IsAkisi"))
      and dlg.root_edit.text() == os.path.abspath(WS2) and dlg.btn_reset.isEnabled())
w.settings.sync()
check("kök ayarı QSettings dosyasında", new_settings().value("workspace/root") == os.path.abspath(WS2))
dlg._reset_root()
check("sıfırla", ws.root() == ws.default_root() and dlg.root_edit.text() == ws.default_root() and not dlg.btn_reset.isEnabled())
dlg.set_root(WS2)
check("5 çıktı kutusu, hepsi işaretli", len(dlg.chk_kind) == 5 and all(c.isChecked() for c in dlg.chk_kind.values()))
dlg.chk_kind["scans"].setChecked(False)
check("kutu -> use ayarı", ws.use("scans") is False and ws.use("inbox") is True)
w.settings.setValue("qrReceiveDir", "C:/eski/yol")
dlg.chk_kind["inbox"].setChecked(False)
dlg.chk_kind["inbox"].setChecked(True)
check("QR kutusu açılınca elle seçilmiş klasör sıfırlanır", not str(w.settings.value("qrReceiveDir", "") or ""))
dlg.chk_kind["scans"].setChecked(True)
# kurtarma
dlg.chk_rec.setChecked(False)
check("kurtarma kapatıldı: ayar + zamanlayıcı durdu", ws.recovery_enabled() is False and not w._recovery_timer.isActive() and not dlg.sp_min.isEnabled())
dlg.chk_rec.setChecked(True)
dlg.sp_min.setValue(7)
check("kurtarma açıldı, 7 dk: zamanlayıcı aralığı", ws.recovery_enabled() and ws.recovery_minutes() == 7
      and w._recovery_timer.isActive() and w._recovery_timer.interval() == 7 * 60 * 1000, str(w._recovery_timer.interval()))
check("süre 1–10 aralığı", (dlg.sp_min.minimum(), dlg.sp_min.maximum()) == (1, 10))
# tema
dlg.cb_theme.setCurrentIndex(dlg.cb_theme.findData("dark"))
check("tema koyu: ayar + pencere", w.settings.value("theme") == "dark" and w.dark_mode is True)
dlg.cb_theme.setCurrentIndex(dlg.cb_theme.findData("light"))
check("tema açık", w.settings.value("theme") == "light" and w.dark_mode is False)
dlg.cb_theme.setCurrentIndex(dlg.cb_theme.findData(""))
check("tema sistem: ayar boş", str(w.settings.value("theme", "") or "") == "")
# son klasör
dlg.chk_last.setChecked(False)
check("son klasör kutusu -> ayar", ws.remember_last() is False)
dlg.chk_last.setChecked(True)
dlg.reload()
check("yeniden yükleme ayarları yansıtır", dlg.sp_min.value() == 7 and dlg.chk_rec.isChecked() and dlg.chk_last.isChecked())
os.environ[ws.ENV_ROOT] = os.path.join(tmp, "envkok")
dlg.reload()
check("env ile belirlenen kök: seç/sıfırla pasif", not dlg.btn_choose.isEnabled() and not dlg.btn_reset.isEnabled() and "ortam" in dlg.root_hint.text())
os.environ.pop(ws.ENV_ROOT)
dlg.reload()
dlg.close()

# --- diyalog varsayılanları çalışma klasörüne bağlı
SRC = os.path.join(tmp, "belge.pdf")
dd = fitz.open()
for i in range(2):
    dd.new_page().insert_text((72, 100), f"Sayfa {i + 1}")
dd.save(SRC)
dd.close()
w.open_paths([SRC])
pump(300)
s = w.sessions[0]
sh = ShareDialog(w, host="127.0.0.1")
check("QR gelenleri: çalışma klasörü\\Gelen", sh._receive_dir == ws.sub("Gelen"), sh._receive_dir)
sh.close()
w.settings.setValue("qrReceiveDir", os.path.join(tmp, "elle"))
sh = ShareDialog(w, host="127.0.0.1")
check("QR: elle seçilen klasör önceliklidir", sh._receive_dir == os.path.join(tmp, "elle"))
sh.close()
w.settings.setValue("qrReceiveDir", "")
ws.set_use("inbox", False)
sh = ShareDialog(w, host="127.0.0.1")
check("QR: tercih kapalıyken eski varsayılan", sh._receive_dir.endswith("PDF Annotator Gelen"), sh._receive_dir)
sh.close()
ws.set_use("inbox", True)
cd = ConvertDialog(w, s, "docx")
check("dönüştürme: Donusturulenler\\belge.docx", cd.path.text() == os.path.join(ws.sub("Donusturulenler"), "belge.docx"), cd.path.text())
cd.close()
ws.set_use("converted", False)
cd = ConvertDialog(w, s, "xlsx")
check("dönüştürme: tercih kapalıyken belgenin yanı", cd.path.text() == os.path.join(tmp, "belge.xlsx"), cd.path.text())
cd.close()
ws.set_use("converted", True)
seen = {}
orig_save, orig_open, orig_opens = QFileDialog.getSaveFileName, QFileDialog.getOpenFileName, QFileDialog.getOpenFileNames


def fake_save(parent, title, directory="", *a, **k):
    seen["save"] = directory
    return ("", "")


QFileDialog.getSaveFileName = staticmethod(fake_save)
from PIL import Image
IMG = os.path.join(tmp, "foto.png")
Image.new("RGB", (300, 400), (240, 240, 240)).save(IMG)


def scan_default(src):
    d = ScanDialog(w, [src])
    d.show()
    pump(300)
    d.generate()
    d.close()
    return seen["save"]


check("tarama PDF: görsel -> Taramalar/foto_tarama.pdf", scan_default(IMG) == os.path.join(ws.sub("Taramalar"), "foto_tarama.pdf"), seen.get("save"))
check("tarama (PDF sayfaları): Taramalar/tarama.pdf", scan_default(SRC) == os.path.join(ws.sub("Taramalar"), "tarama.pdf"), seen.get("save"))
ws.set_use("scans", False)
check("tarama PDF: tercih kapalıyken kaynağın yanı", scan_default(IMG) == os.path.join(tmp, "foto_tarama.pdf"), seen.get("save"))
ws.set_use("scans", True)
w.save_project()
check("proje kaydet: Projeler\\belge.pdfproj.json", seen["save"] == os.path.join(ws.sub("Projeler"), "belge.pdfproj.json"), seen.get("save"))
ws.set_use("projects", False)
w.save_project()
check("proje: tercih kapalıyken belgenin yanı", seen["save"] == os.path.join(tmp, "belge.pdfproj.json"), seen.get("save"))
ws.set_use("projects", True)
QFileDialog.getSaveFileName = orig_save


def fake_open(parent, title, directory="", *a, **k):
    seen["open"] = directory
    return ("", "")


QFileDialog.getOpenFileName = staticmethod(fake_open)
w.open_project()
check("proje aç: Projeler klasöründen başlar", seen["open"] == ws.sub("Projeler"), seen.get("open"))
QFileDialog.getOpenFileName = orig_open


def fake_opens(parent, title, directory="", *a, **k):
    seen["opens"] = directory
    return ([SRC], "")


QFileDialog.getOpenFileNames = staticmethod(fake_opens)
w.open_pdf()
pump(300)
check("Aç: ilk seferde son klasör yok / sonra hatırlanır", ws.last_dir() == tmp, ws.last_dir())
w.open_pdf()
pump(300)
check("Aç: son klasörden başlar", seen["opens"] == tmp, seen.get("opens"))
QFileDialog.getOpenFileNames = orig_opens
while len(w.sessions) > 1:
    w.close_session(len(w.sessions) - 1, confirm=False)
s = w.sessions[0]

# --- otomatik kurtarma (pencere)
ws.clear_drafts()
w.add_annotation(TextAnnotation(QRectF(60, 60, 220, 40), "Kurtarma denemesi", QColor("#c0392b"), 16))
w._mark_dirty()
check("dirty oturum", w._is_dirty(s) and len(s.annotations[0]) == 1)
check("taslak yazıldı (1)", w._autosave_drafts() == 1 and len(ws.list_drafts()) == 1 and ws.list_drafts()[0].id == s.draft_id)
check("değişmeyince yeniden yazılmaz", w._autosave_drafts() == 0)
w.add_annotation(TextAnnotation(QRectF(60, 120, 220, 40), "ikinci", QColor("#000000"), 14))
check("yeni değişiklik -> yeniden yazılır", w._autosave_drafts() == 1 and len(ws.list_drafts()) == 1)
did = s.draft_id
data, proj = ws.read_draft(did)
check("taslak: belge + 2 işaret", len(proj["annotations"]["0"]) == 2 and fitz.open("pdf", data).page_count == 2)
ws.set_recovery_enabled(False)
w.add_annotation(TextAnnotation(QRectF(60, 180, 220, 40), "üçüncü", QColor("#000000"), 14))
check("kurtarma kapalıyken yazılmaz", w._autosave_drafts() == 0)
w.restart_recovery()
check("kapatınca açık oturumun taslağı silindi", ws.list_drafts() == [])
ws.set_recovery_enabled(True)
w._autosave_drafts()
check("yeniden açılınca yazılır", len(ws.list_drafts()) == 1)
w._mark_saved(s)
check("kaydedince taslak silinir", ws.list_drafts() == [])
w._mark_dirty()
sec = s.security
s.security = object()
check("parolalı oturum yedeklenmez", w._autosave_drafts() == 0 and ws.list_drafts() == [])
s.security = sec
check("normal oturum yine yedeklenir", w._autosave_drafts() == 1)
did = s.draft_id
data, proj = ws.read_draft(did)
n_ann = len(proj["annotations"]["0"])
w.close_session(0, confirm=False)
check("oturum kapanınca taslak silinir", ws.list_drafts() == [])

# çökme benzetimi: taslak var, oturum yok
ws.write_draft(did, data, proj, "belge.pdf", 2)
check("kapanmayan belge taslağı bulunur", [d.id for d in ws.list_drafts()] == [did])
n0 = len(w.sessions)
check("'şimdilik değil': taslak kalır, oturum açılmaz", w.check_recovery(decide=lambda ds: "keep") == "keep" and len(w.sessions) == n0
      and len(ws.list_drafts()) == 1)
r = w.check_recovery(decide=lambda ds: "restore")
pump(300)
rs = w.sessions[-1] if len(w.sessions) > n0 else None
check("kurtar: yeni sekme açıldı", r == "restore" and rs is not None)
check("kurtarılan: işaretler ve sayfa sayısı aynı", rs is not None and len(rs.annotations[0]) == n_ann and rs.pdf.page_count == 2
      and rs.annotations[0][0].text == "Kurtarma denemesi")
check("kurtarılan: değişmiş sayılır, özgün yol/başlık korunur", rs is not None and w._is_dirty(rs) and os.path.abspath(rs.path) == os.path.abspath(SRC)
      and rs.title == "belge.pdf")
check("kurtarılan oturum aynı taslak kimliğini kullanır", rs.draft_id == did)
check("canlı oturumun taslağı tekrar önerilmez", w.check_recovery(decide=lambda ds: "restore") is None)
w._mark_saved(rs)
check("kurtarılan kaydedilince taslak silinir (dosya kilitli değil)", ws.list_drafts() == [] and not os.path.exists(os.path.join(ws.recovery_dir(), did + ".pdf")))
ws.write_draft("x1", data, proj, "belge.pdf", 2)
check("'sil': taslaklar silinir", w.check_recovery(decide=lambda ds: "delete") == "delete" and ws.list_drafts() == [])
check("taslak yoksa soru yok", w.check_recovery(decide=lambda ds: "restore") is None)
ws.write_draft("bozuk1", b"%PDF-bozuk", proj, "x", 1)
shown = []
orig_crit = QMessageBox.critical
QMessageBox.critical = staticmethod(lambda *a, **k: shown.append(a[2]))
n1 = len(w.sessions)
w.check_recovery(decide=lambda ds: "restore")
QMessageBox.critical = orig_crit
check("bozuk taslak: hata bildirilir, uygulama düşmez", len(shown) == 1 and len(w.sessions) == n1, str(shown))
ws.clear_drafts()

# --- eski gelen klasörü taşıma (pencere)
OLD2 = os.path.join(tmp, "eski_gelen")
os.makedirs(OLD2)
open(os.path.join(OLD2, "tel.pdf"), "w").write("t")
ws.old_inbox = lambda: OLD2
check("migration: 'later' dosyaya dokunmaz", w.check_migration(decide=lambda o, n: "later") == "later" and os.path.exists(os.path.join(OLD2, "tel.pdf")))
check("migration: 'never' tekrar sormaz", w.check_migration(decide=lambda o, n: "never") == "never" and w.check_migration(decide=lambda o, n: "move") is None)
st2 = w.settings
st2.setValue("workspace/migration_declined", False)
asked = []
check("migration: 'move' taşır", w.check_migration(decide=lambda o, n: (asked.append((o, n)), "move")[1]) == "move"
      and asked == [(OLD2, 1)] and os.path.exists(os.path.join(ws.sub("Gelen"), "tel.pdf")) and not os.path.exists(OLD2))
check("migration: öneri kalmadı", w.check_migration(decide=lambda o, n: "move") is None)

# --- başlangıç denetimleri + zamanlayıcı + normal kapanış
w.startup_checks()
check("startup_checks zamanlayıcıyı kurar", w._recovery_timer.isActive() and w._recovery_timer.interval() == ws.recovery_minutes() * 60000)
s = w.sessions[0]
w._mark_dirty(s)
w._autosave_drafts()
check("kapanış öncesi taslak var", len(ws.list_drafts()) >= 1)
for x in w.sessions:
    x.dirty = False
    x.undo_stack.setClean()
w.close()
pump(200)
check("normal kapanış: taslaklar silindi", ws.list_drafts() == [])

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
from PySide6.QtCore import QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
os._exit(0 if all(ok) else 1)
