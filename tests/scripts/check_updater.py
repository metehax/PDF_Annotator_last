import hashlib, json, os, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


import updater

PAYLOAD = os.urandom(300_000)
SHA = hashlib.sha256(PAYLOAD).hexdigest()
ROUTES = {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        r = ROUTES.get(self.path)
        if r is None:
            self.send_response(404)
            self.end_headers()
            return
        body = r if isinstance(r, bytes) else json.dumps(r).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = f"http://127.0.0.1:{srv.server_port}"
ROUTES["/setup.exe"] = PAYLOAD
ROUTES["/new.json"] = {"version": "9.0.0", "url": B + "/setup.exe", "sha256": SHA, "notes": "Yeni", "size": len(PAYLOAD)}
ROUTES["/same.json"] = {"version": "1.0.0", "url": B + "/setup.exe", "sha256": SHA}
ROUTES["/old.json"] = {"version": "0.9.9", "url": B + "/setup.exe", "sha256": SHA}
ROUTES["/bad.json"] = {"version": "9.0.0", "url": B + "/setup.exe", "sha256": "0" * 64}
ROUTES["/nosha.json"] = {"version": "9.0.0", "url": B + "/setup.exe"}
ROUTES["/garbage"] = b"<html>degil</html>"
ROUTES["/gh.json"] = {"tag_name": "v9.1.0", "body": "Notlar", "assets": [
    {"name": "PDF-Annotator-Setup-9.1.0.exe", "browser_download_url": B + "/setup.exe", "size": len(PAYLOAD),
     "digest": "sha256:" + SHA}]}
ROUTES["/gh2.json"] = {"tag_name": "v9.2.0", "assets": [
    {"name": "PDF-Annotator-Setup-9.2.0.exe", "browser_download_url": B + "/setup.exe"},
    {"name": "PDF-Annotator-Setup-9.2.0.exe.sha256", "browser_download_url": B + "/s.sha256"}]}
ROUTES["/s.sha256"] = (SHA + "  PDF-Annotator-Setup-9.2.0.exe\n").encode()

# sürüm mantığı
check("1.2.10 > 1.2.9", updater.is_newer("1.2.10", "1.2.9"))
check("v2.0 > 1.9.9", updater.is_newer("v2.0", "1.9.9"))
check("1.0 == 1.0.0 (yeni değil)", not updater.is_newer("1.0", "1.0.0"))
check("eski sürüm yeni değil", not updater.is_newer("1.0.0", "1.0.1"))
try:
    updater.parse_version("abc")
    check("geçersiz sürüm reddedilir", False)
except updater.UpdateError:
    check("geçersiz sürüm reddedilir", True)

# HTTP (https değil) reddedilir
updater.ALLOW_HTTP = False
try:
    updater.check(B + "/new.json")
    check("HTTP reddedilir", False)
except updater.UpdateError as ex:
    check("HTTP reddedilir", "HTTPS" in str(ex), str(ex))
try:
    updater.check("")
    check("boş adres: tanımlı değil", False)
except updater.UpdateError as ex:
    check("boş adres: tanımlı değil", "tanımlı değil" in str(ex))

updater.ALLOW_HTTP = True          # yalnız test: yerel sahte sunucu
info = updater.check(B + "/new.json", "1.0.0")
check("yeni sürüm bulunur", info and info.version == "9.0.0" and info.notes == "Yeni" and info.size == len(PAYLOAD))
check("aynı sürümde güncel", updater.check(B + "/same.json", "1.0.0") is None)
check("eski sürümde güncel", updater.check(B + "/old.json", "1.0.0") is None)
for p, ad in (("/nosha.json", "SHA-256 yoksa reddedilir"), ("/garbage", "bozuk yanıt reddedilir"), ("/yok", "404 reddedilir")):
    try:
        updater.check(B + p, "1.0.0")
        check(ad, False)
    except updater.UpdateError:
        check(ad, True)
g = updater.check(B + "/gh.json", "1.0.0")
check("GitHub yanıtı: digest", g and g.version == "v9.1.0" and g.sha256 == SHA and g.url.endswith("/setup.exe"))
g2 = updater.check(B + "/gh2.json", "1.0.0")
check("GitHub yanıtı: .sha256 varlığı", g2 and g2.sha256 == SHA)

# indirme
tmp = tempfile.mkdtemp(prefix="k3_")
prog = []
p = updater.download(info, lambda d, t: prog.append((d, t)), None, tmp)
check("indirme + SHA-256 doğru", os.path.isfile(p) and open(p, "rb").read() == PAYLOAD and prog and prog[-1][0] == len(PAYLOAD))
bad = updater.check(B + "/bad.json", "1.0.0")
try:
    updater.download(bad, None, None, tmp)
    check("bozuk SHA-256 reddedilir", False)
except updater.UpdateError:
    left = [f for f in os.listdir(tmp) if f != os.path.basename(p)]
    check("bozuk SHA-256 reddedilir, dosya kalmaz", not left, str(left))
n = {"i": 0}


def cancel_after():
    n["i"] += 1
    return n["i"] > 2


try:
    updater.download(info, None, cancel_after, os.path.join(tmp, "x") if os.makedirs(os.path.join(tmp, "x")) is None else tmp)
    check("indirme iptali", False)
except updater.Cancelled:
    check("indirme iptali, dosya kalmaz", not os.listdir(os.path.join(tmp, "x")))
updater.ALLOW_HTTP = False
try:
    updater.download(info, None, None, tmp)
    check("indirme HTTP reddedilir", False)
except updater.UpdateError:
    check("indirme HTTP reddedilir", True)

# kurulum çağrısı (sahte)
calls = []
cmd = updater.install(p, calls.append)
check("kurulum komutu", calls == [[p, "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"]] and cmd == calls[0])

# release aracı
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_release
check("make_release: GitHub adresinden taban", make_release.base_from_update_url(
    "https://api.github.com/repos/ben/depo/releases/latest", "1.0.1") == "https://github.com/ben/depo/releases/download/v1.0.1")
check("make_release: sha256_file", make_release.sha256_file(p) == SHA)

srv.shutdown()
print(f"OZET: {sum(ok)}/{len(ok)} gecti")
sys.exit(0 if all(ok) else 1)
