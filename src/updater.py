"""
updater.py
==========
Otomatik güncelleme çekirdeği (arayüzsüz, yalnız stdlib).

`check(url)` → `UpdateInfo` ya da `None` (güncel). `url` ya bir `latest.json`
(`{"version","url","sha256","notes","size"}`) ya da GitHub `releases/latest` API yanıtıdır.
`download` SHA-256'yı zorunlu doğrular (uyuşmazsa dosya silinir); yalnız HTTPS kabul edilir
(`ALLOW_HTTP` yalnız testlerde açılır). `install` kurucuyu sessiz kipte başlatır.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import appinfo

ALLOW_HTTP = False                       # yalnız testler (yerel sahte sunucu); üretimde HTTPS zorunlu
TIMEOUT = 15
MAX_JSON = 1_000_000                     # bildirim yanıtı üst sınırı
INSTALL_ARGS = ("/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS")


class UpdateError(Exception):
    pass


class Cancelled(UpdateError):
    """Kullanıcı indirmeyi iptal etti."""


@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str
    notes: str = ""
    size: int = 0


# -- sürüm karşılaştırma ----------------------------------------------------------
def parse_version(text: str) -> Tuple[int, ...]:
    """'v1.2.10' → (1, 2, 10). Sayısal olmayan sonek (-beta) yok sayılır."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", str(text or ""))
    if not m:
        raise UpdateError(f"Geçersiz sürüm: {text!r}")
    return tuple(int(p) for p in m.group(1).split("."))


def is_newer(candidate: str, current: str) -> bool:
    a, b = list(parse_version(candidate)), list(parse_version(current))
    n = max(len(a), len(b))
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return a > b


# -- ağ ---------------------------------------------------------------------------
def _check_url(url: str) -> str:
    u = urllib.parse.urlparse(str(url or ""))
    if u.scheme == "https" and u.netloc:
        return url
    if u.scheme == "http" and u.netloc and ALLOW_HTTP:
        return url
    raise UpdateError("Güncelleme adresi HTTPS olmalı.")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Yönlendirmeyle HTTPS'ten HTTP'ye düşülmesini engeller."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _ssl_context() -> ssl.SSLContext:
    """Sertifikaları Windows'un kendi güven deposuyla doğrular (truststore). Şirket ağlarında HTTPS denetimi yapan
    güvenlik duvarı sertifikası Windows'ta tanımlıdır; Python'un kendi listesi onu tanımaz ("unable to get local issuer
    certificate"). Doğrulama KAPATILMAZ; paket yoksa standart bağlama düşülür."""
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return ssl.create_default_context()


def _open(url: str):
    _check_url(url)
    opener = urllib.request.build_opener(_SafeRedirect, urllib.request.HTTPSHandler(context=_ssl_context()))
    req = urllib.request.Request(url, headers={
        "User-Agent": f"{appinfo.APP_NAME}/{appinfo.VERSION}", "Accept": "application/json, */*"})
    try:
        return opener.open(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as ex:
        raise UpdateError(f"Sunucu yanıtı: {ex.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as ex:
        raise UpdateError(f"Bağlanılamadı: {getattr(ex, 'reason', ex)}") from None


def _get_json(url: str) -> dict:
    with _open(url) as r:
        raw = r.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON:
        raise UpdateError("Güncelleme bildirimi çok büyük.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise UpdateError("Güncelleme bildirimi okunamadı.") from None
    if not isinstance(data, dict):
        raise UpdateError("Güncelleme bildirimi geçersiz.")
    return data


def _clean_sha(value) -> str:
    s = str(value or "").strip().lower()
    if s.startswith("sha256:"):
        s = s[7:]
    return s if re.fullmatch(r"[0-9a-f]{64}", s) else ""


def _from_github(data: dict) -> UpdateInfo:
    """GitHub `releases/latest` yanıtı: kurucu varlığı = '*Setup*.exe'; özet `digest` ya da '.sha256' varlığı."""
    assets: List[dict] = [a for a in data.get("assets") or [] if isinstance(a, dict)]
    setup = next((a for a in assets if re.search(r"setup.*\.exe$", str(a.get("name", "")), re.I)), None)
    if not setup:
        raise UpdateError("Sürümde kurucu dosyası yok.")
    sha = _clean_sha(setup.get("digest"))
    if not sha:
        side = next((a for a in assets if str(a.get("name", "")).lower() == str(setup["name"]).lower() + ".sha256"), None)
        if side:
            with _open(str(side.get("browser_download_url", ""))) as r:
                words = r.read(512).decode("utf-8", "ignore").split()
            sha = _clean_sha(words[0]) if words else ""
    return UpdateInfo(version=str(data.get("tag_name") or data.get("name") or ""),
                      url=str(setup.get("browser_download_url", "")), sha256=sha,
                      notes=str(data.get("body") or ""), size=int(setup.get("size") or 0))


def parse_info(data: dict) -> UpdateInfo:
    if "tag_name" in data or "assets" in data:
        info = _from_github(data)
    else:
        info = UpdateInfo(version=str(data.get("version") or ""), url=str(data.get("url") or ""),
                          sha256=_clean_sha(data.get("sha256")), notes=str(data.get("notes") or ""),
                          size=int(data.get("size") or 0))
    parse_version(info.version)                      # geçersizse UpdateError
    if not info.url:
        raise UpdateError("Güncelleme adresi eksik.")
    _check_url(info.url)
    if not info.sha256:
        raise UpdateError("Güncellemede SHA-256 özeti yok; güvenlik için reddedildi.")
    return info


def check(url: str, current: Optional[str] = None) -> Optional[UpdateInfo]:
    """Yeni sürüm varsa `UpdateInfo`, güncelse `None`. Hata → `UpdateError`."""
    if not url:
        raise UpdateError("Güncelleme adresi tanımlı değil.")
    info = parse_info(_get_json(url))
    return info if is_newer(info.version, current or appinfo.VERSION) else None


# -- indirme / kurma --------------------------------------------------------------
def download(info: UpdateInfo, progress: Optional[Callable[[int, int], None]] = None,
             cancelled: Optional[Callable[[], bool]] = None, dest_dir: Optional[str] = None) -> str:
    """Kurucuyu geçici klasöre indirir, SHA-256'yı doğrular, dosya yolunu döner."""
    _check_url(info.url)
    if not _clean_sha(info.sha256):
        raise UpdateError("SHA-256 özeti yok.")
    dest_dir = dest_dir or tempfile.mkdtemp(prefix="pdfannotator_update_")
    name = os.path.basename(urllib.parse.urlparse(info.url).path) or "kurulum.exe"
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    path = os.path.join(dest_dir, name)
    part = path + ".part"
    h = hashlib.sha256()
    done = 0
    try:
        with _open(info.url) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or info.size or 0)
            while True:
                if cancelled and cancelled():
                    raise Cancelled("İndirme iptal edildi.")
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if h.hexdigest() != _clean_sha(info.sha256):
            raise UpdateError("İndirilen dosyanın SHA-256 özeti uyuşmuyor; dosya silindi.")
        os.replace(part, path)
        return path
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise


def install_command(path: str) -> List[str]:
    return [path, *INSTALL_ARGS]


def install(path: str, launcher: Optional[Callable[[List[str]], object]] = None) -> List[str]:
    """Kurucuyu başlatır (sessiz, açık uygulamayı kapatıp yeniden başlatır). Çağıran uygulamayı kapatmalı."""
    cmd = install_command(path)
    (launcher or _launch)(cmd)
    return cmd


def _launch(cmd: List[str]) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(cmd, close_fds=True, creationflags=flags if sys.platform == "win32" else 0)
