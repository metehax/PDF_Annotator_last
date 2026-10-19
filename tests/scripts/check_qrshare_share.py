import os, sys, tempfile, time, json
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
import pymupdf as fitz

tmp = tempfile.mkdtemp(prefix="i4s_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


import sharing


def mk(*parts):
    p = os.path.join(tmp, *parts)
    os.makedirs(p, exist_ok=True)
    return p


# ---------------- bulut klasörü algılama (sahte ortam/klasör) ----------------
home = mk("home1")
mk("home1", "OneDrive")
mk("home1", "Dropbox")
mk("home1", "Google Drive", "My Drive")
env = {"OneDrive": os.path.join(home, "OneDrive"), "OneDriveCommercial": mk("kurumsal", "OneDrive - Contoso")}
got = sharing.cloud_folders(env=env, home=home, drives=[])
names = [f.name for f in got]
check("OneDrive (ev + ortam değişkeni tekrarsız), iş hesabı, Google Drive, Dropbox bulundu",
      names.count("OneDrive") == 1 and "OneDrive (iş)" in names and "Google Drive" in names and "Dropbox" in names, str(names))
check("Google Drive 'My Drive' alt klasörünü gösterir", next(f for f in got if f.name == "Google Drive").path.endswith("My Drive"))
check("sıra: OneDrive → Google Drive → Dropbox", names.index("Dropbox") > names.index("Google Drive") > names.index("OneDrive"), str(names))
check("tüm yollar var olan klasör", all(os.path.isdir(f.path) for f in got))
check("olmayan ortam değişkeni yolu yok sayılır", sharing.cloud_folders(env={"OneDrive": os.path.join(tmp, "yok")}, home=mk("home_bos"), drives=[]) == [])
check("hiçbiri yoksa boş liste", sharing.cloud_folders(env={}, home=mk("home_bos2"), drives=[]) == [])
home2 = mk("home2")
mk("home2", "OneDrive - Acme")
mk("home2", "OneDrive")
g2 = sharing.cloud_folders(env={}, home=home2, drives=[])
check("ev klasöründeki 'OneDrive - Acme' ayrı adla bulunur", sorted(f.name for f in g2) == ["OneDrive", "OneDrive (Acme)"], str([f.name for f in g2]))
drv = mk("sahte_surucu")
mk("sahte_surucu", "My Drive")
g3 = sharing.cloud_folders(env={}, home=mk("home3"), drives=[drv])
check("sürücü harfi altındaki 'My Drive' (Drive for desktop)", [f.name for f in g3] == ["Google Drive"] and g3[0].path.endswith("My Drive"))
la = mk("localappdata")
mk("localappdata", "Dropbox")
dbp, dbb = mk("dropbox_kisisel"), mk("dropbox_is")
json.dump({"personal": {"path": dbp}, "business": {"path": dbb}}, open(os.path.join(la, "Dropbox", "info.json"), "w"))
g4 = sharing.cloud_folders(env={"LOCALAPPDATA": la}, home=mk("home4"), drives=[])
check("Dropbox info.json: kişisel ve iş klasörü", [(f.name, os.path.basename(f.path)) for f in g4] == [("Dropbox", "dropbox_kisisel"), ("Dropbox (iş)", "dropbox_is")], str(g4))
open(os.path.join(la, "Dropbox", "info.json"), "w").write("{bozuk")
check("bozuk info.json uygulamayı düşürmez", sharing.cloud_folders(env={"LOCALAPPDATA": la}, home=mk("home5"), drives=[]) == [])
dd = sharing.cloud_folders(env={"OneDrive": env["OneDrive"]}, home=home, drives=[])
check("aynı klasör iki yoldan bulunsa da tek kez", [f.path for f in dd].count(os.path.abspath(env["OneDrive"])) == 1)

f1 = os.path.join(tmp, "Sözleşme taslağı.pdf")
open(f1, "wb").write(b"%PDF-1.4 x")

# ---------------- konumu aç ----------------
calls = {"launch": [], "folder": []}
fake2 = dict(launch=lambda c: calls["launch"].append(list(c)), open_folder=lambda p: calls["folder"].append(p))
r = sharing.reveal(f1, **fake2)
if sys.platform == "win32":
    check("konum: Gezgin dosyayı seçili açar (explorer /select,)", r == "select" and calls["launch"] == [["explorer", "/select,", os.path.normpath(os.path.abspath(f1))]] and calls["folder"] == [], str(calls))
r = sharing.reveal(f1, select=False, **fake2)
check("konum: select=False klasörü açar", r == "folder" and calls["folder"][-1] == os.path.dirname(os.path.abspath(f1)))
r = sharing.reveal(tmp, **fake2)
check("konum: klasör verilirse kendisi açılır", r == "folder" and calls["folder"][-1] == os.path.abspath(tmp))
try:
    sharing.reveal(os.path.join(tmp, "yok.pdf"), **fake2)
    bad = False
except FileNotFoundError:
    bad = True
check("konum: olmayan dosya FileNotFoundError", bad)

# ====================== pencere (Dosya → Paylaş) ======================
from PySide6.QtCore import QSettings, QRectF
from PySide6.QtGui import QAction, QColor, QDesktopServices
from PySide6.QtWidgets import QApplication, QMenu
import main_window as mw
import workspace
from models import TextAnnotation
import mw_share

app = QApplication.instance() or QApplication(sys.argv)
w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
w.stamp_lib.settings = w.settings
w.sig_lib.settings = w.settings
workspace.configure(w.settings)
w.resize(1200, 800)
w.show()


def pump(ms=150):
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.01)


toasts = []
w.toasts.show = lambda *a, **k: toasts.append(a[0])
acts = {a.text(): a for a in w.findChildren(QAction)}
labels = ("Bulut klasörüne kaydet…", "Dosya konumunu aç")
check("menü: Paylaş altında iki eylem", all(t in acts for t in labels))
check("menüde 'Paylaş' alt menüsü var", any(m.title() == "Paylaş" for m in w.findChildren(QMenu)))
check("belge yokken eylemler pasif", not any(acts[t].isEnabled() for t in labels))
check("belge yokken çağrı uyarı verir, hata yok", w.share_cloud() is None and w.share_reveal() is None and len(toasts) == 2)

SRC = os.path.join(tmp, "belge.pdf")
d = fitz.open()
d.new_page().insert_text((72, 100), "Paylasilacak belge", fontsize=16)
d.save(SRC)
d.close()
w.open_paths([SRC])
pump(400)
s = w.sessions[0]
acts = {a.text(): a for a in w.findChildren(QAction)}
check("belge açılınca eylemler etkin", all(acts[t].isEnabled() for t in labels))

opened = []
_orig_open = QDesktopServices.openUrl
QDesktopServices.openUrl = staticmethod(lambda u: (opened.append(u.toString()), True)[1])
popen_calls = []
_orig_popen = sharing._popen
sharing._popen = lambda cmd: popen_calls.append(list(cmd))

# kaydedilmemiş değişiklik -> işaretli kopya yazılır
w.add_annotation(TextAnnotation(QRectF(72, 200, 250, 30), "ISARET PAYLASIM", QColor("#c0392b"), 16))
w._mark_dirty()
shared = w._share_file(s)
check("değişmiş belge: işaretli kopya geçici klasöre yazılır, özgün değişmez", mw_share.SHARE_TMP in shared and shared.endswith("_isaretli.pdf")
      and "PAYLASIM" in fitz.open(shared)[0].get_text() and "PAYLASIM" not in fitz.open(SRC)[0].get_text(), shared)
check("e-posta izi yok", not hasattr(w, "share_email") and not hasattr(sharing, "compose_email") and not hasattr(sharing, "find_outlook"))
# konum
w._mark_saved(s)
popen_calls.clear()
opened.clear()
res = w.share_reveal()
if sys.platform == "win32":
    check("konumu aç: Gezgin dosyayı seçili açar", res == "select" and popen_calls == [["explorer", "/select,", os.path.normpath(os.path.abspath(SRC))]], str(popen_calls))
else:
    check("konumu aç: klasör", res == "folder")

# bulut klasörü
cl = mk("bulut", "OneDrive")
cl2 = mk("bulut", "Dropbox")
fakes = [sharing.CloudFolder("OneDrive", cl)]
_orig_cf = sharing.cloud_folders
sharing.cloud_folders = lambda *a, **k: list(fakes)
toasts.clear()
dest = w.share_cloud()
check("bulut (tek klasör, kaydedilmiş belge): özgün kopyalanır, sormadan", dest == os.path.join(cl, "belge.pdf") and open(dest, "rb").read() == open(SRC, "rb").read(), str(dest))
check("bulut: bilgi iletisi (eşitlemeyi uygulama yapar)", any("Eşitlemeyi ilgili uygulama yapar" in t for t in toasts))
dest2 = w.share_cloud()
check("bulut: var olan dosya ezilmez, (2) eklenir", dest2 == os.path.join(cl, "belge (2).pdf") and os.path.exists(dest))
w.add_annotation(TextAnnotation(QRectF(72, 260, 250, 30), "BULUT ISARET", QColor("#1d3557"), 16))
w._mark_dirty()
dest3 = w.share_cloud()
check("bulut: değişmiş belge işaretli kopya olarak yazılır", dest3 == os.path.join(cl, "belge_isaretli.pdf") and "BULUT" in fitz.open(dest3)[0].get_text())
fakes[:] = [sharing.CloudFolder("OneDrive", cl), sharing.CloudFolder("Dropbox", cl2)]
seen = []
d4 = w.share_cloud(choose=lambda fl: (seen.append([f.name for f in fl]), fl[1])[1])
check("bulut: birden çok klasörde seçim sorulur, seçilene yazılır", seen == [["OneDrive", "Dropbox"]] and d4 and d4.startswith(cl2), str((seen, d4)))
n_before = sorted(os.listdir(cl)) + sorted(os.listdir(cl2))
check("bulut: seçim iptal edilirse hiçbir şey yazılmaz", w.share_cloud(choose=lambda fl: None) is None and sorted(os.listdir(cl)) + sorted(os.listdir(cl2)) == n_before)
fakes.clear()
toasts.clear()
check("bulut: klasör yoksa uyarı, dosya yazılmaz", w.share_cloud() is None and any("bulunamadı" in t for t in toasts))
sharing.cloud_folders = _orig_cf
sharing._popen = _orig_popen
QDesktopServices.openUrl = _orig_open
for x in w.sessions:
    x.dirty = False
    x.undo_stack.setClean()

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
from PySide6.QtCore import QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
os._exit(0 if all(ok) else 1)
