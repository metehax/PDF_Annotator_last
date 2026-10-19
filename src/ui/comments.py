"""
ui/comments.py
==============
Yorumlar paneli: belgedeki tüm yapışkan notlar (sayfa sırasıyla), yanıtlar ve
"çözüldü" durumu. Panel yalnızca listeler ve sinyal yollar; değişiklikleri
MainWindow geri alınabilir komutlarla yapar.
"""

from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

from models import NoteAnnotation
from ui.icons import icon


class CommentsPanel(QWidget):
    gotoRequested = Signal(int, object)        # sayfa, NoteAnnotation
    editRequested = Signal(int, object)
    replyRequested = Signal(int, object)
    toggleRequested = Signal(int, object)
    deleteRequested = Signal(int, object)
    exportRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panelBody")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 4, 10, 10)
        v.setSpacing(8)

        row = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItem("Tümü", "all")
        self.filter.addItem("Açık", "open")
        self.filter.addItem("Çözüldü", "done")
        self.filter.currentIndexChanged.connect(self._render)
        row.addWidget(self.filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Yorumlarda ara…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._render)
        row.addWidget(self.search, 1)
        v.addLayout(row)

        self.summary = QLabel("")
        self.summary.setObjectName("hint")
        v.addWidget(self.summary)

        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setSpacing(2)
        self.list.itemClicked.connect(self._on_clicked)
        self.list.itemDoubleClicked.connect(lambda it: self._emit(self.editRequested, it))
        self.list.currentItemChanged.connect(lambda *_: self._sync_buttons())
        v.addWidget(self.list, 1)

        r1 = QHBoxLayout()
        self.btn_reply = QPushButton(icon("text"), "Yanıtla")
        self.btn_reply.setObjectName("secondary")
        self.btn_reply.clicked.connect(lambda: self._emit(self.replyRequested, self.list.currentItem()))
        self.btn_done = QPushButton(icon("check"), "Çözüldü")
        self.btn_done.setObjectName("secondary")
        self.btn_done.clicked.connect(lambda: self._emit(self.toggleRequested, self.list.currentItem()))
        r1.addWidget(self.btn_reply)
        r1.addWidget(self.btn_done)
        v.addLayout(r1)
        r2 = QHBoxLayout()
        self.btn_edit = QPushButton(icon("rename"), "Düzenle")
        self.btn_edit.setObjectName("secondary")
        self.btn_edit.clicked.connect(lambda: self._emit(self.editRequested, self.list.currentItem()))
        self.btn_del = QPushButton(icon("trash", "danger"), "Sil")
        self.btn_del.setObjectName("secondary")
        self.btn_del.clicked.connect(lambda: self._emit(self.deleteRequested, self.list.currentItem()))
        r2.addWidget(self.btn_edit)
        r2.addWidget(self.btn_del)
        v.addLayout(r2)
        self.btn_export = QPushButton(icon("file"), "Yorumları metin olarak kaydet…")
        self.btn_export.setObjectName("secondary")
        self.btn_export.clicked.connect(self.exportRequested.emit)
        v.addWidget(self.btn_export)

        self._notes: List[Tuple[int, NoteAnnotation]] = []
        self._sync_buttons()

    # -- veri ---------------------------------------------------------------------------
    def set_notes(self, notes: List[Tuple[int, NoteAnnotation]]) -> None:
        selected = self.current_note()
        self._notes = notes
        self._render(select=selected)

    def current_note(self):
        it = self.list.currentItem()
        data = it.data(Qt.ItemDataRole.UserRole) if it else None
        return data[1] if data else None

    def _render(self, *_args, select=None) -> None:
        if select is None:
            select = self.current_note()
        mode = self.filter.currentData()
        q = self.search.text().strip().casefold()
        self.list.blockSignals(True)
        self.list.clear()
        shown = 0
        for page, n in self._notes:
            if mode == "open" and n.done:
                continue
            if mode == "done" and not n.done:
                continue
            if q and q not in (n.full_text() + " " + n.author).casefold():
                continue
            head = f"{'✔ ' if n.done else ''}Sayfa {page + 1} · {n.author} · {n.created}"
            body = n.text or "(boş not)"
            replies = "".join(f"\n   ↳ {r.get('author', '')}: {r.get('text', '')}" for r in n.replies)
            it = QListWidgetItem(f"{head}\n{body}{replies}")
            it.setData(Qt.ItemDataRole.UserRole, (page, n))
            if n.done:
                f = it.font()
                f.setItalic(True)
                it.setFont(f)
                it.setForeground(self.palette().placeholderText())
            self.list.addItem(it)
            if n is select:
                self.list.setCurrentItem(it)
            shown += 1
        if shown == 0:
            empty = QListWidgetItem("Yorum yok. Not aracıyla (M) sayfaya tıklayın."
                                    if not self._notes else "Süzgece uyan yorum yok.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)
        self.list.blockSignals(False)
        open_n = sum(1 for _p, n in self._notes if not n.done)
        self.summary.setText(f"{len(self._notes)} yorum · {open_n} açık"
                             if self._notes else "Bu belgede yorum yok.")
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        n = self.current_note()
        for b in (self.btn_reply, self.btn_done, self.btn_edit, self.btn_del):
            b.setEnabled(n is not None)
        self.btn_export.setEnabled(bool(self._notes))
        if n is not None:
            self.btn_done.setText("Yeniden aç" if n.done else "Çözüldü")

    def _on_clicked(self, it) -> None:
        self._sync_buttons()
        self._emit(self.gotoRequested, it)

    def _emit(self, sig, it) -> None:
        data = it.data(Qt.ItemDataRole.UserRole) if it else None
        if data:
            sig.emit(data[0], data[1])


def ask_note_text(parent, title: str, initial: str = "", prompt: str = "Not metni") -> "str | None":
    """Çok satırlı metin soran küçük pencere. İptalde None döner."""
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(380)
    v = QVBoxLayout(dlg)
    v.addWidget(QLabel(prompt))
    edit = QPlainTextEdit(initial)
    edit.setMinimumHeight(110)
    v.addWidget(edit)
    bb = QDialogButtonBox()
    ok = bb.addButton("Tamam", QDialogButtonBox.ButtonRole.AcceptRole)
    ok.setObjectName("primary")
    bb.addButton("Vazgeç", QDialogButtonBox.ButtonRole.RejectRole)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    v.addWidget(bb)
    edit.setFocus()
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return edit.toPlainText()
