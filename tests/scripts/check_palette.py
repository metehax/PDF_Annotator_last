"""Komut paleti: her menü eylemi/araç/ayar bulunur; eş anlamlı aramalar çalışır."""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
import pymupdf as fitz
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

tmp = tempfile.mkdtemp(prefix="pal_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


app = QApplication.instance() or QApplication(sys.argv)
import main_window as mw, workspace
from ui.palette import score
from mw_common import TOOLS

w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
workspace.configure(w.settings)
w.show()
d = fitz.open(); d.new_page(); d.new_page()
p = os.path.join(tmp, "a.pdf"); d.save(p); d.close()
w.open_paths([p]); app.processEvents()


def found(query):
    """Palet aramasının mantığıyla (başlık, kategori, eş anlamlı) eşleşen başlıklar."""
    out = []
    for c in w._palette_commands(query):
        s = score(query, c.title)
        if s is None and c.category:
            s = score(query, f"{c.category} {c.title}")
        if s is None and c.keywords:
            parts = [score(x, f"{c.title} {c.keywords}") for x in query.split() if x]
            s = None if not parts or any(x is None for x in parts) else sum(parts)
        if s is not None:
            out.append(c.title)
    return out


titles = [c.title for c in w._palette_commands("")]
check("her araç palette (Metin Seç dahil)", all(any(t[1] in x for x in titles) for t in TOOLS if t))
from PySide6.QtGui import QAction
acts = [a for a in w.findChildren(QAction) if a.text() and not a.menu() and a.isEnabled()
        and any(a in m.actions() for _, m in w._menus)]
miss = [a.text() for a in acts if a.text().replace("&", "").rstrip("…").strip().split(" (")[0] not in
        " | ".join(titles).replace(" (açık)", "")]
check("etkin her menü eylemi palette", not miss, str(miss[:5]))

for q, want in (("kopyala", "Metin Seç"), ("ocr", "Otomatik OCR"), ("karart", "Gizle"), ("sansür", "Gizle"),
                ("imzala", "imza"), ("autosave", "Otomatik kaydet"), ("şifre", "Parola"),
                ("hepsini kaydet", "Tümünü kaydet"), ("hareket", "Animasyon"), ("aynı konum", "aynı yere"),
                ("mühür", "Damga"), ("docx", "Word"), ("telefon", "Telefonla aktar"), ("tüm sayfalar", "aynı yere")):
    f = found(q)
    check(f"'{q}' → {want}", any(want.lower() in t.lower() for t in f), str(f[:6]))

c = next(x for x in w._palette_commands("") if x.title.startswith("Otomatik OCR"))
before = workspace.auto_ocr_enabled()
c.run()
check("palet: Otomatik OCR aç/kapa", workspace.auto_ocr_enabled() == (not before))
c.run()
c2 = next(x for x in w._palette_commands("") if x.title.startswith("Sansür/bulanıklaştırmayı"))
c2.run()
check("palet: aynı yere uygula açıldı", w.state.repeat_pages is True)
w.state.repeat_pages = False

for s in w.sessions:
    s.dirty = False
print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
os._exit(0)
