"""Tümünü kaydet penceresi ve 'diğer sayfalara uygula' kapsam penceresi."""
import os
import re
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QRadioButton, QVBoxLayout)


class SaveAllDialog(QDialog):
    """Kaydedilmemiş sekmeleri listeler; üzerine yaz / kopya / klasöre topla."""

    def __init__(self, sessions, parent=None, last_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Tümünü kaydet")
        self.setMinimumWidth(460)
        self.sessions = list(sessions)
        self.folder = ""
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Kaydedilecek belgeler:"))
        self.list = QListWidget()
        for s in self.sessions:
            it = QListWidgetItem(f"{s.title}   —   {os.path.dirname(s.path)}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(it)
        v.addWidget(self.list)
        self.rb_over = QRadioButton("Üzerine yaz (özgün dosyalar değişir)")
        self.rb_copy = QRadioButton("Kopya olarak kaydet (aynı klasörde ‘…_isaretli.pdf’)")
        self.rb_dir = QRadioButton("Hepsini tek bir klasöre kopyala")
        self.rb_over.setChecked(True)
        for rb in (self.rb_over, self.rb_copy, self.rb_dir):
            v.addWidget(rb)
        row = QHBoxLayout()
        self.dir_edit = QLineEdit(last_dir)
        self.dir_edit.setPlaceholderText("Klasör seçin…")
        self.btn_dir = QPushButton("Gözat…")
        self.btn_dir.clicked.connect(self._browse)
        row.addWidget(self.dir_edit, 1)
        row.addWidget(self.btn_dir)
        v.addLayout(row)
        for rb in (self.rb_over, self.rb_copy, self.rb_dir):
            rb.toggled.connect(self._sync)
        self._sync()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Kaydet")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _sync(self, *_):
        on = self.rb_dir.isChecked()
        self.dir_edit.setEnabled(on)
        self.btn_dir.setEnabled(on)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Klasör seç", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def _ok(self):
        if self.rb_dir.isChecked() and not os.path.isdir(self.dir_edit.text().strip()):
            self.dir_edit.setFocus()
            return
        self.accept()

    @property
    def mode(self) -> str:
        return "over" if self.rb_over.isChecked() else ("copy" if self.rb_copy.isChecked() else "dir")

    def chosen(self):
        return [s for i, s in enumerate(self.sessions)
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def target_dir(self) -> str:
        return self.dir_edit.text().strip()


def parse_pages(text: str, count: int) -> Optional[List[int]]:
    """'3-20, 25' → 0 tabanlı sayfa listesi; geçersizse None."""
    out = set()
    for part in re.split(r"[,;\s]+", text.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            return None
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if a < 1 or b < a or b > count:
            return None
        out.update(range(a - 1, b))
    return sorted(out) or None


class PageScopeDialog(QDialog):
    """İşareti hangi sayfalara kopyalayacağını sorar. pages() → 0 tabanlı liste (geçerli sayfa hariç)."""

    def __init__(self, page_count: int, current: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Diğer sayfalara uygula")
        self.count, self.current = page_count, current
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Seçili işaret, aynı konumda şu sayfalara da eklensin:"))
        self.rb_all = QRadioButton("Tüm sayfalar")
        self.rb_odd = QRadioButton("Tek sayfalar (1, 3, 5…)")
        self.rb_even = QRadioButton("Çift sayfalar (2, 4, 6…)")
        self.rb_rng = QRadioButton("Aralık:")
        self.rb_all.setChecked(True)
        self.rng = QLineEdit()
        self.rng.setPlaceholderText("örn. 2-10, 15")
        self.rng.textEdited.connect(lambda _t: self.rb_rng.setChecked(True))
        for w in (self.rb_all, self.rb_odd, self.rb_even):
            v.addWidget(w)
        row = QHBoxLayout()
        row.addWidget(self.rb_rng)
        row.addWidget(self.rng, 1)
        v.addLayout(row)
        self.err = QLabel("")
        self.err.setStyleSheet("color:#c62828;")
        v.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def pages(self) -> Optional[List[int]]:
        n = self.count
        if self.rb_all.isChecked():
            pg = range(n)
        elif self.rb_odd.isChecked():
            pg = range(0, n, 2)
        elif self.rb_even.isChecked():
            pg = range(1, n, 2)
        else:
            pg = parse_pages(self.rng.text(), n) or []
        return [p for p in pg if p != self.current] or None

    def _ok(self):
        if self.pages() is None:
            self.err.setText("Geçerli bir sayfa seçimi yazın.")
            return
        self.accept()
