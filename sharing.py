"""
sharing.py
==========
Paylaşım yardımcıları (arayüzsüz çekirdek; uygulama hiçbir üçüncü taraf servisle kendisi konuşmaz):

* `cloud_folders()` — bilgisayarda yerel olarak senkronlanan OneDrive / Google Drive / Dropbox klasörlerini bulur
  (senkronu o uygulamanın kendisi yapar; biz yalnızca dosyayı o klasöre kopyalarız).
* `compose_email()` — Outlook varsa dosya ekli yeni ileti açar (`outlook.exe /a`), yoksa dosyanın klasörünü gösterir
  ve boş bir `mailto:` iletisi açar (ek, mailto ile verilemez; kullanıcı dosyayı sürükler).
* `reveal()` — dosyanın konumunu Gezgin'de açar.

Dış etkileşimler (süreç başlatma, URL/klasör açma, ortam, kayıt defteri) parametre olarak verilebilir: testler gerçek
Outlook/posta istemcisi/Gezgin açmadan sahte çağrılarla sınanır. Varsayılanlar `subprocess` ve `QDesktopServices`'tir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence
from urllib.parse import quote


@dataclass(frozen=True)
class CloudFolder:
    name: str            # "OneDrive", "Google Drive", "Dropbox"
    path: str


def _isdir(p: Optional[str]) -> bool:
    return bool(p) and os.path.isdir(p)


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _windows_drive_letters() -> List[str]:
    return [f"{c}:\\" for c in "DEFGHIJKLMNOPQRSTUVWXYZ"] if sys.platform == "win32" else []


def cloud_folders(env: Optional[Dict[str, str]] = None, home: Optional[str] = None,
                  drives: Optional[Sequence[str]] = None) -> List[CloudFolder]:
    """Var olan yerel bulut klasörleri (tekrarsız, OneDrive → Google Drive → Dropbox sırasıyla).
    `env`/`home`/`drives` verilirse gerçek ortam yerine onlar kullanılır (testler)."""
    env = os.environ if env is None else env
    home = home or os.path.expanduser("~")
    drives = _windows_drive_letters() if drives is None else list(drives)
    found: List[CloudFolder] = []
    seen = set()

    def add(name: str, path: Optional[str]):
        if _isdir(path) and _norm(path) not in seen:
            seen.add(_norm(path))
            found.append(CloudFolder(name, os.path.abspath(path)))

    # OneDrive: ortam değişkenleri (kişisel/iş), sonra ev klasöründeki "OneDrive*"
    add("OneDrive", env.get("OneDriveConsumer"))
    add("OneDrive (iş)", env.get("OneDriveCommercial"))
    add("OneDrive", env.get("OneDrive"))
    try:
        for n in sorted(os.listdir(home)):
            if n.lower().startswith("onedrive"):
                add("OneDrive" if n.lower() == "onedrive" else f"OneDrive ({n[len('OneDrive'):].strip(' -') or n})",
                    os.path.join(home, n))
    except OSError:
        pass
    # Google Drive (Drive for desktop): "Google Drive", "My Drive", sürücü harfi altında "My Drive"
    for cand in (os.path.join(home, "Google Drive", "My Drive"), os.path.join(home, "Google Drive"),
                 os.path.join(home, "My Drive")):
        add("Google Drive", cand)
    for d in drives:
        add("Google Drive", os.path.join(d, "My Drive"))
    # Dropbox: ev klasörü + info.json (özel konum / iş hesabı)
    add("Dropbox", os.path.join(home, "Dropbox"))
    for base in (env.get("LOCALAPPDATA"), env.get("APPDATA")):
        if not base:
            continue
        info = os.path.join(base, "Dropbox", "info.json")
        try:
            with open(info, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        for key, label in (("personal", "Dropbox"), ("business", "Dropbox (iş)")):
            entry = data.get(key) if isinstance(data, dict) else None
            if isinstance(entry, dict):
                add(label, entry.get("path"))
    return found


# ---------------------------------------------------------------------------
# varsayılan dış eylemler (Qt / subprocess); testlerde sahtesi verilir
# ---------------------------------------------------------------------------
def _qt_open_url(url: str) -> bool:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    return QDesktopServices.openUrl(QUrl(url))


def _qt_open_folder(path: str) -> bool:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def _popen(cmd: List[str]):
    return subprocess.Popen(cmd)


def find_outlook(reg_lookup: Optional[Callable[[], Optional[str]]] = None) -> Optional[str]:
    """Kurulu Outlook (klasik) yürütülebilir dosyasının yolu; yoksa None. Windows kayıt defteri "App Paths" kullanılır."""
    if reg_lookup is not None:
        p = reg_lookup()
        return p if p and os.path.isfile(p) else None
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE") as k:
                p = winreg.QueryValueEx(k, "")[0]
                if p and os.path.isfile(p):
                    return p
        except OSError:
            continue
    return None


def mailto_url(subject: str = "", body: str = "") -> str:
    q = []
    if subject:
        q.append("subject=" + quote(subject))
    if body:
        q.append("body=" + quote(body))
    return "mailto:" + ("?" + "&".join(q) if q else "")


def compose_email(path: str, subject: str = "", body: str = "", *, outlook: Optional[str] = None,
                  launch: Optional[Callable[[List[str]], object]] = None,
                  open_url: Optional[Callable[[str], object]] = None,
                  open_folder: Optional[Callable[[str], object]] = None) -> str:
    """Dosyayı e-postayla göndermeye hazırlar; "outlook" ya da "mailto" döndürür.
    Outlook (`outlook` yolu verilmişse ya da `find_outlook()` bulursa): dosya ekli yeni ileti.
    Yoksa: dosyanın klasörü açılır (dosyayı iletiye sürüklemek için) + boş `mailto:` iletisi."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    exe = outlook if outlook is not None else find_outlook()
    if exe:
        (launch or _popen)([exe, "/a", os.path.abspath(path)])
        return "outlook"
    (open_folder or _qt_open_folder)(os.path.dirname(os.path.abspath(path)))
    (open_url or _qt_open_url)(mailto_url(subject, body or "Ekteki dosyayı bu iletiye ekleyin: " + os.path.basename(path)))
    return "mailto"


def reveal(path: str, *, launch: Optional[Callable[[List[str]], object]] = None,
           open_folder: Optional[Callable[[str], object]] = None, select: bool = True) -> str:
    """Dosyanın konumunu açar: Windows'ta Gezgin dosyayı seçili gösterir; olmazsa klasörü açar.
    "select" | "folder" döndürür. Dosya yoksa `FileNotFoundError`."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    ap = os.path.abspath(path)
    if select and sys.platform == "win32" and os.path.isfile(ap):
        (launch or _popen)(["explorer", "/select,", os.path.normpath(ap)])
        return "select"
    (open_folder or _qt_open_folder)(ap if os.path.isdir(ap) else os.path.dirname(ap))
    return "folder"
