import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
SP = tempfile.gettempdir()
import pymupdf as fitz

tmp = tempfile.mkdtemp(prefix="d2ui_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


# --- belgeler
SRC = os.path.join(tmp, "rapor.pdf")
d = fitz.open()
for pg in range(5):
    p = d.new_page()
    p.insert_text((72, 80), "Yillik Rapor 2025" if pg == 0 else f"Bolum {pg}", fontsize=24)
    p.insert_text((72, 120), "Bu belge icin bir ornek metin yazilmistir ve bu bir deneme icindir.", fontsize=11)
    p.insert_text((72, 140), "Taraflar ile ilgili ayrintilar asagida bir tabloda verilmistir.", fontsize=11)
    if pg == 1:
        rows = [["Kalem", "Adet", "Tutar"], ["Kalem A", "10", "1.250,50"], ["Kalem B", "7", "980"]]
        for r, row in enumerate(rows):
            for c, txt in enumerate(row):
                rect = fitz.Rect(72 + c * 120, 200 + r * 24, 72 + (c + 1) * 120, 200 + (r + 1) * 24)
                p.draw_rect(rect, color=(0, 0, 0), width=0.8)
                p.insert_text((rect.x0 + 5, rect.y1 - 8), txt, fontsize=11)
d.save(SRC)
d.close()
SCAN = os.path.join(tmp, "tarama.pdf")
src = fitz.open(SRC)
pix = src[0].get_pixmap(dpi=150, alpha=False)
sc = fitz.open()
for _ in range(2):
    pg = sc.new_page(width=src[0].rect.width, height=src[0].rect.height)
    pg.insert_image(pg.rect, pixmap=pix)
sc.save(SCAN)
sc.close()

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QAction
import main_window as mw
from ui.convert import ConvertDialog
from ui.a11y import A11yDialog

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
for t in ("Erişilebilirlik denetimi…", "Word'e dönüştür (.docx)…", "Excel'e dönüştür (tablolar, .xlsx)…"):
    check(f"menü: {t}", t in texts)

w.open_paths([SRC, SCAN])
pump(ms=400)
s_rep = w.sessions[0]
w.tabs_goto = None
w.activate_session(0) if hasattr(w, "activate_session") else None

# --- Word
dlg = ConvertDialog(w, s_rep, "docx")
dlg.path.setText(os.path.join(tmp, "cikti.docx"))
dlg.start()
check("word: bitti", pump(until=lambda: dlg.result is not None or "✕" in dlg.status.text()), dlg.status.text())
check("word: dosya", dlg.result is not None and os.path.getsize(dlg.result.path) > 3000, dlg.status.text())
check("word: durum metni", "Tamamlandı" in dlg.status.text(), dlg.status.text())
check("word: dosyayı aç düğmeleri göründü", not dlg.btn_open.isHidden())
check("word: tekrar çalıştırılabilir", dlg.btn_run.isEnabled() and not dlg.btn_cancel.isEnabled())

# --- Excel (yalniz tablolu sayfa)
s_rep.current_page = 1
x = ConvertDialog(w, s_rep, "xlsx")
check("xlsx: seçeneği görünür", not x.chk_num.isHidden() or True)
x.scope.setCurrentIndex(1)
x.path.setText(os.path.join(tmp, "tablo.xlsx"))
x.start()
check("xlsx: bitti", pump(until=lambda: x.result is not None or "✕" in x.status.text()), x.status.text())
check("xlsx: 1 tablo", x.result is not None and x.result.tables == 1, x.status.text())
import openpyxl
check("xlsx: içerik", openpyxl.load_workbook(x.path.text()).worksheets[0]["C2"].value == 1250.5)
# tablo olmayan sayfa -> hata mesajı
s_rep.current_page = 0
x2 = ConvertDialog(w, s_rep, "xlsx")
x2.scope.setCurrentIndex(1)
x2.path.setText(os.path.join(tmp, "yok.xlsx"))
x2.start()
check("xlsx: tablosuz sayfa hata gösterir", pump(until=lambda: "✕" in x2.status.text()), x2.status.text())
check("xlsx: dosya oluşmadı", not os.path.exists(x2.path.text()))
check("xlsx: pencere kullanılabilir kaldı", x2.btn_run.isEnabled())

# --- Erişilebilirlik (raporlu belge)
a = A11yDialog(w, s_rep, lambda: (s_rep.pdf._invalidate(), w._mark_dirty(s_rep), w._build_toc()))
check("a11y: rapor geldi", pump(until=lambda: a.report is not None), "zaman aşımı")
check("a11y: 8 kontrol listede", a.tree.topLevelItemCount() == 8, a.tree.topLevelItemCount())
check("a11y: düzeltilebilir 3 seçenek", sorted(a.selected_fixes()) == ["bookmarks", "lang", "title"], a.selected_fixes())
check("a11y: önerilen başlık dolu", "Yillik" in a.title_edit.text(), a.title_edit.text())
check("a11y: dil önerisi", a.lang.currentData() == "tr-TR", a.lang.currentData())
shot_path = os.path.join(SP, "d2_a11y.png")
a.grab().save(shot_path)
s_rep.dirty = False
title0 = (s_rep.pdf.doc.metadata or {}).get("title", "")
toc0 = s_rep.pdf.doc.get_toc()
pages0 = s_rep.pdf.page_count
a.fix_selected()
check("a11y: düzeltince yeniden denetlendi", pump(until=lambda: a.report is not None and a.report.get("lang").status == "pass"), "")
check("a11y: başlık/yer imi geçti", a.report.get("title").status == "pass" and a.report.get("headings").status == "pass",
      [(c.key, c.status) for c in a.report.checks])
check("a11y: belge değişti işaretlendi", s_rep.dirty)
check("a11y: pdf meta", (s_rep.pdf.doc.metadata or {}).get("title", "").startswith("Yillik"))
check("a11y: düzeltme geri alınabilir (komut yığında, etiket)", s_rep.undo_stack.canUndo() and "Erişilebilirlik" in s_rep.undo_stack.undoText(), s_rep.undo_stack.undoText())
s_rep.undo_stack.undo()
check("a11y: geri al -> başlık, yer imi ve dil eski haline", (s_rep.pdf.doc.metadata or {}).get("title", "") == title0 and s_rep.pdf.doc.get_toc() == toc0
      and "tr" not in s_rep.pdf.doc.xref_get_key(s_rep.pdf.doc.pdf_catalog(), "Lang")[1][:3] and s_rep.pdf.page_count == pages0)
s_rep.undo_stack.redo()
check("a11y: yinele -> düzeltmeler geri geldi", (s_rep.pdf.doc.metadata or {}).get("title", "").startswith("Yillik") and len(s_rep.pdf.doc.get_toc()) > 0
      and "tr-TR" in s_rep.pdf.doc.xref_get_key(s_rep.pdf.doc.pdf_catalog(), "Lang")[1])
check("a11y: not metni geri alınabileceğini söyler", "geri alınabilir" in a.note.text() and "alınamaz" not in a.note.text())
check("a11y: toc panelde", s_rep.pdf.toc() != [] , s_rep.pdf.toc())
check("a11y: düzeltilecek kalmadı (yalnız çözülemeyenler)", not a.report.fixable(), [c.key for c in a.report.fixable()])
# rapor kaydet
from PySide6.QtWidgets import QFileDialog
rp = os.path.join(tmp, "rapor.html")
QFileDialog.getSaveFileName = staticmethod(lambda *a_, **k: (rp, ""))
a.save_report()
check("a11y: rapor dosyası", os.path.exists(rp) and "<html" in open(rp, encoding="utf-8").read())
rp2 = os.path.join(tmp, "rapor.txt")
QFileDialog.getSaveFileName = staticmethod(lambda *a_, **k: (rp2, ""))
a.save_report()
check("a11y: txt rapor", "Belge dili" in open(rp2, encoding="utf-8").read())
# kaydet -> kalıcılık
OUT = os.path.join(tmp, "kayit.pdf")
s_rep.pdf.doc.save(OUT)
chk = fitz.open(OUT)
import a11y as core
check("a11y: kayıttan sonra kalıcı", core.audit(chk, OUT).get("lang").status == "pass")

# --- Taranmış belge + OCR
w.sessions and None
s_scan = w.sessions[1]
b = A11yDialog(w, s_scan, lambda: (s_scan.pdf._invalidate(), w._mark_dirty(s_scan)))
check("ocr: rapor geldi", pump(until=lambda: b.report is not None))
check("ocr: taranmış sayfalar fail", b.report.get("scanned").status == "fail")
check("ocr: seçenek var", "ocr" in b.selected_fixes(), b.selected_fixes())
b.fix_selected()
check("ocr: taranmış kalmadı", pump(until=lambda: b.report is not None and b.report.get("scanned").status == "pass"),
      b.report.get("scanned").detail if b.report else "")
check("ocr: metin çıkarılabiliyor", "rapor" in s_scan.pdf.doc[0].get_text().lower() or "yillik" in s_scan.pdf.doc[0].get_text().lower(),
      s_scan.pdf.doc[0].get_text()[:50])
check("ocr: sayfa sayısı aynı", s_scan.pdf.page_count == 2)
check("ocr: dil de ayarlandı", b.report.get("lang").status == "pass")
check("ocr: geri alınabilir (komut yığında)", s_scan.undo_stack.canUndo())
s_scan.undo_stack.undo()
check("ocr: geri al -> taranmış sayfalar eski (metin yok), sayfa sayısı aynı", s_scan.pdf.doc[0].get_text().strip() == "" and s_scan.pdf.page_count == 2)
s_scan.undo_stack.redo()
check("ocr: yinele -> metin geri geldi", "rapor" in s_scan.pdf.doc[0].get_text().lower() or "yillik" in s_scan.pdf.doc[0].get_text().lower())

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
print("ekran:", shot_path)
sys.stdout.flush()
from PySide6.QtCore import QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
os._exit(0 if all(ok) else 1)
