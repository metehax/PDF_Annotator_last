"""
ui/stamps.py
============
Damga kütüphanesi: hazır damgalar (ONAYLANDI, REDDEDİLDİ, …), kullanıcının
kendi damgaları (isteğe bağlı logolu) ve damga görüntüsünü çizen fonksiyon.

Damga sayfaya bir resim işareti (ImageAnnotation) olarak basılır; böylece
taşıma, boyutlandırma, dışa aktarma ve proje kaydı mevcut altyapıyla çalışır.
Kendi damgaları QSettings'te JSON olarak saklanır.
"""

from __future__ import annotations

import base64
import datetime
import json
import math
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QColorDialog, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from ui.icons import icon

SCALE = 4.0           # damga görüntüsü 1 pt = 4 piksel çözünürlükte çizilir


@dataclass
class StampDef:
    text: str
    color: str
    logo_png_b64: Optional[str] = None
    builtin: bool = False
    uid: str = field(default="")

    def key(self) -> str:
        return self.uid or self.text


BUILTIN_STAMPS: List[StampDef] = [
    StampDef("ONAYLANDI", "#1e8e4f", builtin=True, uid="b:onay"),
    StampDef("REDDEDİLDİ", "#d22f27", builtin=True, uid="b:red"),
    StampDef("GÖRÜLDÜ", "#2f6fde", builtin=True, uid="b:goruldu"),
    StampDef("İNCELENDİ", "#2f6fde", builtin=True, uid="b:incelendi"),
    StampDef("ASLI GİBİDİR", "#1d3f91", builtin=True, uid="b:asli"),
    StampDef("TASLAK", "#6b7280", builtin=True, uid="b:taslak"),
    StampDef("GİZLİ", "#d22f27", builtin=True, uid="b:gizli"),
    StampDef("ÖDENDİ", "#1e8e4f", builtin=True, uid="b:odendi"),
    StampDef("İPTAL", "#d22f27", builtin=True, uid="b:iptal"),
    StampDef("ACİL", "#e2700b", builtin=True, uid="b:acil"),
]


def tr_upper(text: str) -> str:
    return text.replace("i", "İ").replace("ı", "I").upper()


def today() -> str:
    return datetime.date.today().strftime("%d.%m.%Y")


def render_stamp(st: StampDef, subline: str = "", slanted: bool = False,
                 scale: float = SCALE) -> QImage:
    """Damgayı saydam zeminli QImage olarak çizer (boyut: pt * scale)."""
    color = QColor(st.color)
    main_font = QFont("Segoe UI")
    main_font.setBold(True)
    main_font.setPixelSize(int(22 * scale))
    main_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 104)
    sub_font = QFont("Segoe UI")
    sub_font.setPixelSize(int(9.5 * scale))
    sub_font.setBold(True)
    fm_main, fm_sub = QFontMetricsF(main_font), QFontMetricsF(sub_font)
    text = tr_upper(st.text.strip() or "DAMGA")

    logo = QImage()
    if st.logo_png_b64:
        logo.loadFromData(base64.b64decode(st.logo_png_b64))
    pad_x, pad_y = 14 * scale, 8 * scale
    gap = 4 * scale
    text_w = max(fm_main.horizontalAdvance(text), fm_sub.horizontalAdvance(subline) if subline else 0)
    text_h = fm_main.height() + ((fm_sub.height() + 1 * scale) if subline else 0)
    logo_h = text_h
    logo_w = (logo.width() * logo_h / logo.height()) if not logo.isNull() and logo.height() else 0
    inner_w = text_w + (logo_w + 8 * scale if logo_w else 0)
    w, h = inner_w + 2 * pad_x, text_h + 2 * pad_y

    angle = -8.0 if slanted else 0.0
    rad = math.radians(abs(angle))
    W = w * math.cos(rad) + h * math.sin(rad) + 4 * scale
    H = w * math.sin(rad) + h * math.cos(rad) + 4 * scale
    img = QImage(int(math.ceil(W)), int(math.ceil(H)), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.translate(W / 2, H / 2)
    p.rotate(angle)
    p.translate(-w / 2, -h / 2)

    ink = QColor(color)
    ink.setAlphaF(0.92)
    outer = QRectF(1.6 * scale, 1.6 * scale, w - 3.2 * scale, h - 3.2 * scale)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(ink, 2.6 * scale))
    p.drawRoundedRect(outer, 5 * scale, 5 * scale)
    p.setPen(QPen(ink, 0.9 * scale))
    p.drawRoundedRect(outer.adjusted(gap, gap, -gap, -gap), 3 * scale, 3 * scale)

    x = pad_x
    if logo_w:
        p.drawImage(QRectF(x, pad_y, logo_w, logo_h), logo)
        x += logo_w + 8 * scale
    p.setPen(ink)
    p.setFont(main_font)
    block_w = text_w
    y = pad_y + fm_main.ascent()
    p.drawText(QPointF(x + (block_w - fm_main.horizontalAdvance(text)) / 2, y), text)
    if subline:
        p.setFont(sub_font)
        y2 = pad_y + fm_main.height() + 1 * scale + fm_sub.ascent()
        p.drawText(QPointF(x + (block_w - fm_sub.horizontalAdvance(subline)) / 2, y2), subline)
    p.end()
    return img


def image_png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def preview_icon(st: StampDef, height: int = 28) -> QIcon:
    img = render_stamp(st, "", False, scale=2.0)
    pm = QPixmap.fromImage(img.scaledToHeight(height * 2, Qt.TransformationMode.SmoothTransformation))
    pm.setDevicePixelRatio(2.0)
    return QIcon(pm)


# ---------------------------------------------------------------------------
# Kütüphane (hazır + kullanıcı damgaları)
# ---------------------------------------------------------------------------
class StampLibrary:
    KEY = "stamps/custom"

    def __init__(self, settings):
        self.settings = settings
        self.custom: List[StampDef] = []
        self.load()

    def load(self):
        raw = self.settings.value(self.KEY, "")
        self.custom = []
        try:
            for d in json.loads(raw) if raw else []:
                self.custom.append(StampDef(d["text"], d["color"], d.get("logo_png_b64"), False,
                                            d.get("uid") or d["text"]))
        except (ValueError, KeyError, TypeError):
            self.custom = []

    def save(self):
        data = [asdict(s) for s in self.custom]
        self.settings.setValue(self.KEY, json.dumps(data, ensure_ascii=False))

    def all(self) -> List[StampDef]:
        return self.custom + BUILTIN_STAMPS

    def add(self, st: StampDef):
        st.uid = st.uid or f"c:{datetime.datetime.now().timestamp()}"
        self.custom.insert(0, st)
        self.save()

    def remove(self, st: StampDef):
        self.custom = [s for s in self.custom if s.key() != st.key()]
        self.save()


# ---------------------------------------------------------------------------
# Damga düzenleme / kütüphane pencereleri
# ---------------------------------------------------------------------------
class StampEditor(QDialog):
    def __init__(self, parent=None, st: Optional[StampDef] = None):
        super().__init__(parent)
        self.setWindowTitle("Damga" if st is None else "Damgayı düzenle")
        self.st = StampDef(st.text, st.color, st.logo_png_b64, False, st.uid) if st else \
            StampDef("YENİ DAMGA", "#2f6fde")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)
        form = QFormLayout()
        self.text = QLineEdit(self.st.text)
        self.text.setMaxLength(40)
        self.text.textChanged.connect(self._update)
        form.addRow("Yazı:", self.text)
        self.color_btn = QPushButton()
        self.color_btn.setObjectName("colorbtn")
        self.color_btn.setFixedSize(52, 26)
        self.color_btn.clicked.connect(self._pick_color)
        form.addRow("Renk:", self.color_btn)
        logo_row = QHBoxLayout()
        self.btn_logo = QPushButton(icon("image"), "Logo seç…")
        self.btn_logo.setObjectName("secondary")
        self.btn_logo.clicked.connect(self._pick_logo)
        self.btn_logo_clear = QPushButton("Kaldır")
        self.btn_logo_clear.clicked.connect(self._clear_logo)
        logo_row.addWidget(self.btn_logo)
        logo_row.addWidget(self.btn_logo_clear)
        logo_row.addStretch(1)
        form.addRow("Logo:", logo_row)
        v.addLayout(form)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(110)
        self.preview.setObjectName("stampPreview")
        v.addWidget(self.preview)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(460, 330)
        self._update()

    def _update(self):
        self.st.text = self.text.text()
        self.color_btn.setStyleSheet(f"background:{self.st.color};")
        self.btn_logo_clear.setEnabled(bool(self.st.logo_png_b64))
        img = render_stamp(self.st, f"Ad Soyad · {today()}", False, scale=2.0)
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(2.0)
        self.preview.setPixmap(pm)

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self.st.color), self, "Damga rengi")
        if c.isValid():
            self.st.color = c.name()
            self._update()

    def _pick_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Logo seç", "", "Görseller (*.png *.jpg *.jpeg *.bmp *.svg)")
        if not path:
            return
        from pdf_engine import load_image_bytes_from_path
        img = QImage()
        img.loadFromData(load_image_bytes_from_path(path, 512))
        if img.isNull():
            QMessageBox.warning(self, "Logo", "Görsel okunamadı.")
            return
        if img.height() > 256:
            img = img.scaledToHeight(256, Qt.TransformationMode.SmoothTransformation)
        self.st.logo_png_b64 = base64.b64encode(image_png_bytes(img)).decode("ascii")
        self._update()

    def _clear_logo(self):
        self.st.logo_png_b64 = None
        self._update()


class StampLibraryDialog(QDialog):
    """Damgaları listeler; kendi damgalarını ekleme/düzenleme/silme."""

    def __init__(self, library: StampLibrary, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Damga kütüphanesi")
        self.lib = library
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        hint = QLabel("Hazır damgalar değiştirilemez; kendi damgalarınızı (logolu da olabilir) "
                      "ekleyebilir, düzenleyebilir ve silebilirsiniz.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.list = QListWidget()
        self.list.setIconSize(QSize(180, 44))
        self.list.setSpacing(2)
        self.list.currentRowChanged.connect(self._update_buttons)
        self.list.itemDoubleClicked.connect(lambda _i: self._edit())
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.btn_new = QPushButton(icon("plus"), "Yeni damga")
        self.btn_new.setObjectName("secondary")
        self.btn_new.clicked.connect(self._new)
        self.btn_edit = QPushButton(icon("rename"), "Düzenle")
        self.btn_edit.clicked.connect(self._edit)
        self.btn_del = QPushButton(icon("trash", "danger"), "Sil")
        self.btn_del.clicked.connect(self._delete)
        for b in (self.btn_new, self.btn_edit, self.btn_del):
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)
        self.resize(460, 520)
        self._fill()

    def _fill(self, select_key: Optional[str] = None):
        self.list.clear()
        for st in self.lib.all():
            item = QListWidgetItem(preview_icon(st, 40), "" if st.builtin else "  (sizin)")
            item.setData(Qt.ItemDataRole.UserRole, st)
            item.setSizeHint(QSize(0, 52))
            self.list.addItem(item)
            if select_key and st.key() == select_key:
                self.list.setCurrentItem(item)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        self._update_buttons()

    def _current(self) -> Optional[StampDef]:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_buttons(self, *_):
        st = self._current()
        editable = st is not None and not st.builtin
        self.btn_edit.setEnabled(editable)
        self.btn_del.setEnabled(editable)

    def _new(self):
        dlg = StampEditor(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.st.text.strip():
            self.lib.add(dlg.st)
            self._fill(dlg.st.key())

    def _edit(self):
        st = self._current()
        if st is None or st.builtin:
            return
        dlg = StampEditor(self, st)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.st.text.strip():
            for i, c in enumerate(self.lib.custom):
                if c.key() == st.key():
                    self.lib.custom[i] = dlg.st
            self.lib.save()
            self._fill(dlg.st.key())

    def _delete(self):
        st = self._current()
        if st is None or st.builtin:
            return
        if QMessageBox.question(self, "Damgayı sil", f"'{st.text}' damgası silinsin mi?") \
                == QMessageBox.StandardButton.Yes:
            self.lib.remove(st)
            self._fill()
