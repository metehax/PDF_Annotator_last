"""Belge tarama çekirdeği (arayüzsüz): fotoğraftan kâğıdı bulup düzeltme, filtre, PDF'e aktarma.

Görüntüler `numpy` dizisidir: (yükseklik, genişlik, 3), RGB, uint8. Köşeler piksel
koordinatında, sıralı: sol-üst, sağ-üst, sağ-alt, sol-alt (SÖ, SaÖ, SaA, SA).
"""
from __future__ import annotations

import io
import os
from typing import Iterable, Optional, Sequence, Union

import cv2
import numpy as np
import pymupdf as fitz
from PIL import Image, ImageOps

from pdf_engine import IMAGE_EXTS, IMAGE_PAGE_MAX_PT

__all__ = ["IMAGE_EXTS", "FILTERS", "PAGE_SIZES", "load_image", "detect_corners", "order_points",
           "warp", "rotate", "apply_filter", "to_pdf", "images_to_pdfs"]

MAX_SIDE = 3000          # yüklenen görüntünün en uzun kenarı (px)
DETECT_SIDE = 700        # köşe aramada çalışılan küçültülmüş boyut (px)
TO_PDF_MAX_SIDE = 4000   # to_pdf dosya girdilerinde en uzun kenar (px)
MIN_AREA_RATIO = 0.20    # kâğıt dörtgeninin görüntüye oranı (en az)
MAX_AREA_RATIO = 0.98    # bunun üstü "tüm kare" sayılır (kâğıt bulunamadı)

FILTERS = ("orijinal", "otomatik", "belge", "gri", "canlı", "gölgesiz renkli")
PAGE_SIZES = {"a4": (595.276, 841.89), "letter": (612.0, 792.0)}

_TR = str.maketrans("ıİöÖüÜçÇşŞğĞ", "iIoOuUcCsSgG")


def _fold(name: str) -> str:
    return name.strip().translate(_TR).lower()


_FILTER_KEYS = {_fold(f): f for f in FILTERS}


# ---------------------------------------------------------------------------
# Yükleme
# ---------------------------------------------------------------------------
def load_image(path: str, max_side: int = MAX_SIDE) -> np.ndarray:
    """Resmi açar; EXIF yönünü uygular, saydamlığı beyaza yayar, en uzun kenarı `max_side`'a indirir."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, rgba)
        im = im.convert("RGB")
        if max(im.size) > max_side:
            k = max_side / max(im.size)
            im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        return np.ascontiguousarray(np.asarray(im, dtype=np.uint8))


def _as_rgb(img) -> np.ndarray:
    """PIL / gri / RGBA girdisini (h, w, 3) uint8'e çevirir."""
    if isinstance(img, Image.Image):
        img = np.asarray(img.convert("RGB"))
    a = np.asarray(img)
    if a.dtype != np.uint8:
        a = np.clip(a, 0, 255).astype(np.uint8)
    if a.ndim == 2:
        a = np.stack([a] * 3, axis=-1)
    elif a.shape[2] == 4:
        a = a[:, :, :3]
    return np.ascontiguousarray(a)


# ---------------------------------------------------------------------------
# Köşe bulma
# ---------------------------------------------------------------------------
def order_points(pts: Sequence[Sequence[float]]) -> np.ndarray:
    """4 noktayı SÖ, SaÖ, SaA, SA sırasına dizer (ağırlık merkezine göre açıyla; dönük kâğıtta da çalışır)."""
    p = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    c = p.mean(axis=0)
    ang = np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0])      # y aşağı → saat yönünde artar
    p = p[np.argsort(ang)]
    start = int(np.argmin(p[:, 0] + p[:, 1]))              # sol-üste en yakın
    return np.ascontiguousarray(np.roll(p, -start, axis=0))


def _quad_from_contour(cnt: np.ndarray) -> Optional[np.ndarray]:
    hull = cv2.convexHull(cnt)
    peri = cv2.arcLength(hull, True)
    for eps in (0.02, 0.03, 0.04, 0.06, 0.08):
        ap = cv2.approxPolyDP(hull, eps * peri, True)
        if len(ap) == 4:
            return ap.reshape(4, 2).astype(np.float32)
        if len(ap) < 4:
            break
    return None


def _best_quad(mask: np.ndarray) -> Optional[np.ndarray]:
    h, w = mask.shape[:2]
    cnts, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best, best_area = None, 0.0
    for cnt in sorted(cnts, key=cv2.contourArea, reverse=True)[:8]:
        if cv2.contourArea(cnt) < MIN_AREA_RATIO * w * h:
            break
        quad = _quad_from_contour(cnt)
        if quad is None:
            continue
        area = cv2.contourArea(quad)
        if (MIN_AREA_RATIO * w * h <= area <= MAX_AREA_RATIO * w * h
                and cv2.isContourConvex(quad.astype(np.int32)) and area > best_area):
            best, best_area = quad, area
    return best


def _full_image(w: int, h: int) -> np.ndarray:
    return np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)


def detect_corners(img, fallback: bool = True) -> Optional[np.ndarray]:
    """Fotoğraftaki kâğıdın 4 köşesi (SÖ, SaÖ, SaA, SA; piksel). Bulunamazsa `fallback` ise
    tüm görüntünün köşeleri, değilse `None` döner."""
    a = _as_rgb(img)
    H, W = a.shape[:2]
    k = min(1.0, DETECT_SIDE / max(H, W))
    small = cv2.resize(a, (max(1, round(W * k)), max(1, round(H * k))), interpolation=cv2.INTER_AREA) if k < 1 else a
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (5, 5), 0)
    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))

    edges = cv2.dilate(cv2.Canny(gray, 50, 150), ker, iterations=2)
    solid = np.zeros_like(edges)                           # dış konturları doldur, genişletmeyi geri al
    ext, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(solid, ext, -1, 255, cv2.FILLED)
    quad = _best_quad(cv2.erode(solid, ker, iterations=2))
    if quad is None:                                       # kenar zayıfsa: parlak bölge (Otsu)
        _, m = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)))
        quad = _best_quad(m)
    if quad is None:
        return _full_image(W, H) if fallback else None
    quad = order_points(quad / k)
    quad[:, 0] = np.clip(quad[:, 0], 0, W - 1)
    quad[:, 1] = np.clip(quad[:, 1], 0, H - 1)
    return quad


# ---------------------------------------------------------------------------
# Düzeltme / döndürme
# ---------------------------------------------------------------------------
def warp(img, corners) -> np.ndarray:
    """Dörtgeni dikdörtgene açar; çıktı boyutu karşılıklı kenar uzunluklarının büyüğünden gelir."""
    a = _as_rgb(img)
    src = order_points(corners)
    tl, tr, br, bl = src
    w = max(1, round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    h = max(1, round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(a, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def rotate(img, derece: float) -> np.ndarray:
    """Saat yönünde döndürür. 90'ın katları kayıpsız; diğer açılarda tuval büyür, boşluk beyaz."""
    a = _as_rgb(img)
    d = float(derece) % 360
    if d == 0:
        return a.copy()
    if d % 90 == 0:
        return np.ascontiguousarray(np.rot90(a, k=-int(d // 90)))
    h, w = a.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), -d, 1.0)   # OpenCV: pozitif = saat yönünün tersi
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = round(h * sin + w * cos), round(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(a, m, (nw, nh), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))


# ---------------------------------------------------------------------------
# Filtreler
# ---------------------------------------------------------------------------
def _bright_contrast(a: np.ndarray, parlaklik: float, kontrast: float) -> np.ndarray:
    """parlaklik, kontrast: -100…100 (0 = değişmez)."""
    if not parlaklik and not kontrast:
        return a
    alpha = 1.0 + max(-100.0, min(100.0, kontrast)) / 100.0
    beta = max(-100.0, min(100.0, parlaklik)) * 2.55
    return cv2.convertScaleAbs(a, alpha=alpha, beta=beta + 128 * (1 - alpha))


def _background(a: np.ndarray) -> np.ndarray:
    """Aydınlatma/gölge arka planı: küçültülmüş kopyada yazıyı silip (kapama) bulanıklaştırır, geri büyütür."""
    h, w = a.shape[:2]
    k = min(1.0, 512 / max(h, w))
    s = cv2.resize(a, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1 else a
    s = cv2.dilate(s, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    s = cv2.medianBlur(s, 21)
    s = cv2.GaussianBlur(s, (0, 0), 3)
    return cv2.resize(s, (w, h), interpolation=cv2.INTER_LINEAR) if k < 1 else s


def _flatten(a: np.ndarray) -> np.ndarray:
    """Gölgeyi kaldırır: görüntü / arka plan."""
    bg = np.maximum(_background(a).astype(np.float32), 1.0)
    return np.clip(a.astype(np.float32) / bg * 255.0, 0, 255).astype(np.uint8)


def _unsharp(a: np.ndarray, amount: float = 0.6, sigma: float = 1.2) -> np.ndarray:
    blur = cv2.GaussianBlur(a, (0, 0), sigma)
    return cv2.addWeighted(a, 1 + amount, blur, -amount, 0)


def _gray3(g: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.stack([g] * 3, axis=-1))


def apply_filter(img, ad: str = "orijinal", parlaklik: float = 0, kontrast: float = 0) -> np.ndarray:
    """Filtre uygular (bkz. `FILTERS`; Türkçe karakter/büyük harf farkı yok sayılır).
    Çıktı her zaman giriş boyutunda (h, w, 3) uint8; `belge` yalnızca 0/255 içerir."""
    key = _FILTER_KEYS.get(_fold(ad))
    if key is None:
        raise ValueError(f"Bilinmeyen filtre: {ad!r}")
    a = _as_rgb(img)
    if key == "orijinal":
        out = a.copy()
    elif key == "otomatik":
        g = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
        lo, hi = np.percentile(g, (1, 99))
        if hi - lo < 8:
            out = a.copy()
        else:
            out = np.clip((a.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
        out = _unsharp(out, 0.4)
    elif key == "belge":
        g = _bright_contrast(_flatten(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)), parlaklik, kontrast)
        block = max(15, (min(g.shape) // 20) | 1)
        bw = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 15)
        return _gray3(bw)
    elif key == "gri":
        out = _gray3(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY))
    elif key == "canlı":
        lab = cv2.cvtColor(a, cv2.COLOR_RGB2LAB)
        lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(lab[:, :, 0])
        hsv = cv2.cvtColor(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB), cv2.COLOR_RGB2HSV)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1].astype(np.float32) * 1.3, 0, 255).astype(np.uint8)
        out = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    else:  # gölgesiz renkli
        out = _unsharp(_flatten(a), 0.3)
    return _bright_contrast(out, parlaklik, kontrast)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
PageInput = Union[np.ndarray, Image.Image, str]


def _encode(a: np.ndarray, jpeg_kalite: int) -> bytes:
    """Siyah-beyaz/gri içerik için PNG (küçük), renkli/gri tonlamalı için JPEG."""
    buf = io.BytesIO()
    gray = bool(np.array_equal(a[:, :, 0], a[:, :, 1]) and np.array_equal(a[:, :, 1], a[:, :, 2]))
    if gray:
        g = a[:, :, 0]
        if np.isin(g, (0, 255)).all():
            Image.fromarray(g).convert("1").save(buf, format="PNG", optimize=True)
        else:
            Image.fromarray(g).save(buf, format="JPEG", quality=int(jpeg_kalite), optimize=True)
    else:
        Image.fromarray(a, "RGB").save(buf, format="JPEG", quality=int(jpeg_kalite), optimize=True)
    return buf.getvalue()


def to_pdf(sayfalar: Iterable[PageInput], out_path: Optional[str] = None, sayfa_boyutu: str = "a4",
           kenar_bosluk_pt: float = 0, jpeg_kalite: int = 85, yon: str = "otomatik",
           max_kenar: int = TO_PDF_MAX_SIDE):
    """Görüntüleri (dizi / PIL / dosya yolu) sayfa başına bir görüntü olacak şekilde PDF yapar.
    `sayfa_boyutu`: "a4" | "letter" | "orijinal" (piksel oranı; en uzun kenar `IMAGE_PAGE_MAX_PT`'yi aşmaz).
    Görüntü kenar boşluğu içinde orantılı sığdırılır; `yon`: "otomatik" (görüntüye göre) | "dikey" | "yatay".
    Dosya yolu girdileri en uzun kenarı `max_kenar` px'e kadar korunarak yüklenir.
    `out_path` verilirse dosyaya yazar ve yolu döndürür, yoksa açık `fitz.Document` döndürür."""
    boyut = _fold(sayfa_boyutu)
    if boyut != "orijinal" and boyut not in PAGE_SIZES:
        raise ValueError(f"Bilinmeyen sayfa boyutu: {sayfa_boyutu!r}")
    yon = _fold(yon)
    if yon not in ("otomatik", "dikey", "yatay"):
        raise ValueError(f"Bilinmeyen yön: {yon!r}")
    doc = fitz.open()
    try:
        for item in sayfalar:
            a = _as_rgb(load_image(item, max_kenar) if isinstance(item, str) else item)
            h, w = a.shape[:2]
            if boyut == "orijinal":
                s = min(1.0, IMAGE_PAGE_MAX_PT / max(w, h))
                pw, ph = w * s, h * s
                m = 0.0
            else:
                pw, ph = PAGE_SIZES[boyut]
                if (w > h) if yon == "otomatik" else (yon == "yatay"):
                    pw, ph = ph, pw
                m = max(0.0, min(float(kenar_bosluk_pt), min(pw, ph) / 2 - 1))
            page = doc.new_page(width=pw, height=ph)
            page.insert_image(fitz.Rect(m, m, pw - m, ph - m), stream=_encode(a, jpeg_kalite), keep_proportion=True)
        if doc.page_count == 0:
            raise ValueError("Taranacak sayfa yok")
        if out_path is None:
            return doc
        tmp = out_path + ".part"
        doc.save(tmp, garbage=3, deflate=True)
        doc.close()
        os.replace(tmp, out_path)
        return out_path
    except Exception:
        if not doc.is_closed:
            doc.close()
        raise


def images_to_pdfs(paths: Sequence[str], out: str, ayri: bool = False, sayfa_boyutu: str = "a4",
                   yon: str = "otomatik", kenar_bosluk_pt: float = 0, jpeg_kalite: int = 85,
                   progress=None, cancelled=None) -> list:
    """Görsel dosyalarını PDF'e çevirir (süzgeçsiz, olduğu gibi). `ayri=False`: hepsi `out` dosyasında
    tek PDF; `ayri=True`: `out` klasörüne her görsel için `<ad>.pdf` (var olan ad bozulmaz, "(2)" eklenir).
    `progress(i, n)`, `cancelled()` isteğe bağlı; iptalde `convert.Cancelled` fırlar ve yazılan dosya kalmaz.
    Yazılan dosya yollarının listesini döndürür."""
    from convert import Cancelled
    paths = list(paths)
    if not paths:
        raise ValueError("Çevrilecek görsel yok")
    n = len(paths)
    opts = dict(sayfa_boyutu=sayfa_boyutu, kenar_bosluk_pt=kenar_bosluk_pt, jpeg_kalite=jpeg_kalite, yon=yon)
    written: list = []

    def step(i):
        if cancelled is not None and cancelled():
            raise Cancelled()
        if progress is not None:
            progress(i, n)

    try:
        if not ayri:
            doc = fitz.open()
            try:
                for i, p in enumerate(paths):
                    step(i)
                    with to_pdf([p], **opts) as one:
                        doc.insert_pdf(one)
                step(n)
                tmp = out + ".part"
                doc.save(tmp, garbage=3, deflate=True)
            finally:
                doc.close()
            os.replace(tmp, out)
            written.append(out)
        else:
            os.makedirs(out, exist_ok=True)
            for i, p in enumerate(paths):
                step(i)
                base = os.path.splitext(os.path.basename(p))[0] + ".pdf"
                dest, k = os.path.join(out, base), 2
                while os.path.exists(dest):
                    dest = os.path.join(out, f"{os.path.splitext(base)[0]} ({k}).pdf")
                    k += 1
                to_pdf([p], dest, **opts)
                written.append(dest)
            step(n)
    except BaseException:
        for f in written + [out + ".part"]:
            if ayri or f.endswith(".part"):
                try:
                    os.remove(f)
                except OSError:
                    pass
        raise
    return written
