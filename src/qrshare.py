"""QR ile telefon ↔ bilgisayar dosya aktarımı (arayüzsüz çekirdek).

Yerel ağda, rastgele anahtarlı (URL'nin içinde) küçük bir HTTP sunucusu açar.
Telefon tarayıcısı: dosya/fotoğraf seçer ya da kamerayla çeker (yükleme),
sunulan belgeleri indirir. Yalnızca PDF ve resim kabul edilir (uzantı + dosya
imzası denetlenir); dosya adı temizlenir, boyut/adet sınırlıdır. Sunucu
yalnızca verilen adrese bağlanır ve `stop()` ile hemen durur.

İsteğe bağlı 6 haneli PIN (`pin=`; internet tüneli gibi güvenilmeyen yollar için): PIN varsa telefon önce PIN sayfasını
görür; doğru PIN oturum çerezi verir, çerezsiz her istek reddedilir. Toplam 5 yanlış denemede sunucu kilitlenir
(doğru PIN de artık kabul edilmez; `unlock()`/`new_pin()` ile açılır). PIN yoksa davranış eskisi gibidir.
"""
from __future__ import annotations

import hmac
import io
import json
import os
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Optional
from urllib.parse import quote, unquote

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")
ALLOWED_EXTS = (".pdf",) + IMAGE_EXTS
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_FILES = 100
PIN_DIGITS = 6
ALLOWED_ACTIONS = ("scan", "photo", "pdf")   # X-Action: belge tara · fotoğraf olarak · PDF olarak; boş = eski davranış
MAX_PIN_ATTEMPTS = 5
COOKIE_NAME = "pdfsid"
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_SIGNATURES = {
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG",),
    ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".bmp": (b"BM",),
    ".tif": (b"II*\x00", b"MM\x00*"), ".tiff": (b"II*\x00", b"MM\x00*"),
    ".webp": (b"RIFF",),
}


def generate_pin() -> str:
    """Rastgele 6 haneli PIN (başında sıfır olabilir)."""
    return f"{secrets.randbelow(10 ** PIN_DIGITS):0{PIN_DIGITS}d}"


def valid_pin(pin: str) -> bool:
    return isinstance(pin, str) and len(pin) == PIN_DIGITS and pin.isascii() and pin.isdigit()


def sanitize_filename(name: str) -> str:
    """Yol ayırıcıları, denetim karakterlerini ve Windows'ta sorunlu adları temizler."""
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "", name).strip(" .")
    stem, ext = os.path.splitext(name)
    stem = stem.strip(" .")[:100] or "dosya"
    if stem.lower() in _RESERVED:
        stem = "_" + stem
    return stem + ext.lower()


def unique_path(folder: str, name: str) -> str:
    stem, ext = os.path.splitext(name)
    path = os.path.join(folder, name)
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return path


def lan_addresses() -> List[str]:
    """Yerel ağ IPv4 adresleri; yönlendirmede kullanılan (Wi‑Fi/Ethernet) ilk sırada."""
    found: List[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))                  # paket gönderilmez; yalnız yol seçilir
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out: List[str] = []
    for ip in found:
        if ip not in out and not ip.startswith(("127.", "169.254.", "0.")):
            out.append(ip)
    return out


def qr_png(url: str, scale: int = 8) -> bytes:
    """URL için siyah-beyaz QR (PNG baytları); tema ne olursa olsun okunabilir."""
    import segno
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=scale, border=3)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Telefon sayfası
# ---------------------------------------------------------------------------
PAGE = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>PDF Annotator</title>
<style>
:root{--bg:#f4f5f7;--card:#fff;--text:#16181d;--muted:#5a606a;--accent:#3e63f2;--ok:#1f9d57;--bad:#dc3a3a;--line:#e2e4e8}
@media(prefers-color-scheme:dark){:root{--bg:#141518;--card:#1b1c20;--text:#e9eaed;--muted:#a3a7b0;--accent:#5b7cfa;--ok:#3fb97a;--bad:#f05252;--line:#2a2c31}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px system-ui,Segoe UI,Roboto,sans-serif;padding:16px;max-width:560px;margin:auto}
h1{font-size:20px;margin:8px 0 16px}h2{font-size:15px;color:var(--muted);margin:0 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:14px}
.btn{display:block;width:100%;padding:16px;margin:0 0 10px;border:0;border-radius:12px;background:var(--accent);color:#fff;font-size:16px;font-weight:600;text-align:center}
.opt{display:block;padding:12px 6px;font-size:16px;min-height:44px}.opt input{width:20px;height:20px;vertical-align:middle;margin-right:8px;display:inline-block}
.btn.alt{background:transparent;color:var(--accent);border:2px solid var(--accent)}
input[type=file]{display:none}.hint{color:var(--muted);font-size:13px;margin:6px 0 0}
.row{padding:10px 0;border-top:1px solid var(--line);font-size:14px;word-break:break-all}.row:first-child{border-top:0}
.bar{height:6px;border-radius:3px;background:var(--line);margin-top:6px;overflow:hidden}.bar i{display:block;height:100%;width:0;background:var(--accent)}
.ok{color:var(--ok)}.bad{color:var(--bad)}a.dl{color:var(--accent);font-weight:600;text-decoration:none}
</style></head><body>
<h1>Bilgisayara gönder</h1>
<div class="card">
<h2>Ne yapılsın?</h2>
<label class="opt"><input type="radio" name="act" value="scan" checked> Belge tara (köşe düzeltmeli)</label>
<label class="opt"><input type="radio" name="act" value="photo"> Fotoğraf olarak gönder</label>
<label class="opt"><input type="radio" name="act" value="pdf"> PDF olarak gönder</label>
<label class="btn" for="pick">Dosya veya fotoğraf seç (birden çok olabilir)</label>
<input id="pick" type="file" multiple accept=".pdf,image/*,application/pdf">
<label class="btn alt" for="cam">Kamerayla çek</label>
<input id="cam" type="file" accept="image/*" capture="environment">
<p class="hint">PDF ve resim dosyaları kabul edilir (en çok __MAX__ MB). Dosyalar doğrudan bilgisayardaki uygulamada açılır.</p>
<div id="up"></div><p class="hint" id="sum"></p></div>
<div class="card" id="dlcard" style="display:none"><h2>Bilgisayardan indir</h2><div id="dl"></div></div>
<script>
const $=s=>document.querySelector(s);let queue=[],busy=false,sent=0;
function add(files){for(const f of files)queue.push(f);next()}
$('#pick').onchange=e=>{add(e.target.files);e.target.value=''};
$('#cam').onchange=e=>{add(e.target.files);e.target.value=''};
const MAXB=__MAX__*1048576;
function next(){if(busy||!queue.length)return;busy=true;const f=queue.shift();
const row=document.createElement('div');row.className='row';
const t=document.createElement('div');t.textContent=f.name+' ('+(f.size/1048576).toFixed(1)+' MB)';
const bar=document.createElement('div');bar.className='bar';const fill=document.createElement('i');bar.appendChild(fill);
const st=document.createElement('div');row.append(t,bar,st);$('#up').prepend(row);
if(f.size>MAXB){st.className='bad';st.textContent='✕ Dosya çok büyük (en çok __MAX__ MB)';busy=false;next();return}
const x=new XMLHttpRequest();x.open('POST','up');x.setRequestHeader('X-Filename',encodeURIComponent(f.name));x.setRequestHeader('X-Action',(document.querySelector('input[name=act]:checked')||{}).value||'photo');
x.upload.onprogress=e=>{if(e.lengthComputable)fill.style.width=(100*e.loaded/e.total)+'%'};
const done=(ok,msg)=>{if(ok){sent++;$('#sum').textContent='Gönderilen: '+sent+' dosya'}st.className=ok?'ok':'bad';st.textContent=msg;busy=false;next()};
x.onload=()=>{let r={};try{r=JSON.parse(x.responseText)}catch(_){}
if(x.status==200&&r.ok){fill.style.width='100%';done(true,'✓ Gönderildi')}else done(false,'✕ '+(r.error||('Hata '+x.status)))};
x.onerror=()=>done(false,'✕ Bağlantı hatası');x.send(f)}
async function poll(){try{const r=await fetch('list',{cache:'no-store'});const j=await r.json();const box=$('#dl');box.textContent='';
$('#dlcard').style.display=j.files.length?'block':'none';
for(const f of j.files){const d=document.createElement('div');d.className='row';const a=document.createElement('a');a.className='dl';a.href='d/'+f.i;a.textContent='⬇ '+f.name;a.setAttribute('download',f.name);
d.append(a,document.createTextNode(' ('+(f.size/1048576).toFixed(1)+' MB)'));box.appendChild(d)}}catch(_){}}
poll();setInterval(poll,4000);
</script></body></html>
"""


PIN_PAGE = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>PDF Annotator</title>
<style>
:root{--bg:#f4f5f7;--card:#fff;--text:#16181d;--muted:#5a606a;--accent:#3e63f2;--bad:#dc3a3a;--line:#e2e4e8}
@media(prefers-color-scheme:dark){:root{--bg:#141518;--card:#1b1c20;--text:#e9eaed;--muted:#a3a7b0;--accent:#5b7cfa;--bad:#f05252;--line:#2a2c31}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px system-ui,Segoe UI,Roboto,sans-serif;padding:16px;max-width:420px;margin:auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-top:40px}
h1{font-size:19px;margin:0 0 8px}p{color:var(--muted);font-size:14px;margin:0 0 14px}
input{width:100%;padding:14px;font-size:24px;letter-spacing:8px;text-align:center;border:1px solid var(--line);border-radius:10px;background:transparent;color:var(--text)}
button{display:block;width:100%;margin-top:12px;padding:14px;border:0;border-radius:12px;background:var(--accent);color:#fff;font-size:16px;font-weight:600}
#msg{margin-top:10px;font-size:14px;color:var(--bad);min-height:20px}
</style></head><body><div class="card">
<h1>PIN gerekli</h1><p>Bilgisayardaki PDF Annotator penceresinde görünen __DIGITS__ haneli PIN'i girin.</p>
<input id="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="__DIGITS__" placeholder="______">
<button id="go">Devam</button><div id="msg"></div></div>
<script>
const $=s=>document.querySelector(s);
async function go(){const v=$('#pin').value.trim();if(v.length!=__DIGITS__){$('#msg').textContent='__DIGITS__ haneli PIN girin.';return}
try{const r=await fetch('auth',{method:'POST',body:v,cache:'no-store'});let j={};try{j=await r.json()}catch(_){}
if(r.ok&&j.ok){location.href='./'}else{$('#msg').textContent=j.error||('Hata '+r.status);$('#pin').value=''}}catch(_){$('#msg').textContent='Bağlantı hatası'}}
$('#go').onclick=go;$('#pin').onkeydown=e=>{if(e.key=='Enter')go()};
</script></body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 30
    server_version = "PDFAnnotatorShare"
    sys_version = ""

    def log_message(self, *args):                               # konsola yazma
        pass

    # -- yardımcılar ---------------------------------------------------------
    @property
    def share(self) -> "ShareServer":
        return self.server.share                                # type: ignore[attr-defined]

    def _send(self, code: int, body: bytes = b"", ctype: str = "text/plain; charset=utf-8",
              extra: Optional[Dict[str, str]] = None, close: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj: dict, close: bool = False):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", close=close)

    def _route(self) -> Optional[List[str]]:
        """Anahtar doğruysa anahtardan sonraki yol parçalarını verir; değilse 404 yollar."""
        path = self.path.split("?", 1)[0]
        parts = path.split("/")
        if len(parts) < 2 or not hmac.compare_digest(parts[1].encode(), self.share.token.encode()):
            self._send(404, b"404", close=True)
            return None
        if not self.share.pin_required:
            self.share.touch()
        return parts[2:]

    def _session_ok(self) -> bool:
        """PIN gerekmiyorsa her zaman doğru; gerekiyorsa geçerli oturum çerezi aranır (geçerliyse etkinlik sayılır)."""
        sh = self.share
        if not sh.pin_required:
            return True
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE_NAME and sh.session_valid(v):
                sh.touch()
                return True
        return False

    def _auth(self):
        """POST /<anahtar>/auth: gövde = PIN. Doğruysa oturum çerezi verir."""
        sh = self.share
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if length < 0 or length > 64:
            return self._json(400, {"ok": False, "error": "Geçersiz istek."}, close=True)
        body = self.rfile.read(length).decode("utf-8", "ignore").strip() if length else ""
        if not sh.pin_required:
            return self._json(200, {"ok": True})
        res = sh.check_pin(body)
        if res == "ok":
            sid = sh.new_session()
            cookie = f"{COOKIE_NAME}={sid}; Path=/{sh.token}/; HttpOnly; SameSite=Strict"
            return self._send(200, b'{"ok": true}', "application/json; charset=utf-8", extra={"Set-Cookie": cookie})
        if res == "locked":
            return self._json(423, {"ok": False, "locked": True,
                                    "error": "Çok fazla yanlış deneme: kilitlendi. Bilgisayardaki uygulamadan yeni PIN oluşturun."},
                              close=True)
        left = sh.attempts_left
        return self._json(403, {"ok": False, "left": left, "error": f"Yanlış PIN ({left} deneme hakkı kaldı)."})

    # -- GET -----------------------------------------------------------------
    def do_GET(self):
        rest = self._route()
        if rest is None:
            return
        if rest == []:                                           # /<anahtar> → sonuna / ekle (göreli bağlantılar için)
            self._send(301, b"", extra={"Location": f"/{self.share.token}/"})
        elif not self._session_ok():
            if rest == [""]:                                     # PIN sayfası (dosya/liste yok)
                self._send(200, PIN_PAGE.replace("__DIGITS__", str(PIN_DIGITS)).encode("utf-8"), "text/html; charset=utf-8",
                           extra={"Content-Security-Policy": "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'"})
            else:
                self._json(401, {"ok": False, "auth": True, "error": "PIN gerekli."}, close=True)
        elif rest == [""]:
            page = PAGE.replace("__MAX__", str(self.share.max_bytes // (1024 * 1024)))
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8", extra={
                "Content-Security-Policy": "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'"})
        elif rest == ["list"]:
            self._json(200, {"files": self.share.listing()})
        elif len(rest) == 2 and rest[0] == "d" and rest[1].isdigit():
            self._download(int(rest[1]))
        else:
            self._send(404, b"404")

    do_HEAD = do_GET

    def _download(self, index: int):
        item = self.share.offered(index)
        if item is None or not os.path.isfile(item["path"]):
            self._send(404, b"404")
            return
        size = os.path.getsize(item["path"])
        ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", item["name"]) or "dosya"
        self.send_response(200)
        self.send_header("Content-Type", item["type"])
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition",
                         f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(item['name'])}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(item["path"], "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.share.touch()

    def _drain(self, length: int, limit: int = 16 * 1024 * 1024):
        """Reddedilen isteğin gövdesini (en çok `limit` bayt) okuyup atar."""
        if length > limit:
            return
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                return
            remaining -= len(chunk)

    # -- POST (yükleme) --------------------------------------------------------
    def do_POST(self):
        rest = self._route()
        if rest is None:
            return
        if rest == ["auth"]:
            return self._auth()
        if rest != ["up"]:
            self._send(404, b"404", close=True)
            return
        if not self._session_ok():
            return self._json(401, {"ok": False, "auth": True, "error": "PIN gerekli."}, close=True)
        sh = self.share
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if length < 0:
            return self._json(411, {"ok": False, "error": "İçerik uzunluğu bilinmiyor."}, close=True)
        if length == 0:
            return self._json(400, {"ok": False, "error": "Dosya boş."}, close=True)

        def reject(code: int, msg: str):
            self._drain(length)                      # küçük gövdeyi oku: tarayıcı yanıtı bağlantı kopmadan görsün
            self._json(code, {"ok": False, "error": msg}, close=True)

        if length > sh.max_bytes:
            return reject(413, f"Dosya çok büyük (en çok {sh.max_bytes // (1024 * 1024)} MB).")
        if sh.received_count >= MAX_FILES or sh.received_bytes + length > MAX_TOTAL_BYTES:
            return reject(429, "Bu oturum için dosya sınırına ulaşıldı.")
        action = (self.headers.get("X-Action", "") or "").strip().lower()
        if action and action not in ALLOWED_ACTIONS:
            return reject(400, "Bilinmeyen işlem.")
        name = sanitize_filename(unquote(self.headers.get("X-Filename", "")))
        ext = os.path.splitext(name)[1]
        if ext not in ALLOWED_EXTS:
            return reject(415, "Yalnızca PDF ve resim dosyaları kabul edilir.")
        os.makedirs(sh.receive_dir, exist_ok=True)
        dest = unique_path(sh.receive_dir, name)
        part = dest + ".part"
        remaining, head = length, b""
        try:
            with open(part, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    if len(head) < 16:
                        head += chunk[:16 - len(head)]
                    f.write(chunk)
                    remaining -= len(chunk)
                    sh.touch()
            if remaining:
                raise ValueError("Yükleme yarım kaldı.")
            if not head.startswith(_SIGNATURES[ext]):
                raise ValueError("Dosya içeriği uzantısıyla uyuşmuyor.")
            os.replace(part, dest)
        except Exception as ex:
            try:
                os.remove(part)
            except OSError:
                pass
            return self._json(400, {"ok": False, "error": str(ex) or "Yükleme başarısız."}, close=True)
        sh.received_count += 1
        sh.received_bytes += length
        sh.actions[dest] = action
        self._json(200, {"ok": True, "name": os.path.basename(dest)})
        if sh.on_received:
            try:
                sh.on_received(dest)
            except Exception:
                pass


class ShareServer:
    """`start()` ile açılır, `stop()` ile kapanır. `host`: bağlanılacak yerel adres."""

    def __init__(self, receive_dir: str, on_received: Optional[Callable[[str], None]] = None,
                 host: str = "127.0.0.1", port: int = 0, max_bytes: int = MAX_FILE_BYTES,
                 token: Optional[str] = None, pin: Optional[str] = None):
        if pin is not None and not valid_pin(pin):
            raise ValueError(f"PIN {PIN_DIGITS} haneli rakam olmalı")
        self.receive_dir = receive_dir
        self.on_received = on_received
        self.host = host
        self.port = port
        self.max_bytes = max_bytes
        self.token = token or secrets.token_urlsafe(16)
        self.pin: Optional[str] = pin                    # None: PIN yok (eski davranış)
        self.failed_attempts = 0
        self._sessions: set = set()
        self.received_count = 0
        self.actions: dict = {}                          # kaydedilen yol → X-Action ("" = belirtilmedi)
        self.received_bytes = 0
        self._offers: List[dict] = []
        self._lock = threading.Lock()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._last = time.monotonic()

    # -- yaşam döngüsü -------------------------------------------------------
    def start(self) -> "ShareServer":
        httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        httpd.daemon_threads = True
        httpd.share = self                                      # type: ignore[attr-defined]
        self._httpd = httpd
        self.port = httpd.server_address[1]
        self._thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="qrshare", daemon=True)
        self._thread.start()
        self.touch()
        return self

    def stop(self):
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/{self.token}/"

    def touch(self):
        self._last = time.monotonic()

    # -- PIN ---------------------------------------------------------------------
    @property
    def pin_required(self) -> bool:
        return self.pin is not None

    @property
    def locked(self) -> bool:
        return self.pin_required and self.failed_attempts >= MAX_PIN_ATTEMPTS

    @property
    def attempts_left(self) -> int:
        return max(0, MAX_PIN_ATTEMPTS - self.failed_attempts)

    def check_pin(self, candidate: str) -> str:
        """"ok" | "bad" | "locked". Kilitliyken doğru PIN de kabul edilmez; yanlış deneme sayacı tüm istemciler için ortaktır
        (tünelde hepsi aynı yerel adresten gelir). Karşılaştırma sabit sürelidir."""
        with self._lock:
            if self.locked:
                return "locked"
            if self.pin is not None and valid_pin(candidate) and hmac.compare_digest(candidate.encode(), self.pin.encode()):
                self.failed_attempts = 0
                return "ok"
            self.failed_attempts += 1
            return "locked" if self.locked else "bad"

    def new_session(self) -> str:
        sid = secrets.token_urlsafe(24)
        with self._lock:
            self._sessions.add(sid)
        return sid

    def session_valid(self, sid: str) -> bool:
        with self._lock:
            return any(hmac.compare_digest(sid.encode(), x.encode()) for x in self._sessions)

    def set_pin(self, pin: Optional[str]) -> None:
        """PIN'i değiştirir (None: kaldırır); kilit ve açık oturumlar sıfırlanır."""
        if pin is not None and not valid_pin(pin):
            raise ValueError(f"PIN {PIN_DIGITS} haneli rakam olmalı")
        with self._lock:
            self.pin = pin
            self.failed_attempts = 0
            self._sessions.clear()

    def new_pin(self) -> str:
        pin = generate_pin()
        self.set_pin(pin)
        return pin

    def unlock(self) -> None:
        """Kilidi açar (yanlış deneme sayacını sıfırlar); PIN aynı kalır."""
        with self._lock:
            self.failed_attempts = 0

    def idle_seconds(self) -> float:
        return time.monotonic() - self._last

    # -- telefona sunulan dosyalar ---------------------------------------------
    def offer(self, path: str, name: Optional[str] = None) -> int:
        name = sanitize_filename(name or os.path.basename(path))
        ext = os.path.splitext(name)[1]
        ctype = "application/pdf" if ext == ".pdf" else "application/octet-stream"
        with self._lock:
            for i, it in enumerate(self._offers):
                if it["name"] == name:                           # aynı ad: güncel hâliyle değiştir
                    self._offers[i] = {"path": path, "name": name, "type": ctype}
                    return i
            self._offers.append({"path": path, "name": name, "type": ctype})
            return len(self._offers) - 1

    def clear_offers(self):
        with self._lock:
            self._offers.clear()

    def offered(self, index: int) -> Optional[dict]:
        with self._lock:
            return self._offers[index] if 0 <= index < len(self._offers) else None

    def listing(self) -> List[dict]:
        with self._lock:
            return [{"i": i, "name": it["name"],
                     "size": os.path.getsize(it["path"]) if os.path.isfile(it["path"]) else 0}
                    for i, it in enumerate(self._offers)]
