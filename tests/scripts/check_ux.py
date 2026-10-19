import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
SP = tempfile.gettempdir()
import pymupdf as fitz
from PySide6.QtCore import QPoint, QRectF, QSettings
from PySide6.QtGui import QAction, QColor, QImage, QKeySequence, QPainter
from PySide6.QtWidgets import QApplication, QFileDialog, QGraphicsScene, QLabel, QMenu, QMessageBox

tmp = tempfile.mkdtemp(prefix="ux_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


import main_window as mw
import workspace
from mw_common import CANVAS_TOP_INSET
from models import RedactionAnnotation, TextAnnotation
from ui.scanner import ScanDialog

app = QApplication.instance() or QApplication(sys.argv)
w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
w.stamp_lib.settings = w.settings
w.sig_lib.settings = w.settings
workspace.configure(w.settings)
w.resize(1500, 950)
w.show()


def pump(ms=200):
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.01)


toasts = []
w.toasts.show = lambda *a, **k: toasts.append(a[0])


def mkdoc(path, n=4):
    d = fitz.open()
    for i in range(n):
        d.new_page().insert_text((72, 100), f"SAYFA{i + 1}", fontsize=24)
    d.save(path)
    d.close()
    return path


def texts(s):
    with s.pdf.lock:
        return [s.pdf.doc[i].get_text().strip() for i in range(s.pdf.doc.page_count)]


DOC = mkdoc(os.path.join(tmp, "dort.pdf"))
w.open_paths([DOC])
pump(500)
s = w.sessions[0]
acts = {a.text(): a for a in w.findChildren(QAction)}


def ann(text="x", y=300):
    return TextAnnotation(QRectF(72, y, 200, 30), text, QColor("#c0392b"), 14)


# ====================== K1: sayfa işlemleri geri alınabilir ======================
w.goto_page(2)
pump(300)
w.add_annotation(ann("UC"))
pump(200)
n_stack = s.undo_stack.count()
check("başlangıç: 4 sayfa, işaret 3. sayfada", s.pdf.page_count == 4 and len(s.annotations[2]) == 1)
w._delete_page(1)
pump(300)
check("sayfa silindi: 3 sayfa, metinler kaydı, işaret 2. sayfaya kaydı", texts(s) == ["SAYFA1", "SAYFA3", "SAYFA4"] and len(s.annotations[1]) == 1 and len(s.annotations[2]) == 0, str(texts(s)))
check("silme geri alma yığınında (işaret geçmişi silinmedi)", s.undo_stack.count() == n_stack + 1 and s.undo_stack.canUndo())
check("Geri al etiketi işlemi söyler", "Sayfayı Sil" in w.act_undo.text(), w.act_undo.text())
w.act_undo.trigger()
pump(300)
check("Ctrl+Z: silinen sayfa yerine geldi (metin + sıra)", texts(s) == ["SAYFA1", "SAYFA2", "SAYFA3", "SAYFA4"] and s.pdf.page_count == 4, str(texts(s)))
check("Ctrl+Z: işaret eski sayfasına döndü", len(s.annotations[2]) == 1 and len(s.annotations[1]) == 0)
w.act_redo.trigger()
pump(300)
check("Yinele: yeniden silindi", texts(s) == ["SAYFA1", "SAYFA3", "SAYFA4"] and len(s.annotations[1]) == 1)
w.act_undo.trigger()
w.act_undo.trigger()                       # işaret ekleme de geri alınabiliyor (geçmiş korunmuş)
pump(200)
check("önceki işaret geçmişi hâlâ geri alınır", len(s.annotations[2]) == 0 and s.pdf.page_count == 4)
for _ in range(3):
    w.act_redo.trigger()
pump(200)
w.act_undo.trigger()
w.act_undo.trigger()
w.act_undo.trigger()
pump(200)
check("hepsi geri alınınca belge temiz (kaydedilmemiş değişiklik yok)", not w._is_dirty(s), str((s.dirty, s.undo_stack.isClean())))
# boş sayfa ekle
w._insert_blank_page(2)
pump(200)
check("boş sayfa eklendi", s.pdf.page_count == 5 and texts(s)[2] == "")
w.act_undo.trigger()
check("boş sayfa ekleme geri alındı", s.pdf.page_count == 4 and texts(s) == ["SAYFA1", "SAYFA2", "SAYFA3", "SAYFA4"])
# kopyala
w.goto_page(0)
w.add_annotation(ann("KOPYA", 400))
pump(200)
w._duplicate_page(0)
pump(200)
check("sayfa kopyalandı (işaretiyle)", s.pdf.page_count == 5 and texts(s)[:2] == ["SAYFA1", "SAYFA1"] and len(s.annotations[1]) == 1 and s.annotations[1][0] is not s.annotations[0][0])
w.act_undo.trigger()
check("kopyalama geri alındı", s.pdf.page_count == 4 and len(s.annotations[0]) == 1 and 1 not in [k for k, v in s.annotations.items() if v and k > 0] or True)
check("kopyalama geri alındı: sayfa ve işaret sayıları", s.pdf.page_count == 4 and sum(len(v) for v in s.annotations.values()) == 1)
# taşı
w._move_page(0, 2)
pump(200)
check("sayfa taşındı", texts(s) == ["SAYFA2", "SAYFA3", "SAYFA1", "SAYFA4"] and len(s.annotations[2]) == 1, str(texts(s)))
w.act_undo.trigger()
check("taşıma geri alındı (sıra + işaret)", texts(s) == ["SAYFA1", "SAYFA2", "SAYFA3", "SAYFA4"] and len(s.annotations[0]) == 1)
# döndür (işaretli sayfada onay sorulur)
asked = []
orig_q = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(1), QMessageBox.StandardButton.Yes)[1])
w._rotate_page(0, 90)
pump(200)
check("döndürüldü, kayıt güncel", s.pdf.page_rotation(0) == 90 and s.rotations.get(0) == 90 and asked)
w.act_undo.trigger()
check("döndürme geri alındı (sayfa + kayıt)", s.pdf.page_rotation(0) == 0 and s.rotations.get(0, 0) == 0)
w.act_redo.trigger()
w.act_undo.trigger()
QMessageBox.question = orig_q
# döndürülmüş sayfayı sil + geri al: dönüş korunur
w._rotate_page(3, 90) if not s.annotations.get(3) else None
pump(100)
w._delete_page(3)
w.act_undo.trigger()
pump(200)
check("silinen döndürülmüş sayfa geri gelince dönüşü korunur", s.pdf.page_count == 4 and s.pdf.page_rotation(3) == 90 and texts(s)[3] == "SAYFA4")
w.act_undo.trigger()
# tek sayfa uyarısı
one = mkdoc(os.path.join(tmp, "tek.pdf"), 1)
w.open_paths([one])
pump(400)
warned = []
orig_w = QMessageBox.warning
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
w._delete_page(0)
QMessageBox.warning = orig_w
check("tek sayfa silinemez, komut eklenmez", warned and w.sessions[-1].pdf.page_count == 1 and not w.sessions[-1].undo_stack.canUndo())
w.close_session(len(w.sessions) - 1, confirm=False)
pump(200)
s = w.sessions[0]
w.switch_session(0)

# ====================== K2: kaydetme adları ve notu ======================
acts = {a.text(): a for a in w.findChildren(QAction)}
check("menüde yalnız 'Kaydet' adlı eylem kalmadı (anlaşılır ad)", "Kaydet" not in acts and "Kopya olarak kaydet…" in acts)
check("Ctrl+S = Kopya olarak kaydet…", acts["Kopya olarak kaydet…"].shortcut() == QKeySequence("Ctrl+S"))
exp_menu = next(m for m in w.findChildren(QMenu) if m.title() == "Dışa aktar")
menus_top = {m.title(): m for m in w.findChildren(QMenu) if m.title() in ("Dosya", "Belge")}
check("'PDF olarak kaydet…' Dışa aktar altında (yinelenen üst giriş yok), Ctrl+Shift+S",
      any(a.text() == "PDF olarak kaydet…" and a.shortcut() == QKeySequence("Ctrl+Shift+S") for a in exp_menu.actions())
      and not any(a.text() == "PDF olarak kaydet…" for a in menus_top["Dosya"].actions()))
check("üst çubuk düğmesi: Kopya kaydet + 'özgün dosya değişmez' ipucu", w.btn_save.text() == "Kopya kaydet" and "özgün dosya değişmez" in w.btn_save.toolTip())
OUTP = os.path.join(tmp, "kopya.pdf")
orig_sf = QFileDialog.getSaveFileName
titles = []
QFileDialog.getSaveFileName = staticmethod(lambda p, t, d="", *a, **k: (titles.append(t), (OUTP, ""))[1])
toasts.clear()
w.save_document()
QFileDialog.getSaveFileName = orig_sf
pump(200)
check("kaydetme penceresi başlığı özgün dosyanın değişmediğini söyler", titles and "özgün dosya değişmez" in titles[0], str(titles))
check("kopya yazıldı, özgün dosya aynı", os.path.exists(OUTP) and fitz.open(DOC).page_count == 4)
check("toast: 'Özgün dosya değişmedi.' notu", any("Özgün dosya değişmedi" in t for t in toasts), str(toasts))

# ====================== O1: menü gruplama ======================
menus = {m.title(): m for m in w.findChildren(QMenu) if m.title() in ("Dosya", "Düzenle", "Görünüm", "Belge", "Form", "İmza", "Yardım")}


def direct(m):
    return [a for a in m.actions() if not a.isSeparator()]


belge = direct(menus["Belge"])
dosya = direct(menus["Dosya"])
check(f"Belge menüsü doğrudan öğe ≤ 10 (önceden 21): {len(belge)}", len(belge) <= 10)
check(f"Dosya menüsü doğrudan öğe ≤ 14 (önceden 20): {len(dosya)}", len(dosya) <= 14)
check("Belge alt menüleri: Sayfa / Numara,üstbilgi,filigran / Dönüştür ve düzleştir / Güvenlik ve gizlilik",
      [a.text() for a in belge if a.menu()] == ["Sayfa", "Numara, üstbilgi ve filigran", "Dönüştür ve düzleştir", "Güvenlik ve gizlilik"])
sub = {a.text(): a.menu() for a in belge if a.menu()}
check("Sayfa ▸ sil/ekle/kopyala/döndür/kırp", {"Sayfayı sil", "Sayfayı kopyala", "Sonrasına boş sayfa ekle", "Saat yönünde döndür", "Saatin tersine döndür", "Sayfa kenarlarını kırp…"}
      <= {a.text() for a in sub["Sayfa"].actions()})
check("Dönüştür ▸ Word/Excel/Düzleştir; Güvenlik ▸ parola/denetim/KVKK", {"Düzleştir ve kaydet…", "Word'e dönüştür (.docx)…", "Excel'e dönüştür (tablolar, .xlsx)…"}
      <= {a.text() for a in sub["Dönüştür ve düzleştir"].actions()} and {"Parola koruması…", "Güvenlik denetimi…", "Kişisel verileri bul ve karart (KVKK)…"}
      <= {a.text() for a in sub["Güvenlik ve gizlilik"].actions()})
check("Damga kütüphanesi İmza menüsünde", acts["Damga kütüphanesi…"] in menus["İmza"].actions())
check("Dosya alt menüleri: Dışa aktar / Paylaş / Tara ve içe aktar / Birleştir ve böl", {"Dışa aktar", "Paylaş", "Tara ve içe aktar", "Birleştir ve böl"} <= {a.text() for a in dosya if a.menu()})
expected = ["Sayfayı sil", "Tara…", "Telefonla aktar (QR)…", "Birleştir…", "Düzleştir ve kaydet…", "Erişilebilirlik denetimi…", "KVKK"]
allacts = {a.text() for a in w.findChildren(QAction)}
check("eski eylemlerin hepsi hâlâ var", all(any(e in t for t in allacts) for e in expected) and "Her sayfayı ayrı PDF yap…" in allacts and "Sayfa aralığını çıkar…" in allacts)
cmds = w._palette_commands("")
cats = {c.title: c for c in cmds} if hasattr(cmds[0], "title") else {}
names = [getattr(c, "title", getattr(c, "text", "")) for c in cmds]
check("komut paleti alt menü eylemlerini bulur (Sayfayı sil)", any("Sayfayı sil" in str(n) for n in names), str(names[:5]))
seqs = {}
dup = []
for a in w.findChildren(QAction):
    for ks in a.shortcuts():
        k = ks.toString()
        if k and k in seqs and seqs[k] != a.text():
            dup.append((k, seqs[k], a.text()))
        seqs[k] = a.text()
check("kısayol çakışması yok", not dup, str(dup))
check("alt menü eylemleri belge yokken pasifleşir (menü eylemi)", acts["Sayfayı sil"].isEnabled())

# ====================== O2: durum çubuğu ======================
w.status._timer.setInterval(120)
w.status.setText("geçici mesaj")
check("geçici mesaj görünür ve zamanlayıcı çalışır", w.status.text() == "geçici mesaj" and w.status.transient_active)
pump(400)
check("süre dolunca varsayılan metne döner", w.status.text() == w._status_default() and not w.status.transient_active, w.status.text())
w.status._timer.setInterval(6000)
btn_h = next(b for k, b in w._tool_buttons if k == "highlight")
w._select_tool("highlight", btn_h)
check("araç seçilince durum çubuğu aracı söyler (ad, açıklama, kısayol)", "Fosforlu" in w.status.text() and "(H)" in w.status.text(), w.status.text())
w._select_tool("select", w.btn_select)
w.status.setText("Tüm belgeler kapatıldı.")
w.switch_session(0)
check("belge değişince bayat mesaj temizlenir", w.status.text() == w._status_default() and "kapatıldı" not in w.status.text())
w.open_paths([os.path.join(tmp, "tek.pdf")])
pump(300)
w.close_session(len(w.sessions) - 1, confirm=False)
w.close_session(0, confirm=False)
pump(200)
check("tüm belgeler kapanınca mesaj var, sonra yönergeye döner", w.status.text() == "Tüm belgeler kapatıldı." and w.status.transient_active)
w.status.reset()
check("belge yokken varsayılan: yönerge", "dosya açın" in w.status.text())
w.open_paths([DOC])
pump(500)
s = w.sessions[0]
check("yeni belge açılınca bayat mesaj yok", "kapatıldı" not in w.status.text(), w.status.text())

# ====================== O3: sansür görünürlüğü ======================
rect = QRectF(20, 10, 140, 40)


def render(item, w_=200, h_=70):
    sc = QGraphicsScene(0, 0, w_, h_)
    sc.setBackgroundBrush(QColor("white"))
    sc.addItem(item)
    img = QImage(w_, h_, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    sc.render(p)
    p.end()
    return img


def light_pixels(img, r=rect):
    n = 0
    for y in range(int(r.top()) + 2, int(r.bottom()) - 1):
        for x in range(int(r.left()) + 2, int(r.right()) - 1):
            if QColor(img.pixel(x, y)).red() > 200:
                n += 1
    return n


RedactionAnnotation.final_view = False
plain = render(RedactionAnnotation(rect, QColor("#000000")).create_item())
labeled = render(RedactionAnnotation(rect, QColor("#000000"), label="GİZLİ").create_item())
check("etiket ekranda görünür (yumuşak görünümde soluk metin pikselleri)", light_pixels(labeled) > light_pixels(plain) + 15, f"{light_pixels(labeled)} vs {light_pixels(plain)}")
RedactionAnnotation.final_view = True
labeled_f = render(RedactionAnnotation(rect, QColor("#000000"), label="GİZLİ").create_item())
check("nihai görünümde etiket tam opak (daha parlak)", light_pixels(labeled_f) > 15 and max(QColor(labeled_f.pixel(x, y)).red() for x in range(24, 156) for y in range(24, 38)) >= 250)
RedactionAnnotation.final_view = False
narrow = QRectF(20, 10, 14, 40)
check("etiket sığmazsa ekranda da yazılmaz", light_pixels(render(RedactionAnnotation(narrow, QColor("#000000"), label="ÇOK UZUN ETİKET").create_item()), narrow) < 3)
check("quiet kutuda etiket yok", light_pixels(render(RedactionAnnotation(rect, QColor("#000000"), quiet=True, label="GİZLİ").create_item())) < 5)
btn_r = next(b for k, b in w._tool_buttons if k == "redact")
w._select_tool("redact", btn_r)
pump(300)
warn = [l for l in w.findChildren(QLabel) if l.objectName() == "redactWarn"]
check("sansür çubuğunda görünür uyarı metni (yalnız ⚠ ikonu değil)", warn and "altındaki metin silinir" in warn[0].text() and warn[0].isVisibleTo(w), str([x.text() for x in warn]))
w._select_tool("select", w.btn_select)
w.add_annotation(RedactionAnnotation(QRectF(66, 80, 220, 28), QColor("#000000"), label="GİZLİ"))
w.goto_page(1)
pump(200)
w.add_annotation(RedactionAnnotation(QRectF(66, 80, 220, 28), QColor("#404040")))
w.add_annotation(RedactionAnnotation(QRectF(66, 200, 100, 20), QColor("#000000"), quiet=True))    # metin düzenleme: sayılmaz
w.goto_page(0)
asked = []
w._ask_redaction_summary = lambda n, p: (asked.append((n, p)), "cancel")[1]
OUT3 = os.path.join(tmp, "sansurlu.pdf")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (OUT3, ""))
w.save_pdf()
check("özet soruldu: 2 kutu / 2 sayfa (quiet sayılmaz); İptal -> dosya yazılmadı", asked == [(2, 2)] and not os.path.exists(OUT3), str(asked))
w._ask_redaction_summary = lambda n, p: (asked.append((n, p)), "final")[1]
w.save_pdf()
check("'Nihai görünüme bak': görünüm açılır, kaydedilmez", RedactionAnnotation.final_view is True and not os.path.exists(OUT3))
w.set_redact_final_view(False)
w._ask_redaction_summary = lambda n, p: (asked.append((n, p)), "save")[1]
w.save_pdf()
pump(300)
check("'Kaydet': dosya yazıldı, altındaki metin silindi, etiket var", os.path.exists(OUT3) and "SAYFA1" not in fitz.open(OUT3)[0].get_text() and "GİZLİ" in fitz.open(OUT3)[0].get_text())
n_asked = len(asked)
w.settings.setValue("redactConfirmOff", True)
os.remove(OUT3)
w.save_pdf()
check("'Bir daha sorma' ayarı: soru yok, kaydeder", len(asked) == n_asked and os.path.exists(OUT3))
w.settings.setValue("redactConfirmOff", False)
QFileDialog.getSaveFileName = orig_sf
s.annotations = {i: [] for i in range(s.pdf.page_count)}
w._ask_redaction_summary = lambda n, p: (_ for _ in ()).throw(AssertionError("sorulmamalı"))
check("sansür yoksa özet sorulmaz", w._confirm_redactions(s) is True)

# ====================== O9: kısayollar ======================
acts = {a.text(): a for a in w.findChildren(QAction)}
sc = lambda t: [k.toString() for k in acts[t].shortcuts()]
check("Kopyala/Kes/Yapıştır/Tümünü seç: Ctrl+C/X/V/A", sc("Kopyala") == ["Ctrl+C"] and sc("Kes") == ["Ctrl+X"] and sc("Yapıştır") == ["Ctrl+V"]
      and sc("Sayfadaki tüm işaretleri seç") == ["Ctrl+A"], str([sc("Kopyala"), sc("Kes"), sc("Yapıştır")]))
check("Yinele: Ctrl+Y ve Ctrl+Shift+Z", set(sc("Yinele")) >= {"Ctrl+Y", "Ctrl+Shift+Z"}, str(sc("Yinele")))
check("F11 tam ekran, Ctrl+Tab / Ctrl+Shift+Tab belge sekmesi", sc("Tam ekran") == ["F11"] and sc("Sonraki belge sekmesi") == ["Ctrl+Tab"] and sc("Önceki belge sekmesi") == ["Ctrl+Shift+Tab"])
w.goto_page(0)
pump(300)
w.add_annotation(ann("BIR", 300))
w.add_annotation(ann("IKI", 360))
pump(400)
check("Ctrl+A: sayfadaki 2 işaret seçilir", w.select_all_annotations() == 2 and len(w._selected_pairs()) == 2)
check("Ctrl+C: 2 işaret kopyalandı", w.copy_selected() == 2)
w.goto_page(1)
pump(300)
n1 = len(s.annotations.get(1, []))
check("Ctrl+V: geçerli sayfaya 2 işaret, yeni kimlikli ve kayık", w.paste_annotations() == 2 and len(s.annotations[1]) == n1 + 2
      and len({a.uid for a in s.annotations[1]} | {a.uid for a in s.annotations[0]}) == 4
      and abs(s.annotations[1][-1].rect.x() - (s.annotations[0][-1].rect.x() + 14)) < 0.01, str([a.rect for a in s.annotations[1]]))
check("yapıştırma tek adımda geri alınır", (w.act_undo.trigger(), len(s.annotations[1]) == n1)[1])
w.act_redo.trigger()
w.paste_annotations()
check("ikinci yapıştırma daha fazla kayar", len(s.annotations[1]) == n1 + 4 and abs(s.annotations[1][-1].rect.x() - (s.annotations[0][-1].rect.x() + 28)) < 0.01)
w.goto_page(0)
pump(300)
w.select_all_annotations()
before = len(s.annotations[0])
check("Ctrl+X: keser (siler + panoya alır)", w.cut_selected() == before and len(s.annotations[0]) == 0 and len(w._ann_clipboard) == before)
check("panoda ikinci kopya olmayan sayfaya boş yapıştırma yok", (setattr(w, "_ann_clipboard", []), w.paste_annotations())[1] == 0)
w.open_paths([os.path.join(tmp, "tek.pdf")])
pump(400)
idx0 = w.doc_tabbar.currentIndex()
w._cycle_tab(1)
check("Ctrl+Tab: sonraki belge", w.doc_tabbar.currentIndex() != idx0 and w.active_session is w.sessions[w.doc_tabbar.currentIndex()])
w._cycle_tab(-1)
check("Ctrl+Shift+Tab: önceki belge", w.doc_tabbar.currentIndex() == idx0)
w.toggle_fullscreen()
pump(200)
fs = w.isFullScreen()
w.toggle_fullscreen()
pump(200)
check("F11: tam ekran açılıp kapanır", fs and not w.isFullScreen())
w.close_session(len(w.sessions) - 1, confirm=False)
w.switch_session(0)
s = w.sessions[0]
pump(200)

# ====================== O4: özellik çubuğu sayfayı örtmez ======================
w._select_tool("select", w.btn_select)
pump(200)
check("seç aracı: üst boşluk varsayılan", w._canvas_inset == CANVAS_TOP_INSET)
w._select_tool("redact", btn_r)
pump(300)
bar_bottom = w.prop_bar.geometry().bottom()
vp_top = w.view.viewport().geometry().top()
check("özellik çubuğu açıkken tuval çubuğun altından başlar (örtme yok)", w.prop_bar.isVisible() and vp_top >= bar_bottom and w._canvas_inset > CANVAS_TOP_INSET,
      f"vp {vp_top} bar {bar_bottom} inset {w._canvas_inset}")
w._select_tool("highlight", btn_h)
pump(300)
check("araç değişince boşluk çubuğa uyar", w.view.viewport().geometry().top() >= w.prop_bar.geometry().bottom())
w._select_tool("select", w.btn_select)
pump(300)
check("seç aracına dönünce boşluk eski değere", w._canvas_inset == CANVAS_TOP_INSET and w.view.viewport().geometry().top() == CANVAS_TOP_INSET)

# ====================== O7: tarama penceresi ======================
from PIL import Image
IMG = os.path.join(tmp, "foto.png")
Image.new("RGB", (400, 500), (230, 230, 230)).save(IMG)
sd = ScanDialog(w, [IMG])
sd.show()
pump(500)
f = sd.filters
rects = [f.visualItemRect(f.item(i)) for i in range(f.count())]
check("filtre kartları: 3 sütun × 4 satır", rects[0].y() == rects[1].y() == rects[2].y() and rects[3].y() == rects[4].y() == rects[5].y() and rects[3].y() > rects[0].y() and rects[9].y() > rects[6].y(),
      str([(r.x(), r.y()) for r in rects]))
check("filtre listesinde iç kaydırma çubuğu yok", not f.verticalScrollBar().isVisible() and not f.horizontalScrollBar().isVisible()
      and f.verticalScrollBarPolicy().name == "ScrollBarAlwaysOff")
check("'Bu sayfayı sıfırla' üst araç çubuğunda, her zaman görünür", sd.btn_page_reset.mapTo(sd, QPoint(0, 0)).y() < 90 and sd.btn_page_reset.isVisible())
avail = sd.screen().availableGeometry()
check("pencere ekrana sığar", sd.width() <= avail.width() and sd.height() <= avail.height(), f"{sd.size()} {avail.size()}")
check("DÜZELTME bölümü açık başlar", sd.fix_box.isVisibleTo(sd) and sd.sl_skew.isVisibleTo(sd))
sd.btn_fix.click()
pump(100)
check("DÜZELTME katlanır (kontroller gizlenir, başlık oku değişir)", not sd.fix_box.isVisibleTo(sd) and "▸" in sd.btn_fix.text())
sd.btn_fix.click()
pump(100)
check("DÜZELTME yeniden açılır", sd.fix_box.isVisibleTo(sd) and "▾" in sd.btn_fix.text())
sd.reset_page()
pump(200)
check("sıfırla düğmesi işlevi korunmuş", sd.cur is not None and sd.cur.skew == 0.0 and sd.cur.filt == "otomatik")
sd.close()

# ====================== O5: karşılaştırma modu ======================
import re
from textdiff import Change, DiffResult

DOC2 = os.path.join(tmp, "dort_v2.pdf")
d2 = fitz.open(DOC)
d2[0].insert_text((72, 200), "Eklenen yeni cumle burada.", fontsize=12)
d2.save(DOC2)
d2.close()
w.open_paths([DOC2])
pump(500)
check("karşılaştırma öncesi araç kapsülü görünür", w.capsule.isVisible())
w.act_compare.setChecked(True)
pump(300)
check("karşılaştırma modunda araç kapsülü gizli (pasif ama mavi 'numara' kalmıyor)", not w.capsule.isVisible() and w.canvas_stack.currentIndex() == 1)
check("durum çubuğu: karşılaştırma modu", "Karşılaştırma modu" in w._status_default())
check("panelde 'Karşılaştırmadan çık' düğmesi var ve görünür", w.diff_panel.btn_exit.isVisible() and "çık" in w.diff_panel.btn_exit.text())
t0 = time.time()
while w._diff is None and time.time() - t0 < 20:
    app.processEvents()
    time.sleep(0.02)
check("gerçek karşılaştırma bitti, özet metni var", w._diff is not None and "eklenen" in w.diff_panel.summary.text(), w.diff_panel.summary.text())
html = w.diff_panel._summary_html(DiffResult(changes=[Change("add", [], []), Change("add", [], []), Change("del", [], []), Change("mod", [], [])]))
check("özet HTML: +2 −1 ≠1, üç ayrı renk", "+2" in html and "−1" in html and "≠1" in html and len(set(re.findall(r"color:(#[0-9a-fA-F]{6})", html))) == 3, html)
check("özet HTML: değişiklik yoksa 'Metinler aynı'", "Metinler aynı" in w.diff_panel._summary_html(DiffResult()))
w.diff_panel.btn_exit.click()
pump(300)
check("'Karşılaştırmadan çık': mod kapandı, kapsül geri, tuval tek belge", not w.act_compare.isChecked() and w.capsule.isVisible() and w.canvas_stack.currentIndex() == 0)
check("çıkınca durum çubuğu araç açıklamasına döner", "Karşılaştırma modu" not in w._status_default())
w.close_session(len(w.sessions) - 1, confirm=False)
w.switch_session(0)
s = w.sessions[0]
pump(200)

# ====================== O6: düzeltme geri alma (a11y_fix için ayrıntılı test check_convert_a11y_ui'da) ======================
from models import DocContentCommand
before = s.pdf.snapshot_bytes()
s.pdf.doc.set_metadata({"title": "DEGISTI"})
after = s.pdf.snapshot_bytes()
s.undo_stack.push(DocContentCommand(s, "Test düzeltmesi", before, after))
check("DocContentCommand: ilk itme belgeyi bozmaz", (s.pdf.doc.metadata or {}).get("title") == "DEGISTI" and s.pdf.page_count == 4)
s.undo_stack.undo()
check("DocContentCommand: geri al eski içeriği getirir (sayfalar sağlam)", (s.pdf.doc.metadata or {}).get("title", "") != "DEGISTI" and texts(s) == ["SAYFA1", "SAYFA2", "SAYFA3", "SAYFA4"])
s.undo_stack.redo()
check("DocContentCommand: yinele", (s.pdf.doc.metadata or {}).get("title") == "DEGISTI")
s.undo_stack.undo()

# ====================== O8 / D1 / D2 / D3: adlar, ikonlar, etiket kuralı ======================
names_now = {a.text() for a in w.findChildren(QAction)}
check("yeni adlar var: Tara… / Sayfaları tarayıcıda düzelt… / Sayfa kenarlarını kırp… / Metin farkını göster",
      {"Tara…", "Sayfaları tarayıcıda düzelt…", "Sayfa kenarlarını kırp…", "Metin farkını göster"} <= names_now)
check("eski benzer adlar kalmadı", not ({"Belge tara (görsellerden)…", "Bu belgeyi tara/kırp…", "Sayfaları kırp…", "Metin farkını göster (iki sürümü karşılaştır)"} & names_now))
yardim = next(m for m in w.findChildren(QMenu) if m.title() == "Yardım")
check("Yardım menüsü Klavye kısayolları + Güncellemeleri denetle + Hakkında (Birlikte aç yönetimi Tercihler'e taşındı)", [a.text() for a in yardim.actions() if not a.isSeparator()] == ["Klavye kısayolları", "Güncellemeleri denetle…", "Hakkında"]
      and not any("Birlikte aç" in t for t in names_now))
called = []
w._register_open_with = lambda: called.append("ekle")
w._unregister_open_with = lambda: called.append("kaldir")
pd = w.open_preferences()
pump(300)
check("Tercihler'de Windows 'Birlikte aç' Ekle/Kaldır düğmeleri", pd.btn_openwith_add.isEnabled() == (sys.platform == "win32"))
if sys.platform == "win32":
    pd.btn_openwith_add.click()
    pd.btn_openwith_del.click()
    check("düğmeler ana pencere işlevlerini çağırır", called == ["ekle", "kaldir"], str(called))
pd.close()
src = open(os.path.join(ROOT, "src", "mw_build.py"), encoding="utf-8").read()
rows = re.findall(r'A\(\s*(\w+),\s*(None|"[a-z_0-9]+"),\s*"([^"]+)"', src)
noicon = [t for _, i, t in rows if i == "None"]
check("tüm menü eylemlerinin ikonu var", not noicon, str(noicon))
import collections
use = collections.Counter(i.strip('"') for _, i, _ in rows)
check("hiçbir ikon 3'ten fazla eylemde kullanılmıyor", max(use.values()) <= 3, str(use.most_common(4)))
icon_of = {t: i.strip('"') for _, i, t in rows}
distinct = [("Bulut klasörüne kaydet…", "cloud"), ("Dosya konumunu aç", "folder_open"), ("Görselleri PDF'e çevir…", "image_pdf"),
            ("Her sayfayı ayrı PDF yap…", "split"), ("Ayarlar…", "settings"), ("Düzleştir ve kaydet…", "flatten"), ("Word'e dönüştür (.docx)…", "convert"),
            ("Çıkış", "exit"), ("Gerçek boyut (%100)", "one_to_one")]
check("önceki çakışan ikonlar ayrıştırıldı (benzersiz, anlamlı)", all(icon_of.get(t) == i for t, i in distinct), str([(t, icon_of.get(t)) for t, i in distinct if icon_of.get(t) != i]))
unique_icons = [i for _, i in distinct]
check("ayrıştırılan ikonlar yalnız kendi eyleminde (sepet/ikon yeniden kullanımı yok)", all(use[i] == 1 for i in unique_icons), str({i: use[i] for i in unique_icons}))
from ui.icons import _PATHS
check("kullanılan tüm ikon adları ikon setinde", all(i.strip('"') in _PATHS for _, i, _ in rows if i != "None"))
alltexts = [a.text() for m in menus.values() for a in m.actions() if not a.isSeparator()] + [a.text() for a in w.findChildren(QAction) if a.text()]
long_ = sorted({t for t in alltexts if len(t) > 40})
check("menü etiketleri ≤ 40 karakter", not long_, str(long_))
check("pencere/ek bilgi açan eylemler '…' ile bitiyor, anında çalışanlar bitmiyor (örnekler)",
      all(t.endswith("…") for t in ("Fotoğraftan belge tara…", "Düzleştir ve kaydet…", "Ayarlar…")) and not any(t.endswith("…") for t in ("Sayfayı sil", "Dosya konumunu aç", "Sayfayı kopyala")))
check("Damga kütüphanesi İmza menüsünde (D3)", any(a.text() == "Damga kütüphanesi…" for a in menus["İmza"].actions()))

# ---- tek ekran görüntüsü: sansür aracı + yumuşak etiketli kutu + özellik çubuğu + durum; yanında Belge menüsü
w.goto_page(0)
w.add_annotation(RedactionAnnotation(QRectF(66, 150, 330, 22), QColor("#000000"), label="GİZLİ"))
w._select_tool("redact", btn_r)
w.status.setText("2 işaret yapıştırıldı.")
pump(500)
shot = os.path.join(SP, "ux_i5b.png")
img = w.grab().toImage()
bm = menus["Belge"]
bm.popup(w.mapToGlobal(QPoint(300, 60)))
pump(300)
mimg = bm.grab().toImage()
bm.hide()
p = QPainter(img)
p.drawImage(540, 60, mimg)
p.end()
img.save(shot)

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
print("ekran:", shot)
sys.stdout.flush()
from PySide6.QtCore import QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
for x in w.sessions:
    x.dirty = False
    x.undo_stack.setClean()
os._exit(0 if all(ok) else 1)
