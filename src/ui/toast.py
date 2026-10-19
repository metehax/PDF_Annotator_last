"""
ui/toast.py
===========
Köşede beliren ve kendiliğinden kaybolan kısa bildirimler. "Tamam"a
basılması gereken bilgi pencerelerinin yerini alır; hatalar yine pencere
olarak gösterilir.

    toasts.show("PDF kaydedildi", "success", action=("Klasörde göster", fn))
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget,
)

from ui import theme
from ui.icons import icon, pixmap as icon_pixmap

_KIND_ICON = {"success": "check", "info": "info", "warning": "warning", "error": "warning"}


class Toast(QFrame):
    def __init__(self, host: QWidget, text: str, kind: str = "success",
                 action: Optional[Tuple[str, Callable[[], None]]] = None, timeout_ms: int = 3200):
        super().__init__(host)
        self.setObjectName("toast")
        self.setProperty("kind", kind)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 9, 8, 9)
        h.setSpacing(10)
        t = theme.current()
        color = {"success": t["accent_text"], "info": t["accent_text"],
                 "warning": t["warning"], "error": t["danger"]}.get(kind, t["accent_text"])
        ico = QLabel()
        ico.setPixmap(icon_pixmap(_KIND_ICON.get(kind, "info"), 18, color, self.devicePixelRatioF()))
        h.addWidget(ico)
        lbl = QLabel(text)
        lbl.setObjectName("toastText")
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(420)
        h.addWidget(lbl, 1)
        if action is not None:
            btn = QPushButton(action[0])
            btn.setObjectName("toastAction")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda: (action[1](), self.dismiss()))
            h.addWidget(btn)
        close = QToolButton()
        close.setObjectName("barBtn")
        close.setIcon(icon("close"))
        close.setIconSize(QSize(14, 14))
        close.setFixedSize(24, 24)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.dismiss)
        h.addWidget(close)

        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._closing = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._timeout = timeout_ms
        self.adjustSize()

    def appear(self) -> None:
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(self._timeout)

    def enterEvent(self, e):
        self._timer.stop()             # üzerindeyken kaybolmasın
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self._closing:
            self._timer.start(1500)
        super().leaveEvent(e)

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._anim.stop()
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.deleteLater)
        self._anim.start()


class ToastManager:
    """Bildirimleri ana bölgenin sağ altına, üst üste dizer."""

    MARGIN = 16
    GAP = 8
    MAX = 4

    def __init__(self, host: QWidget):
        self.host = host
        self._toasts: List[Toast] = []

    def show(self, text: str, kind: str = "success",
             action: Optional[Tuple[str, Callable[[], None]]] = None, timeout_ms: int = 3200) -> Toast:
        t = Toast(self.host, text, kind, action, timeout_ms)
        t.destroyed.connect(lambda _=None, t=t: self._forget(t))
        self._toasts.append(t)
        while len(self._toasts) > self.MAX:
            self._toasts.pop(0).dismiss()
        self.relayout()
        t.appear()
        return t

    def _forget(self, t: Toast) -> None:
        if t in self._toasts:
            self._toasts.remove(t)
        self.relayout()

    def relayout(self) -> None:
        try:
            y = self.host.height() - self.MARGIN
        except RuntimeError:            # pencere kapanırken ana bölge silinmiş olabilir
            return
        for t in reversed(self._toasts):
            try:
                t.adjustSize()
                y -= t.height()
                t.move(self.host.width() - t.width() - self.MARGIN, y)
                y -= self.GAP
            except RuntimeError:        # C++ tarafı zaten silinmiş
                pass
