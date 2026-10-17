"""
ui/watermark.py
===============
Filigran diyaloğu.
"""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSlider, QSpinBox, QWidget,
)

from models import WatermarkConfig
from pdf_engine import load_image_bytes_from_path
from ui.icons import icon


# ---------------------------------------------------------------------------
# Filigran diyaloğu
# ---------------------------------------------------------------------------
class WatermarkDialog(QDialog):
    def __init__(self, initial: WatermarkConfig, page_count: int, current_page: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filigran Ekle")
        self.setMinimumWidth(380)
        self._cfg = copy.deepcopy(initial)
        self._page_count = page_count
        self._current_page = current_page

        form = QFormLayout(self)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Metin", "Resim"])
        self.mode_combo.setCurrentIndex(0 if self._cfg.mode == "text" else 1)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        form.addRow("Tür:", self.mode_combo)

        self.text_edit = QLineEdit(self._cfg.text)
        form.addRow("Metin:", self.text_edit)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 300)
        self.font_size_spin.setValue(int(self._cfg.font_size))
        form.addRow("Punto:", self.font_size_spin)

        self.color_btn = QPushButton()
        self.color_btn.setFixedHeight(26)
        self._set_color_btn(self._cfg.color)
        self.color_btn.clicked.connect(self._pick_color)
        form.addRow("Renk:", self.color_btn)

        self.image_btn = QPushButton(icon("image"), "Görsel Seç…")
        self.image_btn.setObjectName("secondary")
        self.image_btn.clicked.connect(self._pick_image)
        self.image_preview = QLabel("(seçilmedi)")
        self.image_preview.setFixedHeight(60)
        form.addRow("Görsel:", self.image_btn)
        form.addRow("", self.image_preview)
        self._image_bytes = self._cfg.image_bytes

        self.image_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.image_scale_slider.setRange(2, 100)
        self.image_scale_slider.setValue(int(self._cfg.image_scale * 100))
        form.addRow("Görsel Ölçek (%):", self.image_scale_slider)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(2, 100)
        self.opacity_slider.setValue(int(self._cfg.opacity * 100))
        form.addRow("Saydamlık (%):", self.opacity_slider)

        self.rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self.rotation_slider.setRange(-90, 90)
        self.rotation_slider.setValue(int(self._cfg.rotation))
        self.rotation_lbl = QLabel(f"{self._cfg.rotation:.0f}°")
        self.rotation_slider.valueChanged.connect(
            lambda v: self.rotation_lbl.setText(f"{v}°"))
        rot_row = QWidget(); rl = QHBoxLayout(rot_row); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.rotation_slider, 1); rl.addWidget(self.rotation_lbl)
        form.addRow("Döndürme (-90° / +90°):", rot_row)

        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["Tekli (Ortada)", "Döşenmiş (Tüm Sayfa)"])
        self.layout_combo.setCurrentIndex(0 if self._cfg.layout == "single" else 1)
        form.addRow("Yerleşim:", self.layout_combo)

        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["Aktif Sayfa", "Sayfa Aralığı", "Tüm Belge"])
        self.scope_combo.setCurrentIndex({"current": 0, "range": 1, "all": 2}[self._cfg.scope])
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        form.addRow("Kapsam:", self.scope_combo)

        self.range_row = QWidget()
        rr = QHBoxLayout(self.range_row); rr.setContentsMargins(0, 0, 0, 0)
        self.start_spin = QSpinBox(); self.start_spin.setRange(1, max(1, page_count))
        self.start_spin.setValue(self._cfg.page_start)
        self.end_spin = QSpinBox(); self.end_spin.setRange(1, max(1, page_count))
        self.end_spin.setValue(self._cfg.page_end if self._cfg.page_end else page_count)
        rr.addWidget(QLabel("Başlangıç:")); rr.addWidget(self.start_spin)
        rr.addWidget(QLabel("Bitiş:")); rr.addWidget(self.end_spin)
        form.addRow("", self.range_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._on_mode_changed(self.mode_combo.currentIndex())
        self._on_scope_changed(self.scope_combo.currentIndex())

    def _set_color_btn(self, color: QColor):
        self.color_btn.setStyleSheet(f"background:{color.name()};")
        self._color = QColor(color)

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "Filigran rengi")
        if c.isValid():
            self._set_color_btn(c)

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Filigran Görseli Seç", "",
                                              "Görseller (*.png *.jpg *.jpeg *.bmp *.svg)")
        if not path:
            return
        try:
            self._image_bytes = load_image_bytes_from_path(path)
            pm = QPixmap.fromImage(QImage.fromData(self._image_bytes))
            self.image_preview.setPixmap(pm.scaledToHeight(56, Qt.TransformationMode.SmoothTransformation))
        except Exception as ex:
            QMessageBox.warning(self, "Uyarı", f"Görsel yüklenemedi:\n{ex}")

    def _on_mode_changed(self, idx):
        is_text = idx == 0
        self.text_edit.setEnabled(is_text)
        self.font_size_spin.setEnabled(is_text)
        self.color_btn.setEnabled(is_text)
        self.image_btn.setEnabled(not is_text)
        self.image_scale_slider.setEnabled(not is_text)

    def _on_scope_changed(self, idx):
        self.range_row.setVisible(idx == 1)

    def get_config(self) -> WatermarkConfig:
        mode = "text" if self.mode_combo.currentIndex() == 0 else "image"
        scope = ["current", "range", "all"][self.scope_combo.currentIndex()]
        layout = "single" if self.layout_combo.currentIndex() == 0 else "tiled"
        return WatermarkConfig(
            mode=mode, text=self.text_edit.text(), font_size=float(self.font_size_spin.value()),
            color=QColor(self._color), opacity=self.opacity_slider.value() / 100.0,
            rotation=float(self.rotation_slider.value()), image_bytes=self._image_bytes,
            image_scale=self.image_scale_slider.value() / 100.0, layout=layout,
            tile_spacing=1.6, scope=scope, page_start=self.start_spin.value(),
            page_end=self.end_spin.value(),
        )
