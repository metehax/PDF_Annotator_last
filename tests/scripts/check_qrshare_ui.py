import os, sys, tempfile, time, threading, socket, urllib.request, urllib.error, json
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
SP = tempfile.gettempdir()
import pymupdf as fitz

tmp = tempfile.mkdtemp(prefix="fui_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


SRC = os.path.join(tmp, "belge.pdf")
d = fitz.open()
for i in range(3):
    d.new_page().insert_text((72, 80), f"Sayfa {i + 1} metni")
d.save(SRC)
phone_pdf = os.path.join(tmp, "telefon.pdf")
d2 = fitz.open(); d2.new_page().insert_text((72, 80), "telefondan geldi"); d2.save(phone_pdf)
pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 50), False); pm.set_rect(pm.irect, (30, 120, 220))
photo = pm.tobytes("jpeg")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QAction
import main_window as mw
from ui.share import ShareDialog

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
        except urllib.error.HTTPError as ex:
            box["v"] = (ex.code, ex.read())
        except Exception as ex:
            box["e"] = ex
    t = threading.Thread(target=run, daemon=True)
    t.start()
    box["t"] = t
    return box


def post(url, data, name):
    r = urllib.request.Request(url + "up", data=data, method="POST", headers={"X-Filename": name})
    with urllib.request.urlopen(r, timeout=15) as resp:
        return resp.status, resp.read()


def get(url):
    with urllib.request.urlopen(url, timeout=15) as resp:
        return resp.status, resp.read()


texts = [a.text() for a in w.findChildren(QAction)]
check("menü: Telefonla aktar (QR)…", "Telefonla aktar (QR)…" in texts)

w.open_paths([SRC])
pump(ms=300)
recv = os.path.join(tmp, "gelen")
dlg = ShareDialog(w, host="127.0.0.1", receive_dir=recv)
dlg.show()
w._share_dialog = dlg
srv = dlg.server
url = srv.url
check("sunucu çalışıyor, adres gösteriliyor", srv.running and dlg.url_lbl.text() == url)
check("qr görüntüsü var", dlg.qr.pixmap() is not None and not dlg.qr.pixmap().isNull())
check("belge açıkken sunma düğmesi etkin", dlg.btn_offer.isEnabled())

# telefondan PDF -> kaydedilir ve açılır
n0 = len(w.sessions)
box = bg(lambda: post(url, open(phone_pdf, "rb").read(), "telefon.pdf"))
check("yükleme yanıtı", pump(until=lambda: "v" in box or "e" in box) and box.get("v", (0,))[0] == 200, box.get("e"))
check("uygulamada açıldı", pump(until=lambda: len(w.sessions) == n0 + 1), len(w.sessions))
check("dosya gelen klasöründe", os.path.exists(os.path.join(recv, "telefon.pdf")))
check("açılan belge telefondakiyle aynı", w.sessions[-1].pdf.doc[0].get_text().strip() == "telefondan geldi")
check("listede görünür", dlg.log.count() == 1 and "telefon.pdf" in dlg.log.item(0).text())

# otomatik aç kapalı -> yalnız kaydedilir
dlg.chk_open.setChecked(False)
box = bg(lambda: post(url, photo, "foto.jpg"))
pump(until=lambda: dlg.log.count() == 2)
pump(ms=300)
check("otomatik aç kapalıyken açılmadı", len(w.sessions) == n0 + 1 and os.path.exists(os.path.join(recv, "foto.jpg")))
dlg.chk_open.setChecked(True)
check("listeden çift tıkla açılır", (dlg._open_item(dlg.log.item(0)), pump(until=lambda: len(w.sessions) == n0 + 2))[1])

# reddedilen dosya listeyi bozmaz
box = bg(lambda: post(url, b"MZ\x90\x00" * 20, "kotu.exe"))
pump(until=lambda: "v" in box)
check("exe reddedildi (415)", box.get("v", (0,))[0] == 415, box)
check("reddedilen listeye girmedi", dlg.log.count() == 2 and not os.path.exists(os.path.join(recv, "kotu.exe")))

# telefona gönder
w.switch_session(0)
pump(ms=200)
dlg._sync_buttons()
dlg.offer_active()
check("sunulan listede", [f["name"] for f in srv.listing()] == ["belge.pdf"], srv.listing())
check("sunulan etiketi", "belge.pdf" in dlg.offer_lbl.text())
box = bg(lambda: get(url + "d/0"))
pump(until=lambda: "v" in box)
got = box.get("v", (0, b""))[1]
doc = fitz.open("pdf", got)
check("indirilen belge açık belge", box["v"][0] == 200 and doc.page_count == 3 and "Sayfa 1" in doc[0].get_text(), box.get("e"))
check("sunulan geçici dosya kaldırılabilir", dlg.btn_unoffer.isEnabled())
dlg._unoffer()
check("kaldırınca indirme yok", srv.listing() == [])

# foto -> tarayıcı kuyruğu
check("tarayıcı seçeneği kapalıyken düğme pasif", not dlg.chk_scan.isChecked() and not dlg.btn_scan.isEnabled())
dlg.chk_scan.setChecked(True)
ns = len(w.sessions)
for nm in ("sayfa1.jpg", "sayfa2.jpg"):
    box = bg(lambda nm=nm: post(url, photo, nm))
    pump(until=lambda: "v" in box)
check("foto kuyruğa birikti (iki)", pump(until=lambda: len(dlg._scan_queue) == 2), len(dlg._scan_queue))
check("fotolar belge olarak açılmadı", len(w.sessions) == ns)
check("taramayı bitir düğmesi sayıyı gösterir", dlg.btn_scan.isEnabled() and "(2)" in dlg.btn_scan.text(), dlg.btn_scan.text())
box = bg(lambda: post(url, open(phone_pdf, "rb").read(), "kuyruk.pdf"))
check("PDF yine belge olarak açılır", pump(until=lambda: len(w.sessions) == ns + 1), len(w.sessions))
check("PDF kuyruğa girmedi", len(dlg._scan_queue) == 2)
sd = dlg.finish_scan()
pump(ms=300)
check("taramayı bitir: tarayıcı iki fotoyla açıldı", sd is not None and len(sd.pages) == 2
      and [os.path.basename(p.src.path) for p in sd.pages] == ["sayfa1.jpg", "sayfa2.jpg"], sd and len(sd.pages))
check("kuyruk boşaldı, düğme pasif", dlg._scan_queue == [] and not dlg.btn_scan.isEnabled())
sd.close()
dlg.chk_scan.setChecked(False)

# ================= I4: aynı ağda değil misiniz? + tünel/PIN =================
import http.client
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication as _QA

opened = []
_orig_open = QDesktopServices.openUrl
QDesktopServices.openUrl = staticmethod(lambda u: (opened.append(u.toString()), True)[1])
dlg.chk_open.setChecked(False)
check("yardım kutusu başta gizli", dlg.help_box.isHidden() and not dlg.btn_help.isChecked())
dlg.btn_help.setChecked(True)
check("yardım: mobil sıcak nokta adımları, internet gerekmez", not dlg.help_box.isHidden() and "sıcak nokta" in dlg.help_lbl.text().lower()
      and "internet gerekmez" in dlg.help_lbl.text())
dlg.btn_wifi.click()
check("Wi-Fi ayarlarını aç düğmesi ms-settings adresini açar", opened and opened[-1] == "ms-settings:network-wifi", str(opened))
dlg.btn_help.setChecked(False)
check("yardım tekrar gizlenir", dlg.help_box.isHidden())

check("tünel kutusu başta kapalı/gizli, PIN yok", not dlg.chk_tunnel.isChecked() and dlg.tunnel_box.isHidden() and not dlg.server.pin_required)
lookups = []
_orig_gai = socket.getaddrinfo
socket.getaddrinfo = lambda host, *a, **k: (lookups.append(host), _orig_gai(host, *a, **k))[1]
dlg.chk_tunnel.setChecked(True)
pump(ms=200)
sv = dlg.server
check("tünel kipi: sunucu yalnız 127.0.0.1'de, PIN'li", sv.host == "127.0.0.1" and sv.pin_required)
check("tünel kipi: PIN etiketi 6 hane, ağ listesi pasif", dlg.pin_lbl.text() == sv.pin and len(sv.pin) == 6 and sv.pin.isdigit() and not dlg.ip_combo.isEnabled())
check("tünel kipi: uyarı metni (dosyalar servisten geçer, uygulama kendisi bağlanmaz)", "servisten geçer" in dlg.tunnel_warn.text()
      and "kendisi bağlanmaz" in dlg.tunnel_warn.text() and "5 yanlış" in dlg.tunnel_warn.text())
check("adres girilmeden QR yok, yönerge var", dlg.share_url() == "" and dlg.url_lbl.text() == "Tünel adresini girin"
      and (dlg.qr.pixmap() is None or dlg.qr.pixmap().isNull()))
check("yerel bağlantı noktası gösterilir", str(sv.port) in dlg.port_lbl.text())
port = sv.port
check("adres geçerli: QR + bağlantı tünel adresi + anahtar", dlg.set_tunnel_address("https://ornek.trycloudflare.com/") is True
      and dlg.share_url() == f"https://ornek.trycloudflare.com/{sv.token}/" and dlg.url_lbl.text() == dlg.share_url()
      and dlg.qr.pixmap() is not None and not dlg.qr.pixmap().isNull())
for bad in ("ornek", "ftp://x.com", "https://a b.com", "javascript:alert(1)", "", "https://x.com/?q=1", "https://"):
    before = dlg.share_url()
    check(f"geçersiz tünel adresi reddedilir: {bad!r}", dlg.set_tunnel_address(bad) is False and dlg.share_url() == before)
check("tünel adresi ayarda saklanır", str(w.settings.value("share/tunnelUrl")) == "https://ornek.trycloudflare.com")
_QA.clipboard().clear()
dlg._copy_url()
check("kopyala: tünel bağlantısı panoda", _QA.clipboard().text() == dlg.share_url())
check("uygulama tünel adresine kendisi bağlanmadı (DNS çözümlemesi yok)", not any("trycloudflare" in str(h) for h in lookups), str(lookups))
socket.getaddrinfo = _orig_gai


def hreq(method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", sv.port, timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    out = (r.status, r.read(), dict(r.getheaders()))
    c.close()
    return out


tk = sv.token
st, body, _ = hreq("GET", f"/{tk}/")
check("telefon önce PIN sayfasını görür", st == 200 and b"PIN gerekli" in body and b"Kamerayla" not in body)
check("PIN'siz yükleme reddedilir, dosya yazılmaz", hreq("POST", f"/{tk}/up", photo, {"X-Filename": "izinsiz.jpg"})[0] == 401
      and not os.path.exists(os.path.join(recv, "izinsiz.jpg")))
for k in range(5):
    st, body, _ = hreq("POST", f"/{tk}/auth", b"000000" if sv.pin != "000000" else b"111111")
pump(ms=100)
dlg.refresh_pin_state()
check("5 yanlış PIN: sunucu kilitlendi (423), kilidi aç düğmesi görünür", st == 423 and sv.locked and not dlg.btn_unlock.isHidden()
      and "kilitlendi" in dlg.pin_state.text())
check("kilitliyken doğru PIN de geçmez", hreq("POST", f"/{tk}/auth", sv.pin.encode())[0] == 423)
dlg.btn_unlock.click()
check("Kilidi aç: kilit kalkar, düğme gizlenir", not sv.locked and dlg.btn_unlock.isHidden())
st, body, hd = hreq("POST", f"/{tk}/auth", sv.pin.encode())
ck = {"Cookie": hd.get("Set-Cookie", "").split(";")[0]}
check("doğru PIN: oturum çerezi", st == 200 and "pdfsid=" in ck["Cookie"])
n_log = dlg.log.count()
st, body, _ = hreq("POST", f"/{tk}/up", photo, {"X-Filename": "pinli.jpg", **ck})
check("PIN'li oturumda yükleme çalışır, dosya gelenlerde", st == 200 and pump(until=lambda: dlg.log.count() == n_log + 1)
      and os.path.exists(os.path.join(recv, "pinli.jpg")))
old_pin = sv.pin
dlg.btn_newpin.click()
check("Yeni PIN: PIN değişir, eski oturum geçersiz", dlg.pin_lbl.text() == sv.pin and sv.pin != old_pin)
check("Yeni PIN: eski çerez reddedilir", hreq("GET", f"/{tk}/list", headers=ck)[0] == 401)
dlg.chk_tunnel.setChecked(False)
pump(ms=200)
sv2 = dlg.server
check("tünel kapanınca PIN kalkar, yerel ağ kipi geri gelir", not sv2.pin_required and sv2.host == "127.0.0.1" and dlg.ip_combo.isEnabled()
      and dlg.tunnel_box.isHidden() and dlg._pin is None)
c = http.client.HTTPConnection("127.0.0.1", sv2.port, timeout=10)
c.request("GET", f"/{sv2.token}/")
r2 = c.getresponse()
b2 = r2.read()
c.close()
check("PIN'siz kipte sayfa doğrudan açılır (geriye uyumlu)", r2.status == 200 and b"Kamerayla" in b2 and b"PIN gerekli" not in b2)
check("QR adresi yerel adrese döndü", dlg.share_url() == sv2.url and dlg.url_lbl.text() == sv2.url)
dlg.chk_tunnel.setChecked(True)
pump(ms=200)
check("tünel yeniden açılınca kayıtlı adres gelir, yeni PIN üretilir", dlg.tunnel_edit.text() == "https://ornek.trycloudflare.com"
      and dlg.server.pin_required)
dlg.chk_tunnel.setChecked(False)
QDesktopServices.openUrl = _orig_open

# görüntü: sonda tek kez
shot = os.path.join(SP, "f_share.png")
dlg.grab().save(shot)

# adres değişince anahtar yenilenir, eski adres kapanır
old_url, old_port, old_tok = srv.url, srv.port, srv.token
dlg._start("127.0.0.1")
check("yeniden başlatınca yeni anahtar", dlg.server.token != old_tok and dlg.url_lbl.text() == dlg.server.url)
try:
    socket.create_connection(("127.0.0.1", old_port), timeout=1).close()
    check("eski sunucu kapandı", False)
except OSError:
    check("eski sunucu kapandı", True)
srv = dlg.server
tmpdir = None

# boşta kalınca kapanır
srv._last -= 15 * 60 + 5
dlg._check_idle()
pump(ms=200)
check("boşta kalınca pencere kapandı, sunucu durdu", not dlg.isVisible() and not srv.running)

# pencere kapanınca sunucu durur + geçici dosyalar silinir
dlg2 = ShareDialog(w, host="127.0.0.1", receive_dir=recv)
dlg2.show()
w._share_dialog = dlg2
dlg2.offer_active()
tdir = dlg2._tmp
port2 = dlg2.server.port
check("geçici sunum klasörü oluştu", tdir and os.path.isdir(tdir))
dlg2.close()
pump(ms=200)
try:
    socket.create_connection(("127.0.0.1", port2), timeout=1).close()
    check("pencere kapanınca sunucu durdu", False)
except OSError:
    check("pencere kapanınca sunucu durdu", True)
check("geçici klasör silindi", not os.path.exists(tdir))

# ana pencere kapanınca da durur
dlg3 = ShareDialog(w, host="127.0.0.1", receive_dir=recv)
dlg3.show()
w._share_dialog = dlg3
srv3 = dlg3.server
for s in w.sessions:
    s.dirty = False
w.close()
pump(ms=300)
check("ana pencere kapanınca sunucu durdu", not srv3.running)

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
print("ekran:", shot)
sys.stdout.flush()
from PySide6.QtCore import QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
os._exit(0 if all(ok) else 1)
