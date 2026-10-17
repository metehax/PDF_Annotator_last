"""Erişilebilirlik denetimi (arayüzsüz çekirdek).

`audit(doc)` bir `A11yReport` döndürür: etiketli PDF, belge dili, başlık,
başlık yapısı (yer imleri), alternatif metin, okuma sırası, gömülü yazı tipleri
ve taranmış sayfa kontrolleri. Düzeltilebilenler (`Check.fix`): `lang`, `title`,
`bookmarks`, `ocr` — ilk üçü `apply_fixes`, OCR arayüzdeki arka plan işiyle.
"""
from __future__ import annotations

import html
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import pymupdf as fitz

PASS, WARN, FAIL, INFO = "pass", "warn", "fail", "info"
_ICON = {PASS: "✓", WARN: "⚠", FAIL: "✕", INFO: "ℹ"}
LANGUAGES = [("tr-TR", "Türkçe"), ("en-US", "İngilizce (ABD)"), ("en-GB", "İngilizce (BK)"),
             ("de-DE", "Almanca"), ("fr-FR", "Fransızca"), ("es-ES", "İspanyolca"),
             ("ar", "Arapça"), ("ru-RU", "Rusça")]
FIX_LABEL = {"lang": "Belge dilini ayarla", "title": "Belge başlığını ayarla ve pencere başlığında göster",
             "bookmarks": "Başlıklardan yer imleri oluştur", "ocr": "Taranmış sayfalara OCR uygula"}
_FILENAME_TITLE = re.compile(r"\.(docx?|pdf|pptx?|xlsx?|indd|odt|rtf|txt)$|^microsoft (word|powerpoint|excel)\b",
                             re.I)


@dataclass
class Check:
    key: str
    title: str
    status: str
    detail: str
    items: List[str] = field(default_factory=list)
    fix: Optional[str] = None                   # 'lang' | 'title' | 'bookmarks' | 'ocr'
    data: Dict = field(default_factory=dict)

    @property
    def icon(self) -> str:
        return _ICON[self.status]


@dataclass
class A11yReport:
    checks: List[Check] = field(default_factory=list)
    pages: int = 0
    tagged: bool = False
    cancelled: bool = False

    def count(self, status: str) -> int:
        return sum(1 for c in self.checks if c.status == status)

    def get(self, key: str) -> Optional[Check]:
        return next((c for c in self.checks if c.key == key), None)

    def fixable(self) -> List[Check]:
        return [c for c in self.checks if c.fix and c.status in (WARN, FAIL)]

    def summary(self) -> str:
        return (f"{self.count(PASS)} geçti · {self.count(WARN)} uyarı · {self.count(FAIL)} sorun"
                + (f" · {len(self.fixable())} tek tıkla düzeltilebilir" if self.fixable() else ""))


# ---------------------------------------------------------------------------
# Düşük düzey yardımcılar
# ---------------------------------------------------------------------------
def _key(doc, xref: int, key: str) -> Tuple[str, str]:
    try:
        return doc.xref_get_key(xref, key)
    except Exception:
        return ("null", "null")


def _has(doc, xref: int, key: str) -> bool:
    return _key(doc, xref, key)[0] != "null"


def _catalog(doc) -> int:
    return doc.pdf_catalog()


def _marked(doc, cat: int) -> bool:
    t, v = _key(doc, cat, "MarkInfo")
    if t == "dict":
        return bool(re.search(r"/Marked\s+true", v))
    if t == "xref":
        return _key(doc, int(v.split()[0]), "Marked")[1] == "true"
    return False


def _lang(doc, cat: int) -> str:
    t, v = _key(doc, cat, "Lang")
    return v.strip("()").strip() if t == "string" else ""


def _display_doc_title(doc, cat: int) -> bool:
    t, v = _key(doc, cat, "ViewerPreferences")
    if t == "dict":
        return bool(re.search(r"/DisplayDocTitle\s+true", v))
    if t == "xref":
        return _key(doc, int(v.split()[0]), "DisplayDocTitle")[1] == "true"
    return False


def _scan_structure(doc, cancelled=None) -> Dict[str, int]:
    """Etiket ağacındaki öğeleri sayar (S türü): başlıklar, şekiller, alt metinsiz şekiller."""
    stats = {"headings": 0, "figures": 0, "figures_no_alt": 0, "tables": 0, "tables_no_th": 0}
    th_tables = 0
    for x in range(1, doc.xref_length()):
        if cancelled and x % 2000 == 0 and cancelled():
            break
        t, v = _key(doc, x, "S")
        if t != "name":
            continue
        if v in ("/H", "/H1", "/H2", "/H3", "/H4", "/H5", "/H6"):
            stats["headings"] += 1
        elif v == "/Figure":
            stats["figures"] += 1
            texts = (_key(doc, x, "Alt"), _key(doc, x, "ActualText"))
            if not any(tt != "null" and vv.strip("() ") for tt, vv in texts):
                stats["figures_no_alt"] += 1
        elif v == "/Table":
            stats["tables"] += 1
        elif v == "/TH":
            th_tables += 1
    if stats["tables"] and not th_tables:
        stats["tables_no_th"] = stats["tables"]
    return stats


def _page_text(page) -> str:
    return page.get_text("text").strip()


def _image_cover(page) -> float:
    """Sayfa alanının görsellerle kapladığı oran (0..1, örtüşmeler kabaca)."""
    area = max(page.rect.width * page.rect.height, 1.0)
    total = 0.0
    try:
        for info in page.get_image_info():
            r = fitz.Rect(info["bbox"]) & page.rect
            total += max(r.width, 0) * max(r.height, 0)
    except Exception:
        return 0.0
    return min(total / area, 1.0)


def guess_language(doc, sample_pages: int = 4) -> str:
    text = " ".join(_page_text(doc[i]) for i in range(min(doc.page_count, sample_pages))).lower()
    if not text.strip():
        return "tr-TR"
    letters = sum(text.count(c) for c in "ğüşıöç")
    tr_words = sum(len(re.findall(rf"\b{w}\b", text)) for w in ("ve", "bir", "bu", "için", "ile", "olarak"))
    en_words = sum(len(re.findall(rf"\b{w}\b", text)) for w in ("the", "and", "of", "to", "is", "for"))
    de_words = sum(len(re.findall(rf"\b{w}\b", text)) for w in ("der", "die", "und", "das", "nicht"))
    if letters >= 3 or tr_words > max(en_words, de_words):
        return "tr-TR"
    if de_words > en_words:
        return "de-DE"
    return "en-US" if en_words else "tr-TR"


# ---------------------------------------------------------------------------
# Başlık algılama (yer imleri ve başlık önerisi için)
# ---------------------------------------------------------------------------
def detect_headings(doc, max_pages: int = 400) -> List[Tuple[int, str, int, float]]:
    """(düzey, metin, sayfa 1 tabanlı, boyut) listesi; gövde metninden belirgin büyük satırlar."""
    sizes: Counter = Counter()
    lines: List[Tuple[int, str, float, bool]] = []
    for p in range(min(doc.page_count, max_pages)):
        for block in doc[p].get_text("dict").get("blocks", []):
            if block.get("type", 0) != 0:
                continue
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if s["text"].strip()]
                if not spans:
                    continue
                text = " ".join(s["text"].strip() for s in spans)
                size = round(max(s["size"] for s in spans), 1)
                bold = all(bool(s["flags"] & 16) or "bold" in s["font"].lower() for s in spans)
                sizes[size] += len(text)
                lines.append((p + 1, text, size, bold))
    if not sizes:
        return []
    body = sizes.most_common(1)[0][0]
    cand = [(pg, tx, sz) for pg, tx, sz, bd in lines
            if 3 <= len(tx) <= 120 and (sz >= body * 1.2 or (bd and sz >= body * 1.05))
            and not re.fullmatch(r"[\d\W]+", tx)]
    levels = sorted({sz for _, _, sz in cand}, reverse=True)[:3]
    out = []
    for pg, tx, sz in cand:
        if sz in levels:
            out.append((levels.index(sz) + 1, tx, pg, sz))
    return out


def suggest_title(doc, path: str = "") -> str:
    if doc.page_count:
        best = None
        for block in doc[0].get_text("dict").get("blocks", []):
            if block.get("type", 0) != 0:
                continue
            for line in block.get("lines", []):
                text = " ".join(s["text"].strip() for s in line.get("spans", []) if s["text"].strip())
                size = max((s["size"] for s in line.get("spans", [])), default=0)
                if 3 <= len(text) <= 150 and (best is None or size > best[0] + 0.5):
                    best = (size, text)
        if best:
            return best[1]
    return os.path.splitext(os.path.basename(path))[0] if path else ""


def _toc_from_headings(heads) -> List[List]:
    toc, prev = [], 0
    for level, text, page, _sz in heads:
        level = min(level, prev + 1) if prev else 1          # set_toc: ilk düzey 1, atlama yok
        toc.append([level, text[:200], page])
        prev = level
    return toc


# ---------------------------------------------------------------------------
# Denetim
# ---------------------------------------------------------------------------
def audit(doc, path: str = "", cancelled: Optional[Callable[[], bool]] = None) -> A11yReport:
    cat = _catalog(doc)
    n = doc.page_count
    rep = A11yReport(pages=n)
    has_tree = _has(doc, cat, "StructTreeRoot")
    marked = _marked(doc, cat)
    rep.tagged = has_tree and marked
    stats = _scan_structure(doc, cancelled) if has_tree else {}

    # 1) Etiketli PDF
    if rep.tagged:
        rep.checks.append(Check("tagged", "Etiketli PDF", PASS, "Belge etiketli (yapı ağacı var)."))
    else:
        why = "yapı ağacı yok" if not has_tree else "“Etiketli” işareti kapalı"
        rep.checks.append(Check("tagged", "Etiketli PDF", FAIL,
                                f"Belge etiketli değil ({why}). Ekran okuyucular başlık, liste ve tabloları tanıyamaz. "
                                "Kaynak uygulamadan (Word vb.) “etiketli PDF” seçeneğiyle yeniden dışa aktarın; "
                                "bu araç etiket ağacı üretemez."))

    # 2) Dil
    lang = _lang(doc, cat)
    if lang:
        rep.checks.append(Check("lang", "Belge dili", PASS, f"Dil tanımlı: {lang}."))
    else:
        guess = guess_language(doc)
        rep.checks.append(Check("lang", "Belge dili", FAIL,
                                "Belge dili tanımlı değil; ekran okuyucu yanlış dilde okuyabilir. "
                                f"Önerilen: {guess}.", fix="lang", data={"suggest": guess}))

    # 3) Başlık
    title = (doc.metadata or {}).get("title", "").strip()
    shown = _display_doc_title(doc, cat)
    sugg = suggest_title(doc, path)
    if title and not _FILENAME_TITLE.search(title) and shown:
        rep.checks.append(Check("title", "Belge başlığı", PASS, f"Başlık: “{title}”, pencere başlığında gösteriliyor."))
    elif title and not _FILENAME_TITLE.search(title):
        rep.checks.append(Check("title", "Belge başlığı", WARN,
                                f"Başlık var (“{title}”) ama pencere başlığında gösterilmiyor.", fix="title",
                                data={"suggest": title}))
    else:
        why = "dosya adına benziyor" if title else "boş"
        rep.checks.append(Check("title", "Belge başlığı", FAIL, f"Belge başlığı {why}. Önerilen: “{sugg}”.",
                                fix="title", data={"suggest": sugg}))

    # 4) Başlık yapısı
    toc = doc.get_toc(simple=True)
    heads = detect_headings(doc) if not toc and not stats.get("headings") else []
    if stats.get("headings"):
        rep.checks.append(Check("headings", "Başlık yapısı", PASS, f"Etiket ağacında {stats['headings']} başlık öğesi var."))
    elif toc:
        rep.checks.append(Check("headings", "Başlık yapısı", PASS if not has_tree else WARN,
                                f"{len(toc)} yer imi var" + ("" if not has_tree else ", ancak etiket ağacında başlık öğesi yok") + "."))
    elif n < 4 and not heads:
        rep.checks.append(Check("headings", "Başlık yapısı", INFO, "Kısa belge; başlık/yer imi zorunlu değil."))
    elif heads:
        rep.checks.append(Check("headings", "Başlık yapısı", WARN,
                                f"Yer imi yok; görsel olarak {len(heads)} başlık algılandı. Yer imleri oluşturulabilir.",
                                items=[f"{'  ' * (lv - 1)}{tx}  (s.{pg})" for lv, tx, pg, _ in heads[:25]],
                                fix="bookmarks", data={"toc": _toc_from_headings(heads)}))
    else:
        rep.checks.append(Check("headings", "Başlık yapısı", WARN if n >= 4 else INFO,
                                "Yer imi ve belirgin başlık algılanamadı; uzun belgelerde başlık yapısı gezinmeyi kolaylaştırır."))

    # sayfa taraması: görsel, taranmış, okuma sırası, yazı tipi
    images: Dict[int, int] = {}
    scanned: List[int] = []
    order_bad: List[str] = []
    fonts: Dict[int, Tuple[str, str, List[int]]] = {}
    for p in range(n):
        if cancelled and cancelled():
            rep.cancelled = True
            return rep
        page = doc[p]
        txt = _page_text(page)
        cover = _image_cover(page)
        if len(txt) < 3 and cover >= 0.5:
            scanned.append(p)
        count = 0
        try:
            for info in page.get_image_info():
                r = fitz.Rect(info["bbox"])
                if r.width >= 24 and r.height >= 24 and not (len(txt) < 3 and cover >= 0.5):
                    count += 1
        except Exception:
            pass
        if count:
            images[p] = count
        if not has_tree and len(txt) >= 3:
            blocks = [b for b in page.get_text("blocks") if b[6] == 0]
            jumps = sum(1 for a, b in zip(blocks, blocks[1:]) if b[3] < a[1] - 12 and b[0] <= a[0] + 5)
            if len(blocks) >= 4 and jumps >= 2:
                order_bad.append(f"Sayfa {p + 1}: {jumps} geri sıçrama")
        try:
            for f in page.get_fonts(full=True):
                x, ext, ftype, base = f[0], f[1], f[2], f[3]
                if x not in fonts:
                    fonts[x] = (base.split("+")[-1] or f[4], "" if (ext not in ("n/a", "") or ftype == "Type3") else "yok", [])
                fonts[x][2].append(p + 1)
        except Exception:
            pass

    # 5) Alternatif metin
    if has_tree:
        if stats["figures"] == 0:
            rep.checks.append(Check("alt", "Alternatif metin", PASS if not images else WARN,
                                    "Etiket ağacında şekil yok." if not images else
                                    f"{sum(images.values())} görsel var ama etiket ağacında şekil (Figure) öğesi yok."))
        elif stats["figures_no_alt"]:
            rep.checks.append(Check("alt", "Alternatif metin", FAIL,
                                    f"{stats['figures_no_alt']} / {stats['figures']} şekilde alternatif metin yok. "
                                    "Alt metin içerik bilgisi gerektirdiğinden kaynak uygulamada girilmelidir."))
        else:
            rep.checks.append(Check("alt", "Alternatif metin", PASS, f"{stats['figures']} şeklin hepsinde alternatif metin var."))
    elif images:
        total = sum(images.values())
        rep.checks.append(Check("alt", "Alternatif metin", FAIL,
                                f"{total} görsel var; belge etiketsiz olduğundan alternatif metin tanımlanamıyor.",
                                items=[f"Sayfa {p + 1}: {c} görsel" for p, c in list(images.items())[:30]]))
    else:
        rep.checks.append(Check("alt", "Alternatif metin", PASS, "Anlamlı görsel yok."))

    # 6) Okuma sırası
    if has_tree:
        rep.checks.append(Check("order", "Okuma sırası", INFO,
                                "Sıra etiket ağacından okunur. Doğruluğu için belgeyi ekran okuyucuyla ya da "
                                "Acrobat'ın “Sırayı oku” özelliğiyle deneyin."))
    elif order_bad:
        rep.checks.append(Check("order", "Okuma sırası", WARN,
                                "Bazı sayfalarda metin akışı görsel sıradan farklı görünüyor (sütun/yan çubuk karışmış olabilir).",
                                items=order_bad[:30]))
    else:
        rep.checks.append(Check("order", "Okuma sırası", PASS, "Metin akışı görsel sıraya uyuyor (sezgisel denetim)."))

    # 7) Gömülü yazı tipleri
    missing = [(name, pages) for name, flag, pages in fonts.values() if flag]
    if missing:
        rep.checks.append(Check("fonts", "Gömülü yazı tipleri", WARN,
                                f"{len(missing)} yazı tipi gömülü değil; başka bilgisayarda farklı görünebilir ve "
                                "erişilebilirlik standardını (PDF/UA) bozar. Kaynakta “yazı tiplerini göm” seçeneğini açın.",
                                items=[f"{name} (s. {_pages_text(pages)})" for name, pages in missing[:30]]))
    else:
        rep.checks.append(Check("fonts", "Gömülü yazı tipleri", PASS,
                                "Tüm yazı tipleri gömülü." if fonts else "Yazı tipi kullanılmıyor."))

    # 8) Taranmış sayfalar
    if scanned:
        rep.checks.append(Check("scanned", "Taranmış sayfalar", FAIL,
                                f"{len(scanned)} sayfa yalnızca resimden oluşuyor; ekran okuyucu bu sayfaları okuyamaz. "
                                "OCR ile metin katmanı eklenebilir.",
                                items=[f"Sayfa {p + 1}" for p in scanned[:40]], fix="ocr", data={"pages": scanned}))
    else:
        rep.checks.append(Check("scanned", "Taranmış sayfalar", PASS, "Tüm sayfalarda metin katmanı var."))
    return rep


def _pages_text(pages: List[int]) -> str:
    pages = sorted(set(pages))
    return ", ".join(map(str, pages[:8])) + ("…" if len(pages) > 8 else "")


# ---------------------------------------------------------------------------
# Düzeltmeler (OCR hariç: o, arka plan işiyle arayüzde yapılır)
# ---------------------------------------------------------------------------
def apply_fixes(doc, keys: List[str], *, lang: str = "tr-TR", title: str = "",
                toc: Optional[List[List]] = None) -> List[str]:
    """Seçili düzeltmeleri doğrudan açık belgeye uygular; yapılanların açıklamasını döndürür."""
    cat = _catalog(doc)
    done: List[str] = []
    if "lang" in keys and lang:
        doc.xref_set_key(cat, "Lang", f"({lang})")
        done.append(f"Belge dili: {lang}")
    if "title" in keys:
        meta = dict(doc.metadata or {})
        if title.strip():
            meta["title"] = title.strip()
            doc.set_metadata(meta)
        _set_display_doc_title(doc, cat)
        done.append(f"Başlık: “{(doc.metadata or {}).get('title', '')}”")
    if "bookmarks" in keys and toc:
        doc.set_toc(toc)
        done.append(f"{len(toc)} yer imi oluşturuldu")
    return done


def _set_display_doc_title(doc, cat: int):
    t, v = _key(doc, cat, "ViewerPreferences")
    try:
        if t == "null":
            doc.xref_set_key(cat, "ViewerPreferences", "<</DisplayDocTitle true>>")
        elif t == "xref":
            doc.xref_set_key(int(v.split()[0]), "DisplayDocTitle", "true")
        else:
            doc.xref_set_key(cat, "ViewerPreferences/DisplayDocTitle", "true")
    except Exception:
        doc.xref_set_key(cat, "ViewerPreferences", "<</DisplayDocTitle true>>")


def ocr_replace_pages(doc, results: List[Tuple[int, bytes]]) -> int:
    """OCR'lı tek sayfalık PDF'leri (sayfa indeksi, bayt) ilgili sayfaların yerine koyar.
    Sayfa boyutu özgün sayfayla aynı tutulur; sayfa sayısı değişmediğinden indeksler kayar."""
    n = 0
    for idx, data in results:
        r = doc[idx].rect
        with fitz.open("pdf", data) as one:
            newp = doc.new_page(pno=idx + 1, width=r.width, height=r.height)
            newp.show_pdf_page(newp.rect, one, 0)
        doc.delete_page(idx)
        n += 1
    return n


# ---------------------------------------------------------------------------
# Rapor çıktısı
# ---------------------------------------------------------------------------
def report_text(rep: A11yReport, name: str = "") -> str:
    out = [f"Erişilebilirlik raporu{' — ' + name if name else ''}", rep.summary(), ""]
    for c in rep.checks:
        out.append(f"[{c.icon}] {c.title}: {c.detail}")
        out.extend(f"      - {it}" for it in c.items)
    return "\n".join(out) + "\n"


def report_html(rep: A11yReport, name: str = "") -> str:
    color = {PASS: "#1f9d57", WARN: "#b7791f", FAIL: "#dc3a3a", INFO: "#5a606a"}
    rows = []
    for c in rep.checks:
        items = "".join(f"<li>{html.escape(i)}</li>" for i in c.items)
        rows.append(f"<h3 style='color:{color[c.status]}'>{c.icon} {html.escape(c.title)}</h3>"
                    f"<p>{html.escape(c.detail)}</p>" + (f"<ul>{items}</ul>" if items else ""))
    return ("<!doctype html><html lang='tr'><meta charset='utf-8'><title>Erişilebilirlik raporu</title>"
            "<body style='font-family:Segoe UI,Arial,sans-serif;max-width:760px;margin:2em auto'>"
            f"<h1>Erişilebilirlik raporu</h1><p><b>{html.escape(name)}</b></p><p>{html.escape(rep.summary())}</p>"
            + "".join(rows) + "</body></html>")
