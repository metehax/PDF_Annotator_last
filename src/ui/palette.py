"""
ui/palette.py
=============
Ctrl+K komut paleti: yazarak her komuta ulaşma.

Arama Türkçe karakterlere duyarsızdır ("dondur" -> "Döndür") ve harfler
sırayla geçtiği sürece eşleşir ("flgr" -> "Filigran"); tam kelime başı
eşleşmeleri üstte listelenir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QVBoxLayout, QWidget,
)

from ui import theme
from ui.icons import icon

_TR = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
                     "Ç": "c", "Ğ": "g", "İ": "i", "I": "i", "Ö": "o", "Ş": "s", "Ü": "u"})


def normalize(text: str) -> str:
    return text.translate(_TR).lower()


def score(query: str, text: str) -> Optional[int]:
    """Düşük puan daha iyi; eşleşmezse None."""
    q, t = normalize(query).strip(), normalize(text)
    if not q:
        return 0
    if t.startswith(q):
        return 0
    idx = t.find(q)
    if idx >= 0:
        return 10 + (0 if t[idx - 1] == " " else 10) + idx
    # harfler sırayla geçiyor mu?
    pos, gaps = -1, 0
    for ch in q:
        nxt = t.find(ch, pos + 1)
        if nxt < 0:
            return None
        gaps += nxt - pos - 1
        pos = nxt
    return 100 + gaps


@dataclass
class Command:
    title: str
    run: Callable[[], None]
    category: str = ""
    icon_name: Optional[str] = None
    shortcut: str = ""
    qicon: Optional[QIcon] = None


class CommandPalette(QFrame):
    """Ana pencerenin üstünde ortada beliren arama kutusu + sonuç listesi."""

    WIDTH = 580
    commandRun = Signal(str)           # çalıştırılan komutun başlığı ("son kullanılanlar" için)

    def __init__(self, host: QWidget, provider: Callable[[str], List[Command]]):
        super().__init__(host)
        self.setObjectName("palette")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._provider = provider
        self._commands: List[Command] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setObjectName("paletteEdit")
        self.edit.setPlaceholderText("Komut ara… (ör. döndür, filigran, ocr, sayfa 12)")
        self.edit.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.edit.textChanged.connect(self._refresh)
        self.edit.installEventFilter(self)
        v.addWidget(self.edit)
        self.list = QListWidget()
        self.list.setObjectName("paletteList")
        self.list.setUniformItemSizes(True)
        self.list.itemActivated.connect(self._run_item)
        self.list.itemClicked.connect(self._run_item)
        v.addWidget(self.list)
        self.empty = QLabel("Eşleşen komut yok")
        self.empty.setObjectName("hint")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.empty)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(40)
        self._shadow.setOffset(0, 12)
        self.setGraphicsEffect(self._shadow)
        self.hide()

    # -- açma / kapama --------------------------------------------------------
    def open(self) -> None:
        self._shadow.setColor(theme.qcolor("shadow"))
        self.edit.blockSignals(True)
        self.edit.clear()
        self.edit.blockSignals(False)
        self._refresh()
        self.show()
        self.raise_()
        self.edit.setFocus()

    def close_palette(self) -> None:
        self.hide()
        p = self.parentWidget()
        if p is not None:
            p.setFocus()

    def reposition(self) -> None:
        host = self.parentWidget()
        w = min(self.WIDTH, host.width() - 32)
        rows = min(9, max(1, self.list.count()))
        list_h = rows * 38 + 6 if self.list.count() else 0
        self.list.setFixedHeight(list_h)
        self.list.setVisible(self.list.count() > 0)
        self.empty.setVisible(self.list.count() == 0)
        self.adjustSize()
        self.setFixedWidth(w)
        self.adjustSize()
        self.move((host.width() - w) // 2, 64)

    # -- içerik -----------------------------------------------------------------
    def _refresh(self) -> None:
        query = self.edit.text()
        cmds = self._provider(query)
        ranked = []
        for i, c in enumerate(cmds):
            s = score(query, c.title)
            if s is None and c.category:
                s2 = score(query, f"{c.category} {c.title}")
                s = None if s2 is None else s2 + 50
            if s is not None:
                ranked.append((s, i, c))
        ranked.sort(key=lambda x: (x[0], x[1]))
        self._commands = [c for _, _, c in ranked[:60]]
        self.list.clear()
        for c in self._commands:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 36))
            self.list.addItem(item)
            self.list.setItemWidget(item, self._row(c))
        if self._commands:
            self.list.setCurrentRow(0)
        self.reposition()

    def _row(self, c: Command) -> QWidget:
        w = QWidget()
        w.setObjectName("paletteRow")
        h = QHBoxLayout(w)
        h.setContentsMargins(10, 0, 10, 0)
        h.setSpacing(10)
        ico = QLabel()
        qi = c.qicon if c.qicon is not None and not c.qicon.isNull() else             (icon(c.icon_name) if c.icon_name else None)
        if qi is not None:
            ico.setPixmap(qi.pixmap(QSize(18, 18), self.devicePixelRatioF()))
        ico.setFixedWidth(20)
        h.addWidget(ico)
        title = QLabel(c.title)
        title.setObjectName("paletteTitle")
        h.addWidget(title, 1)
        if c.category:
            cat = QLabel(c.category)
            cat.setToolTip(c.category)
            cat.setObjectName("paletteCat")
            h.addWidget(cat)
        if c.shortcut:
            sc = QLabel(c.shortcut)
            sc.setObjectName("kbd")
            h.addWidget(sc)
        for lbl in w.findChildren(QLabel):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return w

    def _run_item(self, item: QListWidgetItem) -> None:
        row = self.list.row(item)
        if 0 <= row < len(self._commands):
            cmd = self._commands[row]
            self.close_palette()
            self.commandRun.emit(cmd.title)
            cmd.run()

    # -- klavye -------------------------------------------------------------
    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QEvent.Type.KeyPress:
            key = ev.key()
            if key == Qt.Key.Key_Escape:
                self.close_palette()
                return True
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                n = self.list.count()
                if n:
                    step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1,
                            Qt.Key.Key_PageDown: 8, Qt.Key.Key_PageUp: -8}[key]
                    self.list.setCurrentRow(max(0, min(n - 1, self.list.currentRow() + step)))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.list.currentItem()
                if item is not None:
                    self._run_item(item)
                return True
        if obj is self.edit and ev.type() == QEvent.Type.FocusOut:
            # listeye tıklanırken kapanmasın
            if not self.list.underMouse():
                self.close_palette()
        return super().eventFilter(obj, ev)

