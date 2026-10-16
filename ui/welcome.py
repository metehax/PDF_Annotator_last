"""
ui/welcome.py
=============
Hiç belge açık değilken gösterilen açılış ekranı: sürükle-bırak alanı,
"Dosya aç" düğmesi ve son açılan dosyalar.
"""

from __future__ import annotations

import os
from typing import List

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ui import theme
from ui.icons import icon, pixmap as icon_pixmap


class _RecentRow(QPushButton):
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.setObjectName("recentItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(path)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(12)
        ext = os.path.splitext(path)[1].lower()
        ico = QLabel()
        ico.setPixmap(icon_pixmap("file" if ext == ".pdf" else "image", 20,
                                  theme.current()["accent_text"], self.devicePixelRatioF()))
        ico.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        h.addWidget(ico)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        name = QLabel(os.path.basename(path))
        name.setObjectName("recentName")
        folder = QLabel()
        folder.setObjectName("recentFolder")
        folder.setText(folder.fontMetrics().elidedText(os.path.dirname(path),
                                                       Qt.TextElideMode.ElideMiddle, 440))
        for lbl in (name, folder):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            texts.addWidget(lbl)
        h.addLayout(texts, 1)
        self.setMinimumHeight(52)


class WelcomeScreen(QWidget):
    openRequested = Signal()
    recentRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("welcome")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(2)

        card = QWidget()
        card.setMaximumWidth(560)
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(18)

        title = QLabel("PDF ve resimlerinizi açın")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("İşaretleyin, düzenleyin, karşılaştırın ve dışa aktarın.")
        sub.setObjectName("welcomeSub")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(title)
        v.addWidget(sub)

        self.drop = QFrame()
        self.drop.setObjectName("dropZone")
        dv = QVBoxLayout(self.drop)
        dv.setContentsMargins(24, 30, 24, 30)
        dv.setSpacing(12)
        self._drop_icon = QLabel()
        self._drop_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dv.addWidget(self._drop_icon)
        hint = QLabel("Dosyaları buraya sürükleyip bırakın")
        hint.setObjectName("dropHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dv.addWidget(hint)
        fmt = QLabel("PDF, PNG, JPG, BMP, GIF, TIFF, WEBP")
        fmt.setObjectName("dropFormats")
        fmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dv.addWidget(fmt)
        self.btn_open = QPushButton(icon("open", "on_accent"), "Dosya aç")
        self.btn_open.setObjectName("primary")
        self.btn_open.setIconSize(QSize(18, 18))
        self.btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open.setMinimumHeight(38)
        self.btn_open.clicked.connect(self.openRequested.emit)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_open)
        row.addStretch(1)
        dv.addSpacing(4)
        dv.addLayout(row)
        shortcut = QLabel("ya da Ctrl+O")
        shortcut.setObjectName("dropFormats")
        shortcut.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dv.addWidget(shortcut)
        v.addWidget(self.drop)

        self.recent_title = QLabel("SON AÇILANLAR")
        self.recent_title.setObjectName("sectionTitle")
        v.addWidget(self.recent_title)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(4)
        v.addLayout(self.recent_box)

        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(card, 4)
        h.addStretch(1)
        outer.addLayout(h)
        outer.addStretch(3)
        self._recent: List[str] = []
        self.refresh_theme()

    def refresh_theme(self) -> None:
        self._drop_icon.setPixmap(icon_pixmap("download", 40, theme.current()["accent_text"],
                                              self.devicePixelRatioF()))
        self.set_recent(self._recent)

    def set_recent(self, paths: List[str]) -> None:
        self._recent = [p for p in paths if os.path.exists(p)][:6]
        while self.recent_box.count():
            item = self.recent_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for p in self._recent:
            row = _RecentRow(p)
            row.clicked.connect(lambda _=False, path=p: self.recentRequested.emit(path))
            self.recent_box.addWidget(row)
        self.recent_title.setVisible(bool(self._recent))
