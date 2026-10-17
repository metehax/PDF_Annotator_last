import os, sys, tempfile, time, json, socket, http.client, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
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

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
os._exit(0 if all(ok) else 1)
