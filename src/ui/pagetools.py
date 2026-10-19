"""
ui/pagetools.py
===============
Sayfa araçları pencereleri:

* HeadFootDialog   — sayfa numarası / üstbilgi / altbilgi / Bates numaralandırma
* CropPagesDialog  — sayfaları kenar boşluğuna göre kırpma
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
    QSpinBox, QVBoxLayout,
)

from headfoot import HeadFootConfig, resolve
from ui.icons import icon

MM = 72.0 / 25.4          # 1 mm = 2.8346 pt

_TOKENS = (("Sayfa no", "{sayfa}"), ("Toplam", "{toplam}"), ("Tarih", "{tarih}"),
           ("Dosya adı", "{dosya}"), ("Bates", "{bates}"))

_PRESETS = (
    ("Alt orta: Sayfa 1 / 12", ("", "", ""), ("", "Sayfa {sayfa} / {toplam}", "")),
    ("Alt sağ: 1", ("", "", ""), ("", "", "{sayfa}")),
    ("Alt orta: 1", ("", "", ""), ("", "{sayfa}", "")),
    ("Üst: dosya adı + tarih, alt: sayfa", ("{dosya}", "", "{tarih}"), ("", "{sayfa} / {toplam}", "")),
    ("Bates (alt sağ)", ("", "", ""), ("", "", "{bates}")),
    ("Bates + sayfa no", ("", "", ""), ("{bates}", "", "Sayfa {sayfa} / {toplam}")),
)


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("hint")
    lbl.setWordWrap(True)
    return lbl


class HeadFootDialog(QDialog):
    """Sayfa numarası / üstbilgi / altbilgi / Bates. `bates=True` ise Bates ön ayarıyla açılır."""

    def __init__(self, initial: HeadFootConfig, page_count: int, filename: str,
                 bates: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bates numaralandırma" if bates else "Sayfa numarası, üstbilgi ve altbilgi")
        self.setMinimumWidth(560)
        self._page_count = page_count
        self._filename = filename
        self._color = QColor.fromRgbF(*initial.color)
        self._last_edit: Optional[QLineEdit] = None

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # -- hazır düzenler --------------------------------------------------
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Hazır düzen:"))
        self.preset = QComboBox()
        self.preset.addItem("Seçin…", None)
        for name, head, foot in _PRESETS:
            self.preset.addItem(name, (head, foot))
        self.preset.currentIndexChanged.connect(self._apply_preset)
        prow.addWidget(self.preset, 1)
        root.addLayout(prow)

        # -- 2 satır x 3 sütun metin kutusu ------------------------------------
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        for c, name in enumerate(("Sol", "Orta", "Sağ")):
            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(lbl, 0, c + 1)
        self.edits: Dict[str, list] = {"header": [], "footer": []}
        for r, (key, title) in enumerate((("header", "Üstbilgi"), ("footer", "Altbilgi"))):
            grid.addWidget(QLabel(title), r + 1, 0)
            for c in range(3):
                e = QLineEdit(getattr(initial, key)[c])
                e.textChanged.connect(self._update_preview)
                e.installEventFilter(self)
                self.edits[key].append(e)
                grid.addWidget(e, r + 1, c + 1)
        root.addLayout(grid)

        # -- yer tutucu düğmeleri ------------------------------------------------
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Ekle:"))
        for label, token in _TOKENS:
            b = QPushButton(label)
            b.setObjectName("secondary")
            b.setToolTip(f"İmlecin olduğu kutuya {token} ekler")
            b.clicked.connect(lambda _=False, t=token: self._insert_token(t))
            trow.addWidget(b)
        trow.addStretch(1)
        root.addLayout(trow)

        self.preview = QLabel()
        self.preview.setObjectName("hint")
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.preview)

        # -- görünüm ---------------------------------------------------------------
        box = QGroupBox("Görünüm ve kapsam")
        form = QFormLayout(box)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(5, 48)
        self.size_spin.setValue(int(initial.font_size))
        self.size_spin.valueChanged.connect(self._update_preview)
        form.addRow("Punto:", self.size_spin)
        self.color_btn = QPushButton()
        self.color_btn.setFixedHeight(24)
        self.color_btn.clicked.connect(self._pick_color)
        self._paint_color()
        form.addRow("Renk:", self.color_btn)
        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(5, 120)
        self.margin_spin.setSuffix(" mm")
        self.margin_spin.setValue(round(initial.margin / MM, 1))
        form.addRow("Kenar boşluğu:", self.margin_spin)
        self.start_spin = QSpinBox()
        self.start_spin.setRange(-999, 99999)
        self.start_spin.setValue(initial.start_number)
        self.start_spin.valueChanged.connect(self._update_preview)
        form.addRow("İlk sayfa numarası:", self.start_spin)

        scope_row = QHBoxLayout()
        self.rb_all = QRadioButton("Tüm sayfalar")
        self.rb_range = QRadioButton("Aralık:")
        (self.rb_range if initial.scope == "range" else self.rb_all).setChecked(True)
        self.from_spin = QSpinBox()
        self.to_spin = QSpinBox()
        for sp, v in ((self.from_spin, initial.page_start), (self.to_spin, initial.page_end)):
            sp.setRange(1, max(1, page_count))
            sp.setValue(min(max(1, v), max(1, page_count)))
            sp.valueChanged.connect(self._update_preview)
        if initial.scope != "range":
            self.to_spin.setValue(max(1, page_count))
        scope_row.addWidget(self.rb_all)
        scope_row.addWidget(self.rb_range)
        scope_row.addWidget(self.from_spin)
        scope_row.addWidget(QLabel("–"))
        scope_row.addWidget(self.to_spin)
        scope_row.addStretch(1)
        self.rb_all.toggled.connect(self._update_preview)
        form.addRow("Sayfalar:", scope_row)
        self.chk_skip = QCheckBox("İlk sayfaya yazma (kapak sayfası)")
        self.chk_skip.setChecked(initial.skip_first)
        self.chk_skip.toggled.connect(self._update_preview)
        form.addRow("", self.chk_skip)
        root.addWidget(box)

        # -- Bates ------------------------------------------------------------------
        self.bates_box = QGroupBox("Bates numarası  ({bates} yer tutucusu için)")
        bf = QFormLayout(self.bates_box)
        brow = QHBoxLayout()
        self.b_prefix = QLineEdit(initial.bates_prefix)
        self.b_prefix.setPlaceholderText("Önek (ör. DAVA-)")
        self.b_digits = QSpinBox()
        self.b_digits.setRange(1, 12)
        self.b_digits.setValue(initial.bates_digits)
        self.b_digits.setSuffix(" hane")
        self.b_start = QSpinBox()
        self.b_start.setRange(0, 999999999)
        self.b_start.setValue(initial.bates_start)
        self.b_suffix = QLineEdit(initial.bates_suffix)
        self.b_suffix.setPlaceholderText("Sonek")
        for w in (self.b_prefix, self.b_digits, self.b_start, self.b_suffix):
            brow.addWidget(w)
        bf.addRow(brow)
        bf.addRow(_hint("Bates: hukuki belge setlerinde her sayfaya benzersiz, ardışık bir "
                        "tanıtıcı basılır (ör. DAVA-000001). Başlangıç değerini ikinci bir set "
                        "için kaldığınız yerden devam ettirebilirsiniz."))
        for w in (self.b_prefix, self.b_suffix):
            w.textChanged.connect(self._update_preview)
        for w in (self.b_digits, self.b_start):
            w.valueChanged.connect(self._update_preview)
        root.addWidget(self.bates_box)

        # -- düğmeler ----------------------------------------------------------------
        bb = QDialogButtonBox()
        ok = bb.addButton("Kaydet…", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setObjectName("primary")
        bb.addButton("Vazgeç", QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        if bates:
            self.preset.setCurrentIndex(5)     # "Bates (alt sağ)"
            self.b_prefix.setFocus()
        self._update_preview()

    # -- olaylar ---------------------------------------------------------------------------
    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.Type.FocusIn and isinstance(obj, QLineEdit):
            self._last_edit = obj
        return super().eventFilter(obj, ev)

    def _apply_preset(self):
        data = self.preset.currentData()
        if not data:
            return
        head, foot = data
        for c in range(3):
            self.edits["header"][c].setText(head[c])
            self.edits["footer"][c].setText(foot[c])

    def _insert_token(self, token: str):
        e = self._last_edit or self.edits["footer"][1]
        e.insert(token)
        e.setFocus()

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "Yazı rengi")
        if c.isValid():
            self._color = c
            self._paint_color()

    def _paint_color(self):
        self.color_btn.setStyleSheet(f"background:{self._color.name()};")

    def _update_preview(self, *_):
        cfg = self.get_config()
        pages = cfg.pages(self._page_count)
        if not pages:
            self.preview.setText("Seçili aralıkta yazılacak sayfa yok.")
            return
        count = len(pages)
        lines = []
        for label, row in (("Üst", cfg.header), ("Alt", cfg.footer)):
            if any(t.strip() for t in row):
                cells = [resolve(t, cfg, 0, count, self._filename) for t in row]
                lines.append(f"{label}:  {cells[0]}  |  {cells[1]}  |  {cells[2]}")
        if lines:
            self.preview.setText(f"Önizleme ({pages[0] + 1}. sayfa, toplam {count} sayfa)\n" + "\n".join(lines))
        else:
            self.preview.setText("Henüz yazılacak bir metin girilmedi.")

    # -- sonuç -----------------------------------------------------------------------------
    def get_config(self) -> HeadFootConfig:
        return HeadFootConfig(
            header=[e.text() for e in self.edits["header"]],
            footer=[e.text() for e in self.edits["footer"]],
            font_size=float(self.size_spin.value()),
            color=(self._color.redF(), self._color.greenF(), self._color.blueF()),
            margin=self.margin_spin.value() * MM,
            start_number=self.start_spin.value(),
            skip_first=self.chk_skip.isChecked(),
            scope="all" if self.rb_all.isChecked() else "range",
            page_start=self.from_spin.value(),
            page_end=self.to_spin.value(),
            bates_prefix=self.b_prefix.text(),
            bates_suffix=self.b_suffix.text(),
            bates_digits=self.b_digits.value(),
            bates_start=self.b_start.value(),
        )

    def accept(self):
        if self.get_config().is_empty():
            self.preview.setText("Kaydetmek için en az bir kutuya metin yazın.")
            return
        super().accept()


class CropPagesDialog(QDialog):
    """Kenarlardan kırpma. Sonuç: (üst, alt, sol, sağ) pt ve sayfa kapsamı."""

    def __init__(self, page_count: int, current_page: int, page_size, auto_bbox, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sayfaları kırp")
        self.setMinimumWidth(380)
        self._auto_bbox = auto_bbox            # callable(page_index) -> (üst, alt, sol, sağ) pt | None
        self._current = current_page
        self._page_count = page_count
        self._w, self._h = page_size

        root = QVBoxLayout(self)
        root.addWidget(_hint("Her kenardan ne kadarının kesileceğini girin. Kırpma yalnızca sayfanın "
                             "görünen alanını küçültür; Ctrl+Z ile geri alınır."))
        form = QFormLayout()
        self.spins: Dict[str, QDoubleSpinBox] = {}
        for key, label in (("top", "Üstten:"), ("bottom", "Alttan:"),
                           ("left", "Soldan:"), ("right", "Sağdan:")):
            sp = QDoubleSpinBox()
            sp.setRange(0, 500)
            sp.setDecimals(1)
            sp.setSuffix(" mm")
            sp.valueChanged.connect(self._update_info)
            self.spins[key] = sp
            form.addRow(label, sp)
        root.addLayout(form)

        self.chk_link = QCheckBox("Dört kenarı birlikte değiştir")
        self.chk_link.toggled.connect(self._update_info)
        root.addWidget(self.chk_link)
        for sp in self.spins.values():
            sp.valueChanged.connect(self._sync_linked)

        self.btn_auto = QPushButton(icon("fit_page"), "İçeriğe göre otomatik (bu sayfa)")
        self.btn_auto.setObjectName("secondary")
        self.btn_auto.clicked.connect(self._do_auto)
        root.addWidget(self.btn_auto)

        scope = QHBoxLayout()
        self.rb_cur = QRadioButton("Bu sayfa")
        self.rb_all = QRadioButton("Tüm sayfalar")
        self.rb_range = QRadioButton("Aralık:")
        self.rb_cur.setChecked(True)
        self.from_spin = QSpinBox()
        self.to_spin = QSpinBox()
        for sp in (self.from_spin, self.to_spin):
            sp.setRange(1, max(1, page_count))
        self.from_spin.setValue(current_page + 1)
        self.to_spin.setValue(max(1, page_count))
        for w in (self.rb_cur, self.rb_all, self.rb_range, self.from_spin, QLabel("–"), self.to_spin):
            scope.addWidget(w)
        scope.addStretch(1)
        root.addLayout(scope)

        self.info = QLabel()
        self.info.setObjectName("hint")
        root.addWidget(self.info)

        bb = QDialogButtonBox()
        ok = bb.addButton("Kırp", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setObjectName("primary")
        bb.addButton("Vazgeç", QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self._update_info()

    def _sync_linked(self, v):
        if not self.chk_link.isChecked():
            return
        for sp in self.spins.values():
            if sp.value() != v:
                sp.blockSignals(True)
                sp.setValue(v)
                sp.blockSignals(False)
        self._update_info()

    def _do_auto(self):
        res = self._auto_bbox(self._current)
        if res is None:
            self.info.setText("Bu sayfada içerik bulunamadı.")
            return
        for key, val in zip(("top", "bottom", "left", "right"), res):
            self.spins[key].blockSignals(True)
            self.spins[key].setValue(round(val / MM, 1))
            self.spins[key].blockSignals(False)
        self._update_info()

    def _update_info(self, *_):
        t, b, l, r = self.margins_pt()
        w, h = self._w - l - r, self._h - t - b
        if w < 20 or h < 20:
            self.info.setText("Kırpma çok büyük: sayfada yeterli alan kalmıyor.")
        else:
            self.info.setText(f"Sonuç boyutu (bu sayfa için): {w / MM:.0f} × {h / MM:.0f} mm")

    def margins_pt(self):
        s = self.spins
        return tuple(s[k].value() * MM for k in ("top", "bottom", "left", "right"))

    def pages(self):
        if self.rb_all.isChecked():
            return list(range(self._page_count))
        if self.rb_range.isChecked():
            lo, hi = sorted((self.from_spin.value(), self.to_spin.value()))
            return list(range(lo - 1, hi))
        return [self._current]

    def accept(self):
        t, b, l, r = self.margins_pt()
        if not any((t, b, l, r)):
            self.info.setText("En az bir kenar için değer girin.")
            return
        if self._w - l - r < 20 or self._h - t - b < 20:
            return
        super().accept()
