"""
models.py
=========
PDF İşaretleme Aracı — veri modeli katmanı.

Bu modül; PDF üzerine konan işaretlerin (annotation) nesne modelini, resim
yerleştirme ve filigran yapılandırmasını, araç durumunu (ToolState), aktif
bir PDF oturumunun tüm durumunu (DocumentSession) ve Qt'nin yerleşik
QUndoStack mimarisine bağlı komut (QUndoCommand) sınıflarını içerir.

Tasarım ilkeleri:
    * Koordinatlar HER ZAMAN PDF puntosu (72 dpi) cinsindendir; ekran/ölçek
      dönüşümü görünüm (views.py) katmanında yapılır.
    * Her Annotation dört şeyi bilir: create_item() (Qt sahne nesnesi),
      apply_to_page() (PyMuPDF'e kalıcı yazma), translate() (taşıma) ve
      to_dict()/from_dict() (JSON proje serileştirme).
    * Yeniden boyutlandırılabilen türler (Şekil, Vurgu, Sansür, Metin,
      Resim, Numara) ayrıca get_rect()/set_rect() sağlar; gizmo.py bu arayüz
      üzerinden 8 noktalı kulpları çizer.
    * Geçmiş (undo/redo) işlemleri, DocumentSession.undo_stack (QUndoStack)
      üzerinden QUndoCommand alt sınıflarıyla yürütülür.
"""

from __future__ import annotations

import math
import os
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import pymupdf as fitz

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QPainterPath, QPen, QPixmap, QTransform,
    QUndoCommand, QUndoStack,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsItemGroup, QGraphicsPathItem,
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsSimpleTextItem,
    QGraphicsTextItem,
)

RENDER_SCALE = 2.0          # Sayfa render çözünürlük çarpanı (ekran önizleme)
LRU_CACHE_SIZE = 10          # PDFDocument render önbelleğinin tutacağı sayfa sayısı


# ---------------------------------------------------------------------------
# Küçük yardımcılar
# ---------------------------------------------------------------------------
def qcolor_to_fitz(color: Optional[QColor]) -> Optional[Tuple[float, float, float]]:
    if color is None:
        return None
    return (color.redF(), color.greenF(), color.blueF())


def color_to_hex_alpha(color: QColor) -> str:
    """#RRGGBBAA biçiminde, alfa dahil geri döndürülebilir string."""
    return color.name(QColor.NameFormat.HexArgb)


def color_from_hex_alpha(s: str) -> QColor:
    return QColor(s)


def number_to_color(n: int, saturation: int = 200, value: int = 225) -> QColor:
    """Her numaraya HER ZAMAN aynı, birbirinden ayırt edilebilir bir renk
    üretir (altın açı / golden-angle hue dağılımı). Saf bir n->renk
    fonksiyonu olduğundan iki farklı PDF'te bile aynı numara her zaman aynı
    rengi alır; karşılaştırma modunda ekstra bir eşleme mekanizması gerekmez.
    """
    hue = int((n * 137.508) % 360)
    c = QColor()
    c.setHsv(hue, saturation, value)
    return c


def arrow_wing_points(p1, p2, size: float = 12.0, angle_deg: float = 28.0):
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1e-6
    back = (-dx / length, -dy / length)
    ang = math.radians(angle_deg)

    def rot(vx, vy, theta):
        return (vx * math.cos(theta) - vy * math.sin(theta),
                vx * math.sin(theta) + vy * math.cos(theta))

    w1 = rot(*back, ang)
    w2 = rot(*back, -ang)
    return ((x2 + w1[0] * size, y2 + w1[1] * size),
            (x2 + w2[0] * size, y2 + w2[1] * size))


def catmull_rom_to_beziers(points: List[Tuple[float, float]]
                            ) -> List[Tuple[Tuple[float, float], Tuple[float, float],
                                             Tuple[float, float], Tuple[float, float]]]:
    """Bir nokta dizisini (serbest çizim) düzgün bir eğriye dönüştürür.

    Uniform Catmull-Rom eğrisini, her ardışık nokta çifti için bir kübik
    Bézier segmentine çevirir (klasik 1/6 teğet formülü). Sonuç, hem Qt
    sahnesinde (QPainterPath.cubicTo) hem de PyMuPDF'e yazarken
    (page.draw_bezier) doğrudan kullanılabilir — böylece ekranda görünen
    çizgi ile PDF'e gömülen çizgi birebir aynı şekli alır.

    En az 3 nokta gerektirir; daha azı için None döner (çağıran taraf düz
    çizgiye / tek noktaya düşer).
    """
    n = len(points)
    if n < 3:
        return []
    pts = [points[0]] + list(points) + [points[-1]]
    segments = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
        segments.append((p1, c1, c2, p2))
    return segments


# ---------------------------------------------------------------------------
# Annotation model ailesi
# ---------------------------------------------------------------------------
_ANNOTATION_REGISTRY: Dict[str, type] = {}


def _register(type_name: str):
    def deco(cls):
        cls.TYPE = type_name
        _ANNOTATION_REGISTRY[type_name] = cls
        return cls
    return deco


class Annotation:
    """Tüm işaret türlerinin ortak arayüzü."""

    TYPE: str = "base"

    def __init__(self) -> None:
        self.uid: str = uuid.uuid4().hex

    # -- Qt sahnesi -----------------------------------------------------
    def create_item(self) -> QGraphicsItem:
        raise NotImplementedError

    # -- PyMuPDF'e kalıcı yazma ------------------------------------------
    def apply_to_page(self, page: "fitz.Page", font_ctx) -> None:
        raise NotImplementedError

    # -- taşıma -----------------------------------------------------------
    def translate(self, dx: float, dy: float) -> None:
        raise NotImplementedError

    # -- yeniden boyutlandırma (gizmo.py bu arayüzü kullanır) --------------
    def get_rect(self) -> Optional[QRectF]:
        return None

    def set_rect(self, rect: QRectF) -> None:
        pass

    def is_resizable(self) -> bool:
        return self.get_rect() is not None

    # -- JSON proje serileştirme -------------------------------------------
    def to_dict(self) -> dict:
        raise NotImplementedError

    @staticmethod
    def from_dict(d: dict) -> "Annotation":
        cls = _ANNOTATION_REGISTRY[d["type"]]
        return cls._from_dict(d)

    @classmethod
    def _from_dict(cls, d: dict) -> "Annotation":
        raise NotImplementedError


@_register("text")
class TextAnnotation(Annotation):
    """Çok satırlı metin notu. PDF'e insert_textbox ile yazılır (satır
    kaydırmalarını doğru işler); Türkçe karakterler için güvenli font
    fallback mekanizması PDFEngine.resolve_font() tarafından sağlanır."""

    def __init__(self, rect: QRectF, text: str, color: QColor, size: float,
                 font_family: str = "Arial"):
        super().__init__()
        self.rect = QRectF(rect)
        self.text = text
        self.color = QColor(color)
        self.size = float(size)
        self.font_family = font_family

    def create_item(self) -> QGraphicsItem:
        item = QGraphicsTextItem(self.text)
        font = QFont(self.font_family)
        font.setPointSizeF(max(1.0, self.size))
        item.setFont(font)
        item.setDefaultTextColor(self.color)
        item.setPos(self.rect.topLeft())
        item.setTextWidth(max(20.0, self.rect.width()))
        return item

    def apply_to_page(self, page, font_ctx) -> None:
        r = fitz.Rect(self.rect.left(), self.rect.top(), self.rect.right(), self.rect.bottom())
        color = qcolor_to_fitz(self.color)
        kwargs = dict(fontsize=self.size, color=color, fill_opacity=1, align=0, lineheight=1.15)
        from fonts import pdf_font_ctx
        font_ctx = pdf_font_ctx(self.font_family) or font_ctx
        if font_ctx is not None:
            rc = page.insert_textbox(r, self.text, fontname=font_ctx[0], fontfile=font_ctx[1], **kwargs)
        else:
            rc = page.insert_textbox(r, self.text, fontname="helv", **kwargs)
        if rc < 0:
            # Kutu metne sığmadı: aynı genişlikte, yeterince uzun bir kutuyla
            # tekrar dene ki metin asla sessizce kaybolmasın.
            grown = fitz.Rect(r.x0, r.y0, r.x1, r.y1 + abs(rc) + self.size * 2)
            if font_ctx is not None:
                page.insert_textbox(grown, self.text, fontname=font_ctx[0],
                                     fontfile=font_ctx[1], **kwargs)
            else:
                page.insert_textbox(grown, self.text, fontname="helv", **kwargs)

    def translate(self, dx, dy) -> None:
        self.rect.translate(dx, dy)

    def get_rect(self) -> Optional[QRectF]:
        return QRectF(self.rect)

    def set_rect(self, rect: QRectF) -> None:
        old_h = max(1.0, self.rect.height())
        self.rect = QRectF(rect)
        # Kutunun yüksekliği oranında punto boyutunu da ölçekle ki metin
        # kutuya görsel olarak orantılı kalsın.
        scale = max(0.1, self.rect.height() / old_h)
        self.size = max(4.0, self.size * scale) if abs(scale - 1.0) > 1e-6 else self.size

    def to_dict(self) -> dict:
        return dict(type=self.TYPE, uid=self.uid,
                    rect=[self.rect.x(), self.rect.y(), self.rect.width(), self.rect.height()],
                    text=self.text, color=color_to_hex_alpha(self.color), size=self.size,
                    font_family=self.font_family)

    @classmethod
    def _from_dict(cls, d):
        x, y, w, h = d["rect"]
        obj = cls(QRectF(x, y, w, h), d["text"], color_from_hex_alpha(d["color"]), d["size"],
                  d.get("font_family", "Arial"))
        obj.uid = d.get("uid", obj.uid)
        return obj


@_register("ink")
class InkAnnotation(Annotation):
    """Serbest çizim. Catmull-Rom -> kübik Bézier dönüşümüyle yumuşatılır;
    hem ekran çizimi hem PDF çıktısı aynı eğri segmentlerini kullanır."""

    def __init__(self, points, color: QColor, width: float, opacity: float = 1.0):
        super().__init__()
        self.points: List[Tuple[float, float]] = [tuple(p) for p in points]
        self.color = QColor(color)
        self.width = float(width)
        self.opacity = float(opacity)

    def _segments(self):
        return catmull_rom_to_beziers(self.points)

    def create_item(self) -> QGraphicsItem:
        path = QPainterPath()
        segs = self._segments()
        if segs:
            path.moveTo(*self.points[0])
            for _p0, c1, c2, p3 in segs:
                path.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(*p3))
        elif self.points:
            path.moveTo(*self.points[0])
            for p in self.points[1:]:
                path.lineTo(*p)
            if len(self.points) == 1:
                path.lineTo(self.points[0][0] + 0.1, self.points[0][1])
        item = QGraphicsPathItem(path)
        pen = QPen(self.color, self.width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        c = QColor(self.color)
        c.setAlphaF(self.opacity)
        pen.setColor(c)
        item.setPen(pen)
        return item

    def apply_to_page(self, page, font_ctx) -> None:
        color = qcolor_to_fitz(self.color)
        segs = self._segments()
        if segs:
            for p0, c1, c2, p3 in segs:
                page.draw_bezier(fitz.Point(*p0), fitz.Point(*c1), fitz.Point(*c2), fitz.Point(*p3),
                                  color=color, width=self.width, stroke_opacity=self.opacity,
                                  lineCap=1, lineJoin=1)
        elif len(self.points) == 1:
            page.draw_circle(fitz.Point(*self.points[0]), self.width / 2, color=color, fill=color,
                              stroke_opacity=self.opacity, fill_opacity=self.opacity)
        elif len(self.points) == 2:
            page.draw_line(fitz.Point(*self.points[0]), fitz.Point(*self.points[1]),
                            color=color, width=self.width, stroke_opacity=self.opacity, lineCap=1)

    def translate(self, dx, dy) -> None:
        self.points = [(x + dx, y + dy) for x, y in self.points]

    def to_dict(self) -> dict:
        return dict(type=self.TYPE, uid=self.uid, points=[list(p) for p in self.points],
                    color=color_to_hex_alpha(self.color), width=self.width, opacity=self.opacity)

    @classmethod
    def _from_dict(cls, d):
        obj = cls([tuple(p) for p in d["points"]], color_from_hex_alpha(d["color"]),
                  d["width"], d.get("opacity", 1.0))
        obj.uid = d.get("uid", obj.uid)
        return obj


@_register("line")
class LineAnnotation(Annotation):
    def __init__(self, p1, p2, color: QColor, width: float,
                 opacity: float = 1.0, arrow: bool = True):
        super().__init__()
        self.p1, self.p2 = tuple(p1), tuple(p2)
        self.color = QColor(color)
        self.width = float(width)
        self.opacity = float(opacity)
        self.arrow = arrow

    def _segments(self):
        segs = [(self.p1, self.p2)]
        if self.arrow:
            w1, w2 = arrow_wing_points(self.p1, self.p2, size=max(10.0, self.width * 3.5))
            segs.append((self.p2, w1))
            segs.append((self.p2, w2))
        return segs

    def create_item(self) -> QGraphicsItem:
        path = QPainterPath()
        for a, b in self._segments():
            path.moveTo(*a)
            path.lineTo(*b)
        item = QGraphicsPathItem(path)
        pen = QPen(self.color, self.width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        c = QColor(self.color)
        c.setAlphaF(self.opacity)
        pen.setColor(c)
        item.setPen(pen)
        return item

    def apply_to_page(self, page, font_ctx) -> None:
        color = qcolor_to_fitz(self.color)
        for a, b in self._segments():
            page.draw_line(fitz.Point(*a), fitz.Point(*b), color=color,
                            width=self.width, stroke_opacity=self.opacity, lineCap=1)

    def translate(self, dx, dy) -> None:
        self.p1 = (self.p1[0] + dx, self.p1[1] + dy)
        self.p2 = (self.p2[0] + dx, self.p2[1] + dy)

    def to_dict(self) -> dict:
        return dict(type=self.TYPE, uid=self.uid, p1=list(self.p1), p2=list(self.p2),
                    color=color_to_hex_alpha(self.color), width=self.width,
                    opacity=self.opacity, arrow=self.arrow)

    @classmethod
    def _from_dict(cls, d):
        obj = cls(tuple(d["p1"]), tuple(d["p2"]), color_from_hex_alpha(d["color"]),
                  d["width"], d.get("opacity", 1.0), d.get("arrow", True))
        obj.uid = d.get("uid", obj.uid)
        return obj


@_register("shape")
class ShapeAnnotation(Annotation):
    def __init__(self, rect: QRectF, kind: str, fill: Optional[QColor], outline: Optional[QColor],
                 width: float, fill_opacity: float):
        super().__init__()
        self.rect = QRectF(rect).normalized()
        self.kind = kind  # "rect" | "oval"
        self.fill = QColor(fill) if fill else None
        self.outline = QColor(outline) if outline else None
        self.width = float(width)
        self.fill_opacity = float(fill_opacity)

    def create_item(self) -> QGraphicsItem:
        item = (QGraphicsEllipseItem(self.rect) if self.kind == "oval"
                else QGraphicsRectItem(self.rect))
        if self.fill is not None:
            fc = QColor(self.fill)
            fc.setAlphaF(self.fill_opacity)
            item.setBrush(QBrush(fc))
        else:
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        if self.outline is not None and self.width > 0:
            item.setPen(QPen(self.outline, self.width))
        else:
            item.setPen(QPen(Qt.PenStyle.NoPen))
        return item

    def apply_to_page(self, page, font_ctx) -> None:
        r = fitz.Rect(self.rect.left(), self.rect.top(), self.rect.right(), self.rect.bottom())
        fill = qcolor_to_fitz(self.fill)
        outline = qcolor_to_fitz(self.outline)
        common = dict(color=outline, fill=fill, width=self.width if outline else 0,
                      fill_opacity=self.fill_opacity, stroke_opacity=1)
        (page.draw_oval if self.kind == "oval" else page.draw_rect)(r, **common)

    def translate(self, dx, dy) -> None:
        self.rect.translate(dx, dy)

    def get_rect(self) -> Optional[QRectF]:
        return QRectF(self.rect)

    def set_rect(self, rect: QRectF) -> None:
        self.rect = QRectF(rect).normalized()

    def to_dict(self) -> dict:
        return dict(type=self.TYPE, uid=self.uid,
                    rect=[self.rect.x(), self.rect.y(), self.rect.width(), self.rect.height()],
                    kind=self.kind,
                    fill=color_to_hex_alpha(self.fill) if self.fill else None,
                    outline=color_to_hex_alpha(self.outline) if self.outline else None,
                    width=self.width, fill_opacity=self.fill_opacity)

    @classmethod
    def _from_dict(cls, d):
        x, y, w, h = d["rect"]
        fill = color_from_hex_alpha(d["fill"]) if d.get("fill") else None
        outline = color_from_hex_alpha(d["outline"]) if d.get("outline") else None
        obj = cls(QRectF(x, y, w, h), d["kind"], fill, outline, d["width"], d["fill_opacity"])
        obj.uid = d.get("uid", obj.uid)
        return obj


@_register("highlight")
class HighlightAnnotation(Annotation):
    def __init__(self, rect: QRectF, color: QColor, opacity: float):
        super().__init__()
        self.rect = QRectF(rect).normalized()
        self.color = QColor(color)
        self.opacity = float(opacity)

    def create_item(self) -> QGraphicsItem:
        item = QGraphicsRectItem(self.rect)
        c = QColor(self.color)
        c.setAlphaF(self.opacity)
        item.setBrush(QBrush(c))
        item.setPen(QPen(Qt.PenStyle.NoPen))
        return item

    def apply_to_page(self, page, font_ctx) -> None:
        r = fitz.Rect(self.rect.left(), self.rect.top(), self.rect.right(), self.rect.bottom())
        page.draw_rect(r, color=None, fill=qcolor_to_fitz(self.color), fill_opacity=self.opacity)

    def translate(self, dx, dy) -> None:
        self.rect.translate(dx, dy)

    def get_rect(self) -> Optional[QRectF]:
        return QRectF(self.rect)

    def set_rect(self, rect: QRectF) -> None:
        self.rect = QRectF(rect).normalized()

    def to_dict(self) -> dict:
        return dict(type=self.TYPE, uid=self.uid,
                    rect=[self.rect.x(), self.rect.y(), self.rect.width(), self.rect.height()],
                    color=color_to_hex_alpha(self.color), opacity=self.opacity)

    @classmethod
    def _from_dict(cls, d):
        x, y, w, h = d["rect"]
        obj = cls(QRectF(x, y, w, h), color_from_hex_alpha(d["color"]), d["opacity"])
        obj.uid = d.get("uid", obj.uid)
        return obj


@_register("redaction")
class RedactionAnnotation(Annotation):
    """Gerçek sansürleme: dışa aktarırken altındaki içeriği kalıcı siler."""

    def __init__(self, rect: QRectF, fill_color: QColor, quiet: bool = False):
        super().__init__()
        self.rect = QRectF(rect).normalized()
        self.fill_color = QColor(fill_color)
        # quiet=True: metin düzenleme aracının "orijinali sil" adımı (kırmızı
        # kesikli kenarlık gösterilmez, katman adı farklıdır).
        self.quiet = bool(quiet)

    def create_item(self) -> QGraphicsItem:
        item = QGraphicsRectItem(self.rect)
        item.setBrush(QBrush(QColor(self.fill_color)))
        if self.quiet:
            item.setPen(QPen(Qt.PenStyle.NoPen))
        else:
            item.setPen(QPen(QColor("#ff4d4d"), 1.5, Qt.PenStyle.DashLine))
        return item

    def apply_to_page(self, page, font_ctx) -> None:
        r = fitz.Rect(self.rect.left(), self.rect.top(), self.rect.right(), self.rect.bottom())
        page.add_redact_annot(r, fill=qcolor_to_fitz(self.fill_color) or (0, 0, 0))

    def translate(self, dx, dy) -> None:
        self.rect.translate(dx, dy)

    def get_rect(self) -> Optional[QRectF]:
        return QRectF(self.rect)

    def set_rect(self, rect: QRectF) -> None:
        self.rect = QRectF(rect).normalized()

    def to_dict(self) -> dict:
        return dict(type=self.TYPE, uid=self.uid,
                    rect=[self.rect.x(), self.rect.y(), self.rect.width(), self.rect.height()],
                    fill_color=color_to_hex_alpha(self.fill_color), quiet=self.quiet)

    @classmethod
    def _from_dict(cls, d):
        x, y, w, h = d["rect"]
        obj = cls(QRectF(x, y, w, h), color_from_hex_alpha(d["fill_color"]), d.get("quiet", False))
        obj.uid = d.get("uid", obj.uid)
        return obj


@_register("number")
class NumberAnnotation(Annotation):
    """Otomatik numaralandırma: renkli daire + içinde beyaz sayı."""

    def __init__(self, x, y, number: int, color: QColor, size: float):
        super().__init__()
        self.x, self.y = float(x), float(y)
        self.number = int(number)
        self.color = QColor(color)
        self.size = float(size)

    def create_item(self) -> QGraphicsItem:
        r = self.size * 0.9
        group = QGraphicsItemGroup()
        ellipse = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
        ellipse.setBrush(QBrush(QColor(self.color)))
        ellipse.setPen(QPen(Qt.PenStyle.NoPen))
        group.addToGroup(ellipse)

        text = QGraphicsSimpleTextItem(str(self.number))
        font = QFont()
        font.setPixelSize(max(1, int(round(self.size))))
        font.setBold(True)
        text.setFont(font)
        text.setBrush(QBrush(QColor("#ffffff")))
        tb = text.boundingRect()
        text.setPos(-tb.width() / 2, -tb.height() / 2)
        group.addToGroup(text)

        group.setPos(self.x, self.y)
        return group

    def apply_to_page(self, page, font_ctx) -> None:
        color = qcolor_to_fitz(self.color)
        r = self.size * 0.9
        page.draw_circle(fitz.Point(self.x, self.y), r, color=color, fill=color)
        text = str(self.number)
        tw = fitz.get_text_length(text, fontname="hebo", fontsize=self.size)
        baseline = fitz.Point(self.x - tw / 2, self.y + self.size * 0.35)
        page.insert_text(baseline, text, fontsize=self.size, color=(1, 1, 1), fontname="hebo")

    def translate(self, dx, dy) -> None:
        self.x += dx
        self.y += dy

    def get_rect(self) -> Optional[QRectF]:
        r = self.size * 0.9
        return QRectF(self.x - r, self.y - r, 2 * r, 2 * r)

    def set_rect(self, rect: QRectF) -> None:
        r = max(4.0, (rect.width() + rect.height()) / 4.0)
        self.size = r / 0.9
        self.x = rect.center().x()
        self.y = rect.center().y()

    def to_dict(self) -> dict:
        return dict(type=self.TYPE, uid=self.uid, x=self.x, y=self.y, number=self.number,
                    color=color_to_hex_alpha(self.color), size=self.size)

    @classmethod
    def _from_dict(cls, d):
        obj = cls(d["x"], d["y"], d["number"], color_from_hex_alpha(d["color"]), d["size"])
        obj.uid = d.get("uid", obj.uid)
        return obj


@_register("image")
class ImageAnnotation(Annotation):
    """Sayfa üzerine yerleştirilen resim (PNG/JPEG/SVG rasterize edilmiş/
    pano). Saydamlık, dışa aktarırken Pillow ile alfa kanalına gömülür ki
    PDF görüntüleyicisi ne olursa olsun aynı görünsün."""

    def __init__(self, rect: QRectF, image_bytes: bytes, opacity: float = 1.0,
                 keep_aspect: bool = True, source_path: Optional[str] = None):
        super().__init__()
        self.rect = QRectF(rect)
        self.image_bytes = image_bytes    # her zaman PNG/JPEG ham verisi
        self.opacity = float(opacity)
        self.keep_aspect = keep_aspect
        self.source_path = source_path
        self._qimage_cache: Optional[QImage] = None

    def _qimage(self) -> QImage:
        if self._qimage_cache is None:
            img = QImage()
            img.loadFromData(self.image_bytes)
            self._qimage_cache = img
        return self._qimage_cache

    def native_size(self) -> Tuple[int, int]:
        img = self._qimage()
        return (img.width() or 1, img.height() or 1)

    def create_item(self) -> QGraphicsItem:
        pm = QPixmap.fromImage(self._qimage())
        item = QGraphicsPixmapItem(pm)
        if pm.width() and pm.height():
            sx = self.rect.width() / pm.width()
            sy = self.rect.height() / pm.height()
            t = QTransform()
            t.scale(sx if sx else 1.0, sy if sy else 1.0)
            item.setTransform(t)
        item.setPos(self.rect.topLeft())
        item.setOpacity(max(0.0, min(1.0, self.opacity)))
        return item

    def apply_to_page(self, page, font_ctx) -> None:
        from pdf_engine import bake_opacity_into_image  # local import: döngüsel bağımlılığı önler
        r = fitz.Rect(self.rect.left(), self.rect.top(), self.rect.right(), self.rect.bottom())
        stream = bake_opacity_into_image(self.image_bytes, self.opacity)
        page.insert_image(r, stream=stream, keep_proportion=False, overlay=True)

    def translate(self, dx, dy) -> None:
        self.rect.translate(dx, dy)

    def get_rect(self) -> Optional[QRectF]:
        return QRectF(self.rect)

    def set_rect(self, rect: QRectF) -> None:
        self.rect = QRectF(rect)
        self._qimage_cache = self._qimage_cache  # pixmap yeniden ölçeklenir, veri sabit kalır

    def to_dict(self) -> dict:
        import base64
        return dict(type=self.TYPE, uid=self.uid,
                    rect=[self.rect.x(), self.rect.y(), self.rect.width(), self.rect.height()],
                    image_b64=base64.b64encode(self.image_bytes).decode("ascii"),
                    opacity=self.opacity, keep_aspect=self.keep_aspect,
                    source_path=self.source_path)

    @classmethod
    def _from_dict(cls, d):
        import base64
        x, y, w, h = d["rect"]
        data = base64.b64decode(d["image_b64"])
        obj = cls(QRectF(x, y, w, h), data, d.get("opacity", 1.0),
                  d.get("keep_aspect", True), d.get("source_path"))
        obj.uid = d.get("uid", obj.uid)
        return obj


# ---------------------------------------------------------------------------
# Filigran (Watermark) yapılandırması
# ---------------------------------------------------------------------------
@dataclass
class WatermarkConfig:
    mode: str = "text"                       # "text" | "image"
    text: str = "TASLAK"
    font_size: float = 48.0
    color: QColor = field(default_factory=lambda: QColor("#c0392b"))
    opacity: float = 0.30
    rotation: float = 45.0                   # -90..+90, varsayılan 45°
    image_bytes: Optional[bytes] = None
    image_scale: float = 1.0                 # 0..1 arası; sayfa genişliğine oran
    layout: str = "single"                   # "single" | "tiled"
    tile_spacing: float = 1.6                 # döşemede öge başına boşluk çarpanı
    scope: str = "all"                       # "current" | "range" | "all"
    page_start: int = 1
    page_end: int = 1

    def pages_for(self, page_count: int, current_index: int) -> List[int]:
        if self.scope == "current":
            return [current_index]
        if self.scope == "range":
            lo = max(1, min(self.page_start, page_count))
            hi = max(1, min(self.page_end, page_count))
            if lo > hi:
                lo, hi = hi, lo
            return list(range(lo - 1, hi))
        return list(range(page_count))


# ---------------------------------------------------------------------------
# Araç durumu
# ---------------------------------------------------------------------------
class ToolState:
    def __init__(self) -> None:
        self.tool = "select"
        self.stroke_color = QColor("#e63946")
        self.fill_color = QColor("#ffd166")
        self.text_color = QColor("#1d3557")
        self.hl_color = QColor("#fff176")
        self.redact_color = QColor("#000000")
        self.number_color = QColor("#e63946")
        self.pen_width = 3.0
        self.pen_opacity = 1.0
        self.font_size = 20.0
        self.font_family = "Arial"
        self.edit_force_ocr = False      # Metin Düzenle: gerçek metin olsa da OCR kullan
        self.edit_mode = "line"          # "line" | "block"
        self.hl_thickness = 14.0
        self.fill_opacity = 0.40
        self.snap = True
        self.line_arrow = True
        self.number_start = 1
        self.number_size = 18.0
        self.number_multicolor = False
        self.number_pair_mode = False
        self.image_opacity = 1.0
        self.image_keep_aspect = True
        self.watermark = WatermarkConfig()


# ---------------------------------------------------------------------------
# Geri Al / Yinele — QUndoCommand alt sınıfları
# ---------------------------------------------------------------------------
class _AnnotationCommandBase(QUndoCommand):
    """Ortak alan: hangi sayfaya dokunulduğunu bilir ve her redo/undo
    sonrası ui callback'ini tetikler (görünüm tazeleme)."""

    def __init__(self, session: "DocumentSession", page: int,
                 on_change: Optional[Callable[["DocumentSession", int], None]], text: str):
        super().__init__(text)
        self.session = session
        self.page = page
        self.on_change = on_change

    def _notify(self):
        if self.on_change is not None:
            self.on_change(self.session, self.page)


class AddAnnotationCommand(_AnnotationCommandBase):
    """Sayfaya bir işaret ekler. Numara sayacını da yönetir (verilirse)."""

    def __init__(self, session, page, ann: Annotation, on_change=None,
                 counter_before: Optional[int] = None, counter_after: Optional[int] = None,
                 counter_setter: Optional[Callable[[int], None]] = None,
                 label: str = "İşaret Ekle"):
        super().__init__(session, page, on_change, label)
        self.ann = ann
        self.counter_before = counter_before
        self.counter_after = counter_after
        self.counter_setter = counter_setter

    def redo(self):
        self.session.annotations.setdefault(self.page, [])
        if self.ann not in self.session.annotations[self.page]:
            self.session.annotations[self.page].append(self.ann)
        # NOT: varlık kontrolü counter_setter'ın KENDİSİ üzerinden yapılır —
        # counter_before/after'ın kendisi meşru biçimde None olabilir
        # (ör. "henüz sayaç yoktu"), bu yüzden "is not None" ile atlanamaz.
        if self.counter_setter is not None:
            self.counter_setter(self.counter_after)
        self._notify()

    def undo(self):
        lst = self.session.annotations.get(self.page, [])
        if self.ann in lst:
            lst.remove(self.ann)
        if self.counter_setter is not None:
            self.counter_setter(self.counter_before)
        self._notify()


class RemoveAnnotationCommand(_AnnotationCommandBase):
    def __init__(self, session, page, ann: Annotation, on_change=None, label="İşaret Sil"):
        super().__init__(session, page, on_change, label)
        self.ann = ann

    def redo(self):
        lst = self.session.annotations.get(self.page, [])
        if self.ann in lst:
            lst.remove(self.ann)
        self._notify()

    def undo(self):
        self.session.annotations.setdefault(self.page, [])
        if self.ann not in self.session.annotations[self.page]:
            self.session.annotations[self.page].append(self.ann)
        self._notify()


class MoveAnnotationCommand(_AnnotationCommandBase):
    def __init__(self, session, page, ann: Annotation, dx: float, dy: float,
                 on_change=None, label="Taşı"):
        super().__init__(session, page, on_change, label)
        self.ann = ann
        self.dx, self.dy = dx, dy

    def redo(self):
        self.ann.translate(self.dx, self.dy)
        self._notify()

    def undo(self):
        self.ann.translate(-self.dx, -self.dy)
        self._notify()


class ResizeAnnotationCommand(_AnnotationCommandBase):
    def __init__(self, session, page, ann: Annotation, old_rect: QRectF, new_rect: QRectF,
                 on_change=None, label="Yeniden Boyutlandır"):
        super().__init__(session, page, on_change, label)
        self.ann = ann
        self.old_rect = QRectF(old_rect)
        self.new_rect = QRectF(new_rect)

    def redo(self):
        self.ann.set_rect(self.new_rect)
        self._notify()

    def undo(self):
        self.ann.set_rect(self.old_rect)
        self._notify()


class ZOrderCommand(_AnnotationCommandBase):
    """Bir işareti katman sırasında en öne/en arkaya taşır."""

    def __init__(self, session, page, ann: Annotation, to_front: bool, on_change=None,
                 label="Katman Sırası"):
        super().__init__(session, page, on_change, label)
        self.ann = ann
        self.to_front = to_front
        self.old_index: Optional[int] = None

    def redo(self):
        lst = self.session.annotations.get(self.page, [])
        if self.ann in lst:
            self.old_index = lst.index(self.ann)
            lst.remove(self.ann)
            lst.append(self.ann) if self.to_front else lst.insert(0, self.ann)
        self._notify()

    def undo(self):
        lst = self.session.annotations.get(self.page, [])
        if self.ann in lst and self.old_index is not None:
            lst.remove(self.ann)
            idx = min(self.old_index, len(lst))
            lst.insert(idx, self.ann)
        self._notify()


# ---------------------------------------------------------------------------
# Belge oturumu — açık bir PDF'in tüm durumu
# ---------------------------------------------------------------------------
class DocumentSession:
    """Açık bir PDF'in TÜM durumu: belge + işaretler + kendi QUndoStack'i +
    aktif sayfa. MainWindow, sekmeli çoklu belge yönetimi için bir
    DocumentSession listesi tutar."""

    def __init__(self, pdf, path: str):
        self.pdf = pdf                       # pdf_engine.PDFDocument
        self.path = path
        self.title = os.path.basename(path)
        self.annotations: Dict[int, List[Annotation]] = {i: [] for i in range(pdf.page_count)}
        self.current_page = 0
        self.undo_stack = QUndoStack()
        self.undo_stack.setUndoLimit(500)
        self.number_counter: Optional[int] = None     # None = henüz başlamadı
        self.dirty = False
        self.rotations: Dict[int, int] = {}            # sayfa -> ek döndürme (derece, 90'ın katı)

    def close(self):
        """Dosya kilitlenmelerini önlemek için PyMuPDF belgesini açıkça
        kapatır (C seviyesinde bellek sızıntısını da engeller)."""
        try:
            self.pdf.close()
        except Exception:
            pass

    # -- proje (JSON) serileştirme -----------------------------------------
    def to_project_dict(self) -> dict:
        return dict(
            version=1,
            source_pdf=os.path.abspath(self.path),
            title=self.title,
            rotations={str(k): v for k, v in self.rotations.items()},
            annotations={str(page): [a.to_dict() for a in anns]
                         for page, anns in self.annotations.items()},
        )

    def load_project_dict(self, d: dict) -> None:
        self.annotations = {i: [] for i in range(self.pdf.page_count)}
        for page_str, anns in d.get("annotations", {}).items():
            page = int(page_str)
            if page not in self.annotations:
                continue
            self.annotations[page] = [Annotation.from_dict(a) for a in anns]
        self.rotations = {int(k): v for k, v in d.get("rotations", {}).items()}
        self.undo_stack.clear()
        self.dirty = False
