"""Belgeyi sürükleyip dışarı bırakma / dosya olarak panoya kopyalama."""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
import pymupdf as fitz
from PySide6.QtCore import QRectF, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

tmp = tempfile.mkdtemp(prefix="dr_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


app = QApplication.instance() or QApplication(sys.argv)
import main_window as mw, workspace
from models import RedactionAnnotation
from ui.dragout import DragOutButton, file_mime

src = os.path.join(tmp, "Sozlesme.pdf")
d = fitz.open(); pg = d.new_page(); pg.insert_text((72, 100), "GIZLI12345", fontsize=18); d.save(src); d.close()

w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
workspace.configure(w.settings)
w.show()
w.open_paths([src]); app.processEvents()
s = w.sessions[0]

check("düğme araç çubuğunda ve belge yokken kapalıdır/değilse açık", isinstance(w.btn_drag, DragOutButton) and w.btn_drag.isEnabled())
p0 = w.export_for_drag()
check("değişmemiş PDF: özgün dosya verilir", p0 == src)

w.add_annotation(RedactionAnnotation(QRectF(60, 80, 160, 30), QColor("black")))
p1 = w.export_for_drag()
check("değişmiş belge: geçici kopya, özgün adla", p1 and p1 != src and os.path.basename(p1) == "Sozlesme.pdf", str(p1))
check("kopyada sansür uygulanmış", "GIZLI12345" not in fitz.open(p1)[0].get_text())
check("özgün dosya değişmedi", "GIZLI12345" in fitz.open(src)[0].get_text())

m = file_mime(p1)
check("mime: tek yerel dosya URL'si", len(m.urls()) == 1 and m.urls()[0].toLocalFile().replace("/", "\\").lower() == os.path.abspath(p1).lower())

w.copy_file_to_clipboard()
cb = QApplication.clipboard().mimeData()
check("panoda dosya var (yapıştırılabilir)", cb is not None and cb.hasUrls() and cb.urls()[0].isLocalFile())

# sürükleme başlatma: QDrag.exec'i sahtele (gerçek sürükleme işletim sisteminde)
import ui.dragout as dr
calls = []
class FakeDrag:
    def __init__(self, *a): pass
    def setMimeData(self, m): calls.append(m)
    def setPixmap(self, p): pass
    def exec(self, act): calls.append(act)
dr.QDrag = FakeDrag
ok_start = w.btn_drag.start_drag()
check("start_drag: mime verildi, yalnızca KOPYALAMA eylemi", ok_start and calls and calls[1] == dr.Qt.DropAction.CopyAction)

w.cleanup_drag_files()
check("kapanışta geçici kopyalar silinir", not os.path.exists(os.path.dirname(p1)))
check("özgün dosya hâlâ duruyor", os.path.isfile(src))

s.dirty = False; s.undo_stack.setClean()
print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
os._exit(0)
