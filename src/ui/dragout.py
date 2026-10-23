"""
ui/dragout.py
=============
Belgeyi uygulamadan sürükleyip dışarı bırakma: e-posta penceresine (ek), klasöre, masaüstüne.
Düğmeden sürükleyince `make_file()` çağrılır (işaretli geçici kopya ya da değişmemiş özgün dosya);
yalnızca KOPYALAMA eylemi sunulur, özgün dosya asla taşınmaz/silinmez.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import QMimeData, QPoint, QUrl, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QToolButton


def file_mime(path: str) -> QMimeData:
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(os.path.abspath(path))])
    return m


class DragOutButton(QToolButton):
    def __init__(self, make_file: Callable[[], Optional[str]], parent=None):
        super().__init__(parent)
        self._make_file = make_file
        self._press: Optional[QPoint] = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press is not None and e.buttons() & Qt.MouseButton.LeftButton
                and (e.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance()):
            self._press = None
            self.setDown(False)
            self.start_drag()
            return
        super().mouseMoveEvent(e)

    def start_drag(self) -> bool:
        path = self._make_file()
        if not path:
            return False
        drag = QDrag(self)
        drag.setMimeData(file_mime(path))
        drag.setPixmap(self.icon().pixmap(32, 32))
        drag.exec(Qt.DropAction.CopyAction)
        return True
