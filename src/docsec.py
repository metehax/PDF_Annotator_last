"""
docsec.py
=========
Belge güvenliği ve bilgileri (arayüzden bağımsız, PyMuPDF üzerine):

* Parola koruması ve izinler -> `SecurityOptions`, `save_kwargs()`
* Sıkıştırma seviyeleri      -> `COMPRESS_LEVELS`, `apply_compression()`
* Güvenlik denetimi           -> `scan()` -> `Finding` listesi
* Temizlik                    -> `clean()`
* Belge bilgileri yardımcıları -> `info_summary()`
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import pymupdf as fitz

# ---------------------------------------------------------------------------
# Parola ve izinler
# ---------------------------------------------------------------------------
PERMISSIONS: List[Tuple[str, str, int]] = [
    ("print", "Yazdırma", fitz.PDF_PERM_PRINT),
    ("print_hq", "Yüksek kaliteli yazdırma", fitz.PDF_PERM_PRINT_HQ),
    ("copy", "Metin ve görsel kopyalama", fitz.PDF_PERM_COPY),
    ("modify", "İçeriği düzenleme", fitz.PDF_PERM_MODIFY),
    ("annotate", "Yorum ve işaret ekleme", fitz.PDF_PERM_ANNOTATE),
    ("form", "Form doldurma", fitz.PDF_PERM_FORM),
    ("assemble", "Sayfa ekleme / silme / döndürme", fitz.PDF_PERM_ASSEMBLE),
    ("accessibility", "Ekran okuyucu erişimi", fitz.PDF_PERM_ACCESSIBILITY),
]
ALL_PERMS = {k for k, _, _ in PERMISSIONS}


@dataclass
class SecurityOptions:
    user_password: str = ""                    # açma parolası (boş: parola sorulmaz)
    owner_password: str = ""                   # izin parolası (boş + kısıtlama: rastgele üretilir)
    allowed: set = field(default_factory=lambda: set(ALL_PERMS))

    @property
    def active(self) -> bool:
        return bool(self.user_password) or self.allowed != ALL_PERMS

    def describe(self) -> str:
        parts = []
        if self.user_password:
            parts.append("açma parolası")
        denied = [lbl for k, lbl, _ in PERMISSIONS if k not in self.allowed]
        if denied:
            parts.append("kısıtlı: " + ", ".join(d.lower() for d in denied))
        return "; ".join(parts) or "koruma yok"


def save_kwargs(sec: Optional[SecurityOptions]) -> Dict:
    """Document.save()/tobytes() için şifreleme argümanları."""
    if sec is None or not sec.active:
        return {"encryption": fitz.PDF_ENCRYPT_NONE}
    perms = 0
    for key, _lbl, flag in PERMISSIONS:
        if key in sec.allowed:
            perms |= flag
    owner = sec.owner_password or secrets.token_urlsafe(18)
    return {
        "encryption": fitz.PDF_ENCRYPT_AES_256,
        "owner_pw": owner,
        "user_pw": sec.user_password or None,
        "permissions": perms,
    }


# ---------------------------------------------------------------------------
# Sıkıştırma
# ---------------------------------------------------------------------------
COMPRESS_LEVELS: Dict[str, Dict] = {
    "light": dict(title="Hafif", desc="Görüntü kalitesine dokunmaz; yalnızca gereksiz veriyi temizler "
                  "ve içeriği yeniden sıkıştırır.", images=None, subset=False),
    "balanced": dict(title="Dengeli (önerilen)", desc="Yüksek çözünürlüklü resimleri 150 dpi'ye "
                     "indirir (kalite %80). Ekranda ve normal baskıda fark edilmez.",
                     images=dict(dpi_threshold=200, dpi_target=150, quality=80), subset=True),
    "strong": dict(title="Güçlü", desc="Resimleri 100 dpi'ye indirir (kalite %60). E-posta ve arşiv "
                   "için en küçük dosya; baskıda kalite düşebilir.",
                   images=dict(dpi_threshold=120, dpi_target=100, quality=60), subset=True),
}


def apply_compression(doc: "fitz.Document", level: Optional[str]) -> Dict:
    """Belgeyi yerinde küçültür; save() için ek argümanları döner."""
    if not level:
        return dict(garbage=3, deflate=True)
    cfg = COMPRESS_LEVELS[level]
    if cfg["images"]:
        try:
            doc.rewrite_images(**cfg["images"])
        except Exception:
            pass                       # bozuk/desteklenmeyen resimler: olduğu gibi kalır
    if cfg["subset"]:
        try:
            doc.subset_fonts()
        except Exception:
            pass
    return dict(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True,
                clean=True, use_objstms=1)


def human_size(n: int) -> str:
    for unit in ("bayt", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bayt" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024.0
    return str(n)


# ---------------------------------------------------------------------------
# Güvenlik denetimi
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    kind: str            # CHECKS anahtarı
    count: int
    items: List[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return CHECKS[self.kind][0]

    @property
    def severity(self) -> str:
        return CHECKS[self.kind][1]

    @property
    def explain(self) -> str:
        return CHECKS[self.kind][2]


# anahtar: (başlık, önem: high|medium|low, açıklama)
CHECKS: Dict[str, Tuple[str, str, str]] = {
    "javascript": ("JavaScript kodu", "high",
                   "Belge açıldığında ya da bir öğeye tıklanınca çalışabilen betikler."),
    "auto_action": ("Otomatik eylemler", "high",
                    "Belge ya da sayfa açılınca kendiliğinden yürütülen eylemler (OpenAction/AA)."),
    "launch": ("Program / dosya çalıştırma", "high",
               "Bilgisayarda bir dosya ya da program başlatmaya çalışan eylemler."),
    "submit": ("Veri gönderme / içe aktarma", "medium",
               "Form verisini internete gönderen ya da dışarıdan veri alan eylemler."),
    "remote_goto": ("Başka belgeye atlama", "medium",
                    "Başka bir PDF dosyasını açmaya çalışan bağlantılar."),
    "embedded": ("Gömülü dosyalar", "medium",
                 "PDF'in içine eklenmiş dosyalar; zararlı içerik taşıyabilir."),
    "attach_annots": ("Dosya eki notları", "medium", "Sayfa üzerinde dosya eki taşıyan notlar."),
    "rich_media": ("Çoklu ortam / 3B içerik", "medium", "Video, ses, Flash ya da 3B içerik."),
    "links": ("Dış bağlantılar", "low", "İnternet adreslerine giden bağlantılar."),
    "xfa": ("XFA formu", "low", "Eski tip, betik çalıştırabilen form biçimi."),
    "hidden_layers": ("Gizli katmanlar", "low", "Görünmeyen ama belgede duran içerik katmanları."),
    "metadata": ("Belge bilgileri (metadata)", "low",
                 "Yazar, kurum, oluşturan program gibi kişisel/kurumsal bilgiler."),
    "xml_metadata": ("XMP metadata", "low", "Düzenleme geçmişi içerebilen ek bilgi bloğu."),
}

# Temizlik seçenekleri: anahtar -> (etiket, varsayılan seçili mi, açıklama)
CLEAN_OPTIONS: Dict[str, Tuple[str, bool, str]] = {
    "javascript": ("JavaScript ve otomatik eylemler", True, ""),
    "launch": ("Çalıştırma / gönderme eylemleri", True, ""),
    "embedded": ("Gömülü dosyalar ve dosya eki notları", True, ""),
    "links": ("Tüm bağlantılar", False, "İçindekiler bağlantıları dahil hepsi kaldırılır."),
    "metadata": ("Belge bilgileri ve XMP metadata", True, ""),
    "thumbnails": ("Gömülü küçük resimler", True, ""),
    "hidden_text": ("Görünmeyen metin", False,
                    "DİKKAT: Taranmış belgelerin OCR katmanı da görünmez metindir; bunu seçerseniz "
                    "belgede arama yapılamaz hâle gelir."),
}


def _key(doc, xref, key) -> Tuple[str, str]:
    try:
        return doc.xref_get_key(xref, key)
    except Exception:
        return ("null", "null")


def scan(doc: "fitz.Document") -> List[Finding]:
    found: Dict[str, Finding] = {}

    def add(kind, item=""):
        f = found.setdefault(kind, Finding(kind, 0))
        f.count += 1
        if item and len(f.items) < 50:
            f.items.append(item)

    cat = doc.pdf_catalog()
    if _key(doc, cat, "OpenAction")[0] != "null":
        add("auto_action", "Belge açılış eylemi (OpenAction)")
    if _key(doc, cat, "AA")[0] != "null":
        add("auto_action", "Belge düzeyinde ek eylemler (AA)")
    if _key(doc, cat, "AcroForm/XFA")[0] != "null":
        add("xfa", "Belgede XFA form verisi var")

    for xref in range(1, doc.xref_length()):
        try:
            keys = doc.xref_get_keys(xref)
        except Exception:
            continue
        if not keys:
            continue
        # eylem ya kendi nesnesinde (/S) ya da bir bağlantının içinde (/A/S) durur
        for prefix in ("", "A/"):
            if prefix and "A" not in keys:
                continue
            if not prefix and "S" not in keys and "JS" not in keys:
                continue
            s_type = _key(doc, xref, prefix + "S")[1]
            has_js = _key(doc, xref, prefix + "JS")[0] != "null"
            if has_js or s_type == "/JavaScript":
                add("javascript", f"Nesne {xref}")
            if s_type == "/Launch":
                target = _key(doc, xref, prefix + "F/F")[1] or _key(doc, xref, prefix + "F")[1]
                add("launch", f"{target.strip('()')} (nesne {xref})")
            elif s_type in ("/SubmitForm", "/ImportData"):
                add("submit", f"{s_type[1:]} (nesne {xref})")
            elif s_type == "/GoToR":
                add("remote_goto", f"Nesne {xref}")
        sub = _key(doc, xref, "Subtype")[1] if "Subtype" in keys else ""
        if sub in ("/RichMedia", "/Movie", "/Sound", "/Screen", "/3D"):
            add("rich_media", f"{sub[1:]} (nesne {xref})")

    for name in doc.embfile_names():
        add("embedded", name)

    for page in doc:
        if _key(doc, page.xref, "AA")[0] != "null":
            add("auto_action", f"Sayfa {page.number + 1} açılış/kapanış eylemi")
        for ln in page.get_links():
            if ln.get("kind") == fitz.LINK_URI:
                add("links", f"Sayfa {page.number + 1}: {ln.get('uri', '')}")
        for annot in page.annots(types=[fitz.PDF_ANNOT_FILE_ATTACHMENT]) or []:
            try:
                fname = annot.file_info.get("filename", "")
            except Exception:
                fname = ""
            add("attach_annots", f"Sayfa {page.number + 1}: {fname}")

    try:
        ocgs = doc.get_ocgs() or {}
        ui = doc.layer_ui_configs() if ocgs else []
        hidden = [c.get("text", "") for c in ui if not c.get("on", True)]
        for h in hidden:
            add("hidden_layers", h or "(adsız katman)")
    except Exception:
        pass

    meta = {k: v for k, v in (doc.metadata or {}).items()
            if v and k in ("author", "creator", "producer", "title", "subject", "keywords")}
    if meta:
        f = found.setdefault("metadata", Finding("metadata", 0))
        f.count = len(meta)
        labels = dict(author="Yazar", creator="Oluşturan", producer="Üreten", title="Başlık",
                      subject="Konu", keywords="Anahtar kelimeler")
        f.items = [f"{labels[k]}: {v}" for k, v in meta.items()]
    try:
        if doc.get_xml_metadata():
            add("xml_metadata", "XMP bloğu var")
    except Exception:
        pass

    order = list(CHECKS)
    return sorted(found.values(), key=lambda f: order.index(f.kind))


def clean(doc: "fitz.Document", options: Iterable[str]) -> None:
    """Seçilen içeriği belgeden kalıcı olarak kaldırır (yerinde)."""
    opts = set(options)
    cat = doc.pdf_catalog()
    if "javascript" in opts:
        for key in ("OpenAction", "AA", "Names/JavaScript"):
            if _key(doc, cat, key)[0] != "null":
                doc.xref_set_key(cat, key, "null")
        for page in doc:
            if _key(doc, page.xref, "AA")[0] != "null":
                doc.xref_set_key(page.xref, "AA", "null")
    for xref in range(1, doc.xref_length()):
        try:
            keys = doc.xref_get_keys(xref)
        except Exception:
            continue
        if not keys:
            continue
        if "javascript" in opts and not ("A" in keys) and (
                "JS" in keys or _key(doc, xref, "S")[1] == "/JavaScript"):
            doc.update_object(xref, "<<>>")                  # betiği tamamen boşalt
            continue
        for prefix in ("", "A/"):
            if prefix and "A" not in keys:
                continue
            s_type = _key(doc, xref, prefix + "S")[1]
            risky = (("launch" in opts and s_type in ("/Launch", "/SubmitForm", "/ImportData", "/GoToR"))
                     or ("javascript" in opts and (s_type == "/JavaScript"
                                                   or _key(doc, xref, prefix + "JS")[0] != "null")))
            if risky:
                if prefix:
                    doc.xref_set_key(xref, "A", "null")       # bağlantının eylemini kaldır
                else:
                    doc.xref_set_key(xref, "S", "/GoTo")      # zararsız, hedefsiz eylem
                    for k in ("F", "JS", "Win", "Mac", "Unix", "Flags", "URL"):
                        doc.xref_set_key(xref, k, "null")
    if "embedded" in opts:
        for name in list(doc.embfile_names()):
            doc.embfile_del(name)
    doc.scrub(
        attached_files="embedded" in opts,
        clean_pages=False,
        embedded_files="embedded" in opts,
        hidden_text="hidden_text" in opts,
        javascript="javascript" in opts,
        metadata="metadata" in opts,
        redactions=False,
        remove_links="links" in opts,
        reset_fields=False,
        reset_responses=False,
        thumbnails="thumbnails" in opts,
        xml_metadata="metadata" in opts,
    )


# ---------------------------------------------------------------------------
# Belge bilgileri
# ---------------------------------------------------------------------------
META_FIELDS: List[Tuple[str, str]] = [
    ("title", "Başlık"), ("author", "Yazar"), ("subject", "Konu"),
    ("keywords", "Anahtar kelimeler"), ("creator", "Oluşturan uygulama"),
]


def pdf_date(s: str) -> str:
    """'D:20241016093000+03'00' -> '16.10.2024 09:30'"""
    s = (s or "").strip()
    if s.startswith("D:"):
        s = s[2:]
    if len(s) >= 8 and s[:8].isdigit():
        out = f"{s[6:8]}.{s[4:6]}.{s[0:4]}"
        if len(s) >= 12 and s[8:12].isdigit():
            out += f" {s[8:10]}:{s[10:12]}"
        return out
    return s or "—"


def info_summary(doc: "fitz.Document", path: str) -> List[Tuple[str, str]]:
    m = doc.metadata or {}
    rows = [
        ("Dosya", os.path.basename(path)),
        ("Klasör", os.path.dirname(os.path.abspath(path))),
        ("Dosya boyutu", human_size(os.path.getsize(path)) if os.path.exists(path) else "—"),
        ("Sayfa sayısı", str(doc.page_count)),
        ("PDF sürümü", (m.get("format") or "—").replace("PDF ", "")),
        ("Oluşturulma", pdf_date(m.get("creationDate", ""))),
        ("Değiştirilme", pdf_date(m.get("modDate", ""))),
        ("Üreten", m.get("producer") or "—"),
        ("Şifreleme", m.get("encryption") or "Yok"),
        ("Gömülü dosya", str(doc.embfile_count())),
    ]
    if doc.page_count:
        r = doc[0].rect
        rows.insert(4, ("Sayfa boyutu", f"{r.width * 25.4 / 72:.0f} × {r.height * 25.4 / 72:.0f} mm"))
    return rows
