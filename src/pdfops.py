"""
pdfops.py
=========
Birleştirme / bölme çekirdeği (arayüzsüz): sayfa aralığı ayrıştırma, `merge`, `split`.
Çıktılar önce `.part` dosyasına yazılır, sonra `os.replace` edilir; iptalde (convert.Cancelled)
bu çağrıda oluşan hiçbir dosya kalmaz.
"""

from __future__ import annotations

import os
import re
from typing import Callable, List, Optional, Sequence, Tuple

import pymupdf as fitz

from convert import Cancelled
from pdf_engine import clamp_scale, image_to_pdf_document, is_image_path

SPLIT_MODES = ("ranges", "ranges_one", "every", "bookmarks", "pages")


def parse_ranges(text: str, page_count: int) -> List[int]:
    """"1-3, 5, 8-" → 0 tabanlı sayfa dizini (sıra korunur). Boş metin = tüm sayfalar."""
    out: List[int] = []
    for g in parse_groups(text, page_count):
        out.extend(g)
    return out


def parse_groups(text: str, page_count: int) -> List[List[int]]:
    """Virgülle ayrılmış her parça bir grup (aralık). Boş metin = tek grup, tüm sayfalar."""
    if page_count < 1:
        raise ValueError("Belgede sayfa yok.")
    text = (text or "").strip()
    if not text:
        return [list(range(page_count))]
    groups: List[List[int]] = []
    for part in re.split(r"[,;]", text):
        part = part.strip()
        if not part:
            raise ValueError("Boş aralık var (fazladan virgül).")
        m = re.fullmatch(r"(\d*)\s*(-)?\s*(\d*)", part)
        if not m or not (m.group(1) or m.group(3)):
            raise ValueError(f"Geçersiz aralık: “{part}”.")
        a, dash, b = m.group(1), m.group(2), m.group(3)
        if not dash:
            lo = hi = int(a)
        else:
            lo = int(a) if a else 1
            hi = int(b) if b else page_count
        for v in (lo, hi):
            if v < 1 or v > page_count:
                raise ValueError(f"Sayfa {v} belgede yok (1–{page_count} arası olmalı).")
        if lo > hi:
            raise ValueError(f"Aralık ters: “{part}” (başlangıç bitişten büyük).")
        groups.append(list(range(lo - 1, hi)))
    return groups


def format_ranges(pages: Sequence[int]) -> str:
    """0 tabanlı dizinler → "1-3, 5" (görüntü için)."""
    res, i = [], 0
    p = list(pages)
    while i < len(p):
        j = i
        while j + 1 < len(p) and p[j + 1] == p[j] + 1:
            j += 1
        res.append(str(p[i] + 1) if i == j else f"{p[i] + 1}-{p[j] + 1}")
        i = j + 1
    return ", ".join(res)


def open_source(path: str) -> "fitz.Document":
    return image_to_pdf_document(path)[0] if is_image_path(path) else fitz.open(path)


def page_count(path: str) -> int:
    d = open_source(path)
    try:
        return d.page_count
    finally:
        d.close()


def unique_path(path: str) -> str:
    """Var olan dosyayı ezmemek için `ad (2).pdf` biçiminde numaralar."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def _save_atomic(doc: "fitz.Document", out: str) -> None:
    part = out + ".part"
    try:
        doc.save(part)
        os.replace(part, out)
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass


def _insert_pages(dst: "fitz.Document", src: "fitz.Document", pages: Sequence[int]) -> None:
    i = 0
    p = list(pages)
    while i < len(p):                                  # ardışık sayfalar tek çağrıda
        j = i
        while j + 1 < len(p) and p[j + 1] == p[j] + 1:
            j += 1
        dst.insert_pdf(src, from_page=p[i], to_page=p[j])
        i = j + 1


def merge(sources: Sequence[Tuple[str, str]], out: str,
          progress: Optional[Callable[[int, int], None]] = None,
          cancelled: Optional[Callable[[], bool]] = None) -> str:
    """`sources`: [(yol, aralık_metni)] sırayla birleştirilir. Çıktı yolunu döndürür."""
    if not sources:
        raise ValueError("Birleştirilecek dosya yok.")
    merged = fitz.open()
    try:
        for k, (path, rng) in enumerate(sources):
            if cancelled and cancelled():
                raise Cancelled()
            try:
                src = open_source(path)
            except Exception as ex:
                raise ValueError(f"{os.path.basename(path)} açılamadı: {ex}") from ex
            try:
                try:
                    pages = parse_ranges(rng, src.page_count)
                except ValueError as ex:
                    raise ValueError(f"{os.path.basename(path)}: {ex}") from ex
                _insert_pages(merged, src, pages)
            finally:
                src.close()
            if progress:
                progress(k + 1, len(sources))
        if cancelled and cancelled():
            raise Cancelled()
        _save_atomic(merged, out)
    finally:
        merged.close()
    return out


def _bookmark_groups(doc: "fitz.Document", level: int = 1) -> List[Tuple[str, List[int]]]:
    """Belirtilen düzeydeki yer imlerinden (başlık, sayfa dizinleri) grupları; ilk yer iminden
    önceki sayfalar 'Giriş' grubu olur."""
    toc = [(t, p - 1) for lv, t, p in doc.get_toc(simple=True) if lv == level and 1 <= p <= doc.page_count]
    if not toc:
        raise ValueError("Belgede bölünecek yer imi yok.")
    starts: List[Tuple[str, int]] = []
    for t, p in toc:
        if not starts or starts[-1][1] != p:
            starts.append((t, p))
    groups: List[Tuple[str, List[int]]] = []
    if starts[0][1] > 0:
        groups.append(("Giris", list(range(0, starts[0][1]))))
    for i, (t, p) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else doc.page_count
        groups.append((t, list(range(p, end))))
    return groups


def plan_split(doc: "fitz.Document", mode: str, ranges: str = "", every: int = 1) -> List[Tuple[str, List[int]]]:
    """Bölme planı: [(etiket, sayfa dizinleri)]. 'ranges_one' tek grup (seçili sayfalar hep birlikte)."""
    n = doc.page_count
    if mode == "ranges":
        gs = parse_groups(ranges, n)
        return [(format_ranges(g), g) for g in gs]
    if mode == "ranges_one":
        g = parse_ranges(ranges, n)
        return [(format_ranges(g), g)]
    if mode == "every":
        if every < 1:
            raise ValueError("Sayfa sayısı en az 1 olmalı.")
        return [(f"{a + 1}-{min(a + every, n)}" if min(a + every, n) - a > 1 else str(a + 1),
                 list(range(a, min(a + every, n)))) for a in range(0, n, every)]
    if mode == "bookmarks":
        return _bookmark_groups(doc)
    if mode == "pages":
        return [(str(i + 1), [i]) for i in range(n)]
    raise ValueError(f"Bilinmeyen bölme kipi: {mode}")


_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe(name: str) -> str:
    return _BAD.sub("_", name).strip(" .") or "bolum"


def split(src_path: str, out_dir: str, mode: str = "pages", ranges: str = "", every: int = 1,
          template: str = "{ad}_{n}", progress: Optional[Callable[[int, int], None]] = None,
          cancelled: Optional[Callable[[], bool]] = None) -> List[str]:
    """`template`: {ad} kaynak adı, {n} sıra numarası, {aralik} sayfa aralığı/yer imi başlığı.
    Var olan dosyaların üstüne yazmaz (otomatik numara). İptalde oluşan dosyalar silinir."""
    doc = open_source(src_path)
    made: List[str] = []
    try:
        plan = plan_split(doc, mode, ranges, every)
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(src_path))[0]
        taken = set()
        try:
            for i, (label, pages) in enumerate(plan):
                if cancelled and cancelled():
                    raise Cancelled()
                try:
                    name = template.format(ad=base, n=i + 1, aralik=label)
                except (KeyError, IndexError, ValueError) as ex:
                    raise ValueError("Ad şablonu geçersiz: {ad}, {n}, {aralik} kullanın.") from ex
                path = unique_path(os.path.join(out_dir, _safe(name) + ".pdf"))
                while path in taken:
                    path = unique_path(path)
                taken.add(path)
                part = fitz.open()
                try:
                    _insert_pages(part, doc, pages)
                    _save_atomic(part, path)
                finally:
                    part.close()
                made.append(path)
                if progress:
                    progress(i + 1, len(plan))
        except BaseException:
            for p in made:
                try:
                    os.remove(p)
                except OSError:
                    pass
            raise
    finally:
        doc.close()
    return made


def split_many(paths: Sequence[str], out_dir: str, per_file_dir: bool = False,
               progress: Optional[Callable[[int, int], None]] = None,
               cancelled: Optional[Callable[[], bool]] = None, **opts) -> List[str]:
    """Birden çok PDF'i aynı kuralla böler (kural aralığı belgede yoksa o dosya hata verir).
    İptal/hata olursa bu çağrıda üretilen hiçbir dosya kalmaz."""
    made: List[str] = []
    try:
        for k, p in enumerate(paths):
            d = os.path.join(out_dir, _safe(os.path.splitext(os.path.basename(p))[0])) if per_file_dir else out_dir
            try:
                made += split(p, d, progress=None, cancelled=cancelled, **opts)
            except ValueError as ex:
                raise ValueError(f"{os.path.basename(p)}: {ex}") from ex
            if progress:
                progress(k + 1, len(paths))
    except BaseException:
        for f in made:
            try:
                os.remove(f)
            except OSError:
                pass
        raise
    return made


def render_thumb(path: str, index: int, max_side: int = 160):
    """(png_baytları) — önizleme küçük resmi; `MAX_PIXELS` sınırına uyar."""
    d = open_source(path)
    try:
        pg = d[index]
        r = pg.rect
        sc = clamp_scale(r, max_side / max(r.width, r.height, 1.0))
        return pg.get_pixmap(matrix=fitz.Matrix(sc, sc), alpha=False).tobytes("png")
    finally:
        d.close()
