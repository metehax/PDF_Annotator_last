"""
ui/sidepanel.py
===============
Sol kenar: ince ikon şeridi + yanında kayarak açılan panel.

Şeritteki bir ikona tıklayınca ilgili sayfa panelde açılır; aynı ikona
tekrar tıklayınca panel kapanır. Açılıp kapanma kısa bir animasyonla olur.
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from ui.icons import icon

PANEL_WIDTH = 264


class SidePanel(QWidget):
    pageChanged = Signal(str)          # açılan sayfanın anahtarı ("" = kapalı)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self.rail = QFrame()
        self.rail.setObjectName("sideRail")
        self.rail.setFixedWidth(52)
        self._rail_lay = QVBoxLayout(self.rail)
        self._rail_lay.setContentsMargins(6, 10, 6, 10)
        self._rail_lay.setSpacing(4)
        self._rail_lay.addStretch(1)
        self._bottom_index = 0          # alt bölüm için ekleme noktası
        h.addWidget(self.rail)

        self.panel = QFrame()
        self.panel.setObjectName("sidePanel")
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        pv.addWidget(self.title)
        self.stack = QStackedWidget()
        pv.addWidget(self.stack, 1)
        self.panel.setMinimumWidth(0)
        self.panel.setMaximumWidth(PANEL_WIDTH)
        h.addWidget(self.panel)

        self._buttons: Dict[str, QToolButton] = {}
        self._pages: Dict[str, int] = {}
        self._titles: Dict[str, str] = {}
        self._current = ""
        self._anim = QPropertyAnimation(self.panel, b"maximumWidth", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)

    # -- kurulum ---------------------------------------------------------------
    def _rail_button(self, icon_name: str, tooltip: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName("railBtn")
        b.setIcon(icon(icon_name, "toggle"))
        b.setIconSize(QSize(20, 20))
        b.setFixedSize(40, 40)
        b.setToolTip(tooltip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def add_page(self, key: str, icon_name: str, title: str, widget: QWidget) -> QToolButton:
        b = self._rail_button(icon_name, title)
        b.setCheckable(True)
        b.clicked.connect(lambda _=False, k=key: self.toggle(k))
        self._rail_lay.insertWidget(self._rail_lay.count() - 1 - self._bottom_index, b,
                                    0, Qt.AlignmentFlag.AlignHCenter)
        self._buttons[key] = b
        self._pages[key] = self.stack.addWidget(widget)
        self._titles[key] = title
        return b

    def add_bottom_button(self, icon_name: str, tooltip: str, slot) -> QToolButton:
        b = self._rail_button(icon_name, tooltip)
        b.clicked.connect(slot)
        self._rail_lay.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
        self._bottom_index += 1
        return b

    def page_buttons(self):
        return list(self._buttons.values())

    # -- durum ---------------------------------------------------------------
    def current(self) -> str:
        return self._current

    def is_open(self) -> bool:
        return bool(self._current)

    def show_page(self, key: str, animate: bool = True) -> None:
        if key not in self._pages:
            return
        was_open = self.is_open()
        self._current = key
        self.stack.setCurrentIndex(self._pages[key])
        self.title.setText(self._titles[key])
        for k, b in self._buttons.items():
            b.setChecked(k == key)
        self.panel.show()
        if not was_open:
            self._animate_to(PANEL_WIDTH, animate)
        self.pageChanged.emit(key)

    def collapse(self, animate: bool = True) -> None:
        if not self.is_open():
            return
        self._current = ""
        for b in self._buttons.values():
            b.setChecked(False)
        self._animate_to(0, animate)
        self.pageChanged.emit("")

    def toggle(self, key: str) -> None:
        if self._current == key:
            self.collapse()
        else:
            self.show_page(key)

    def _animate_to(self, width: int, animate: bool) -> None:
        self._anim.stop()
        if not animate:
            self.panel.setMaximumWidth(width)
            self._on_anim_finished()
            return
        self._anim.setStartValue(self.panel.width() if self.panel.isVisible() else 0)
        self._anim.setEndValue(width)
        self._anim.start()

    def _on_anim_finished(self) -> None:
        if not self.is_open():
            self.panel.hide()
        else:
            self.panel.setMaximumWidth(PANEL_WIDTH)
