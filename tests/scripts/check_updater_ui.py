import hashlib, json, os, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
tmp = tempfile.mkdtemp(prefix="k3ui_")
os.environ["PDF_ANNOTATOR_WORKSPACE"] = os.path.join(tmp, "ws")
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


import appinfo
import main_window as mw
import updater
import workspace

PAYLOAD = os.urandom(100_000)
SHA = hashlib.sha256(PAYLOAD).hexdigest()
state = {"version": "9.0.0"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/setup.exe":
            body = PAYLOAD
        else:
            body = json.dumps({"version": state["version"], "url": B + "/setup.exe", "sha256": SHA, "notes": "N", "size": len(PAYLOAD)}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = f"http://127.0.0.1:{srv.server_port}"

app = QApplication.instance() or QApplication(sys.argv)


def pump(cond, sec=8):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
w.stamp_lib.settings = w.settings
w.sig_lib.settings = w.settings
workspace.configure(w.settings)
w.show()
toasts = []
w.toasts.show = lambda text, kind="success", *a, **k: toasts.append(text)

# adres yok → kapalı
check("üretim adresi GitHub (https)", appinfo.UPDATE_URL.startswith("https://api.github.com/repos/"))
appinfo.UPDATE_URL = ""                    # adres yoksa davranışı sınamak için
w.check_updates(manual=True)
check("adres yoksa 'tanımlı değil'", any("tanımlı değil" in t for t in toasts))
w.auto_check_updates()
check("adres yoksa sessiz otomatik denetim iş başlatmaz", w._update_job is None)
dlg = w.open_preferences()
check("tercihlerde denetim düğmesi kapalı", not dlg.btn_upd.isEnabled())

# adres var
updater.ALLOW_HTTP = True
w.update_url = lambda: B + "/latest.json"
offered, installed = [], []
w._ask_update = lambda info: (offered.append(info), True)[1]
updater.install = lambda path, launcher=None: installed.append(path) or [path]
closed = []
w.close = lambda: closed.append(1)

state["version"] = appinfo.VERSION
toasts.clear()
w.check_updates(manual=True)
check("güncelse 'Güncelsiniz'", pump(lambda: any("Güncelsiniz" in t for t in toasts)) and not offered)

state["version"] = "9.0.0"
w.check_updates(manual=True)
check("yeni sürüm sunulur", pump(lambda: bool(offered)) and offered[0].version == "9.0.0")
check("indirilir ve kurulum başlatılır", pump(lambda: bool(installed)) and os.path.isfile(installed[0])
      and open(installed[0], "rb").read() == PAYLOAD)
check("uygulama kapanır", pump(lambda: bool(closed)))
check("sürüm notları", w._update_info is not None and w._update_info.notes == "N")

# ağ hatası: sessiz otomatik, elle denetimde bildirim
w.update_url = lambda: "http://127.0.0.1:1/x.json"
toasts.clear()
w.check_updates(manual=False)
pump(lambda: w._update_job is None)
check("ağ hatası otomatikte sessiz", not toasts)
w.check_updates(manual=True)
check("ağ hatası elle denetimde bildirilir", pump(lambda: any("denetlenemedi" in t for t in toasts)))

# otomatik denetim ayarı
w.settings.setValue("update/auto", False)
offered.clear()
w.update_url = lambda: B + "/latest.json"
w.auto_check_updates()
check("otomatik kapalıyken denetlenmez", w._update_job is None)

srv.shutdown()
w.__class__.close(w)
print(f"OZET: {sum(ok)}/{len(ok)} gecti")
sys.exit(0 if all(ok) else 1)
