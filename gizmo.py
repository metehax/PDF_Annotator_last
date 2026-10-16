"""
gizmo.py
========
Seçili nesneler (dikdörtgen, daire, metin kutusu, resim) için 8 noktalı
dönüştürme/boyutlandırma kulpları (transform gizmo).

`SelectionGizmo`, hedef bir işaretin (Annotation.get_rect()) etrafına köşe
ve kenar ortalarına yerleştirilmiş 8 küçük kare kulp çizer. Kullanıcı bir
kulpu sürüklediğinde dikdörtgen canlı önizlenir; fare bırakıldığında
`resizeFinished(old_rect, new_rect)` sinyali yayılır — gerçek veri modeli
(Annotation.set_rect) ve Geri Al kaydı YALNIZCA bu noktada, çağıran taraf
(views.py / main_window.py) tarafından oluşturulur. Böylece her piksellik
fare hareketi ayrı bir undo kaydı yaratmaz.

Taşıma (nesneyi sürükleyerek konum değiştirme) bu modülün sorumluluğunda
DEĞİLDİR: Seç aracı, Qt'nin yerleşik `ItemIsMovable` bayrağıyla çalışmaya
devam eder (views.py). Gizmo yalnızca yeniden boyutlandırmadan sorumludur.

En-boy oranı kilidi:
    * Görseller (resim) İÇİN varsayılan davranış oranı KORUR; Shift basılı
      tutulduğunda serbest (oran bozulabilir) boyutlandırmaya geçer.
    * Şekil / metin kutuları için varsayılan SERBEST'tir; Shift basılı
      tutulduğunda oran kilitlenir.
    Bu, `default_aspect_lock` ile Shift durumunun XOR'lanmasıyla elde
    edilir: fiili_kilit = default_aspect_lock XOR shift_basılı.
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QPen
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsObject, QGraphicsRectItem, QGraphicsSceneMouseEvent,
)

HANDLE_SIZE = 9.0
HANDLE_ROLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"]

_CURSOR_FOR_ROLE = {
    "nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
    "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
    "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
    "e": Qt.CursorShape.SizeHorCursor, "w": Qt.CursorShape.SizeHorCursor,
}


class _GizmoHandle(QGraphicsRectItem):
    """8 kulptan biri: köşe (nw/ne/sw/se) ya da kenar-ortası (n/s/e/w)."""

    def __init__(self, role: str, overlay: "SelectionGizmo"):
        super().__init__(-HANDLE_SIZE / 2, -HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE, overlay)
        self.role = role
        self.overlay = overlay
        self.setBrush(QBrush(QColor("#ffffff")))
        self.setPen(QPen(QColor("#3a86ff"), 1.4))
        self.setZValue(1001)
        self.setCursor(QCursor(_CURSOR_FOR_ROLE.get(role, Qt.CursorShape.SizeAllCursor)))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self._dragging = False

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._dragging = True
        self.overlay.begin_resize(self.role)
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if self._dragging:
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.overlay.update_resize(self.role, event.scenePos(), shift)
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if self._dragging:
            self._dragging = False
            self.overlay.finish_resize()
        event.accept()


class SelectionGizmo(QGraphicsObject):
    """Bir işaretin seçili olduğunu gösteren kesikli çerçeve + 8 kulp.

    Kullanım: sahneye bir kez eklenir, `set_rect()` ile konumlandırılır,
    seçim kalkınca `hide()` edilir. `default_aspect_lock`, hedefin türüne
    göre (resim=True, diğerleri=False) views.py tarafından ayarlanır.
    """

    resizeFinished = Signal(QRectF, QRectF)   # (eski_rect, yeni_rect) — sahne/PDF birimi

    def __init__(self, default_aspect_lock: bool = False, min_size: float = 6.0, parent=None):
        super().__init__(parent)
        self.default_aspect_lock = default_aspect_lock
        self.min_size = min_size
        self._rect = QRectF()
        self._drag_ref_rect = QRectF()
        self._active_role: Optional[str] = None
        self.setZValue(999)

        self.outline = QGraphicsRectItem(self)
        self.outline.setPen(QPen(QColor("#3a86ff"), 1.2, Qt.PenStyle.DashLine))
        self.outline.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.outline.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, False)

        self.handles: Dict[str, _GizmoHandle] = {role: _GizmoHandle(role, self) for role in HANDLE_ROLES}

    # QGraphicsObject zorunlu arayüzü ------------------------------------
    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-10, -10, 10, 10)

    def paint(self, painter, option, widget=None):
        pass  # tüm görsel öğeler alt itemlarla (outline + kulplar) çiziliyor

    # -- konumlandırma ------------------------------------------------------
    def set_rect(self, rect: QRectF) -> None:
        self._rect = QRectF(rect).normalized()
        self.outline.setRect(self._rect)
        self._layout_handles()
        self.prepareGeometryChange()

    def rect(self) -> QRectF:
        return QRectF(self._rect)

    def set_aspect_lock_default(self, locked: bool) -> None:
        self.default_aspect_lock = locked

    def _layout_handles(self) -> None:
        r = self._rect
        positions = {
            "nw": r.topLeft(), "n": QPointF(r.center().x(), r.top()),
            "ne": r.topRight(), "e": QPointF(r.right(), r.center().y()),
            "se": r.bottomRight(), "s": QPointF(r.center().x(), r.bottom()),
            "sw": r.bottomLeft(), "w": QPointF(r.left(), r.center().y()),
        }
        for role, pt in positions.items():
            self.handles[role].setPos(pt)

    # -- sürükleme mantığı ----------------------------------------------
    def begin_resize(self, role: str) -> None:
        self._active_role = role
        self._drag_ref_rect = QRectF(self._rect)

    def update_resize(self, role: str, scene_pos: QPointF, shift_held: bool) -> None:
        keep_aspect = self.default_aspect_lock != shift_held   # XOR
        new_rect = self._compute_rect(role, self._drag_ref_rect, scene_pos, keep_aspect)
        self._rect = new_rect
        self.outline.setRect(new_rect)
        self._layout_handles()

    def _compute_rect(self, role: str, orig: QRectF, pos: QPointF, keep_aspect: bool) -> QRectF:
        x0, y0, x1, y1 = orig.left(), orig.top(), orig.right(), orig.bottom()
        nx0, ny0, nx1, ny1 = x0, y0, x1, y1
        if "w" in role:
            nx0 = min(pos.x(), x1 - self.min_size)
        if "e" in role:
            nx1 = max(pos.x(), x0 + self.min_size)
        if "n" in role:
            ny0 = min(pos.y(), y1 - self.min_size)
        if "s" in role:
            ny1 = max(pos.y(), y0 + self.min_size)

        if keep_aspect and role in ("nw", "ne", "sw", "se") and orig.height() > 0:
            aspect = orig.width() / orig.height()
            w = max(self.min_size, nx1 - nx0)
            h = w / aspect if aspect > 0 else (ny1 - ny0)
            if role == "se":
                ny1 = ny0 + h
            elif role == "sw":
                ny1 = ny0 + h
            elif role == "ne":
                ny0 = ny1 - h
            elif role == "nw":
                ny0 = ny1 - h

        return QRectF(QPointF(nx0, ny0), QPointF(nx1, ny1)).normalized()

    def finish_resize(self) -> None:
        if self._active_role is None:
            return
        old_rect = QRectF(self._drag_ref_rect)
        new_rect = QRectF(self._rect)
        self._active_role = None
        if old_rect != new_rect and new_rect.width() >= self.min_size and new_rect.height() >= self.min_size:
            self.resizeFinished.emit(old_rect, new_rect)
        else:
            # Anlamlı bir değişiklik yoksa (ör. tıklama-bırakma) sessizce
            # eski haline dön.
            self.set_rect(old_rect)
