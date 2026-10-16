"""
ui/overlays.py
==============
Çalışma alanının üzerinde yüzen, gölgeli çubuklar (araç kapsülü, özellik
çubuğu, seçim ve sayfa çubukları) için ortak yapı taşları.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QToolButton, QWidget,
)

from ui import theme
from ui.icons import icon


class FloatingBar(QFrame):
    """Yuvarlak köşeli, gölgeli yatay çubuk. Ebeveyninin üzerinde serbestçe
    konumlandırılır (bir yerleşime eklenmez)."""

    def __init__(self, parent: QWidget, object_name: str = "floatBar", margins=(6, 5, 6, 5),
                 spacing: int = 2):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(*margins)
        self.lay.setSpacing(spacing)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(28)
        self._shadow.setOffset(0, 6)
        self.setGraphicsEffect(self._shadow)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        self._shadow.setColor(theme.qcolor("shadow"))

    def add(self, w: QWidget, stretch: int = 0) -> QWidget:
        self.lay.addWidget(w, stretch)
        return w

    def add_separator(self) -> QFrame:
        sep = QFrame(self)
        sep.setObjectName("barSep")
        sep.setFixedSize(1, 22)
        self.lay.addWidget(sep, 0, Qt.AlignmentFlag.AlignVCenter)
        return sep

    def add_button(self, icon_name: str, tooltip: str, slot=None, checkable: bool = False,
                   role: str = "default", size: int = 32, icon_size: int = 18,
                   object_name: str = "barBtn") -> QToolButton:
        b = QToolButton(self)
        b.setObjectName(object_name)
        b.setIcon(icon(icon_name, role))
        b.setIconSize(QSize(icon_size, icon_size))
        b.setFixedSize(size, size)
        b.setToolTip(tooltip)
        b.setCheckable(checkable)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if slot is not None:
            b.clicked.connect(slot)
        self.lay.addWidget(b)
        return b

    def fit(self, max_width: Optional[int] = None) -> None:
        """Boyutu içeriğe göre ayarlar (gerekirse genişliği sınırlar)."""
        self.adjustSize()
        hint = self.sizeHint()
        w = hint.width() if max_width is None else min(hint.width(), max_width)
        self.resize(w, hint.height())
