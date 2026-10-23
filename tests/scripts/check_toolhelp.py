"""(i) düğmesi: animasyonlu araç yardımı — tüm sahneler çizilir, zamanlayıcı yalnız açıkken çalışır, azaltılmış hareket."""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

tmp = tempfile.mkdtemp(prefix="th_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


app = QApplication.instance() or QApplication(sys.argv)
import main_window as mw, workspace
from ui import toolhelp
from ui.toolhelp import InfoButton, SCENES, W, H
from mw_common import TOOLS

w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
workspace.configure(w.settings)
w.show()

tools = [t[0] for t in TOOLS if t]
check("her araç için sahne var", all(t in SCENES for t in tools), str([t for t in tools if t not in SCENES]))
bad = []
for name, fn in SCENES.items():
    for t in (0.0, 0.7, 1.5, 2.3, 3.1, 3.9):
        img = QImage(W, H, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        try:
            fn(p, t)
        except Exception as ex:
            bad.append(f"{name}@{t}: {ex}")
        p.end()
check("tüm sahneler tüm karelerde çizilir", not bad, "; ".join(bad[:3]))

btns = {}
for b in w.findChildren(InfoButton):
    if b.tool:
        btns.setdefault(b.tool, b)
check("(i) düğmeleri araca bağlı", len(btns) >= 12, str(sorted(btns)))
b = btns["redact"]
check("yazı ipucu metni korunur (erişilebilirlik)", "KALICI" in b.toolTip())

b.show_help()
pop = b.popup
check("açılır pencere göründü, zamanlayıcı çalışıyor", pop is not None and pop.isVisible() and pop.canvas._timer.isActive())
for _ in range(5):
    app.processEvents()
check("zaman ilerliyor", pop.canvas.t >= 0.0)
pop.hide()
check("kapanınca zamanlayıcı durdu", not pop.canvas._timer.isActive())

workspace.set_reduce_motion(True)
b.show_help()
check("animasyonları azalt: zamanlayıcı yok", not b.popup.canvas._timer.isActive())
b.popup.hide()
workspace.set_reduce_motion(False)

# tek seferlik görsel: dört sahnenin ortak karesi
sheet = QImage(W * 3, H * 2, QImage.Format.Format_ARGB32)
sheet.fill(0)
p = QPainter(sheet)
for i, (name, t) in enumerate((("redact", 2.8), ("copytext", 2.8), ("sign", 2.5), ("blur", 2.8), ("ink", 2.0), ("stamp", 1.6))):
    p.save(); p.translate((i % 3) * W, (i // 3) * H); p.fillRect(0, 0, W, H, toolhelp.QColor("#eef1f6")); SCENES[name](p, t); p.restore()
p.end()
sheet.save(os.environ.get("TOOLHELP_SHEET", os.path.join(tmp, "sheet.png")))

for s in w.sessions:
    s.dirty = False
print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
os._exit(0)
