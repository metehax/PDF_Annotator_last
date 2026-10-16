"""
workflow.py
===========
Görsel iş akışı çekirdeği (arayüzsüz): adım zinciri, şablon kütüphanesi, çalıştırıcı, rapor.

Bir iş akışı sıralı adımlardır; her adım mevcut motoru yeniden kullanır:
  ocr (ocr.py) · rotate · watermark (pdf_engine) · headfoot (headfoot.py) · kvkk (pii.py)
  compress / password (docsec.py) · save (çıktı adı/yeri)

Sayfaları değiştiren adımlar yazıldığı sırayla çalışır. "Kaydederken uygulanan" adımlar
(compress, password, save) sırası ne olursa olsun en sonda, tek kayıtta uygulanır.
Çıktı her zaman geçici dosyaya yazılıp atomik olarak yerine konur; iptalde yarım dosya kalmaz.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import pymupdf as fitz

import docsec
import ocr
import pii

VERSION = 1
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")
DEFAULT_SUFFIX = "_islendi"


class Cancelled(Exception):
    """Kullanıcı durdurdu."""


class StepError(Exception):
    """Adım kullanıcıya gösterilecek bir nedenle çalışamadı."""


# ---------------------------------------------------------------------------
# Adım ayar şeması (arayüz bu şemadan form üretir)
# ---------------------------------------------------------------------------
@dataclass
class Param:
    key: str
    label: str
    kind: str                       # text|password|int|float|bool|choice|multi|color|folder|file
    default: Any = ""
    choices: Optional[List[Tuple[Any, str]]] = None   # choice/multi: (değer, etiket)
    minv: float = 0
    maxv: float = 100
    hint: str = ""
    show_if: Optional[Tuple[str, Any]] = None         # (başka_param, değer) eşleşirse görünür

    def coerce(self, v: Any) -> Any:
        """Geçersiz/eksik değeri sessizce varsayılana indirir (bozuk şablon uygulamayı düşürmez)."""
        try:
            k = self.kind
            if k == "bool":
                return bool(v)
            if k == "int":
                return int(max(self.minv, min(self.maxv, int(v))))
            if k == "float":
                return float(max(self.minv, min(self.maxv, float(v))))
            if k in ("text", "password", "folder", "file"):
                return str(v)
            if k == "color":
                s = str(v)
                return s if re.fullmatch(r"#[0-9a-fA-F]{6}", s) else self.default
            if k == "choice":
                return v if v in [c[0] for c in self.choices or []] else self.default
            if k == "multi":
                have = set(v) if isinstance(v, (list, tuple, set)) else set()
                return [c[0] for c in self.choices or [] if c[0] in have]
        except (TypeError, ValueError):
            pass
        return copy.deepcopy(self.default)


SCOPE_CHOICES = [("all", "Tüm sayfalar"), ("odd", "Tek sayfalar"), ("even", "Çift sayfalar"),
                 ("range", "Sayfa aralığı")]
_RANGE = dict(show_if=("scope", "range"))


def _scope_params() -> List[Param]:
    return [Param("scope", "Kapsam", "choice", "all", SCOPE_CHOICES),
            Param("page_start", "İlk sayfa", "int", 1, minv=1, maxv=100000, **_RANGE),
            Param("page_end", "Son sayfa", "int", 1, minv=1, maxv=100000, **_RANGE)]


def pages_of(p: dict, count: int) -> List[int]:
    """Kapsam ayarından 0 tabanlı sayfa listesi."""
    sc = p.get("scope", "all")
    if sc == "odd":
        return list(range(0, count, 2))
    if sc == "even":
        return list(range(1, count, 2))
    if sc == "range":
        lo = max(1, min(int(p.get("page_start", 1)), count))
        hi = max(1, min(int(p.get("page_end", count)), count))
        if lo > hi:
            lo, hi = hi, lo
        return list(range(lo - 1, hi))
    return list(range(count))


# ---------------------------------------------------------------------------
# Çalışma bağlamı
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, doc, name: str, font_ctx, inner: Callable[[float, str], None],
                 cancelled: Optional[Callable[[], bool]], overrides: Optional[dict] = None):
        self.doc = doc
        self.name = name
        self.font_ctx = font_ctx
        self.inner = inner
        self.cancelled = cancelled
        self.overrides = overrides or {}
        self.security: Optional[docsec.SecurityOptions] = None
        self.compress: Optional[str] = None
        self.save: Optional[dict] = None

    def check(self):
        if self.cancelled is not None and self.cancelled():
            raise Cancelled()

    def replace(self, new_doc):
        old, self.doc = self.doc, new_doc
        try:
            old.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Adım türleri
# ---------------------------------------------------------------------------
def _run_ocr(ctx: Ctx, p: dict) -> str:
    tess = ocr.find_tessdata()
    if tess is None:
        raise StepError("OCR için Tesseract dil verisi bulunamadı (Belge → OCR penceresindeki kurulum notuna bakın)")
    lang = ocr.pick_language(tess, p["language"] or None)
    n = ctx.doc.page_count
    todo = [i for i in range(n) if not p["only_missing"] or not ctx.doc[i].get_text("text").strip()]
    if not todo:
        return "Tüm sayfalarda metin var; atlandı"
    out = fitz.open()
    try:
        for i in range(n):
            ctx.check()
            if i in todo:
                pix = ctx.doc[i].get_pixmap(dpi=p["dpi"], alpha=False)
                with fitz.open("pdf", pix.pdfocr_tobytes(language=lang, tessdata=tess)) as one:
                    out.insert_pdf(one)
            else:
                out.insert_pdf(ctx.doc, from_page=i, to_page=i)
            ctx.inner((i + 1) / n, f"OCR sayfa {i + 1}/{n}")
    except BaseException:
        out.close()
        raise
    ctx.replace(out)
    return f"{len(todo)}/{n} sayfa tanındı ({lang})"


def _run_rotate(ctx: Ctx, p: dict) -> str:
    pages = pages_of(p, ctx.doc.page_count)
    for i in pages:
        pg = ctx.doc[i]
        pg.set_rotation((pg.rotation + int(p["degrees"])) % 360)
    return f"{len(pages)} sayfa {p['degrees']}° döndürüldü"


def _run_watermark(ctx: Ctx, p: dict) -> str:
    from PySide6.QtGui import QColor
    from models import WatermarkConfig
    import pdf_engine
    cfg = WatermarkConfig()
    cfg.mode = p["mode"]
    cfg.text, cfg.font_size, cfg.opacity = p["text"], p["font_size"], p["opacity"] / 100.0
    cfg.color, cfg.rotation, cfg.layout = QColor(p["color"]), p["rotation"], p["layout"]
    if p["mode"] == "image":
        if not p["image_path"] or not os.path.isfile(p["image_path"]):
            raise StepError("Filigran resmi seçilmemiş ya da bulunamadı")
        cfg.image_bytes = pdf_engine.load_image_bytes_from_path(p["image_path"], 1024)
        cfg.image_scale = p["image_scale"] / 100.0
    elif not p["text"].strip():
        raise StepError("Filigran metni boş")
    pages = pages_of(p, ctx.doc.page_count)
    pdf_engine.apply_watermark_to_pages(ctx.doc, cfg, ctx.font_ctx, pages)
    return f"{len(pages)} sayfaya filigran"


def _run_headfoot(ctx: Ctx, p: dict) -> str:
    import headfoot
    cfg = headfoot.HeadFootConfig()
    cfg.header = [p["h_left"], p["h_center"], p["h_right"]]
    cfg.footer = [p["f_left"], p["f_center"], p["f_right"]]
    cfg.font_size, cfg.margin, cfg.start_number, cfg.skip_first = p["font_size"], p["margin"], p["start_number"], p["skip_first"]
    cfg.scope = "range" if p["scope"] == "range" else "all"
    cfg.page_start, cfg.page_end = p["page_start"], p["page_end"]
    cfg.bates_prefix, cfg.bates_digits, cfg.bates_start = p["bates_prefix"], p["bates_digits"], p["bates_start"]
    if cfg.is_empty():
        raise StepError("Üstbilgi/altbilgi metinlerinin hepsi boş")
    headfoot.apply_header_footer(ctx.doc, cfg, ctx.font_ctx, ctx.name)
    return f"{len(cfg.pages(ctx.doc.page_count))} sayfaya yazıldı"


def _run_kvkk(ctx: Ctx, p: dict) -> str:
    kinds = p["kinds"]
    if not kinds:
        raise StepError("Hiçbir veri türü seçilmemiş")
    ocr_env = None
    if p["ocr"]:
        tess = ocr.find_tessdata()
        if tess:
            ocr_env = (tess, ocr.pick_language(tess))
    h = p["color"].lstrip("#")
    fill = tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    total, n = 0, ctx.doc.page_count
    for i in range(n):
        ctx.check()
        page = ctx.doc[i]
        hits = pii.scan_page(page, kinds, ocr_env)
        for hit in hits:
            page.add_redact_annot(fitz.Rect(hit.rect) * page.derotation_matrix, fill=fill)
        if hits:
            page.apply_redactions()
            total += len(hits)
        ctx.inner((i + 1) / n, f"KVKK taraması {i + 1}/{n}")
    note = "" if ocr_env or not p["ocr"] else " (OCR kurulu değil; taranmış sayfalar atlandı)"
    return f"{total} kişisel veri karartıldı{note}"


def _run_compress(ctx: Ctx, p: dict) -> str:
    ctx.compress = p["level"]
    return docsec.COMPRESS_LEVELS[p["level"]]["title"]


def _run_password(ctx: Ctx, p: dict) -> str:
    user, owner = p["user_password"], p["owner_password"]
    if p["ask"]:
        user = ctx.overrides.get("user_password", "")
        owner = ""
    ctx.security = docsec.SecurityOptions(user_password=user, owner_password=owner, allowed=set(p["allowed"]))
    if not ctx.security.active:
        return "Koruma uygulanmadı (parola yok, kısıtlama yok)"
    return ctx.security.describe()


def _run_save(ctx: Ctx, p: dict) -> str:
    ctx.save = dict(p)
    return SAVE_MODES.get(p["mode"], p["mode"])


SAVE_MODES = {"suffix": "Aynı klasöre, ada ek getirerek", "folder": "Seçilen klasöre", "overwrite": "Özgün dosyanın üstüne (yedekli)"}

_FINAL = "final"
_PAGE = "page"


@dataclass
class StepType:
    key: str
    title: str
    desc: str
    icon: str
    phase: str
    params: List[Param]
    run: Callable[[Ctx, dict], str]
    summary: Callable[[dict], str]

    def defaults(self) -> dict:
        return {p.key: copy.deepcopy(p.default) for p in self.params}

    def sanitize(self, raw: Optional[dict]) -> dict:
        raw = raw or {}
        return {p.key: (p.coerce(raw[p.key]) if p.key in raw else copy.deepcopy(p.default)) for p in self.params}


def _label(choices, value) -> str:
    return next((lbl for v, lbl in choices if v == value), str(value))


_WM_LAYOUT = [("single", "Ortada tek"), ("tiled", "Döşeli")]
_COMPRESS_CHOICES = [(k, v["title"]) for k, v in docsec.COMPRESS_LEVELS.items()]
_PERM_CHOICES = [(k, lbl) for k, lbl, _f in docsec.PERMISSIONS]
_KVKK_CHOICES = list(pii.CATEGORIES.items())


def _scope_text(p: dict) -> str:
    if p.get("scope") == "range":
        return f"sayfa {p['page_start']}–{p['page_end']}"
    return _label(SCOPE_CHOICES, p.get("scope", "all")).lower()


def _hf_summary(p: dict) -> str:
    for key, name in (("f_center", "Altbilgi"), ("f_left", "Altbilgi"), ("f_right", "Altbilgi"),
                      ("h_center", "Üstbilgi"), ("h_left", "Üstbilgi"), ("h_right", "Üstbilgi")):
        if p[key].strip():
            return f"{name}: {p[key]} · {_scope_text(p)}"
    return "Metin yok"


STEP_TYPES: Dict[str, StepType] = {t.key: t for t in [
    StepType("ocr", "OCR (metin tanıma)", "Taranmış sayfalara aranabilir/seçilebilir metin katmanı ekler.", "ocr", _PAGE,
             [Param("language", "Dil", "text", "tur+eng", hint="Tesseract dil kodları, + ile birleştirilir"),
              Param("dpi", "Çözünürlük (dpi)", "int", 200, minv=100, maxv=600),
              Param("only_missing", "Yalnızca metni olmayan sayfalar", "bool", True,
                    hint="Zaten metni olan sayfalar olduğu gibi kalır (daha hızlı)")],
             _run_ocr, lambda p: f"{p['language'] or 'otomatik dil'} · {p['dpi']} dpi · "
                                 + ("yalnız metinsiz sayfalar" if p["only_missing"] else "tüm sayfalar")),
    StepType("rotate", "Döndür", "Seçili sayfaları saat yönünde döndürür.", "rotate_cw", _PAGE,
             [Param("degrees", "Açı", "choice", 90, [(90, "90° saat yönü"), (180, "180°"), (270, "90° saat yönü tersi")])]
             + _scope_params(),
             _run_rotate, lambda p: f"{p['degrees']}° · {_scope_text(p)}"),
    StepType("compress", "Sıkıştır", "Dosya boyutunu küçültür (kaydederken uygulanır).", "compress", _FINAL,
             [Param("level", "Seviye", "choice", "balanced", _COMPRESS_CHOICES,
                    hint="Hafif: kalite aynı · Dengeli: 150 dpi · Güçlü: 100 dpi")],
             _run_compress, lambda p: docsec.COMPRESS_LEVELS[p["level"]]["title"]),
    StepType("watermark", "Filigran", "Metin ya da resim filigranı ekler.", "watermark", _PAGE,
             [Param("mode", "Tür", "choice", "text", [("text", "Metin"), ("image", "Resim")]),
              Param("text", "Metin", "text", "TASLAK", show_if=("mode", "text")),
              Param("font_size", "Yazı boyutu", "float", 48.0, minv=8, maxv=300, show_if=("mode", "text")),
              Param("color", "Renk", "color", "#c0392b", show_if=("mode", "text")),
              Param("image_path", "Resim dosyası", "file", "", show_if=("mode", "image")),
              Param("image_scale", "Resim boyutu (%)", "int", 60, minv=5, maxv=100, show_if=("mode", "image")),
              Param("opacity", "Opaklık (%)", "int", 30, minv=5, maxv=100),
              Param("rotation", "Açı (°)", "float", 45.0, minv=-90, maxv=90),
              Param("layout", "Yerleşim", "choice", "single", _WM_LAYOUT)] + _scope_params(),
             _run_watermark, lambda p: (f"“{p['text']}”" if p["mode"] == "text" else "Resim") +
                                       f" · %{p['opacity']} · {_scope_text(p)}"),
    StepType("headfoot", "Sayfa numarası / üstbilgi", "Sayfa numarası, üstbilgi/altbilgi, Bates numarası.", "headfoot", _PAGE,
             [Param("f_left", "Altbilgi · sol", "text", ""),
              Param("f_center", "Altbilgi · orta", "text", "{sayfa} / {toplam}",
                    hint="{sayfa} {toplam} {tarih} {dosya} {bates} kullanılabilir"),
              Param("f_right", "Altbilgi · sağ", "text", ""),
              Param("h_left", "Üstbilgi · sol", "text", ""), Param("h_center", "Üstbilgi · orta", "text", ""),
              Param("h_right", "Üstbilgi · sağ", "text", ""),
              Param("font_size", "Yazı boyutu", "float", 10.0, minv=5, maxv=48),
              Param("margin", "Kenar boşluğu (pt)", "float", 28.0, minv=0, maxv=200),
              Param("start_number", "İlk numara", "int", 1, minv=0, maxv=100000),
              Param("skip_first", "İlk sayfaya yazma (kapak)", "bool", False),
              Param("bates_prefix", "Bates öneki", "text", ""),
              Param("bates_digits", "Bates hane sayısı", "int", 6, minv=1, maxv=12),
              Param("bates_start", "Bates başlangıcı", "int", 1, minv=0, maxv=10 ** 9),
              Param("scope", "Kapsam", "choice", "all", [("all", "Tüm sayfalar"), ("range", "Sayfa aralığı")]),
              Param("page_start", "İlk sayfa", "int", 1, minv=1, maxv=100000, show_if=("scope", "range")),
              Param("page_end", "Son sayfa", "int", 1, minv=1, maxv=100000, show_if=("scope", "range"))],
             _run_headfoot, _hf_summary),
    StepType("kvkk", "KVKK karartma", "Kişisel verileri bulup kalıcı olarak karartır (metin PDF'ten silinir).", "privacy", _PAGE,
             [Param("kinds", "Karartılacak veriler", "multi", [k for k, _ in _KVKK_CHOICES], _KVKK_CHOICES),
              Param("ocr", "Metni olmayan sayfalarda OCR ile ara", "bool", True,
                    hint="Taranmış belgelerde kişisel veriyi bulmak için gerekli"),
              Param("color", "Kutu rengi", "color", "#000000")],
             _run_kvkk, lambda p: ", ".join(pii.CATEGORIES[k] for k in p["kinds"]) or "Veri türü seçilmedi"),
    StepType("password", "Parola / izinler", "Açma parolası ve izin kısıtlamaları (kaydederken uygulanır).", "lock", _FINAL,
             [Param("ask", "Çalıştırırken parolayı sor (şablona yazılmaz)", "bool", True),
              Param("user_password", "Açma parolası", "password", "", show_if=("ask", False),
                    hint="Şablonla birlikte bilgisayarınızda düz metin saklanır"),
              Param("owner_password", "İzin (sahip) parolası", "password", "", show_if=("ask", False),
                    hint="Boş + kısıtlama: rastgele üretilir"),
              Param("allowed", "İzin verilenler", "multi", [k for k, _ in _PERM_CHOICES], _PERM_CHOICES)],
             _run_password, lambda p: ("parola çalıştırırken sorulur" if p["ask"] else
                                       docsec.SecurityOptions(p["user_password"], p["owner_password"], set(p["allowed"])).describe())
             + (" · kısıtlı" if set(p["allowed"]) != docsec.ALL_PERMS and p["ask"] else "")),
    StepType("save", "Kaydet", "Çıktının adını ve yerini belirler (en sonda uygulanır).", "save", _FINAL,
             [Param("mode", "Nereye", "choice", "suffix", [(k, v) for k, v in SAVE_MODES.items()]),
              Param("suffix", "Ada eklenecek", "text", DEFAULT_SUFFIX, show_if=("mode", "suffix")),
              Param("folder", "Klasör", "folder", "", show_if=("mode", "folder")),
              Param("keep_structure", "Alt klasör yapısını koru", "bool", True, show_if=("mode", "folder")),
              Param("backup", "Özgün dosyanın .yedek kopyasını sakla", "bool", True, show_if=("mode", "overwrite"))],
             _run_save, lambda p: (f"…{p['suffix']}.pdf, aynı klasöre" if p["mode"] == "suffix" else
                                   f"{p['folder'] or '(klasör seçilmedi)'}" if p["mode"] == "folder" else "özgün dosyanın üstüne")),
]}
STEP_ORDER = ["ocr", "rotate", "watermark", "headfoot", "kvkk", "compress", "password", "save"]


# ---------------------------------------------------------------------------
# Zincir ve şablon
# ---------------------------------------------------------------------------
@dataclass
class Step:
    type: str
    params: dict = field(default_factory=dict)
    enabled: bool = True

    def __post_init__(self):
        if self.type not in STEP_TYPES:
            raise ValueError(f"Bilinmeyen adım türü: {self.type!r}")
        self.params = STEP_TYPES[self.type].sanitize(self.params)

    @property
    def stype(self) -> StepType:
        return STEP_TYPES[self.type]

    def summary(self) -> str:
        return self.stype.summary(self.params)


@dataclass
class Workflow:
    name: str = ""
    steps: List[Step] = field(default_factory=list)
    description: str = ""
    builtin: bool = False

    def add(self, type_: str, params: Optional[dict] = None, index: Optional[int] = None) -> Step:
        st = Step(type_, params or {})
        if index is None or index >= len(self.steps):
            self.steps.append(st)
        else:
            self.steps.insert(max(0, index), st)
        return st

    def enabled_steps(self) -> List[Step]:
        return [s for s in self.steps if s.enabled]

    def to_dict(self) -> dict:
        return {"version": VERSION, "name": self.name, "description": self.description,
                "steps": [{"type": s.type, "enabled": s.enabled, "params": s.params} for s in self.steps]}

    @classmethod
    def from_dict(cls, d: dict) -> "Workflow":
        if not isinstance(d, dict) or not isinstance(d.get("steps"), list):
            raise ValueError("İş akışı verisi geçersiz")
        if int(d.get("version", 1)) > VERSION:
            raise ValueError("Bu şablon daha yeni bir sürümle kaydedilmiş")
        steps = []
        for s in d["steps"]:
            if not isinstance(s, dict):
                raise ValueError("Adım verisi geçersiz")
            steps.append(Step(str(s.get("type", "")), s.get("params") or {}, bool(s.get("enabled", True))))
        return cls(str(d.get("name", "")), steps, str(d.get("description", "")))

    def copy(self) -> "Workflow":
        w = Workflow.from_dict(self.to_dict())
        w.builtin = self.builtin
        return w

    def validate(self) -> List[Tuple[str, str]]:
        """[(düzey 'uyarı'|'bilgi', metin)] — çalışmayı engellemez, olası hataları önceden söyler."""
        out: List[Tuple[str, str]] = []
        act = self.enabled_steps()
        if not act:
            return [("uyarı", "Zincirde etkin adım yok")]
        pos = {t: [i for i, s in enumerate(act) if s.type == t] for t in STEP_TYPES}
        for t in ("save", "compress", "password"):
            if len(pos[t]) > 1:
                out.append(("uyarı", f"Birden çok '{STEP_TYPES[t].title}' adımı var; sonuncusu geçerli"))
        if pos["ocr"]:
            first_ocr = pos["ocr"][0]
            for t in ("watermark", "headfoot"):
                if any(i < first_ocr for i in pos[t]):
                    out.append(("uyarı", f"'{STEP_TYPES[t].title}' OCR'dan önce: eklenen metin yüzünden sayfalar "
                                         "metinli sayılır ve OCR atlanabilir; OCR'ı öne alın"))
            for i in pos["kvkk"]:
                if i < first_ocr and not act[i].params["ocr"]:
                    out.append(("uyarı", "KVKK karartma OCR'dan önce ve kendi OCR seçeneği kapalı: taranmış "
                                         "sayfalarda veri bulunamaz"))
        for i in pos["password"]:
            p = act[i].params
            if not p["ask"] and not p["user_password"] and set(p["allowed"]) == docsec.ALL_PERMS:
                out.append(("bilgi", "Parola adımı hiçbir koruma uygulamıyor (parola yok, kısıtlama yok)"))
        for i in pos["headfoot"]:
            p = act[i].params
            if not any(p[k].strip() for k in ("f_left", "f_center", "f_right", "h_left", "h_center", "h_right")):
                out.append(("uyarı", "Sayfa numarası adımında tüm metinler boş"))
        if pos["save"] and pos["save"][0] != len(act) - 1:
            out.append(("bilgi", "Kaydet adımı sırası ne olursa olsun en sonda uygulanır"))
        if not pos["save"]:
            out.append(("bilgi", f"Kaydet adımı yok: çıktı aynı klasöre '{DEFAULT_SUFFIX}' eklenerek yazılır"))
        return out


# ---------------------------------------------------------------------------
# Hazır şablonlar ve kütüphane
# ---------------------------------------------------------------------------
def _wf(name: str, desc: str, *steps: Tuple[str, dict]) -> Workflow:
    w = Workflow(name, [Step(t, p) for t, p in steps], desc)
    w.builtin = True
    return w


BUILTINS: List[Workflow] = [
    _wf("Taranmış belgeyi düzenle", "OCR ile aranabilir yap, boyutu küçült.",
        ("ocr", {}), ("compress", {"level": "balanced"}), ("save", {"suffix": "_ocr"})),
    _wf("KVKK paylaşım kopyası", "Kişisel verileri karart, 'KOPYA' filigranı ekle, yazdırma dışında kısıtla.",
        ("kvkk", {}), ("watermark", {"text": "KOPYA", "opacity": 18, "font_size": 72}),
        ("password", {"ask": True, "allowed": ["print", "print_hq", "accessibility"]}), ("save", {"suffix": "_kvkk"})),
    _wf("Arşiv paketi", "OCR + sayfa numarası + güçlü sıkıştırma.",
        ("ocr", {}), ("headfoot", {}), ("compress", {"level": "strong"}), ("save", {"suffix": "_arsiv"})),
    _wf("Dosya hazırlığı (Bates)", "Her sayfaya Bates numarası ve sayfa numarası yaz.",
        ("headfoot", {"f_left": "{bates}", "f_center": "", "f_right": "{sayfa} / {toplam}", "bates_prefix": "DOS-"}),
        ("save", {"suffix": "_bates"})),
]


class WorkflowLibrary:
    """Şablonlar QSettings benzeri bir nesnede (value/setValue) JSON olarak saklanır."""
    KEY = "workflows"

    def __init__(self, settings):
        self.settings = settings

    def _user(self) -> Dict[str, dict]:
        try:
            d = json.loads(self.settings.value(self.KEY, "") or "{}")
            return d if isinstance(d, dict) else {}
        except (ValueError, TypeError):
            return {}

    def names(self) -> List[str]:
        return [w.name for w in BUILTINS] + sorted(n for n in self._user() if n not in {w.name for w in BUILTINS})

    def is_builtin(self, name: str) -> bool:
        return any(w.name == name for w in BUILTINS)

    def get(self, name: str) -> Workflow:
        for w in BUILTINS:
            if w.name == name:
                return w.copy()
        d = self._user().get(name)
        if d is None:
            raise KeyError(name)
        w = Workflow.from_dict(d)
        w.name = name
        return w

    def save(self, wf: Workflow, name: Optional[str] = None) -> str:
        name = (name or wf.name).strip()
        if not name:
            raise ValueError("Şablon adı boş olamaz")
        if self.is_builtin(name):
            raise ValueError("Hazır şablonların üstüne yazılamaz; başka bir ad verin")
        d = wf.to_dict()
        d["name"] = name
        users = self._user()
        users[name] = d
        self.settings.setValue(self.KEY, json.dumps(users, ensure_ascii=False))
        wf.name = name
        return name

    def delete(self, name: str) -> bool:
        users = self._user()
        if name not in users:
            return False
        del users[name]
        self.settings.setValue(self.KEY, json.dumps(users, ensure_ascii=False))
        return True

    @staticmethod
    def export_json(wf: Workflow) -> str:
        return json.dumps(wf.to_dict(), ensure_ascii=False, indent=2)

    @staticmethod
    def import_json(text: str) -> Workflow:
        try:
            return Workflow.from_dict(json.loads(text))
        except json.JSONDecodeError as ex:
            raise ValueError(f"Geçerli bir şablon dosyası değil: {ex}") from ex


# ---------------------------------------------------------------------------
# Kaynaklar, sonuçlar, rapor
# ---------------------------------------------------------------------------
@dataclass
class Source:
    name: str                          # görünen ad (dosya adı)
    path: Optional[str] = None         # diskteki dosya (açık belge için kaydedilmemişse None)
    data: Optional[bytes] = None       # bellekteki PDF (açık belge: işaretli kopya)
    rel_dir: str = ""                  # klasör taramasında kök'e göre alt klasör
    protect_original: bool = False     # True: özgün dosyanın üstüne yazılmaz (açık belge)


@dataclass
class StepResult:
    title: str
    status: str                        # ok | hata
    message: str = ""
    seconds: float = 0.0


@dataclass
class FileResult:
    name: str
    source: str = ""
    output: str = ""
    status: str = "ok"                 # ok | hata | iptal
    message: str = ""
    steps: List[StepResult] = field(default_factory=list)
    pages: int = 0
    size_before: int = 0
    size_after: int = 0
    seconds: float = 0.0


@dataclass
class BatchReport:
    workflow: str
    results: List[FileResult] = field(default_factory=list)
    seconds: float = 0.0
    cancelled: bool = False

    @property
    def ok(self) -> int:
        return sum(1 for r in self.results if r.status == "ok")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "hata")

    def summary(self) -> str:
        s = f"{self.ok}/{len(self.results)} dosya tamamlandı"
        if self.failed:
            s += f", {self.failed} hata"
        if self.cancelled:
            s += " (durduruldu)"
        return s + f" · {self.seconds:.1f} sn"

    def to_text(self) -> str:
        lines = [f"İş akışı: {self.workflow}", self.summary(), ""]
        for r in self.results:
            lines.append(f"[{r.status.upper()}] {r.name} → {r.output or '-'}"
                         f"  ({docsec.human_size(r.size_before)} → {docsec.human_size(r.size_after)}, {r.pages} sayfa)")
            if r.message:
                lines.append(f"    {r.message}")
            for s in r.steps:
                lines.append(f"    · {s.title}: {s.message or s.status}")
        return "\n".join(lines)

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["Dosya", "Durum", "Çıktı", "Sayfa", "Önceki boyut (bayt)", "Sonraki boyut (bayt)", "Süre (sn)", "Mesaj"])
        for r in self.results:
            w.writerow([r.name, r.status, r.output, r.pages, r.size_before, r.size_after, f"{r.seconds:.1f}",
                        r.message or "; ".join(f"{s.title}: {s.message}" for s in r.steps if s.message)])
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Çalıştırıcı
# ---------------------------------------------------------------------------
def _unique(path: str) -> str:
    base, ext = os.path.splitext(path)
    cand, n = path, 2
    while os.path.exists(cand):
        cand = f"{base} ({n}){ext}"
        n += 1
    return cand


def resolve_output(save: Optional[dict], src: Source, default_dir: str) -> Tuple[str, bool, bool]:
    """(çıktı yolu, üstüne yazma mı, yedek alınsın mı)."""
    save = save or {"mode": "suffix", "suffix": DEFAULT_SUFFIX}
    stem = os.path.splitext(os.path.basename(src.name))[0]
    mode = save.get("mode", "suffix")
    if mode == "overwrite" and src.path and os.path.isfile(src.path) and not src.protect_original:
        return os.path.splitext(src.path)[0] + ".pdf", True, bool(save.get("backup", True))
    if mode == "folder":
        base = save.get("folder") or default_dir
        if not base:
            raise StepError("Çıktı klasörü belirtilmemiş")
        if save.get("keep_structure", True) and src.rel_dir:
            base = os.path.join(base, src.rel_dir)
        return os.path.join(base, stem + ".pdf"), False, False
    base = os.path.dirname(src.path) if src.path else default_dir
    if not base:
        raise StepError("Kaydedilmemiş belge için çıktı klasörü seçin")
    if mode == "overwrite":                         # açık belge / dosya yok: güvenli yola düş
        suffix = DEFAULT_SUFFIX
    else:
        suffix = save.get("suffix", DEFAULT_SUFFIX)
    return os.path.join(base, stem + suffix + ".pdf"), False, False


def _open_source(src: Source, password: str = ""):
    if src.data is not None:
        return fitz.open("pdf", src.data)
    if not src.path or not os.path.isfile(src.path):
        raise StepError("Dosya bulunamadı")
    if os.path.splitext(src.path)[1].lower() in IMAGE_EXTS:
        with fitz.open(src.path) as img:
            return fitz.open("pdf", img.convert_to_pdf())
    doc = fitz.open(src.path)
    if doc.needs_pass and not doc.authenticate(password or ""):
        doc.close()
        raise StepError("Belge parolalı (kaynak parolası gerekli)")
    return doc


def _write_output(ctx: Ctx, src: Source, default_dir: str, res: FileResult) -> None:
    path, overwrite, backup = resolve_output(ctx.save, src, default_dir)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    kwargs = docsec.apply_compression(ctx.doc, ctx.compress)
    kwargs.update(docsec.save_kwargs(ctx.security))
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(path) or ".")
    os.close(fd)
    try:
        ctx.doc.save(tmp, **kwargs)
        ctx.check()                                 # kayıt bittikten sonra bile iptal edilebilir: dosya konmaz
        if overwrite:
            ctx.doc.close()                         # Windows: açık dosyanın üstüne taşıma reddedilir
            if backup:
                shutil.copy2(path, _unique(os.path.splitext(path)[0] + ".yedek.pdf"))
            os.replace(tmp, path)
        else:
            path = _unique(path)
            os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    res.output = path
    res.size_after = os.path.getsize(path)


def run_file(wf: Workflow, src: Source, default_dir: str = "", progress: Optional[Callable[[float, str], None]] = None,
             cancelled: Optional[Callable[[], bool]] = None, font_ctx=None, overrides: Optional[dict] = None) -> FileResult:
    """Tek dosyada zinciri çalıştırır. Hata/iptal istisna olarak değil sonuçta döner."""
    t0 = time.time()
    res = FileResult(src.name, src.path or "")
    steps = wf.enabled_steps()
    ctx = None
    current = ""
    try:
        if not steps:
            raise StepError("Zincirde etkin adım yok")
        doc = _open_source(src, (overrides or {}).get("open_password", ""))
        res.size_before = len(src.data) if src.data is not None else os.path.getsize(src.path)
        n = len(steps)
        cur = [0]

        def inner(frac: float, msg: str = ""):
            if progress:
                progress((cur[0] + frac) / (n + 1), msg)
        ctx = Ctx(doc, os.path.splitext(os.path.basename(src.name))[0], font_ctx, inner, cancelled, overrides)
        ordered = [s for s in steps if s.stype.phase == _PAGE] + [s for s in steps if s.stype.phase == _FINAL]
        for i, st in enumerate(ordered):
            ctx.check()
            cur[0] = i
            current = st.stype.title
            if progress:
                progress(i / (n + 1), f"{st.stype.title}…")
            t1 = time.time()
            try:
                msg = st.stype.run(ctx, st.params)
            except (Cancelled, StepError):
                raise
            except Exception as ex:
                raise StepError(f"{type(ex).__name__}: {ex}") from ex
            res.steps.append(StepResult(st.stype.title, "ok", msg or "", time.time() - t1))
        current = "Kaydet"
        cur[0] = n
        if progress:
            progress(n / (n + 1), "Kaydediliyor…")
        res.pages = ctx.doc.page_count
        _write_output(ctx, src, default_dir, res)
    except Cancelled:
        res.status, res.message = "iptal", "Durduruldu"
    except StepError as ex:
        res.status = "hata"
        res.message = f"{current}: {ex}" if current else str(ex)
        if current and current != "Kaydet":
            res.steps.append(StepResult(current, "hata", str(ex)))
    except Exception as ex:                          # beklenmeyen: tüm toplu işi düşürmez
        res.status, res.message = "hata", f"{type(ex).__name__}: {ex}"
    finally:
        if ctx is not None:
            try:
                ctx.doc.close()
            except Exception:
                pass
    res.seconds = time.time() - t0
    if progress and res.status == "ok":
        progress(1.0, "Bitti")
    return res


def run_batch(wf: Workflow, sources: List[Source], default_dir: str = "",
              progress: Optional[Callable[[float, str], None]] = None, cancelled: Optional[Callable[[], bool]] = None,
              font_ctx=None, overrides: Optional[dict] = None,
              on_result: Optional[Callable[[FileResult], None]] = None) -> BatchReport:
    """Dosyaları sırayla işler. Bir dosyanın hatası diğerlerini durdurmaz; durdurma istenirse kalanlar 'iptal' sayılır."""
    t0 = time.time()
    rep = BatchReport(wf.name)
    total = max(1, len(sources))
    for i, src in enumerate(sources):
        if cancelled is not None and cancelled():
            rep.cancelled = True
            for rest in sources[i:]:
                r = FileResult(rest.name, rest.path or "", status="iptal", message="Başlatılmadı")
                rep.results.append(r)
                if on_result:
                    on_result(r)
            break

        def p(frac, msg, i=i, name=src.name):
            if progress:
                progress((i + frac) / total, f"{name} ({i + 1}/{len(sources)}) · {msg}")
        r = run_file(wf, src, default_dir, p, cancelled, font_ctx, overrides)
        if r.status == "iptal":
            rep.cancelled = True
        rep.results.append(r)
        if on_result:
            on_result(r)
    rep.seconds = time.time() - t0
    if progress:
        progress(1.0, rep.summary())
    return rep


def collect_files(folder: str, recursive: bool = True, skip_suffix: str = DEFAULT_SUFFIX) -> List[Source]:
    """Klasördeki PDF/resim dosyaları (ada göre sıralı). Çıktı ekini taşıyan dosyalar atlanır (tekrar işlenmesin)."""
    out: List[Source] = []
    folder = os.path.abspath(folder)
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        if not recursive and root != folder:
            continue
        for f in sorted(files):
            stem, ext = os.path.splitext(f)
            if ext.lower() != ".pdf" and ext.lower() not in IMAGE_EXTS:
                continue
            if skip_suffix and stem.endswith(skip_suffix):
                continue
            out.append(Source(f, os.path.join(root, f), rel_dir=os.path.relpath(root, folder) if root != folder else ""))
    return out


def save_suffix_of(wf: Workflow) -> str:
    """Klasör taramasında atlanacak çıktı eki (kaydet adımı 'suffix' modundaysa)."""
    for s in reversed(wf.enabled_steps()):
        if s.type == "save":
            return s.params["suffix"] if s.params["mode"] == "suffix" else ""
    return DEFAULT_SUFFIX
