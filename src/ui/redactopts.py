"""
ui/redactopts.py
================
Sansür seçenekleri (dolgu rengi hazırları + etiket metni): özellik çubuğundaki Sansür sayfası ve KVKK penceresi
aynı bileşeni kullanır; değerler `main.state.redact_color` / `main.state.redact_label` içinde tutulur.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

FILL_PRESETS = (("Siyah", "#000000"), ("Koyu gri", "#404040"), ("Beyaz", "#ffffff"))
LABEL_PRESETS = ("", "GİZLİ", "[KARARTILDI]", "KVKK")


class RedactOptions(QWidget):
    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Dolgu"))
        self.preset_btns = []
        for name, hexcol in FILL_PRESETS:
            b = QPushButton(name)
            b.setObjectName("segBtn")
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, h=hexcol: self.set_fill(QColor(h)))
            row.addWidget(b)
            self.preset_btns.append((hexcol, b))
        row.addStretch(1)
        v.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Etiket"))
        self.label_combo = QComboBox()
        self.label_combo.setEditable(True)
        for t in LABEL_PRESETS:
            self.label_combo.addItem(t)
        self.label_combo.lineEdit().setPlaceholderText("Kutunun üstüne yazılacak metin (isteğe bağlı)")
        self.label_combo.setCurrentText(main.state.redact_label)
        self.label_combo.currentTextChanged.connect(self._label_changed)
        row.addWidget(self.label_combo, 1)
        v.addLayout(row)
        self.refresh()

    # -- durum ----------------------------------------------------------------
    def set_fill(self, color: QColor):
        """Hazır dolgu seçilince ana pencere durumunu ve renk düğmelerini günceller."""
        setter = getattr(self._main, "_set_redact_color", None)
        if setter:
            setter(color)
        else:
            self._main.state.redact_color = QColor(color)
        self.refresh()

    def _label_changed(self, text: str):
        self._main.state.redact_label = text.strip()

    def refresh(self):
        cur = QColor(self._main.state.redact_color).name().lower()
        for hexcol, b in self.preset_btns:
            b.setChecked(hexcol == cur)
        if self.label_combo.currentText().strip() != self._main.state.redact_label:
            self.label_combo.setCurrentText(self._main.state.redact_label)
