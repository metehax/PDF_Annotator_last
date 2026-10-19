import os, sys, tempfile, time, threading, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
import pymupdf as fitz

tmp = tempfile.mkdtemp(prefix="l3_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60), False)
pm.set_rect(pm.irect, (30, 120, 220))
photo = pm.tobytes("jpeg")
pdfb = fitz.open()
pdfb.new_page().insert_text((72, 80), "telefondan")
pdf_bytes = pdfb.tobytes()

import qrshare
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import main_window as mw
from ui.share import ShareDialog

# ---- sunucu: X-Action beyaz listesi ----
recv0 = os.path.join(tmp, "g0")
srv = qrshare.ShareServer(recv0, host="127.0.0.1").start()


def post(url, data, name, action=None):
    h = {"X-Filename": name}
    if action is not None:
        h["X-Action"] = action
    r = urllib.request.Request(url + "up", data=data, method="POST", headers=h)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as ex:
        return ex.code


for act in qrshare.ALLOWED_ACTIONS:
    check(f"X-Action {act} kabul", post(srv.url, photo, f"{act}.jpg", act) == 200)
check("X-Action yok kabul (eski davranış)", post(srv.url, photo, "yok.jpg") == 200)
check("bilinmeyen X-Action reddedilir (400)", post(srv.url, photo, "kotu.jpg", "format_c") == 400)
check("reddedilen kaydedilmedi", not os.path.exists(os.path.join(recv0, "kotu.jpg")))
check("eylem sunucuda kayıtlı", srv.actions.get(os.path.join(recv0, "scan.jpg")) == "scan"
      and srv.actions.get(os.path.join(recv0, "yok.jpg")) == "")
check("beyaz liste", set(qrshare.ALLOWED_ACTIONS) == {"scan", "photo", "pdf"})
import urllib.request as ur
page = ur.urlopen(srv.url, timeout=10).read().decode("utf-8")
check("telefon sayfası: üç işlem + X-Action", all(k in page for k in ("Belge tara", "Fotoğraf olarak", "PDF olarak", "X-Action", "multiple")))
srv.stop()

# ---- pencere ----
app = QApplication.instance() or QApplication(sys.argv)
w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
w.stamp_lib.settings = w.settings
w.sig_lib.settings = w.settings
w.resize(1200, 800)
w.show()


def pump(until=None, limit=20000, ms=100):
    t0 = time.time()
    while (time.time() - t0) * 1000 < (limit if until else ms):
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.01)
    return False


def bg(fn):
    box = {}

    def run():
        try:
            box["v"] = fn()
        except Exception as ex:
            box["e"] = ex
    threading.Thread(target=run, daemon=True).start()
    return box


recv = os.path.join(tmp, "gelen")
w.settings.setValue("share/max_mb", 7)
w.settings.setValue("share/idle_min", 3)
dlg = ShareDialog(w, host="127.0.0.1", receive_dir=recv)
dlg.show()
url = dlg.server.url
check("iki sekme: Telefondan al / Telefona gönder", dlg.tabs.count() == 2
      and dlg.tabs.tabText(0) == "Telefondan al" and dlg.tabs.tabText(1) == "Telefona gönder")
check("ayar: boyut sınırı sunucuya", dlg.server.max_bytes == 7 * 1024 * 1024)
check("ayar: boşta süresi", dlg.idle_limit == 180)
check("otomatik tarayıcı varsayılan açık", dlg.chk_autoscan.isChecked())
w.open_share_send()
check("Paylaş > Telefona gönder sekmeyi açar", w._share_dialog.tabs.currentIndex() == 1)
w._share_dialog.close()
dlg.tabs.setCurrentIndex(0)

# otomatik tarama: ilk foto pencereyi açar, sonrakiler aynı pencereye eklenir
n0 = len(w.sessions)
bg(lambda: post(url, photo, "a1.jpg", "scan"))
check("ilk foto tarayıcıyı kendiliğinden açar", pump(until=lambda: dlg._scan_dlg is not None))
sd = dlg._scan_dlg
pump(ms=300)
check("tarayıcıda 1 sayfa", len(sd.pages) == 1, len(sd.pages))
bg(lambda: post(url, photo, "a2.jpg", "scan"))
check("ikinci foto aynı pencereye eklendi", pump(until=lambda: len(sd.pages) == 2) and dlg._scan_dlg is sd, len(sd.pages))
check("foto belge olarak açılmadı", len(w.sessions) == n0)
check("liste küçük resimli", not dlg.log.item(0).icon().isNull())
sd.close()

# photo -> belge olarak (resim) açılır; pdf -> PDF'e çevrilip açılır
bg(lambda: post(url, photo, "p1.jpg", "photo"))
check("photo: görüntü belge olarak açıldı", pump(until=lambda: len(w.sessions) == n0 + 1))
bg(lambda: post(url, photo, "p2.jpg", "pdf"))
check("pdf: PDF oluştu", pump(until=lambda: os.path.exists(os.path.join(recv, "p2.pdf"))))
check("pdf: PDF açıldı", pump(until=lambda: len(w.sessions) == n0 + 2))

# otomatik tarama kapalı -> kuyruk birikir
dlg.chk_autoscan.setChecked(False)
check("ayar kalıcı", str(w.settings.value("share/auto_scan")).lower() in ("false", "0"))
bg(lambda: post(url, photo, "k1.jpg", "scan"))
check("kapalıyken kuyruğa birikir", pump(until=lambda: len(dlg._scan_queue) == 1))
check("kuyrukta, pencere açılmadı", dlg._scan_dlg is sd and not sd.isVisible())
dlg._scan_queue.clear()
dlg._sync_scan()

# satır eylemleri
dlg.log.setCurrentRow(0)
check("satır düğmeleri etkin", dlg.btn_row_open.isEnabled() and dlg.btn_row_show.isEnabled())
import sharing
shown = []
sharing.reveal = lambda p, **k: shown.append(p)
dlg.row_show()
check("klasörde göster", len(shown) == 1 and os.path.exists(shown[0]))
img_row = next(i for i in range(dlg.log.count()) if dlg.log.item(i).data(0x100).endswith("k1.jpg"))
dlg.log.setCurrentRow(img_row)
outs = dlg.row_pdf()
check("PDF'e çevir", outs and os.path.exists(outs[0]) and fitz.open(outs[0]).page_count == 1, outs)
dlg.log.setCurrentRow(img_row)
sd2 = dlg.row_scan()
pump(ms=300)
check("satırdan Tara tarayıcıyı açar", sd2 is not None and len(sd2.pages) == 1)
sd2.close()

# gönder sekmesi: çoklu dosya
f1 = os.path.join(tmp, "x1.pdf")
f2 = os.path.join(tmp, "x2.pdf")
open(f1, "wb").write(pdf_bytes)
open(f2, "wb").write(pdf_bytes)
check("çoklu dosya sunuldu", dlg.offer_files([f1, f2]) == 2)
check("gönder listesinde iki satır", dlg.out_list.count() == 2, dlg.out_list.count())
box = bg(lambda: urllib.request.urlopen(url + "list", timeout=10).read())
pump(until=lambda: "v" in box)
check("telefon listesinde iki dosya", box.get("v", b"").count(b'"name"') == 2, box.get("v"))
dlg._unoffer()
check("kaldırınca liste boş", dlg.out_list.count() == 0 and dlg.server.listing() == [])
dlg.close()

# varsayılan PIN
w.settings.setValue("share/pin_default", True)
d2 = ShareDialog(w, host="127.0.0.1", receive_dir=recv)
d2.show()
check("PIN varsayılanı: sunucu PIN ister, ekranda görünür", d2.server.pin_required and d2.lan_pin.isVisible()
      and d2.server.pin in d2.lan_pin.text())
d2.close()

# Ayarlar sayfası
from ui.preferences import PreferencesDialog
pd = PreferencesDialog(w)
pd.show_category("Telefon aktarımı")
check("Ayarlar: telefon aktarımı denetimleri", pd.sp_idle.value() == 3 and pd.sp_max.value() == 7 and pd.chk_pin.isChecked())
pd.sp_idle.setValue(9)
check("Ayarlar: değer yazılır", int(w.settings.value("share/idle_min")) == 9)
pd.close()

print(f"OZET: {sum(ok)}/{len(ok)} gecti")
sys.exit(0 if all(ok) else 1)
