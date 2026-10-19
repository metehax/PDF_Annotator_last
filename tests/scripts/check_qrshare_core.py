import os, sys, tempfile, time, json, socket, http.client, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
import pymupdf as fitz

tmp = tempfile.mkdtemp(prefix="f_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


import qrshare

pdf = fitz.open(); pdf.new_page().insert_text((72, 80), "merhaba"); data = pdf.tobytes(); pdf.close()
png = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False); png.set_rect(png.irect, (10, 200, 10)); pngb = png.tobytes("png")
recv = os.path.join(tmp, "gelen")
got = []
srv = qrshare.ShareServer(recv, on_received=got.append, max_bytes=300_000).start()
base = srv.url.rstrip("/")


def req(method, path, body=None, headers=None):
    c = http.client.HTTPConnection(srv.host, srv.port, timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    out = (r.status, r.read(), dict(r.getheaders()))
    c.close()
    return out


tok = srv.token
check("anahtar rastgele ve uzun", len(tok) >= 20 and qrshare.ShareServer("x").token != tok)
st, body, hd = req("GET", f"/{tok}/")
check("sayfa 200", st == 200 and b"Kamerayla" in body and b"capture" in body, st)
check("sayfa guvenlik basliklari", "default-src" in hd.get("Content-Security-Policy", "") and hd.get("Cache-Control") == "no-store")
check("anahtarsiz yol 404", req("GET", "/")[0] == 404 and req("GET", "/yanlis/")[0] == 404)
check("yanlis anahtar yukleme 404", req("POST", "/yanlis/up", b"%PDF-1", {"X-Filename": "a.pdf"})[0] == 404)
check("anahtar sonuna / eklenir", req("GET", f"/{tok}")[0] == 301)
check("bilinmeyen yol 404", req("GET", f"/{tok}/etc/passwd")[0] == 404 and req("GET", f"/{tok}/d/../../x")[0] == 404)

# yukleme
st, body, _ = req("POST", f"/{tok}/up", data, {"X-Filename": "S%C3%B6zle%C5%9Fme.pdf", "Content-Type": "application/octet-stream"})
j = json.loads(body)
check("pdf yuklendi", st == 200 and j["ok"] and j["name"] == "Sözleşme.pdf", (st, body))
check("dosya birebir", open(os.path.join(recv, "Sözleşme.pdf"), "rb").read() == data)
check("callback cagrildi", got and got[-1].endswith("Sözleşme.pdf"), got)
st, body, _ = req("POST", f"/{tok}/up", data, {"X-Filename": "S%C3%B6zle%C5%9Fme.pdf"})
check("ayni ad benzersizlesir", json.loads(body)["name"] == "Sözleşme (2).pdf", body)
st, body, _ = req("POST", f"/{tok}/up", pngb, {"X-Filename": "foto.PNG"})
check("png yuklendi (uzanti kucuk harf)", st == 200 and json.loads(body)["name"] == "foto.png", body)
# guvenlik
st, body, _ = req("POST", f"/{tok}/up", data, {"X-Filename": "..%5C..%5Cevil.pdf"})
saved = json.loads(body).get("name", "")
check("yol gecisi temizlenir", st == 200 and saved == "evil.pdf" and os.path.exists(os.path.join(recv, "evil.pdf")), (st, body))
check("gelen klasor disina yazilmadi", not os.path.exists(os.path.join(tmp, "evil.pdf")) and not os.path.exists(os.path.join(os.path.dirname(tmp), "evil.pdf")))
check("exe reddedilir", req("POST", f"/{tok}/up", b"MZ\x90\x00" * 10, {"X-Filename": "x.exe"})[0] == 415)
check("uzantisiz reddedilir", req("POST", f"/{tok}/up", data, {"X-Filename": "dosya"})[0] == 415)
st, body, _ = req("POST", f"/{tok}/up", b"MZ\x90\x00" * 50, {"X-Filename": "sahte.pdf"})
check("imza uyusmazligi reddedilir", st == 400 and not os.path.exists(os.path.join(recv, "sahte.pdf")), (st, body))
check("reddedilen .part birakmaz", not [f for f in os.listdir(recv) if f.endswith(".part")], os.listdir(recv))
check("buyuk dosya 413", req("POST", f"/{tok}/up", b"%PDF" + b"0" * 400_000, {"X-Filename": "buyuk.pdf"})[0] == 413)
check("bos dosya 400", req("POST", f"/{tok}/up", b"", {"X-Filename": "bos.pdf"})[0] == 400)
# yarim kalan yukleme
s = socket.create_connection((srv.host, srv.port), timeout=5)
s.sendall(f"POST /{tok}/up HTTP/1.1\r\nHost: x\r\nX-Filename: yarim.pdf\r\nContent-Length: 1000\r\n\r\n%PDF-1.4 kisa".encode())
s.shutdown(socket.SHUT_WR)
time.sleep(0.6)
s.close()
check("yarim yukleme kaydedilmez", not os.path.exists(os.path.join(recv, "yarim.pdf")) and not [f for f in os.listdir(recv) if f.endswith(".part")], os.listdir(recv))
check("GET ile yukleme yok", req("GET", f"/{tok}/up")[0] == 404)
check("PUT desteklenmez", req("PUT", f"/{tok}/up", data)[0] in (501, 405))

# indirme
fpath = os.path.join(tmp, "sunulan.pdf"); open(fpath, "wb").write(data)
srv.offer(fpath, "Açık Belge.pdf")
j = json.loads(req("GET", f"/{tok}/list")[1])
check("liste", j["files"] == [{"i": 0, "name": "Açık Belge.pdf", "size": len(data)}], j)
st, body, hd = req("GET", f"/{tok}/d/0")
check("indirme birebir", st == 200 and body == data and hd["Content-Type"] == "application/pdf")
check("Content-Disposition", "attachment" in hd["Content-Disposition"] and "A%C3%A7%C4%B1k" in hd["Content-Disposition"], hd["Content-Disposition"])
check("olmayan indeks 404", req("GET", f"/{tok}/d/5")[0] == 404)
srv.offer(fpath, "Açık Belge.pdf")
check("ayni ad ustune yazar", len(srv.listing()) == 1)
srv.clear_offers()
check("temizlenince 404", req("GET", f"/{tok}/d/0")[0] == 404)
check("kota sayaci", srv.received_count == 4, srv.received_count)

# adres/QR
ips = qrshare.lan_addresses()
print("lan:", ips)
check("lan adresleri loopback degil", all(not i.startswith("127.") for i in ips))
url = f"http://192.168.1.23:51234/{tok}/"
qb = qrshare.qr_png(url)
check("qr png", qb[:8] == b"\x89PNG\r\n\x1a\n" and len(qb) > 300)
try:
    import cv2, numpy as np
    img = cv2.imdecode(np.frombuffer(qb, np.uint8), cv2.IMREAD_GRAYSCALE)
    dec, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    check("qr cozulunce ayni url", dec == url, dec)
except ImportError:
    print("cv2 yok, QR cozme atlandi")
check("dosya adi temizligi", qrshare.sanitize_filename("CON.pdf") == "_CON.pdf" and qrshare.sanitize_filename('a<b>:c?.PDF') == "abc.pdf"
      and qrshare.sanitize_filename("...") == "dosya" and qrshare.sanitize_filename("C:\\x\\y\\z.png") == "z.png")

# durdurma
srv.stop()
try:
    socket.create_connection((srv.host, srv.port), timeout=1).close()
    check("durunca baglanti reddedilir", False)
except OSError:
    check("durunca baglanti reddedilir", True)
check("durum", not srv.running)
srv.stop()
check("ikinci stop sorun cikarmaz", True)


# ================= PIN (internet tüneli gibi güvenilmeyen yollar için) =================
pin_srv = qrshare.ShareServer(os.path.join(tmp, "gelen_pin"), pin="123456", max_bytes=300_000).start()


def preq(server, method, path, body=None, headers=None):
    c = http.client.HTTPConnection(server.host, server.port, timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    out = (r.status, r.read(), dict(r.getheaders()))
    c.close()
    return out


for bad in ("12345", "1234567", "abcdef", "12345a", "١٢٣٤٥٦", 123456, ""):
    try:
        qrshare.ShareServer("x", pin=bad)
        raised = False
    except ValueError:
        raised = True
    check(f"geçersiz PIN reddedilir: {bad!r}", raised)
p1, p2 = qrshare.generate_pin(), qrshare.generate_pin()
check("generate_pin: 6 haneli rakam", len(p1) == 6 and p1.isdigit() and qrshare.valid_pin(p1) and not qrshare.valid_pin("12345"))
plain = qrshare.ShareServer(os.path.join(tmp, "gelen_duz")).start()
check("PIN'siz sunucu eski gibi (pin_required False, kilitlenmez)", plain.pin_required is False and plain.locked is False and plain.pin is None)
check("PIN'siz sunucuda auth yolu zararsız (200)", preq(plain, "POST", f"/{plain.token}/auth", b"000000")[0] == 200 and plain.failed_attempts == 0)
check("PIN'siz sunucuda sayfa doğrudan açılır", b"Kamerayla" in preq(plain, "GET", f"/{plain.token}/")[1])
plain.stop()

ptok = pin_srv.token
check("PIN'li sunucu: pin_required, URL'de PIN yok", pin_srv.pin_required and "123456" not in pin_srv.url)
st, body, hd = preq(pin_srv, "GET", f"/{ptok}/")
check("çerezsiz sayfa = PIN sayfası (dosya arayüzü yok)", st == 200 and b"PIN gerekli" in body and b"Kamerayla" not in body and b'id="pick"' not in body, st)
check("PIN sayfası güvenlik başlıkları", "default-src" in hd.get("Content-Security-Policy", "") and hd.get("Cache-Control") == "no-store")
check("PIN sayfasında PIN yazmaz", b"123456" not in body)
check("çerezsiz liste 401", preq(pin_srv, "GET", f"/{ptok}/list")[0] == 401)
pin_srv.offer(os.path.join(tmp, "sunulan_pin.pdf"), "sunulan.pdf") if open(os.path.join(tmp, "sunulan_pin.pdf"), "wb").write(data) else None
check("çerezsiz indirme 401", preq(pin_srv, "GET", f"/{ptok}/d/0")[0] == 401)
st, body, _ = preq(pin_srv, "POST", f"/{ptok}/up", data, {"X-Filename": "a.pdf"})
check("çerezsiz yükleme 401, dosya yazılmadı", st == 401 and not os.path.exists(os.path.join(tmp, "gelen_pin", "a.pdf")), (st, body))
check("yanlış anahtar yine 404 (PIN'den önce)", preq(pin_srv, "GET", "/yanlis/")[0] == 404 and preq(pin_srv, "POST", "/yanlis/auth", b"123456")[0] == 404)
check("anahtar sonuna / yönlendirmesi PIN'siz de çalışır", preq(pin_srv, "GET", f"/{ptok}")[0] == 301)

st, body, hd = preq(pin_srv, "POST", f"/{ptok}/auth", b"000000")
j = json.loads(body)
check("yanlış PIN: 403, kalan hak", st == 403 and j["ok"] is False and j["left"] == 4 and "Set-Cookie" not in hd, (st, body))
check("yanlış PIN sayacı arttı, kilit yok", pin_srv.failed_attempts == 1 and not pin_srv.locked and pin_srv.attempts_left == 4)
st, body, _ = preq(pin_srv, "POST", f"/{ptok}/auth", b"12345")
check("kısa/biçimsiz PIN de yanlış deneme sayılır", st == 403 and pin_srv.failed_attempts == 2)
check("çok uzun gövde 400 (deneme sayılmaz)", preq(pin_srv, "POST", f"/{ptok}/auth", b"1" * 100)[0] == 400 and pin_srv.failed_attempts == 2)
st, body, hd = preq(pin_srv, "POST", f"/{ptok}/auth", b"123456")
ck = hd.get("Set-Cookie", "")
check("doğru PIN: 200 + oturum çerezi (HttpOnly, SameSite, yol anahtara bağlı)", st == 200 and json.loads(body)["ok"] and "pdfsid=" in ck
      and "HttpOnly" in ck and "SameSite=Strict" in ck and f"Path=/{ptok}/" in ck, ck)
check("doğru PIN sayacı sıfırlar", pin_srv.failed_attempts == 0)
cookie = {"Cookie": ck.split(";")[0]}
st, body, _ = preq(pin_srv, "GET", f"/{ptok}/", headers=cookie)
check("çerezle ana sayfa açılır", st == 200 and b"Kamerayla" in body)
check("çerezle liste ve indirme çalışır", preq(pin_srv, "GET", f"/{ptok}/list", headers=cookie)[0] == 200
      and preq(pin_srv, "GET", f"/{ptok}/d/0", headers=cookie)[1] == data)
st, body, _ = preq(pin_srv, "POST", f"/{ptok}/up", data, {"X-Filename": "pin.pdf", **cookie})
check("çerezle yükleme çalışır (kurallar aynı)", st == 200 and os.path.exists(os.path.join(tmp, "gelen_pin", "pin.pdf")), (st, body))
st, body, _ = preq(pin_srv, "POST", f"/{ptok}/up", b"MZ\x90\x00" * 10, {"X-Filename": "x.exe", **cookie})
check("çerezle de exe reddedilir (415)", st == 415)
st, body, _ = preq(pin_srv, "POST", f"/{ptok}/up", b"x" * 400_000, {"X-Filename": "buyuk.pdf", **cookie})
check("çerezle de boyut sınırı (413)", st == 413)
check("sahte çerez 401", preq(pin_srv, "GET", f"/{ptok}/list", headers={"Cookie": "pdfsid=uydurma"})[0] == 401
      and preq(pin_srv, "GET", f"/{ptok}/list", headers={"Cookie": "baska=" + cookie["Cookie"].split("=", 1)[1]})[0] == 401)
check("çerez PIN'i içermez", "123456" not in cookie["Cookie"])
t0 = pin_srv.idle_seconds()
time.sleep(0.35)
preq(pin_srv, "GET", f"/{ptok}/list")                    # yetkisiz istek boşta sayacını sıfırlamamalı
check("yetkisiz istek boşta sayacını sıfırlamaz", pin_srv.idle_seconds() >= t0 + 0.3, str(pin_srv.idle_seconds()))
preq(pin_srv, "GET", f"/{ptok}/list", headers=cookie)
check("yetkili istek boşta sayacını sıfırlar", pin_srv.idle_seconds() < 0.3)

# kilit: 5 yanlış deneme
lock_dir = os.path.join(tmp, "gelen_kilit")
ls = qrshare.ShareServer(lock_dir, pin="654321").start()
lt = ls.token
st, body, hd = preq(ls, "POST", f"/{lt}/auth", b"654321")
good_cookie = {"Cookie": hd["Set-Cookie"].split(";")[0]}
codes = []
for k in range(5):
    st, body, _ = preq(ls, "POST", f"/{lt}/auth", b"111111")
    codes.append((st, json.loads(body).get("left")))
check("4 yanlış 403 (kalan 4,3,2,1), 5. yanlış 423 kilit", [c[0] for c in codes] == [403, 403, 403, 403, 423] and [c[1] for c in codes[:4]] == [4, 3, 2, 1], str(codes))
check("kilitli: locked True, hak 0", ls.locked and ls.attempts_left == 0)
st, body, _ = preq(ls, "POST", f"/{lt}/auth", b"654321")
check("kilitliyken DOĞRU PIN de reddedilir (423)", st == 423 and json.loads(body)["locked"] is True)
check("kilitliyken yeni çerez verilmez", "Set-Cookie" not in preq(ls, "POST", f"/{lt}/auth", b"654321")[2])
check("kilitten önce alınmış oturum geçerli kalır", preq(ls, "GET", f"/{lt}/list", headers=good_cookie)[0] == 200)
check("kilitliyken çerezsiz erişim kapalı", preq(ls, "GET", f"/{lt}/list")[0] == 401)
ls.unlock()
check("unlock(): sayaç sıfır, aynı PIN çalışır", not ls.locked and preq(ls, "POST", f"/{lt}/auth", b"654321")[0] == 200)
newp = ls.new_pin()
check("new_pin(): yeni PIN, eski PIN ve oturumlar geçersiz", qrshare.valid_pin(newp) and not ls.locked
      and preq(ls, "GET", f"/{lt}/list", headers=good_cookie)[0] == 401
      and (preq(ls, "POST", f"/{lt}/auth", b"654321")[0] == 403 or newp == "654321"))
ls.unlock()
check("new_pin() ile yeni PIN girilebilir", preq(ls, "POST", f"/{lt}/auth", newp.encode())[0] == 200)
ls.set_pin(None)
check("set_pin(None): PIN kalkar, sayfa doğrudan açılır", not ls.pin_required and b"Kamerayla" in preq(ls, "GET", f"/{lt}/")[1])
try:
    ls.set_pin("12")
    raised = False
except ValueError:
    raised = True
check("set_pin geçersiz değeri reddeder", raised)
ls.stop()
pin_srv.stop()

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
os._exit(0 if all(ok) else 1)
