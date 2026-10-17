"""
ui/textdialog.py
================
Metin ekleme diyaloğu (yazı + font + renk + punto, canlı önizleme) ve metin genişliği ölçümü.
"""

from __future__ import annotations

import pymupdf as fitz

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout,
)

from fonts import FONT_FAMILIES


# ---------------------------------------------------------------------------
# Metin ekleme diyaloğu (yazı + font + renk + punto, canlı önizleme)
# ---------------------------------------------------------------------------
def ocr_text_width(text: str, family: str, size: float) -> float:
    """Çok satırlı metnin en geniş satırının genişliği (punto)."""
    from fonts import resolve_font_file
    path = resolve_font_file(family)
    try:
        font = fitz.Font(fontfile=path) if path else fitz.Font("helv")
        return max(font.text_length(l, fontsize=size) for l in text.split("\n"))
    except Exception:
        return len(text) * size * 0.55


class TextDialog(QDialog):
    def __init__(self, family: str, size: float, color: QColor, parent=None,
                 text: str = "", title: str = "Metin Ekle", info: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self._color = QColor(color)

        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.font_combo = QComboBox()
        for fam in FONT_FAMILIES:
            self.font_combo.addItem(fam)
        idx = self.font_combo.findText(family)
        self.font_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Yazı tipi:", self.font_combo)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(4, 300)
        self.size_spin.setValue(int(size))
        form.addRow("Punto:", self.size_spin)

        self.color_btn = QPushButton()
        self.color_btn.setFixedHeight(26)
        self.color_btn.clicked.connect(self._pick_color)
        form.addRow("Renk:", self.color_btn)
        lay.addLayout(form)

        if info:
            info_lbl = QLabel(info)
            info_lbl.setWordWrap(True)
            info_lbl.setObjectName("hint")
            lay.addWidget(info_lbl)
        lay.addWidget(QLabel("Yazı:"))
        self.edit = QPlainTextEdit()
        self.edit.setPlainText(text)
        self.edit.setMinimumHeight(110)
        lay.addWidget(self.edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.font_combo.currentTextChanged.connect(self._refresh_preview)
        self.size_spin.valueChanged.connect(self._refresh_preview)
        self._refresh_preview()

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "Yazı rengi")
        if c.isValid():
            self._color = c
            self._refresh_preview()

    def _refresh_preview(self, *_):
        self.color_btn.setStyleSheet(f"background:{self._color.name()};")
        f = QFont(self.font_combo.currentText())
        f.setPointSize(min(28, max(8, self.size_spin.value())))
        self.edit.setFont(f)
        self.edit.setStyleSheet(f"color:{self._color.name()};")

    def result_values(self):
        return (self.edit.toPlainText(), self.font_combo.currentText(),
                float(self.size_spin.value()), QColor(self._color))
