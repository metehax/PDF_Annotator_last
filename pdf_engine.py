"""
pdf_engine.py
=============
PyMuPDF (fitz) sarmalayıcısı: sayfa render (LRU önbellekli + asenkron),
metin satırı / arama / içindekiler çıkarımı, sayfa yönetimi (ekle / sil /
kopyala / taşı / döndür), PDF & görsel dışa aktarım, filigran motoru ve
JSON proje kaydı.

Performans ve kaynak yönetimi ilkeleri:
    * `PDFDocument._pix_cache`, en fazla `LRU_CACHE_SIZE` sayfayı tutan bir
      `collections.OrderedDict` tabanlı LRU önbellektir; sınırsız büyümez.
    * Render işlemi `PageRenderTask` (QRunnable) ile arka plan iş
      parçacığında (QThreadPool) yapılır; sonuç bir QImage olarak Qt
      sinyaliyle ana iş parçacığına taşınır (QPixmap yalnızca ana iş
      parçacığında oluşturulur — Qt bunu şart koşar).
    * `fitz.Document` nesnesi tek seferde tek iş parçacığından erişilecek
      şekilde bir `threading.RLock` ile korunur (MuPDF thread-safe değildir).
    * `PDFDocument.close()` dosyayı açıkça kapatır; oturum kapatıldığında
      MainWindow bunu çağırarak dosya kilitlenmelerini ve C seviyesi bellek
      sızıntılarını önler.
"""

from __future__ import annotations

import io
import json
import os
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import pymupdf as fitz

from PySide6.QtCore import QBuffer, QIODevice, QObject, QRunnable, QSize, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from models import (
    Annotation, RedactionAnnotation, WatermarkConfig, qcolor_to_fitz,
)

LRU_CACHE_SIZE = 10          # Render önbelleğinde tutulacak azami sayfa sayısı
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")
IMAGE_PAGE_MAX_PT = 1600.0    # Resimden üretilen sayfanın en uzun kenarı (pt)
RENDER_SCALE = 2.0            # Ekran önizleme render çarpanı


# ---------------------------------------------------------------------------
# LRU önbellek
# ---------------------------------------------------------------------------
class LRUCache:
    """Basit, genel amaçlı LRU önbellek (collections.OrderedDict tabanlı).

    Sınırsız büyüyen sözlüklerin aksine, en fazla `maxsize` girdi tutar;
    kapasite aşıldığında en uzun süredir kullanılmayan girdi atılır.
    """

    def __init__(self, maxsize: int = LRU_CACHE_SIZE):
        self.maxsize = maxsize
        self._data: "OrderedDict[Any, Any]" = OrderedDict()

    def get(self, key):
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def put(self, key, value):
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def pop(self, key, default=None):
        return self._data.pop(key, default)

    def clear(self):
        self._data.clear()

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)


# ---------------------------------------------------------------------------
# Font çözümleme (Türkçe karakter güvenli fallback)
# ---------------------------------------------------------------------------
def find_unicode_font() -> Optional[str]:
    candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        r"C:\Windows\Fonts\verdana.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def resolve_font_ctx() -> Optional[Tuple[str, str]]:
    """('trfont', font_dosya_yolu) ya da bulunamazsa None döner."""
    path = find_unicode_font()
    return ("trfont", path) if path else None


def text_width(text: str, font_ctx: Optional[Tuple[str, str]], fontsize: float) -> float:
    """Metin genişliğini hesaplar. Özel bir gömülü font (font_ctx) varsa
    fitz.get_text_length onun adını tanımaz — bu yüzden fitz.Font(fontfile=…)
    üzerinden ölçülür; yoksa yerleşik 'helv' kullanılır."""
    if font_ctx is not None:
        try:
            return fitz.Font(fontfile=font_ctx[1]).text_length(text, fontsize=fontsize)
        except Exception:
            pass
    return fitz.get_text_length(text, fontname="helv", fontsize=fontsize)


# ---------------------------------------------------------------------------
# Görsel yardımcıları (resim ekleme + filigran motoru ortak kullanır)
# ---------------------------------------------------------------------------
def qimage_to_png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def load_image_bytes_from_path(path: str, target_width: int = 1024) -> bytes:
    """PNG/JPEG/BMP/GIF dosyalarını olduğu gibi okur; SVG'yi Qt'nin kendi
    SVG render motoruyla (QSvgRenderer) yüksek çözünürlükte PNG'ye
    rasterize eder (saydamlık korunur)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".svg":
        renderer = QSvgRenderer(path)
        size = renderer.defaultSize()
        if size.width() <= 0 or size.height() <= 0:
            size = QSize(target_width, target_width)
        aspect = size.height() / size.width() if size.width() else 1.0
        w = target_width
        h = max(1, int(round(w * aspect)))
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        renderer.render(painter)
        painter.end()
        return qimage_to_png_bytes(img)
    with open(path, "rb") as f:
        return f.read()


def bake_opacity_into_image(data: bytes, opacity: float) -> bytes:
    """PyMuPDF'in insert_image'i doğrudan bir saydamlık parametresi kabul
    etmediğinden, istenen opaklığı Pillow ile alfa kanalına gömerek PNG
    olarak yeniden üretir. opacity>=~1 ise veri değiştirilmeden döner."""
    opacity = max(0.0, min(1.0, opacity))
    if opacity >= 0.999:
        return data
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    r, g, b, a = im.split()
    a = a.point(lambda v: int(v * opacity))
    im.putalpha(a)
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def rotate_image_bytes(data: bytes, angle_deg: float) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    rotated = im.rotate(-angle_deg, expand=True, resample=Image.BICUBIC)
    out = io.BytesIO()
    rotated.save(out, format="PNG")
    return out.getvalue()


# ---------------------------------------------------------------------------
# Asenkron sayfa render (QThreadPool / QRunnable)
# ---------------------------------------------------------------------------
class RenderSignals(QObject):
    finished = Signal(int, QImage)
    failed = Signal(int, str)


class PageRenderTask(QRunnable):
    """Bir sayfayı arka plan iş parçacığında piksellere dönüştürür.

    UI donmasını önlemek için ana iş parçacığında ASLA çağrılmamalıdır;
    QThreadPool.start(task) ile zamanlanır. Sonuç QImage olarak sinyalle
    taşınır — QPixmap yalnızca ana iş parçacığında (slot içinde)
    oluşturulmalıdır, aksi halde Qt platformuna göre kararsız davranabilir.
    """

    def __init__(self, pdf: "PDFDocument", index: int, invert: bool = False,
                 scale: float = RENDER_SCALE):
        super().__init__()
        self.pdf = pdf
        self.index = index
        self.invert = invert
        self.scale = scale
        self.signals = RenderSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            img = self.pdf.render_qimage_sync(self.index, self.invert, self.scale)
            self.signals.finished.emit(self.index, img)
        except Exception as ex:  # pragma: no cover - savunmacı
            self.signals.failed.emit(self.index, str(ex))


class SearchSignals(QObject):
    # NOT: Signal(dict) yerine Signal(object) kullanılıyor — PySide6, int
    # anahtarlı / fitz.Rect değerli sözlükleri QVariantMap'e dönüştürmeye
    # çalışıp veri kaybediyor. object ile Python nesnesi olduğu gibi taşınır.
    finished = Signal(object)
    failed = Signal(str)


class SearchTask(QRunnable):
    """Tüm belgede metin arar (page.search_for); büyük belgelerde UI'yi
    kilitlemesin diye arka planda çalışır."""

    def __init__(self, pdf: "PDFDocument", query: str):
        super().__init__()
        self.pdf = pdf
        self.query = query
        self.signals = SearchSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            result = self.pdf.search_document(self.query)
            self.signals.finished.emit(result)
        except Exception as ex:  # pragma: no cover
            self.signals.failed.emit(str(ex))


def is_image_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


def image_to_pdf_document(path: str) -> Tuple["fitz.Document", float]:
    """Resim dosyasını (çok sayfalı TIFF dahil) tek sayfa/kare başına bir PDF
    sayfasına dönüştürür. EXIF yönü uygulanır. Döndürülen ikinci değer,
    sayfayı orijinal piksel çözünürlüğüne geri render etmek için gereken
    zoom çarpanıdır."""
    from PIL import Image, ImageOps, ImageSequence

    doc = fitz.open()
    native_zoom = 1.0
    with Image.open(path) as im:
        is_jpeg = (im.format or "").upper() == "JPEG"
        frames = ImageSequence.Iterator(im) if (im.format or "").upper() == "TIFF" else [im]
        for frame in frames:
            fr = ImageOps.exif_transpose(frame.copy())
            has_alpha = fr.mode in ("RGBA", "LA") or (fr.mode == "P" and "transparency" in fr.info)
            fr = fr.convert("RGBA" if has_alpha else "RGB")
            buf = io.BytesIO()
            if is_jpeg and not has_alpha:
                fr.save(buf, format="JPEG", quality=95)
            else:
                fr.save(buf, format="PNG")
            w, h = fr.size
            scale = min(1.0, IMAGE_PAGE_MAX_PT / max(w, h))
            native_zoom = max(native_zoom, 1.0 / scale)
            page = doc.new_page(width=w * scale, height=h * scale)
            page.insert_image(page.rect, stream=buf.getvalue())
    if doc.page_count == 0:
        raise ValueError("Resimde sayfa bulunamadı")
    return doc, native_zoom


class PasswordRequired(Exception):
    """Belge parolalı ve parola verilmedi / yanlış."""

    def __init__(self, wrong: bool = False):
        super().__init__("Parola gerekli" if not wrong else "Parola yanlış")
        self.wrong = wrong


# ---------------------------------------------------------------------------
# PDF belgesi sarmalayıcı
# ---------------------------------------------------------------------------
class PDFDocument:
    """PyMuPDF belgesini sarar: render (LRU önbellekli + asenkron), metin
    çıkarımı / arama / içindekiler, dışa aktarım ve sayfa yönetimi."""

    def __init__(self, path: str, password: Optional[str] = None):
        self.path = path
        self.is_image = is_image_path(path)
        # Resim kaynaklı belgelerde orijinal piksel boyutuna dönüş çarpanı
        self.native_zoom = 1.0
        if self.is_image:
            self.doc, self.native_zoom = image_to_pdf_document(path)
        else:
            self.doc = fitz.open(path)
        # Parolalı belge: doğru parolayla açılır; bellekteki kopya şifresiz yazılır
        self.was_encrypted = bool(getattr(self.doc, "is_encrypted", False) or self.doc.needs_pass)
        if self.doc.needs_pass:
            if not password or not self.doc.authenticate(password):
                self.doc.close()
                raise PasswordRequired(wrong=bool(password))
        self.lock = threading.RLock()          # MuPDF thread-safety koruması
        self._pix_cache = LRUCache(LRU_CACHE_SIZE)
        self._thumb_cache = LRUCache(64)
        self._lines_cache: Dict[int, list] = {}
        # Metin düzenleme aracı: (sayfa, force_ocr) -> ocr.extract_items sonucu
        self.edit_cache: Dict[Tuple[int, bool], Dict] = {}
        # Görünümün neyi yeniden çizmesi gerektiğini anlaması için sayaçlar:
        # layout_rev -> sayfa sayısı/boyutu değişti, _page_rev -> sayfa içeriği
        self.layout_rev = 0
        self._page_rev: Dict[int, int] = {}
        self._closed = False

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def page_size(self, index: int) -> Tuple[float, float]:
        with self.lock:
            r = self.doc[index].rect
            return r.width, r.height

    def page_rev(self, index: int) -> int:
        return self._page_rev.get(index, 0)

    def page_rotation(self, index: int) -> int:
        with self.lock:
            return int(self.doc[index].rotation)

    # -- önbellek yönetimi --------------------------------------------------
    def _invalidate(self):
        """Sayfa yapısı değiştiğinde (ekle/sil/taşı) TÜM önbellekleri
        temizler; sayfa indeksleri kaymış olabileceğinden kısmi güncelleme
        risklidir."""
        self._pix_cache.clear()
        self._thumb_cache.clear()
        self._lines_cache.clear()
        self.edit_cache.clear()
        self.layout_rev += 1
        self._page_rev.clear()

    def _invalidate_page(self, index: int):
        """Yalnızca tek bir sayfayı geçersiz kılar (ör. döndürme)."""
        self._pix_cache.pop(index)
        self._thumb_cache.pop(index)
        self._lines_cache.pop(index, None)
        for k in [k for k in self.edit_cache if k[0] == index]:
            self.edit_cache.pop(k, None)
        self._page_rev[index] = self._page_rev.get(index, 0) + 1

    # -- render ---------------------------------------------------------
    def render_qimage_sync(self, index: int, invert: bool = False,
                           scale: float = RENDER_SCALE) -> QImage:
        """Senkron, saf render — herhangi bir iş parçacığından çağrılabilir
        (kilit ile korunur). UI'de doğrudan kullanmak yerine PageRenderTask
        üzerinden arka planda çağırın."""
        with self.lock:
            page = self.doc[index]
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            if invert:
                pix.invert_irect()
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format.Format_RGB888).copy()
            return img

    def get_cached_pixmap(self, index: int) -> Optional[QPixmap]:
        return self._pix_cache.get(index)

    def cache_pixmap(self, index: int, pixmap: QPixmap) -> None:
        self._pix_cache.put(index, pixmap)

    def render_pixmap(self, index: int, invert: bool = False) -> QPixmap:
        """Senkron yol: önbellekte varsa direkt döner, yoksa hesaplayıp
        önbelleğe alır. Ana iş parçacığından çağrılmalıdır (QPixmap
        oluşturur). Asenkron akış için make_render_task() kullanın."""
        cached = self.get_cached_pixmap(index)
        if cached is not None:
            return cached
        img = self.render_qimage_sync(index, invert)
        pm = QPixmap.fromImage(img)
        self.cache_pixmap(index, pm)
        return pm

    def make_render_task(self, index: int, invert: bool = False,
                         scale: float = RENDER_SCALE) -> PageRenderTask:
        """Bir arka plan render görevi oluşturur (henüz başlatılmaz).
        Çağıran taraf, race durumunu önlemek için sinyalleri bağladıktan
        SONRA `QThreadPool.globalInstance().start(task)` ile başlatmalıdır.
        """
        return PageRenderTask(self, index, invert, scale)

    def thumbnail(self, index: int, scale: float = 0.2) -> QPixmap:
        cached = self._thumb_cache.get(index)
        if cached is not None:
            return cached
        with self.lock:
            page = self.doc[index]
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format.Format_RGB888).copy()
        pm = QPixmap.fromImage(img)
        self._thumb_cache.put(index, pm)
        return pm

    # -- metin / arama / içindekiler -----------------------------------------
    def text_lines(self, index: int):
        if index not in self._lines_cache:
            with self.lock:
                page = self.doc[index]
                rects = []
                data = page.get_text("dict")
                for block in data.get("blocks", []):
                    if block.get("type", 0) != 0:
                        continue
                    for line in block.get("lines", []):
                        rects.append(fitz.Rect(line["bbox"]))
            self._lines_cache[index] = rects
        return self._lines_cache[index]

    def search_page(self, index: int, query: str) -> List["fitz.Rect"]:
        if not query:
            return []
        with self.lock:
            return list(self.doc[index].search_for(query))

    def search_document(self, query: str) -> Dict[int, List["fitz.Rect"]]:
        results: Dict[int, List["fitz.Rect"]] = {}
        if not query:
            return results
        with self.lock:
            for i in range(self.doc.page_count):
                hits = self.doc[i].search_for(query)
                if hits:
                    results[i] = list(hits)
        return results

    def make_search_task(self, query: str) -> SearchTask:
        return SearchTask(self, query)

    def toc(self) -> List[Tuple[int, str, int]]:
        with self.lock:
            try:
                return self.doc.get_toc(simple=True)
            except Exception:
                return []

    # -- sayfa yönetimi ---------------------------------------------------
    def delete_page(self, index: int):
        with self.lock:
            self.doc.delete_page(index)
        self._invalidate()

    def insert_blank_page(self, index: int, width: float, height: float):
        with self.lock:
            self.doc.new_page(pno=index, width=width, height=height)
        self._invalidate()

    def duplicate_page(self, index: int):
        with self.lock:
            self.doc.copy_page(index, to=index)
        self._invalidate()

    def move_page(self, frm: int, to: int):
        with self.lock:
            self.doc.move_page(frm, to)
        self._invalidate()

    def rotate_page(self, index: int, delta_degrees: int):
        """Sayfayı 90°'nin katları kadar döndürür (fitz sayfasının kendi
        /Rotate özelliğine yazılır). PyMuPDF, page.rect ve get_pixmap()
        çıktısını otomatik olarak döndürülmüş boyuta göre üretir; bu sayede
        önizleme ve dışa aktarım EK bir koordinat dönüşümüne gerek kalmadan
        doğru hizalanır. NOT: döndürmeden ÖNCE eklenmiş işaretlerin (x,y)
        koordinatları eski eksen takımına göredir — döndürme sonrası
        kayabilirler (çağıran taraf kullanıcıyı uyarmalıdır)."""
        with self.lock:
            page = self.doc[index]
            page.set_rotation((page.rotation + delta_degrees) % 360)
        self._invalidate_page(index)
        self.layout_rev += 1

    def set_absolute_rotation(self, index: int, degrees: int):
        """JSON proje dosyasından döndürme durumunu geri yüklerken kullanılır."""
        with self.lock:
            self.doc[index].set_rotation(int(degrees) % 360)
        self._invalidate_page(index)
        self.layout_rev += 1

    # -- kaynak temizliği ----------------------------------------------------
    def close(self):
        """Dosya kilitlenmelerini önlemek için PyMuPDF belgesini açıkça
        kapatır; tekrar çağrılması güvenlidir (idempotent)."""
        if self._closed:
            return
        with self.lock:
            try:
                self.doc.close()
            finally:
                self._closed = True
        self._invalidate()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # -- dışa aktarım -------------------------------------------------------
    def _annotated_copy(self, annotations_by_page: Dict[int, List[Annotation]], font_ctx) -> "fitz.Document":
        with self.lock:
            tmp = fitz.open("pdf", self.doc.write())
        for pidx, anns in annotations_by_page.items():
            if not anns:
                continue
            page = tmp[pidx]
            redactions = [a for a in anns if isinstance(a, RedactionAnnotation)]
            others = [a for a in anns if not isinstance(a, RedactionAnnotation)]
            for r in redactions:
                r.apply_to_page(page, font_ctx)
            if redactions:
                page.apply_redactions()
            for a in others:
                a.apply_to_page(page, font_ctx)
        return tmp

    def export_pdf(self, out_path: str, annotations_by_page, font_ctx,
                    watermark: Optional[WatermarkConfig] = None, security=None,
                    compress: Optional[str] = None) -> None:
        """security: docsec.SecurityOptions (parola/izinler), compress: docsec seviye anahtarı."""
        tmp = self._annotated_copy(annotations_by_page, font_ctx)
        if watermark is not None:
            current_index = 0
            pages = (list(range(tmp.page_count)) if watermark.scope != "current"
                     else [current_index])
            apply_watermark_to_pages(tmp, watermark, font_ctx, pages)
        from docsec import apply_compression, save_kwargs
        kwargs = apply_compression(tmp, compress)
        kwargs.update(save_kwargs(security))
        tmp.save(out_path, **kwargs)
        tmp.close()

    def export_image(self, index: int, page_annotations, font_ctx, out_path: str,
                      zoom: Optional[float] = None) -> None:
        if zoom is None:
            # Resim kaynaklıysa orijinal çözünürlükte, PDF ise 3x
            zoom = self.native_zoom if self.is_image else 3.0
        tmp = self._annotated_copy({index: page_annotations}, font_ctx)
        pix = tmp[index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        tmp.close()
        ext = os.path.splitext(out_path)[1].lower()
        if ext in (".png", ".jpg", ".jpeg"):
            pix.save(out_path, jpg_quality=95)
            return
        from PIL import Image
        im = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        im.save(out_path)


# ---------------------------------------------------------------------------
# Filigran (Watermark) motoru
# ---------------------------------------------------------------------------
def _item_base_size(config: WatermarkConfig, page_rect: "fitz.Rect",
                     font_ctx=None) -> Tuple[float, float]:
    if config.mode == "text":
        w = text_width(config.text or " ", font_ctx, config.font_size) or config.font_size
        h = config.font_size * 1.3
        return w, h
    scale = max(0.02, min(1.0, config.image_scale))
    w = page_rect.width * scale
    ar = 1.0
    if config.image_bytes:
        img = QImage()
        img.loadFromData(config.image_bytes)
        if img.width():
            ar = img.height() / img.width()
    return w, w * ar


def _draw_watermark_item(page: "fitz.Page", config: WatermarkConfig, font_ctx, cx: float, cy: float) -> None:
    if config.mode == "text":
        if not config.text:
            return
        color = qcolor_to_fitz(config.color)
        tw = text_width(config.text, font_ctx, config.font_size)
        baseline = fitz.Point(cx - tw / 2, cy + config.font_size * 0.35)
        morph = (fitz.Point(cx, cy), fitz.Matrix(config.rotation))
        kwargs = dict(fontsize=config.font_size, color=color,
                      fill_opacity=config.opacity, morph=morph)
        try:
            if font_ctx is not None:
                page.insert_text(baseline, config.text, fontname=font_ctx[0],
                                  fontfile=font_ctx[1], **kwargs)
            else:
                page.insert_text(baseline, config.text, fontname="helv", **kwargs)
        except Exception:
            pass
    else:
        if not config.image_bytes:
            return
        rotated = rotate_image_bytes(config.image_bytes, config.rotation) if config.rotation else config.image_bytes
        stream = bake_opacity_into_image(rotated, config.opacity)
        img = QImage()
        img.loadFromData(stream)
        base_w, _base_h = _item_base_size(config, page.rect, font_ctx)
        ar = (img.height() / img.width()) if img.width() else 1.0
        rw, rh = base_w, base_w * ar
        rect = fitz.Rect(cx - rw / 2, cy - rh / 2, cx + rw / 2, cy + rh / 2)
        try:
            page.insert_image(rect, stream=stream, keep_proportion=False, overlay=True)
        except Exception:
            pass


def _draw_tiled_watermark(page: "fitz.Page", config: WatermarkConfig, font_ctx) -> None:
    rect = page.rect
    bw, bh = _item_base_size(config, rect, font_ctx)
    step_x = max(bw * config.tile_spacing, 20.0)
    step_y = max(bh * config.tile_spacing, 20.0)
    y = step_y / 2
    row = 0
    while y < rect.height + step_y:
        offset = (step_x / 2) if (row % 2) else 0.0
        x = offset
        while x < rect.width + step_x:
            _draw_watermark_item(page, config, font_ctx, x, y)
            x += step_x
        y += step_y
        row += 1


def apply_watermark_to_pages(doc: "fitz.Document", config: WatermarkConfig, font_ctx,
                              page_indices: List[int]) -> None:
    for idx in page_indices:
        if 0 <= idx < doc.page_count:
            page = doc[idx]
            if config.layout == "tiled":
                _draw_tiled_watermark(page, config, font_ctx)
            else:
                rect = page.rect
                _draw_watermark_item(page, config, font_ctx, rect.width / 2, rect.height / 2)


def apply_watermark_to_document(doc: "fitz.Document", config: WatermarkConfig, font_ctx,
                                 current_index: int = 0) -> None:
    """Kapsam seçimine göre (aktif sayfa / aralık / tüm belge) filigranı
    uygular. `doc` zaten bir çalışma kopyası olmalıdır (kalıcı belge
    üzerinde doğrudan çağrılmaz)."""
    pages = config.pages_for(doc.page_count, current_index)
    apply_watermark_to_pages(doc, config, font_ctx, pages)


# ---------------------------------------------------------------------------
# JSON proje kaydı
# ---------------------------------------------------------------------------
def save_project_json(path: str, session) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session.to_project_dict(), f, ensure_ascii=False, indent=2)


def load_project_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
