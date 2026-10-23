"""
workspace.py
============
Çalışma klasörü ve otomatik kurtarma çekirdeği (arayüzsüz; ayarlar `QSettings` benzeri bir nesnede).

Çalışma klasörü (varsayılan `Belgeler\\PDF Annotator`) altında alt klasörler: Gelen (QR), Taramalar,
Donusturulenler (Word/Excel), Projeler, Yedekler (kurtarma taslakları), IsAkisi. Her çıktı türü için
"bu klasöre kaydet" tercihi vardır (`use`/`set_use`/`out_dir`); kapalıysa diyaloglar eski varsayılanına döner.

Ortam değişkeni `PDF_ANNOTATOR_WORKSPACE` kökü ayardan bağımsız olarak belirler (testler / taşınabilir kullanım).
Otomatik kurtarma: değişmiş oturumlar `Yedekler\\kurtarma\\<id>.pdf` + `<id>.json` taslağı olarak yazılır;
normal kaydetme/kapanış taslağı siler, çökme sonrası açılışta `list_drafts()` ile bulunur.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

ENV_ROOT = "PDF_ANNOTATOR_WORKSPACE"
APP_DIR = "PDF Annotator"
OLD_INBOX_NAME = "PDF Annotator Gelen"

SUBS = ("Gelen", "Taramalar", "Donusturulenler", "Projeler", "Yedekler", "IsAkisi")
# çıktı türü -> (alt klasör, tercih penceresindeki etiket)
KINDS: Dict[str, Tuple[str, str]] = {
    "inbox": ("Gelen", "QR ile telefondan gelen dosyalar"),
    "scans": ("Taramalar", "Tarama PDF'leri"),
    "converted": ("Donusturulenler", "Word / Excel dönüşümleri"),
    "workflow": ("IsAkisi", "İş akışı varsayılan hedefi"),
    "projects": ("Projeler", "Proje (JSON) dosyaları"),
}
RECOVERY_SUB = "kurtarma"
MIN_MINUTES, MAX_MINUTES, DEFAULT_MINUTES = 1, 10, 3

_settings: Any = None


# ---------------------------------------------------------------------------
# ayar erişimi
# ---------------------------------------------------------------------------
def configure(settings) -> None:
    """Ayar deposunu bağlar (`value`/`setValue`). MainWindow kendi `settings` nesnesini verir; testler geçici bir tane."""
    global _settings
    _settings = settings


def _store():
    global _settings
    if _settings is None:
        from PySide6.QtCore import QSettings
        _settings = QSettings("PDFAnnotator", "PDFAnnotator")
    return _settings


def _get(key: str, default: Any = "") -> Any:
    v = _store().value(key, default)
    return default if v is None else v


def _bool(key: str, default: bool) -> bool:
    v = _get(key, default)
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "")
    return bool(v)


def _int(key: str, default: int) -> int:
    try:
        return int(_get(key, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# kök ve alt klasörler
# ---------------------------------------------------------------------------
def documents_dir() -> str:
    try:
        from PySide6.QtCore import QStandardPaths
        d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    except Exception:
        d = ""
    return d or os.path.join(os.path.expanduser("~"), "Documents")


def default_root() -> str:
    return os.path.join(documents_dir(), APP_DIR)


def root() -> str:
    """Çalışma klasörü: ortam değişkeni > ayar > varsayılan. Oluşturmaz."""
    env = os.environ.get(ENV_ROOT, "").strip()
    if env:
        return os.path.abspath(env)
    saved = str(_get("workspace/root", "") or "").strip()
    return os.path.abspath(saved) if saved else default_root()


def is_custom_root() -> bool:
    return bool(os.environ.get(ENV_ROOT, "").strip() or str(_get("workspace/root", "") or "").strip())


def set_root(path: str) -> str:
    """Kökü ayara yazar ve oluşturur; yazılan yolu döndürür."""
    path = os.path.abspath(path)
    os.makedirs(path, exist_ok=True)
    _store().setValue("workspace/root", path)
    return path


def reset_root() -> str:
    _store().setValue("workspace/root", "")
    return root()


def sub(name: str) -> str:
    """Alt klasörü (yoksa oluşturarak) döndürür. `name`: `SUBS` içinden."""
    if name not in SUBS:
        raise ValueError(f"Bilinmeyen çalışma alt klasörü: {name!r}")
    p = os.path.join(root(), name)
    os.makedirs(p, exist_ok=True)
    return p


def ensure_all() -> List[str]:
    return [sub(n) for n in SUBS]


def use(kind: str) -> bool:
    """Bu çıktı türü çalışma klasörüne mi kaydedilsin? (varsayılan: evet)"""
    if kind not in KINDS:
        raise ValueError(f"Bilinmeyen çıktı türü: {kind!r}")
    return _bool(f"workspace/use_{kind}", True)


def set_use(kind: str, on: bool) -> None:
    if kind not in KINDS:
        raise ValueError(f"Bilinmeyen çıktı türü: {kind!r}")
    _store().setValue(f"workspace/use_{kind}", bool(on))


def out_dir(kind: str) -> Optional[str]:
    """Tercih açıksa türün alt klasörü (oluşturulur), kapalıysa None (diyalog eski varsayılanını kullanır)."""
    return sub(KINDS[kind][0]) if use(kind) else None


def join_out(kind: str, name: str, fallback_dir: str = "") -> str:
    """`name` için varsayılan tam yol: tercih açıksa çalışma alt klasöründe, değilse `fallback_dir`'de (boşsa yalnız ad)."""
    d = out_dir(kind) or fallback_dir
    return os.path.join(d, name) if d else name


# ---------------------------------------------------------------------------
# son klasör
# ---------------------------------------------------------------------------
def remember_last() -> bool:
    return _bool("workspace/remember_last", True)


def set_remember_last(on: bool) -> None:
    _store().setValue("workspace/remember_last", bool(on))
    if not on:
        _store().setValue("workspace/last_dir", "")


def last_dir() -> str:
    """Hatırlanan son klasör (tercih kapalıysa ya da klasör yoksa boş)."""
    if not remember_last():
        return ""
    d = str(_get("workspace/last_dir", "") or "")
    return d if d and os.path.isdir(d) else ""


def remember(path: str) -> None:
    """Dosya ya da klasör yolunun klasörünü 'son klasör' olarak saklar (tercih açıksa)."""
    if not remember_last() or not path:
        return
    d = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
    if os.path.isdir(d):
        _store().setValue("workspace/last_dir", d)


# ---------------------------------------------------------------------------
# eski "PDF Annotator Gelen" klasörü
# ---------------------------------------------------------------------------
def old_inbox() -> str:
    return os.path.join(documents_dir(), OLD_INBOX_NAME)


def _files_in(path: str) -> List[str]:
    try:
        return sorted(f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f)))
    except OSError:
        return []


def migration_pending(old: Optional[str] = None) -> bool:
    """Eski gelen klasörü dosya içeriyor, yeni konumdan farklı ve kullanıcı daha önce 'hayır' demedi."""
    old = old or old_inbox()
    if _bool("workspace/migration_declined", False):
        return False
    if os.path.abspath(old) == os.path.abspath(os.path.join(root(), "Gelen")):
        return False
    return os.path.isdir(old) and bool(_files_in(old))


def decline_migration() -> None:
    _store().setValue("workspace/migration_declined", True)


def migrate_old_inbox(old: Optional[str] = None) -> Tuple[int, List[str]]:
    """Eski klasördeki dosyaları `Gelen`'e TAŞIR (aynı ad varsa "(2)" eklenir). Hiçbir şey silinmez; eski klasör
    yalnızca boşaldıysa kaldırılır. (taşınan sayı, hata iletileri) döner."""
    old = old or old_inbox()
    dest = sub("Gelen")
    moved, errors = 0, []
    for name in _files_in(old):
        src = os.path.join(old, name)
        stem, ext = os.path.splitext(name)
        target, n = os.path.join(dest, name), 2
        while os.path.exists(target):
            target = os.path.join(dest, f"{stem} ({n}){ext}")
            n += 1
        try:
            shutil.move(src, target)
            moved += 1
        except OSError as ex:
            errors.append(f"{name}: {ex}")
    try:
        os.rmdir(old)                      # yalnızca boşsa
    except OSError:
        pass
    return moved, errors


# ---------------------------------------------------------------------------
# otomatik kurtarma
# ---------------------------------------------------------------------------
def reduce_motion() -> bool:
    """Açıksa yardım önizlemeleri animasyonsuz (durağan kare) gösterilir."""
    return _bool("ui/reduce_motion", False)


def set_reduce_motion(on: bool) -> None:
    _store().setValue("ui/reduce_motion", bool(on))


def auto_ocr_enabled() -> bool:
    """Açılan belgelerde metni (taranmışsa OCR ile) arka planda hazırla: Metin Seç aracı anında çalışır."""
    return _bool("ocr/auto", True)


def set_auto_ocr_enabled(on: bool) -> None:
    _store().setValue("ocr/auto", bool(on))


def autosave_overwrite() -> bool:
    """Açıksa değişen PDF'ler belirli aralıkla özgün dosyanın ÜZERİNE yazılır (varsayılan kapalı)."""
    return _bool("autosave/overwrite", False)


def set_autosave_overwrite(on: bool) -> None:
    _store().setValue("autosave/overwrite", bool(on))


def recovery_enabled() -> bool:
    return _bool("recovery/enabled", True)


def set_recovery_enabled(on: bool) -> None:
    _store().setValue("recovery/enabled", bool(on))


def recovery_minutes() -> int:
    return max(MIN_MINUTES, min(MAX_MINUTES, _int("recovery/minutes", DEFAULT_MINUTES)))


def set_recovery_minutes(m: int) -> int:
    m = max(MIN_MINUTES, min(MAX_MINUTES, int(m)))
    _store().setValue("recovery/minutes", m)
    return m


def recovery_dir() -> str:
    p = os.path.join(sub("Yedekler"), RECOVERY_SUB)
    os.makedirs(p, exist_ok=True)
    return p


@dataclass
class Draft:
    id: str
    title: str
    source: str            # özgün dosya yolu ("" olabilir)
    pdf_path: str
    json_path: str
    saved_at: float        # taslağın yazıldığı an (epoch)
    pages: int = 0

    def when(self) -> str:
        return time.strftime("%d.%m.%Y %H:%M", time.localtime(self.saved_at))


def _atomic_write(path: str, data: bytes) -> None:
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _safe_id(draft_id: str) -> str:
    if not draft_id or any(c in draft_id for c in "\\/:*?\"<>|") or draft_id.startswith("."):
        raise ValueError(f"Geçersiz taslak kimliği: {draft_id!r}")
    return draft_id


def write_draft(draft_id: str, pdf_bytes: bytes, project: dict, title: str = "", pages: int = 0) -> Draft:
    """Taslağı yazar (önce PDF, sonra JSON: JSON olan taslak eksiksizdir). `project`: `to_project_dict()` çıktısı."""
    draft_id = _safe_id(draft_id)
    d = recovery_dir()
    pdf_path, json_path = os.path.join(d, draft_id + ".pdf"), os.path.join(d, draft_id + ".json")
    now = time.time()
    meta = {"version": 1, "id": draft_id, "title": title or str(project.get("title", "")),
            "source": str(project.get("source_pdf", "") or ""), "saved_at": now, "pages": pages,
            "project": project}
    _atomic_write(pdf_path, pdf_bytes)
    _atomic_write(json_path, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    return Draft(draft_id, meta["title"], meta["source"], pdf_path, json_path, now, pages)


def list_drafts() -> List[Draft]:
    """Eksiksiz (PDF + JSON) taslaklar, yeniden eskiye. Bozuk/yarım olanlar atlanır."""
    out: List[Draft] = []
    d = recovery_dir()
    for f in os.listdir(d):
        if not f.endswith(".json"):
            continue
        did = f[:-5]
        jp, pp = os.path.join(d, f), os.path.join(d, did + ".pdf")
        if not os.path.isfile(pp):
            continue
        try:
            with open(jp, "r", encoding="utf-8") as fh:
                m = json.load(fh)
            out.append(Draft(did, str(m.get("title", did)), str(m.get("source", "")), pp, jp,
                             float(m.get("saved_at", os.path.getmtime(jp))), int(m.get("pages", 0))))
        except (OSError, ValueError, TypeError):
            continue
    return sorted(out, key=lambda x: x.saved_at, reverse=True)


def read_draft(draft_id: str) -> Tuple[bytes, dict]:
    """(PDF baytları, proje sözlüğü). Taslak yoksa/bozuksa `FileNotFoundError`/`ValueError`."""
    draft_id = _safe_id(draft_id)
    d = recovery_dir()
    with open(os.path.join(d, draft_id + ".pdf"), "rb") as f:
        data = f.read()
    with open(os.path.join(d, draft_id + ".json"), "r", encoding="utf-8") as f:
        meta = json.load(f)
    proj = meta.get("project")
    if not isinstance(proj, dict):
        raise ValueError("Taslak bozuk")
    return data, proj


def delete_draft(draft_id: str) -> bool:
    """Taslağı (varsa) siler; sildiyse True."""
    try:
        draft_id = _safe_id(draft_id)
    except ValueError:
        return False
    d = recovery_dir()
    gone = False
    for ext in (".json", ".pdf", ".pdf.part", ".json.part"):
        p = os.path.join(d, draft_id + ext)
        if os.path.exists(p):
            try:
                os.remove(p)
                gone = True
            except OSError:
                pass
    return gone


def clear_drafts() -> int:
    n = 0
    for dr in list_drafts():
        n += bool(delete_draft(dr.id))
    return n
