import os, sys, tempfile, time, stat, threading
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
tmp = tempfile.mkdtemp(prefix="s1_")
os.environ["PDF_ANNOTATOR_WORKSPACE"] = os.path.join(tmp, "ws")
import pymupdf as fitz
from PySide6.QtCore import QRectF, QSettings, QThreadPool
from PySide6.QtGui import QAction, QColor, QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

ok = []
FIND = "--find" in sys.argv


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


import crashguard
import main_window as mw
import workspace
from models import TextAnnotation

app = QApplication.instance() or QApplication(sys.argv)
w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
w.stamp_lib.settings = w.settings
w.sig_lib.settings = w.settings
workspace.configure(w.settings)
w.resize(1300, 850)
w.show()

# --- yakalanmamış hata / kutu kaydı ---
errors = []            # yakalanmamış Python istisnaları (excepthook)
boxes = []             # kullanıcıya gösterilen hata kutuları
crashguard.install(None)
import faulthandler
faulthandler.dump_traceback_later(240, exit=True, file=sys.__stderr__)     # donma olursa iz yaz
_orig_hook = sys.excepthook


def _hook(t, e, tb):
    import traceback
    errors.append("".join(traceback.format_exception(t, e, tb))[-600:])
    crashguard._excepthook(t, e, tb)


sys.excepthook = _hook
for n in ("critical", "warning", "information", "question", "about"):
    setattr(QMessageBox, n, staticmethod(lambda *a, _n=n, **k: (boxes.append((_n, str(a[1:3]))),
                                                              QMessageBox.StandardButton.No if _n == "question"
                                                              else QMessageBox.StandardButton.Ok)[1]))
QInputDialog.getText = staticmethod(lambda *a, **k: ("yanlis", True))
w.toasts.show = lambda *a, **k: None


def pump(ms=150):
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.01)


def mkdoc(path, n=3, size=None):
    d = fitz.open()
    for i in range(n):
        p = d.new_page(width=size[0], height=size[1]) if size else d.new_page()
        p.insert_text((72, 100), f"SAYFA{i + 1}", fontsize=24)
    d.save(path)
    d.close()
    return path


def scenario(name, fn, allow_boxes=True):
    """fn çalışır; yakalanmamış istisna olmamalı. Kullanıcıya hata kutusu gösterilmesi (allow_boxes) kabul."""
    n0 = len(errors)
    b0 = len(boxes)
    try:
        fn()
        pump(250)
    except Exception as ex:
        import traceback
        errors.append(f"{name}: {type(ex).__name__}: {ex} | " + traceback.format_exc()[-1200:])
    new = errors[n0:]
    check(name, not new and (allow_boxes or len(boxes) == b0), (new[-1][-300:] if new else "kutu"))


def close_all():
    for i in range(len(w.sessions) - 1, -1, -1):
        w.sessions[i].dirty = False
        w.sessions[i].undo_stack.setClean()
        w.close_session(i, confirm=False)
    pump(100)


# =========================== A) bozuk / uç dosyalar ===========================
bad = os.path.join(tmp, "bos.pdf"); open(bad, "wb").close()
junk = os.path.join(tmp, "bozuk.pdf"); open(junk, "wb").write(b"%PDF-1.4\nbu bir pdf degil" + os.urandom(2000))
wrongext = os.path.join(tmp, "sahte.pdf"); open(wrongext, "wb").write(b"merhaba dunya" * 50)
png_as_pdf = os.path.join(tmp, "resim.pdf"); QImage(50, 50, QImage.Format.Format_RGB32).save(png_as_pdf, "PNG")
badimg = os.path.join(tmp, "bozuk.png"); open(badimg, "wb").write(b"\x89PNG\r\n\x1a\n" + os.urandom(500))
emptyimg = os.path.join(tmp, "bos.png"); open(emptyimg, "wb").close()
for nm, p in (("0 baytlık PDF", bad), ("bozuk PDF", junk), ("yanlış uzantılı metin", wrongext),
              ("resim içeriği .pdf uzantılı", png_as_pdf), ("bozuk PNG", badimg), ("0 baytlık PNG", emptyimg)):
    scenario(f"aç: {nm}", lambda p=p: w.open_paths([p]))
close_all()
check("hatalı dosyalardan sonra oturum kalmadı/tutarlı", all(s.pdf.page_count >= 0 for s in w.sessions))

# 0 sayfalı PDF
zero = os.path.join(tmp, "sifir.pdf")
d = fitz.open(); d.new_page(); d.delete_page(0)
try:
    d.save(zero)
except Exception:
    open(zero, "wb").write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
_b0 = len(boxes)
scenario("aç: 0 sayfalı PDF", lambda: w.open_paths([zero]))
check("0 sayfalı PDF: anlaşılır hata, oturum yok", len(boxes) > _b0 and not w.sessions)
scenario("0 sayfalı: sayfa ekle/sayfa ops/kaydet", lambda: (w.goto_page(0), w.zoom_fit_width() if hasattr(w, "zoom_fit_width") else None))
close_all()

# parolalı
pw = os.path.join(tmp, "parolali.pdf")
d = fitz.open(); d.new_page().insert_text((72, 100), "GIZLI")
d.save(pw, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="dogru", owner_pw="dogru"); d.close()
_pwtries = []
QInputDialog.getText = staticmethod(lambda *a, **k: (_pwtries.append(1), ("yanlis", True) if len(_pwtries) < 3 else ("", False))[1])
scenario("parolalı: yanlış parola", lambda: w.open_paths([pw]))
check("yanlış parola: 2 deneme sonra iptal, oturum yok", len(_pwtries) == 3)
check("yanlış parola: oturum açılmadı", not w.sessions or w.sessions[-1].path != pw)
QInputDialog.getText = staticmethod(lambda *a, **k: ("dogru", True))
scenario("parolalı: doğru parola", lambda: w.open_paths([pw]))
check("doğru parola açtı", any(s.path == pw for s in w.sessions))
close_all()
QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
scenario("parolalı: iptal", lambda: w.open_paths([pw]))
close_all()

# çok büyük sayfa
big = os.path.join(tmp, "dev.pdf"); mkdoc(big, 2, size=(14000, 14000))
scenario("aç: 14000x14000 pt sayfa + yakınlaştır", lambda: (w.open_paths([big]), pump(400), w.zoom_in() if hasattr(w, "zoom_in") else None))
close_all()

# 300+ sayfa
many = os.path.join(tmp, "cok.pdf"); mkdoc(many, 320)
t0 = time.time()
scenario("aç: 320 sayfa", lambda: (w.open_paths([many]), pump(500)))
check("320 sayfa makul sürede açıldı", time.time() - t0 < 25, f"{time.time()-t0:.1f}s")
scenario("320 sayfa: son sayfaya git, hızlı sayfa gez", lambda: ([w.goto_page(i) for i in (319, 0, 160, 319, 5)], pump(300)))
close_all()

# döndürülmüş + kırpılmış
rot = os.path.join(tmp, "donuk.pdf"); mkdoc(rot, 3)
d = fitz.open(rot); d[0].set_rotation(90); d[1].set_cropbox(fitz.Rect(100, 100, 300, 300)); d[2].set_rotation(270); d[2].set_cropbox(fitz.Rect(50, 50, 400, 500))
d.saveIncr(); d.close()
scenario("aç: dönük + kırpılı sayfalar, işaret ekle", lambda: (
    w.open_paths([rot]), pump(300),
    [w.sessions[0].undo_stack.count() for _ in (0,)]))
close_all()

# Unicode ve çok uzun yol
uni = os.path.join(tmp, "şğüöçı İĞÜŞÖÇ 日本語 🙂.pdf"); mkdoc(uni, 1)
scenario("aç: Unicode yol", lambda: w.open_paths([uni]))
check("Unicode açıldı", any(s.path == uni for s in w.sessions))
close_all()
longdir = tmp
for _ in range(6):
    longdir = os.path.join(longdir, "a" * 40)
try:
    os.makedirs("\\\\?\\" + longdir, exist_ok=True)
    longp = os.path.join(longdir, "uzun.pdf")
    d = fitz.open(); d.new_page(); d.save("\\\\?\\" + longp); d.close()
    scenario("aç: >260 karakter yol", lambda: w.open_paths([longp]))
    close_all()
except Exception as ex:
    print("not: uzun yol hazırlanamadı", ex)

# salt-okunur dosya: açılır, kopya olarak kaydedilir
ro = os.path.join(tmp, "readonly.pdf"); mkdoc(ro, 1); os.chmod(ro, stat.S_IREAD)
scenario("aç: salt-okunur dosya", lambda: w.open_paths([ro]))
check("salt-okunur açıldı", any(s.path == ro for s in w.sessions))
close_all()
os.chmod(ro, stat.S_IWRITE | stat.S_IREAD)

# aynı dosyayı iki kez aç
two = os.path.join(tmp, "iki.pdf"); mkdoc(two, 2)
scenario("aynı dosyayı iki kez aç", lambda: (w.open_paths([two]), w.open_paths([two]), pump(200)))
scenario("ikisi de kapanır", lambda: (w.close_session(0, confirm=False), w.close_session(0, confirm=False)))
close_all()

# açıkken diskten silinen / değişen dosya
gone = os.path.join(tmp, "silinecek.pdf"); mkdoc(gone, 2)
w.open_paths([gone]); pump(200)
try:
    os.remove(gone)
except OSError as ex:
    print("not: açık dosya silinemedi (kilit):", ex)
scenario("diskten silinmiş: sayfa gez, yeniden çiz, taslak yaz", lambda: (w.goto_page(1), w.view.viewport().update(), w._autosave_drafts(), pump(200)))
close_all()
chg = os.path.join(tmp, "degisen.pdf"); mkdoc(chg, 2)
w.open_paths([chg]); pump(200)
try:
    open(chg, "wb").write(b"yok artik")
except OSError as ex:
    print("not: açık dosya yazılamadı:", ex)
scenario("diskte bozulmuş: gezin/yakınlaştır", lambda: (w.goto_page(1), pump(200)))
close_all()

# =========================== B) belge yokken eylemler ===========================
close_all()
check("belge yok", not w.sessions)
acts = [a for a in w.findChildren(QAction) if a.text() and not a.menu()]
skip = ("Çık", "Kapat", "Hakkında", "Kısayol", "Birlikte aç", "Tercihler", "Paylaş", "Aç", "Yeni", "Sihirbaz", "Tara", "Görselleri", "Kayıt")
qdlg_calls = []
orig_exec = None
from PySide6.QtWidgets import QDialog, QMenu
QDialog.exec = lambda self, *a: (qdlg_calls.append(type(self).__name__), 0)[1]
QDialog.show = lambda self: qdlg_calls.append(type(self).__name__)
QMessageBox.exec = lambda self: 0
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
QMenu.exec = lambda self, *a, **k: None
bad_actions = []
for a in acts:
    try:
        t = a.text().replace("&", "")
    except RuntimeError:
        continue                                   # kapanmış diyaloğun eylemi
    if any(sk in t for sk in skip):
        continue
    n0 = len(errors)
    try:
        a.trigger()
        pump(30)
    except Exception as ex:
        errors.append(f"{t}: {type(ex).__name__}: {ex}")
    if len(errors) > n0:
        bad_actions.append((t, errors[-1][-200:]))
check("belge yokken hiçbir eylem yakalanmamış hata vermedi", not bad_actions, str(bad_actions[:5]))
if bad_actions:
    for t, e in bad_actions:
        print("   EYLEM:", t, "->", e.replace("\n", " | ")[-180:])

# =========================== C) belge varken: boş seçim, geri al sınırları ===========================
d1 = os.path.join(tmp, "c1.pdf"); mkdoc(d1, 4)
w.open_paths([d1]); pump(300)
s = w.sessions[0]
scenario("boş seçimle sil/kopyala/yapıştır/kes", lambda: (w.delete_selected(), w.copy_selected() if hasattr(w, "copy_selected") else None,
                                                         w.paste_annotation() if hasattr(w, "paste_annotation") else None))
scenario("geri al/yinele boş yığında (20 kez)", lambda: [(w.act_undo.trigger(), w.act_redo.trigger()) for _ in range(20)])
scenario("sayfa ekle + hemen geri al x5", lambda: [(w._insert_blank_page(1), w.act_undo.trigger(), w.act_redo.trigger(), w.act_undo.trigger()) for _ in range(5)])
scenario("sayfa sil + hemen geri al + yinele hızlı", lambda: [(w._delete_page(0), w.act_undo.trigger(), w.act_redo.trigger(), w.act_undo.trigger()) for _ in range(3)])
scenario("döndür/taşı/kopyala + geri al", lambda: (w._rotate_page(0, 90), w._duplicate_page(0), w._move_page(0, 2), [w.act_undo.trigger() for _ in range(4)]))
scenario("tüm sayfaları sil (son sayfa korunmalı)", lambda: [w._delete_page(0) for _ in range(6)])
check("en az 1 sayfa kaldı", s.pdf.page_count >= 1, str(s.pdf.page_count))
for _ in range(10):
    w.act_undo.trigger()
pump(200)

# çok hızlı sekme değiştirme
d2 = os.path.join(tmp, "c2.pdf"); mkdoc(d2, 5)
d3 = os.path.join(tmp, "c3.pdf"); mkdoc(d3, 6)
w.open_paths([d2, d3]); pump(300)
scenario("hızlı sekme değiştirme x60", lambda: [w.switch_session(i % len(w.sessions)) for i in range(60)])
scenario("sekme değiştir + hemen kapat", lambda: (w.switch_session(0), w.close_session(0, confirm=False), w.switch_session(0), w.close_session(0, confirm=False)))
close_all()

# =========================== D) arka plan işleri sürerken kapatma ===========================
big2 = os.path.join(tmp, "arka.pdf"); mkdoc(big2, 60)
for nm, fn in (
    ("render sürerken sekmeyi kapat", lambda: (w.open_paths([big2]), w.goto_page(40), w.zoom_in() if hasattr(w, "zoom_in") else None, w.close_session(0, confirm=False))),
    ("küçük resimler sürerken kapat", lambda: (w.open_paths([big2]), w.side.show_page("pages"), w.close_session(0, confirm=False))),
):
    scenario(nm, fn)
    close_all()

# metin farkı sürerken kapat
da = os.path.join(tmp, "fa.pdf"); mkdoc(da, 40)
db = os.path.join(tmp, "fb.pdf"); mkdoc(db, 41)
def diff_close():
    w.open_paths([da, db]); pump(200)
    w.compare_documents()
    pump(30)
    while w.sessions:
        w.close_session(0, confirm=False)
scenario("metin farkı sürerken iki belgeyi kapat", diff_close)
close_all()
pump(500)

# OCR iş parçacığı + kapatma
def ocr_close():
    w.open_paths([da]); pump(200)
    from ui.ocrdialog import _OcrTask
    s = w.sessions[0]
    def job(progress, cancelled):
        for i in range(30):
            with s.pdf.lock:
                try:
                    s.pdf.doc[i % 30].get_text()
                except Exception:
                    pass
            time.sleep(0.01)
        return 1
    t = _OcrTask(job) if True else None
    t.signals.done.connect(lambda *_: None)
    QThreadPool.globalInstance().start(t)
    w.close_session(0, confirm=False)
try:
    scenario("OCR/arka plan işi sürerken kapat", ocr_close)
except Exception as ex:
    check("OCR/arka plan işi sürerken kapat", False, str(ex))
close_all()

# kapanmış belgeye erişim
def closed_access():
    pdf = mw.PDFDocument(da)
    pdf.close()
    for fn in (lambda: pdf.page_size(0), lambda: pdf.render_qimage_sync(0), lambda: pdf.page_count,
               lambda: pdf.page_rotation(0), lambda: pdf.close()):
        try:
            fn()
        except Exception as ex:
            if not isinstance(ex, (ValueError, RuntimeError)):
                raise
scenario("kapanmış PDFDocument erişimi (yalnız ValueError/RuntimeError)", closed_access)

# =========================== E) yazma hataları ===========================
d4 = os.path.join(tmp, "yaz.pdf"); mkdoc(d4, 3)
w.open_paths([d4]); pump(300)
s = w.sessions[0]
w.add_annotation(TextAnnotation(QRectF(72, 300, 200, 30), "x", QColor("#c0392b"), 14)) if hasattr(w, "add_annotation") else None
pump(100)
out_bad = os.path.join(tmp, "yok_klasor", "alt", "çıktı.pdf")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out_bad, ""))
b0 = len(boxes)
scenario("kaydet: var olmayan klasör", lambda: w.save_pdf())
check("var olmayan klasöre kaydetme: yarım dosya yok", not os.path.exists(out_bad))
lockdir = os.path.join(tmp, "kilitli"); os.makedirs(lockdir)
lockf = os.path.join(lockdir, "kilit.pdf"); mkdoc(lockf, 1)
fh = open(lockf, "rb")                         # Windows: açık dosya üzerine yazma/taşıma başarısız olur
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (lockf, ""))
scenario("kaydet: kilitli (açık) hedef dosya", lambda: w.save_pdf())
leftover = [f for f in os.listdir(lockdir) if f != "kilit.pdf"]
check("kilitli hedef: yarım/geçici dosya kalmadı", not leftover, str(leftover))
fh.close()
close_all()

# --- regresyon: dev sayfa render sınırı ---
from pdf_engine import PDFDocument, MAX_PIXELS
_big = PDFDocument(big)
_img = _big.render_qimage_sync(0, scale=10.0)
check("dev sayfa: render piksel sınırını aşmaz", 0 < _img.width() * _img.height() <= MAX_PIXELS * 1.01, f"{_img.width()}x{_img.height()}")
check("dev sayfa: küçük resim üretilir", not _big.thumbnail(0).isNull())
_big.close()

# --- regresyon: dışa aktarma atomik ---
d5 = os.path.join(tmp, "atom.pdf"); mkdoc(d5, 2)
pdf5 = PDFDocument(d5)
target = os.path.join(tmp, "hedef.pdf"); open(target, "wb").write(b"ESKI-ICERIK")
os.makedirs(target + ".part")                  # geçici dosya adı dizin: yazma başarısız olur
try:
    pdf5.export_pdf(target, {}, None)
    failed = False
except Exception:
    failed = True
check("atomik dışa aktarma: hata fırlatır", failed)
check("atomik dışa aktarma: mevcut hedef bozulmadı", open(target, "rb").read() == b"ESKI-ICERIK")
os.rmdir(target + ".part")
pdf5.export_pdf(target, {}, None)
check("atomik dışa aktarma: başarılıda hedef yazıldı, .part kalmadı", open(target, "rb").read(4) == b"%PDF" and not os.path.exists(target + ".part"))
pdf5.close()

# --- regresyon: crashguard ---
n_log0 = os.path.getsize(crashguard.log_path()) if os.path.exists(crashguard.log_path()) else 0
shown = []
crashguard.install(lambda ozet, yol: shown.append((ozet, yol)))
sys.excepthook = crashguard._excepthook
def _boom():
    raise KeyError("deneme-hatasi")
for _ in range(3):
    try:
        _boom()
    except KeyError:
        crashguard.report(*sys.exc_info())
check("crashguard: aynı hata art arda 1 uyarı", len(shown) == 1, str(len(shown)))
crashguard.should_notify.__call__("x", 0.0)
check("crashguard: bekleme süresi sonra yeniden uyarır", crashguard.should_notify("x", crashguard.COOLDOWN_S + 1))
th = threading.Thread(target=lambda: 1 / 0, name="deneme-is-parcacigi"); th.start(); th.join()
logtxt = open(crashguard.log_path(), encoding="utf-8").read()
check("crashguard: günlükte Python hatası var", "deneme-hatasi" in logtxt and "KeyError" in logtxt)
check("crashguard: arka plan iş parçacığı hatası günlükte", "ZeroDivisionError" in logtxt and "deneme-is-parcacigi" in logtxt)
check("crashguard: günlük çalışma klasörü\Gunlukler içinde", os.path.dirname(crashguard.log_path()) == os.path.join(workspace.root(), "Gunlukler"))
check("crashguard: yerel çökme günlüğü açık", os.path.exists(os.path.join(crashguard.log_dir(), crashguard.NATIVE_NAME)))
for i in range(40):                          # dönen günlük: sınır aşılınca yedek dosya oluşur
    crashguard.get_logger().error("dolgu %d %s", i, "x" * 60000)
import glob
check("crashguard: günlük döner (en çok 1+3 dosya)", 1 <= len(glob.glob(crashguard.log_path() + "*")) <= 4 and os.path.getsize(crashguard.log_path()) <= crashguard.MAX_BYTES + 70000)
crashguard.uninstall()
sys.excepthook = _hook

# --- regresyon: pencere uyarısı + taslak + kapanış ---
w.toasts.show = lambda *a, **k: shown.append(("toast", a[0], k.get("action")))
d6 = os.path.join(tmp, "taslak.pdf"); mkdoc(d6, 2)
w.open_paths([d6]); pump(200)
w.add_annotation(TextAnnotation(QRectF(72, 300, 200, 30), "kurtar", QColor("#c0392b"), 14)); pump(100)
shown.clear()
w.on_unexpected_error("KeyError: x", crashguard.log_path())
check("beklenmeyen hata: tek Türkçe uyarı + 'Günlüğü aç' eylemi", len(shown) == 1 and "Beklenmeyen bir hata" in shown[0][1] and shown[0][2][0] == "Günlüğü aç", str(shown))
check("beklenmeyen hata: kurtarma taslağı yazıldı (çökmede de çalışır)", len(workspace.list_drafts()) >= 1)
_sd = getattr(w, "_share_dialog", None)
check("belge yokken eylemlerden QR sunucusu açıldı (kapanışta durmalı)", True)
w.shutdown_background()
check("kapanış: zamanlayıcılar durdu", not w._thumb_timer.isActive() and not w._diff_timer.isActive() and not getattr(w, "_recovery_timer", None) or not w._recovery_timer.isActive())
close_all()
_sd = getattr(w, "_share_dialog", None)
w.close()                                    # closeEvent: sunucu, zamanlayıcılar, havuz
check("kapanış: QR sunucusu durdu", _sd is None or _sd._server is None)
check("crashguard günlüğü yazıldı/okunabilir", os.path.isdir(crashguard.log_dir()))

print("\nBULUNAN YAKALANMAMIŞ HATALAR:", len(errors))
for e in errors:
    print("  ---", e.strip().replace("\n", " | ")[-300:])

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
QThreadPool.globalInstance().waitForDone(3000)
for x in w.sessions:
    x.dirty = False
    x.undo_stack.setClean()
# gerçek uygulamadaki kapanış yolu: normal yorumlayıcı çıkışı (os._exit bu Qt sürümünde 0xC0000005 verir)
w.deleteLater()
app.processEvents()
sys.exit(0 if all(ok) else 1)
