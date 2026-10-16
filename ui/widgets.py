"""
ui/widgets.py
=============
Tema ile uyumlu küçük, yeniden kullanılabilir arayüz parçaları.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from ui import theme

THUMB_ROLE = Qt.ItemDataRole.UserRole + 2     # QPixmap (yoksa boş kâğıt çizilir)
THUMB_ASPECT_ROLE = Qt.ItemDataRole.UserRole + 3  # yükseklik / genişlik


class ThumbnailDelegate(QStyledItemDelegate):
    """Sayfa küçük resmini ortalanmış, gölgeli bir "kâğıt" olarak ve altında
    sayfa numarasıyla çizer. Seçili/üzerinde durumları vurgu rengiyle
    gösterilir; görüntünün kendisi asla boyanmaz."""

    PAD = 10
    LABEL_H = 22
    MAX_W = 150

    def _thumb_width(self, option) -> int:
        return max(60, min(self.MAX_W, option.rect.width() - 2 * self.PAD - 24))

    def sizeHint(self, option, index):
        view_w = option.widget.viewport().width() if option.widget else 200
        w = max(60, min(self.MAX_W, view_w - 2 * self.PAD - 24))
        aspect = index.data(THUMB_ASPECT_ROLE) or 1.414
        return QSize(view_w - 4, int(w * aspect) + self.LABEL_H + 2 * self.PAD)

    def paint(self, painter: QPainter, option, index):
        t = theme.current()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(4, 2, -4, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor("accent_soft") if selected else theme.qcolor("hover"))
            painter.drawRoundedRect(r, 10, 10)

        aspect = index.data(THUMB_ASPECT_ROLE) or 1.414
        tw = self._thumb_width(option)
        th = tw * aspect
        page = QRectF(r.center().x() - tw / 2, r.top() + self.PAD, tw, th)

        # gölge + kâğıt
        painter.setPen(Qt.PenStyle.NoPen)
        for i, a in ((3, 14), (2, 22), (1, 34)):
            painter.setBrush(QColor(0, 0, 0, a))
            painter.drawRoundedRect(page.adjusted(-i, -i + 1, i, i + 1), 2 + i, 2 + i)
        painter.setBrush(QColor("#ffffff"))
        painter.drawRect(page)
        pm = index.data(THUMB_ROLE)
        if isinstance(pm, QPixmap) and not pm.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(page, pm, QRectF(pm.rect()))
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t["accent"]), 2))
            painter.drawRect(page.adjusted(-2, -2, 2, 2))

        # sayfa numarası
        label = QRectF(r.left(), page.bottom() + 4, r.width(), self.LABEL_H)
        f = painter.font()
        f.setPixelSize(12)
        f.setBold(selected)
        painter.setFont(f)
        painter.setPen(QColor(t["accent_text"] if selected else t["text_muted"]))
        painter.drawText(label, Qt.AlignmentFlag.AlignCenter, str(index.data(Qt.ItemDataRole.DisplayRole)))
        painter.restore()
