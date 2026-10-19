"""
ui/formui.py
============
PDF formları arayüzü: Formlar paneli (alan listesi + sıfırla/hesapla/sil),
alan özellikleri penceresi ve sayfa üstünde açılan satır içi düzenleyici.
Değişiklikleri MainWindow geri alınabilir komutlarla yapar.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QDate, QEvent, QRect, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from forms import CALC_OPS, DATE_FORMATS, KIND_NAMES, FieldInfo
from ui.icons import icon


def qt_date_format(fmt: str) -> str:
    """AFDate biçimi (dd.mm.yyyy) -> Qt biçimi (dd.MM.yyyy)."""
    return (fmt or DATE_FORMATS[0]).replace("mm", "MM")


def value_text(f: FieldInfo) -> str:
    if f.kind in ("checkbox", "radio"):
        if f.kind == "radio":
            return f.on_state + (" ●" if f.checked else " ○")
        return "✓" if f.checked else "—"
    return f.value


# ---------------------------------------------------------------------------
# Formlar paneli
# ---------------------------------------------------------------------------
class FormsPanel(QWidget):
    gotoRequested = Signal(object)          # FieldInfo
    propsRequested = Signal(object)
    deleteRequested = Signal(object)
    resetRequested = Signal()
    recalcRequested = Signal()
    newRequested = Signal()
    highlightToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panelBody")
        self._fields: List[FieldInfo] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 4, 10, 10)
        v.setSpacing(8)

        self.summary = QLabel("")
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)

        self.chk_highlight = QCheckBox("Alanları vurgula")
        self.chk_highlight.setChecked(True)
        self.chk_highlight.toggled.connect(self.highlightToggled)
        v.addWidget(self.chk_highlight)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Alan", "Tür", "Değer"])
        self.tree.setRootIsDecorated(True)
        self.tree.setColumnWidth(0, 110)
        self.tree.setColumnWidth(1, 80)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._emit(self.gotoRequested, it))
        self.tree.currentItemChanged.connect(lambda *_: self._sync_buttons())
        v.addWidget(self.tree, 1)

        r1 = QHBoxLayout()
        self.btn_fill = QPushButton(icon("edit_text"), "Doldur")
        self.btn_fill.setToolTip("Seçili alana git ve düzenle (çift tıklama da olur)")
        self.btn_fill.clicked.connect(lambda: self._emit(self.gotoRequested, self.tree.currentItem()))
        self.btn_props = QPushButton(icon("sliders"), "Özellikler")
        self.btn_props.clicked.connect(lambda: self._emit(self.propsRequested, self.tree.currentItem()))
        self.btn_del = QPushButton(icon("trash", "danger"), "Sil")
        self.btn_del.clicked.connect(lambda: self._emit(self.deleteRequested, self.tree.currentItem()))
        for b in (self.btn_fill, self.btn_props, self.btn_del):
            b.setObjectName("secondary")
            r1.addWidget(b)
        v.addLayout(r1)
        r2 = QHBoxLayout()
        self.btn_new = QPushButton(icon("plus"), "Yeni alan")
        self.btn_new.setToolTip("Form Alanı aracını seçer: sayfada bir kutu çizin")
        self.btn_new.clicked.connect(self.newRequested)
        self.btn_reset = QPushButton(icon("reset"), "Sıfırla")
        self.btn_reset.setToolTip("Tüm alanları boşalt (geri alınabilir)")
        self.btn_reset.clicked.connect(self.resetRequested)
        self.btn_calc = QPushButton(icon("calc"), "Hesapla")
        self.btn_calc.setToolTip("Hesaplanan alanları yeniden hesapla")
        self.btn_calc.clicked.connect(self.recalcRequested)
        for b in (self.btn_new, self.btn_reset, self.btn_calc):
            b.setObjectName("secondary")
            r2.addWidget(b)
        v.addLayout(r2)
        self._sync_buttons()

    def set_fields(self, fields: List[FieldInfo]) -> None:
        cur = self.current_field()
        cur_key = (cur.page, cur.nm) if cur else None
        self._fields = list(fields)
        self.tree.clear()
        pages = {}
        select = None
        for f in fields:
            parent = pages.get(f.page)
            if parent is None:
                parent = QTreeWidgetItem([f"Sayfa {f.page + 1}"])
                parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.tree.addTopLevelItem(parent)
                pages[f.page] = parent
            it = QTreeWidgetItem([f.name, KIND_NAMES.get(f.kind, "Diğer"), value_text(f)])
            it.setData(0, Qt.ItemDataRole.UserRole, f)
            tip = f"{f.name} — {KIND_NAMES.get(f.kind, 'Diğer')}"
            if f.kind == "calc":
                tip += f"\n{dict(CALC_OPS).get(f.calc_op, f.calc_op)}: {', '.join(f.calc_sources)}"
            it.setToolTip(0, tip)
            parent.addChild(it)
            if cur_key == (f.page, f.nm):
                select = it
        self.tree.expandAll()
        if select is not None:
            self.tree.setCurrentItem(select)
        n = len(fields)
        names = len({f.name for f in fields})
        self.summary.setText(
            f"{names} alan ({n} kutu). Seç aracıyla alana tıklayıp doldurun; "
            "Tab sonraki alana geçer." if n else
            "Bu belgede form alanı yok. 'Yeni alan' ile Form Alanı aracını seçip "
            "sayfada bir kutu çizerek kendi formunuzu oluşturun.")
        self._sync_buttons()

    def current_field(self) -> Optional[FieldInfo]:
        it = self.tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it is not None else None

    def _emit(self, sig, item):
        f = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if f is not None:
            sig.emit(f)

    def _sync_buttons(self):
        has = self.current_field() is not None
        for b in (self.btn_fill, self.btn_props, self.btn_del):
            b.setEnabled(has)
        any_f = bool(self._fields)
        self.btn_reset.setEnabled(any_f)
        self.btn_calc.setEnabled(any(f.kind == "calc" for f in self._fields))


# ---------------------------------------------------------------------------
# Alan özellikleri penceresi
# ---------------------------------------------------------------------------
class FormFieldDialog(QDialog):
    """spec (forms.field_spec biçimi) düzenler. names: belgedeki diğer alan adları,
    radio_groups: mevcut radyo grubu adları."""

    def __init__(self, spec: dict, names: List[str], radio_groups: List[str], parent=None,
                 creating: bool = True):
        super().__init__(parent)
        self.spec = dict(spec)
        self.kind = spec["kind"]
        self.names = [n for n in names if n != spec.get("name")]
        self.setWindowTitle(f"{'Yeni alan' if creating else 'Alan özellikleri'} — "
                            f"{KIND_NAMES[self.kind]}")
        self.setMinimumWidth(380)
        v = QVBoxLayout(self)
        form = QFormLayout()
        v.addLayout(form)

        if self.kind == "radio":
            self.ed_name = QComboBox()
            self.ed_name.setEditable(True)
            self.ed_name.addItems(radio_groups or [])
            self.ed_name.setCurrentText(spec.get("name", ""))
            form.addRow("Grup adı", self.ed_name)
            self.ed_state = QLineEdit(spec.get("on_state", ""))
            self.ed_state.setPlaceholderText("ör. Evet, Kadın, Nakit…")
            form.addRow("Seçenek", self.ed_state)
            form.addRow(self._hint("Aynı grup adındaki düğmelerden yalnızca biri seçilebilir. "
                                   "Seçenek adı Türkçe harfsiz saklanır."))
        else:
            self.ed_name = QLineEdit(spec.get("name", ""))
            form.addRow("Alan adı", self.ed_name)

        if self.kind == "combo":
            self.ed_opts = QPlainTextEdit("\n".join(spec.get("options") or []))
            self.ed_opts.setPlaceholderText("Her satıra bir seçenek")
            self.ed_opts.setFixedHeight(110)
            form.addRow("Seçenekler", self.ed_opts)
        if self.kind == "date":
            self.ed_fmt = QComboBox()
            self.ed_fmt.addItems(DATE_FORMATS)
            self.ed_fmt.setCurrentText(spec.get("date_fmt") or DATE_FORMATS[0])
            form.addRow("Biçim", self.ed_fmt)
        if self.kind == "calc":
            self.ed_op = QComboBox()
            for k, t in CALC_OPS:
                self.ed_op.addItem(t, k)
            self.ed_op.setCurrentIndex(max(0, [k for k, _ in CALC_OPS].index(spec.get("calc_op") or "SUM")))
            form.addRow("İşlem", self.ed_op)
            self.ed_src = QListWidget()
            self.ed_src.setFixedHeight(130)
            chosen = set(spec.get("calc_sources") or [])
            for n in self.names:
                it = QListWidgetItem(n)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if n in chosen else Qt.CheckState.Unchecked)
                self.ed_src.addItem(it)
            form.addRow("Kaynak alanlar", self.ed_src)
            form.addRow(self._hint("Seçili alanlardaki sayılar işleme girer (1.234,5 ya da 2,5 "
                                   "gibi yazımlar anlaşılır). Sonuç alanı salt okunurdur; "
                                   "Acrobat da aynı formülle hesaplar."))
        if self.kind in ("text", "combo", "date", "calc"):
            self.ed_size = QDoubleSpinBox()
            self.ed_size.setRange(0, 72)
            self.ed_size.setDecimals(0)
            self.ed_size.setSpecialValueText("Otomatik")
            self.ed_size.setValue(float(spec.get("font_size") or 0))
            form.addRow("Yazı boyutu", self.ed_size)

        self.err = QLabel("")
        self.err.setObjectName("hint")
        self.err.setStyleSheet("color: #e5484d;")
        v.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Tamam")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    @staticmethod
    def _hint(text):
        lb = QLabel(text)
        lb.setObjectName("hint")
        lb.setWordWrap(True)
        return lb

    def result_spec(self) -> dict:
        s = dict(self.spec)
        if self.kind == "radio":
            s["name"] = self.ed_name.currentText().strip()
            s["on_state"] = self.ed_state.text().strip()
        else:
            s["name"] = self.ed_name.text().strip()
        if self.kind == "combo":
            s["options"] = [o.strip() for o in self.ed_opts.toPlainText().splitlines() if o.strip()]
        if self.kind == "date":
            s["date_fmt"] = self.ed_fmt.currentText()
        if self.kind == "calc":
            s["calc_op"] = self.ed_op.currentData()
            s["calc_sources"] = [self.ed_src.item(i).text() for i in range(self.ed_src.count())
                                 if self.ed_src.item(i).checkState() == Qt.CheckState.Checked]
        if hasattr(self, "ed_size"):
            s["font_size"] = float(self.ed_size.value())
        return s

    def _accept(self):
        s = self.result_spec()
        if not s["name"]:
            self.err.setText("Alan adı boş olamaz.")
            return
        if "." in s["name"]:
            self.err.setText("Alan adında nokta kullanılamaz.")
            return
        if self.kind != "radio" and s["name"] in self.names:
            self.err.setText("Bu adda başka bir alan var; farklı bir ad seçin.")
            return
        if self.kind == "radio" and not s["on_state"]:
            self.err.setText("Seçenek adı boş olamaz.")
            return
        if self.kind == "combo" and not s["options"]:
            self.err.setText("En az bir seçenek girin.")
            return
        if self.kind == "calc" and not s["calc_sources"]:
            self.err.setText("En az bir kaynak alan işaretleyin.")
            return
        self.accept()


# ---------------------------------------------------------------------------
# Sayfa üstünde açılan düzenleyici
# ---------------------------------------------------------------------------
class FormFieldEditor(QWidget):
    """Alanın tam üstüne yerleşen küçük düzenleyici. Enter / odak kaybı ->
    committed(değer), Esc -> vazgeç, Tab / Shift+Tab -> sonraki / önceki alan."""
    committed = Signal(object, str, int)     # FieldInfo, değer, gezinme (+1/-1/0)
    cancelled = Signal()

    def __init__(self, field: FieldInfo, parent: QWidget):
        super().__init__(parent)
        self.field = field
        self._done = False
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        if field.kind == "combo":
            ed = QComboBox()
            ed.addItem("")
            ed.addItems(field.options)
            if field.value and field.value not in field.options:
                ed.addItem(field.value)
            ed.setCurrentText(field.value)
            ed.activated.connect(lambda _i: self._commit(0))
        elif field.kind == "date":
            ed = QDateEdit()
            ed.setCalendarPopup(True)
            fmt = qt_date_format(field.date_fmt)
            ed.setDisplayFormat(fmt)
            d = QDate.fromString(field.value, fmt)
            ed.setDate(d if d.isValid() else QDate.currentDate())
        else:
            ed = QLineEdit(field.value)
            ed.selectAll()
            ed.returnPressed.connect(lambda: self._commit(0))
        ed.setObjectName("formEditor")
        ed.installEventFilter(self)
        h.addWidget(ed)
        self.editor = ed

    def value(self) -> str:
        ed = self.editor
        if isinstance(ed, QComboBox):
            return ed.currentText()
        if isinstance(ed, QDateEdit):
            return ed.date().toString(qt_date_format(self.field.date_fmt))
        return ed.text()

    def place(self, rect: QRect) -> None:
        r = QRect(rect)
        r.setHeight(max(r.height(), 24))
        r.setWidth(max(r.width(), 120 if self.field.kind == "date" else 60))
        self.setGeometry(r)

    def start(self):
        self.show()
        self.raise_()
        self.editor.setFocus()

    def _commit(self, nav: int):
        if self._done:
            return
        self._done = True
        self.committed.emit(self.field, self.value(), nav)

    def cancel(self):
        if not self._done:
            self._done = True
            self.cancelled.emit()

    def finish(self):
        """Dışarıdan kapatma (kaydırma vb.): değeri kaydet."""
        self._commit(0)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress:
            k = ev.key()
            if k == Qt.Key.Key_Escape:
                self.cancel()
                return True
            if k in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                back = k == Qt.Key.Key_Backtab or bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                self._commit(-1 if back else 1)
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not isinstance(self.editor, QLineEdit):
                self._commit(0)
                return True
        elif ev.type() == QEvent.Type.FocusOut:
            popup = isinstance(self.editor, (QComboBox, QDateEdit)) and \
                self.editor.window() is not None and \
                self.editor.window().focusWidget() is not None and \
                self.editor.isAncestorOf(self.editor.window().focusWidget())
            if not popup and ev.reason() != Qt.FocusReason.PopupFocusReason:
                self._commit(0)
        return super().eventFilter(obj, ev)
