"""
ui/workflow.py
==============
Görsel iş akışı oluşturucu penceresi.

Solda adım paleti, ortada sürükleyerek sıralanan zincir, sağda seçili adımın ayarları. Üstte şablon
(kaydet / farklı kaydet / sil / içe-dışa aktar), altta hedef (açık belge · seçilen dosyalar · klasör),
ilerleme çubuğu, durdurma ve sonuç raporu. İş arka plan iş parçacığında çalışır (arayüz donmaz);
asıl iş `workflow.py` çekirdeğindedir.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QProgressBar, QPushButton, QRadioButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import docsec
import workflow as wfm
import workspace
from ui import theme
from ui.icons import icon, pixmap as icon_pixmap

MIME = "application/x-pdfannot-step"
_NEW = "— Yeni zincir —"


# ---------------------------------------------------------------------------
# Arka plan görevi
# ---------------------------------------------------------------------------
class _Sig(QObject):
    progress = Signal(float, str)
    result = Signal(object)
    done = Signal(object)
    failed = Signal(str)


class _WfTask(QRunnable):
    def __init__(self, wf, sources, default_dir, font_ctx, overrides):
        super().__init__()
        self.sig = _Sig()
        self._args = (wf, sources, default_dir, font_ctx, overrides)
        self._cancel = False
        self.setAutoDelete(False)

    def cancel(self):
        self._cancel = True

    def run(self):
        wf, sources, default_dir, font_ctx, overrides = self._args
        try:
            rep = wfm.run_batch(wf, sources, default_dir, self.sig.progress.emit, lambda: self._cancel, font_ctx,
                                overrides, on_result=self.sig.result.emit)
            self.sig.done.emit(rep)
        except Exception as ex:                      # beklenmeyen: arayüze iletilir
            self.sig.failed.emit(f"{type(ex).__name__}: {ex}")


# ---------------------------------------------------------------------------
# Adım ayar formu (şemadan üretilir)
# ---------------------------------------------------------------------------
class ParamForm(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._step: Optional[wfm.Step] = None
        self._form: Optional[QFormLayout] = None
        self._rows: Dict[str, QWidget] = {}
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._body: Optional[QWidget] = None
        self.set_step(None)

    def set_step(self, step: Optional[wfm.Step]):
        self._step = step
        if self._body is not None:
            self._body.setParent(None)
            self._body.deleteLater()
        self._rows = {}
        self._body = QWidget()
        self._outer.addWidget(self._body)
        self._body.show()                             # görünür pencereye sonradan eklenen widget kendiliğinden görünmez
        lay = QVBoxLayout(self._body)
        lay.setContentsMargins(0, 0, 0, 0)
        if step is None:
            hint = QLabel("Soldaki listeden bir adım ekleyin ya da zincirden bir adım seçin.")
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            lay.addWidget(hint)
            lay.addStretch(1)
            self._form = None
            return
        self._form = QFormLayout()
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self._form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._form.setVerticalSpacing(10)
        lay.addLayout(self._form)
        lay.addStretch(1)
        for spec in step.stype.params:
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            v.addWidget(self._make_editor(spec, step.params[spec.key]))
            if spec.hint:
                h = QLabel(spec.hint)
                h.setObjectName("hint")
                h.setWordWrap(True)
                v.addWidget(h)
            label = "" if spec.kind == "bool" else spec.label
            self._form.addRow(label, box)
            self._rows[spec.key] = box
        self._update_visibility()

    def _commit(self, spec: wfm.Param, value):
        if self._step is None:
            return
        self._step.params[spec.key] = spec.coerce(value)
        self._update_visibility()
        self.changed.emit()

    def _update_visibility(self):
        if self._form is None or self._step is None:
            return
        for spec in self._step.stype.params:
            if spec.show_if:
                k, v = spec.show_if
                self._form.setRowVisible(self._rows[spec.key], self._step.params.get(k) == v)

    def _make_editor(self, spec: wfm.Param, value) -> QWidget:
        k, c = spec.kind, lambda v, s=spec: self._commit(s, v)
        if k == "bool":
            w = QCheckBox(spec.label)
            w.setChecked(bool(value))
            w.toggled.connect(c)
            return w
        if k in ("text", "password"):
            w = QLineEdit(str(value))
            if k == "password":
                w.setEchoMode(QLineEdit.EchoMode.Password)
            w.textChanged.connect(c)
            return w
        if k == "int":
            w = QSpinBox()
            w.setRange(int(spec.minv), int(spec.maxv))
            w.setValue(int(value))
            w.valueChanged.connect(c)
            return w
        if k == "float":
            w = QDoubleSpinBox()
            w.setRange(spec.minv, spec.maxv)
            w.setDecimals(1)
            w.setValue(float(value))
            w.valueChanged.connect(c)
            return w
        if k == "choice":
            w = QComboBox()
            for val, lbl in spec.choices or []:
                w.addItem(lbl, val)
            w.setCurrentIndex(max(0, w.findData(value)))
            w.currentIndexChanged.connect(lambda _i, w=w, s=spec: self._commit(s, w.currentData()))
            return w
        if k == "multi":
            w = QWidget()
            g = QGridLayout(w)
            g.setContentsMargins(0, 0, 0, 0)
            boxes = []
            for n, (val, lbl) in enumerate(spec.choices or []):
                cb = QCheckBox(lbl)
                cb.setChecked(val in value)
                boxes.append((val, cb))
                g.addWidget(cb, n // 2, n % 2)
            for _v, cb in boxes:
                cb.toggled.connect(lambda _t, bx=boxes, s=spec: self._commit(s, [v for v, b in bx if b.isChecked()]))
            return w
        if k == "color":
            w = QPushButton(str(value))
            self._paint_color(w, str(value))

            def pick(_=False, w=w, s=spec):
                col = QColorDialog.getColor(QColor(self._step.params[s.key]), self, s.label)
                if col.isValid():
                    self._paint_color(w, col.name())
                    self._commit(s, col.name())
            w.clicked.connect(pick)
            return w
        w = QWidget()                                 # folder / file
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        ed = QLineEdit(str(value))
        btn = QPushButton("…")
        btn.setFixedWidth(34)
        h.addWidget(ed, 1)
        h.addWidget(btn)
        ed.textChanged.connect(c)

        def browse(_=False, ed=ed, kind=k, s=spec):
            if kind == "folder":
                p = QFileDialog.getExistingDirectory(self, s.label, ed.text())
            else:
                p, _f = QFileDialog.getOpenFileName(self, s.label, ed.text(), "Resim (*.png *.jpg *.jpeg *.webp *.bmp)")
            if p:
                ed.setText(p)
        btn.clicked.connect(browse)
        return w

    @staticmethod
    def _paint_color(btn: QPushButton, hexcol: str):
        fg = "#000000" if QColor(hexcol).lightness() > 140 else "#ffffff"
        btn.setText(hexcol)
        btn.setStyleSheet(f"QPushButton {{ background:{hexcol}; color:{fg}; border:1px solid #888; }}")


# ---------------------------------------------------------------------------
# Zincir listesi
# ---------------------------------------------------------------------------
class _Palette(QListWidget):
    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setIconSize(QSize(20, 20))
        self.setSpacing(0)

    def startDrag(self, _actions):                    # noqa: N802
        it = self.currentItem()
        if it is None:
            return
        md = self.mimeData([it])
        md.setData(MIME, str(it.data(Qt.ItemDataRole.UserRole)).encode())
        drag = QDrag(self)
        drag.setMimeData(md)
        drag.exec(Qt.DropAction.CopyAction)


class _ChainList(QListWidget):
    step_dropped = Signal(str, int)                   # adım türü, hedef satır
    order_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSpacing(4)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):                      # noqa: N802
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):                       # noqa: N802
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def _row_at(self, pos) -> int:
        idx = self.indexAt(pos)
        if not idx.isValid():
            return self.count()
        r = self.visualItemRect(self.item(idx.row()))
        return idx.row() + (1 if pos.y() > r.center().y() else 0)

    def dropEvent(self, e):                           # noqa: N802
        if e.mimeData().hasFormat(MIME):
            key = bytes(e.mimeData().data(MIME)).decode()
            self.step_dropped.emit(key, self._row_at(e.position().toPoint()))
            e.acceptProposedAction()
            return
        super().dropEvent(e)                          # iç sıralama
        QTimer.singleShot(0, self.order_changed.emit)  # öğe widget'ları taşımada kaybolur: yeniden kurulacak


class StepCard(QFrame):
    toggled = Signal(bool)
    remove = Signal()

    def __init__(self, number: int, step: wfm.Step):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(10)
        grip = QLabel()
        grip.setPixmap(icon_pixmap("grip", 16, None, 1.0))
        grip.setCursor(Qt.CursorShape.OpenHandCursor)
        num = QLabel(str(number))
        num.setFixedSize(22, 22)
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = theme.current()
        num.setStyleSheet(f"background:{t['accent']}; color:#fff; border-radius:11px; font-weight:600;")
        ico = QLabel()
        ico.setPixmap(icon_pixmap(step.stype.icon, 20, None, 1.0))
        txt = QVBoxLayout()
        txt.setSpacing(0)
        self.title = QLabel(step.stype.title)
        self.title.setStyleSheet("font-weight:600;")
        self.sub = QLabel()
        self.sub.setObjectName("hint")
        txt.addWidget(self.title)
        txt.addWidget(self.sub)
        self.chk = QCheckBox()
        self.chk.setChecked(step.enabled)
        self.chk.setToolTip("Bu adımı çalıştır / atla")
        btn = QPushButton()
        btn.setIcon(icon("trash", "danger"))
        btn.setFlat(True)
        btn.setFixedSize(28, 28)
        btn.setToolTip("Adımı sil")
        for w in (grip, num, ico):
            h.addWidget(w)
        h.addLayout(txt, 1)
        h.addWidget(self.chk)
        h.addWidget(btn)
        self.chk.toggled.connect(self.toggled)
        btn.clicked.connect(self.remove)
        self.set_step(step)

    def set_step(self, step: wfm.Step):
        s = step.summary()
        self.sub.setText(s if len(s) < 70 else s[:67] + "…")
        self.sub.setToolTip(s)
        self.setEnabled(True)
        self.title.setEnabled(step.enabled)
        self.sub.setEnabled(step.enabled)


# ---------------------------------------------------------------------------
# Ana pencere
# ---------------------------------------------------------------------------
class WorkflowDialog(QDialog):
    def __init__(self, main, parent=None):
        super().__init__(parent or main)
        self.setWindowTitle("Görsel iş akışı")
        self.setWindowIcon(icon("workflow", "accent"))
        self.setModal(False)
        self.resize(1160, 800)
        self._main = main
        self.lib = wfm.WorkflowLibrary(main.settings)
        self.wf = wfm.Workflow("Yeni iş akışı")
        self._task: Optional[_WfTask] = None
        self._loading = False
        self._dirty = False
        self._files: List[str] = []
        self.report: Optional[wfm.BatchReport] = None
        self._build()
        self._restore_last()
        self._refresh_templates()
        self._rebuild_chain()
        self._update_targets()

    # -- görünüm kurulumu ------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel("Görsel iş akışı")
        title.setObjectName("propTitle")
        top.addWidget(title)
        top.addSpacing(16)
        top.addWidget(QLabel("Şablon"))
        self.cmb = QComboBox()
        self.cmb.setMinimumWidth(260)
        self.cmb.activated.connect(self._on_template_picked)
        top.addWidget(self.cmb)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Zincir adı")
        self.name_edit.setMaximumWidth(220)
        self.name_edit.textChanged.connect(self._on_name)
        top.addWidget(self.name_edit)
        self.btn_save = QPushButton(icon("save"), "Kaydet")
        self.btn_save.clicked.connect(lambda: self.save_template())
        self.btn_saveas = QPushButton("Farklı kaydet…")
        self.btn_saveas.clicked.connect(lambda: self.save_template(ask=True))
        self.btn_del = QPushButton(icon("trash", "danger"), "Sil")
        self.btn_del.clicked.connect(lambda: self.delete_template())
        more = QPushButton("⋯")
        more.setFixedWidth(34)
        menu = QMenu(more)
        menu.addAction("Dosyaya aktar…", self.export_template)
        menu.addAction("Dosyadan içe aktar…", self.import_template)
        menu.addSeparator()
        menu.addAction("Zinciri temizle", self.clear_chain)
        more.setMenu(menu)
        for b in (self.btn_save, self.btn_saveas, self.btn_del, more):
            top.addWidget(b)
        top.addStretch(1)
        root.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        # palet
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 8, 0)
        cap = QLabel("Adımlar")
        cap.setObjectName("propTitle")
        lv.addWidget(cap)
        self.palette = _Palette()
        for key in wfm.STEP_ORDER:
            st = wfm.STEP_TYPES[key]
            it = QListWidgetItem(icon(st.icon), st.title)
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setToolTip(st.desc)
            it.setSizeHint(QSize(0, 38))
            self.palette.addItem(it)
        self.palette.itemDoubleClicked.connect(lambda it: self.add_step(it.data(Qt.ItemDataRole.UserRole)))
        lv.addWidget(self.palette, 1)
        h = QLabel("Çift tıklayın ya da zincire sürükleyin.")
        h.setObjectName("hint")
        h.setWordWrap(True)
        lv.addWidget(h)
        split.addWidget(left)
        # zincir
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(8, 0, 8, 0)
        cap2 = QLabel("Zincir")
        cap2.setObjectName("propTitle")
        mv.addWidget(cap2)
        self.chain = _ChainList()
        self.chain.currentRowChanged.connect(self._on_select)
        self.chain.step_dropped.connect(lambda k, r: self.add_step(k, r))
        self.chain.order_changed.connect(self._reorder_from_list)
        mv.addWidget(self.chain, 1)
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color:{theme.current()['warning']};")
        mv.addWidget(self.warn)
        hint = QLabel("Adımları sürükleyerek sıralayın. Sıkıştır, Parola ve Kaydet adımları sırası ne olursa olsun "
                      "en sonda uygulanır.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        mv.addWidget(hint)
        split.addWidget(mid)
        # ayarlar
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)
        self.set_title = QLabel("Ayarlar")
        self.set_title.setObjectName("propTitle")
        rv.addWidget(self.set_title)
        self.set_desc = QLabel()
        self.set_desc.setObjectName("hint")
        self.set_desc.setWordWrap(True)
        rv.addWidget(self.set_desc)
        self.form = ParamForm()
        self.form.changed.connect(self._on_params_changed)
        rv.addWidget(self.form, 1)
        self.btn_reset = QPushButton("Varsayılan ayarlara dön")
        self.btn_reset.clicked.connect(self.reset_selected)
        rv.addWidget(self.btn_reset)
        split.addWidget(right)
        split.setSizes([230, 480, 400])
        root.addWidget(split, 1)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(line)

        # hedef
        tg = QGridLayout()
        tg.setHorizontalSpacing(10)
        self.r_doc = QRadioButton("Açık belge")
        self.r_files = QRadioButton("Seçilen dosyalar")
        self.r_folder = QRadioButton("Bütün klasör")
        self.r_doc.setChecked(True)
        self.btn_files = QPushButton("Dosya seç…")
        self.btn_files.clicked.connect(self.pick_files)
        self.lbl_files = QLabel()
        self.lbl_files.setObjectName("hint")
        self.btn_folder = QPushButton("Klasör seç…")
        self.btn_folder.clicked.connect(self.pick_folder)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Klasör yolu")
        self.chk_sub = QCheckBox("Alt klasörler dahil")
        self.chk_sub.setChecked(True)
        self.lbl_doc = QLabel()
        self.lbl_doc.setObjectName("hint")
        tg.addWidget(self.r_doc, 0, 0)
        tg.addWidget(self.lbl_doc, 0, 1, 1, 3)
        tg.addWidget(self.r_files, 1, 0)
        tg.addWidget(self.btn_files, 1, 1)
        tg.addWidget(self.lbl_files, 1, 2, 1, 2)
        tg.addWidget(self.r_folder, 2, 0)
        tg.addWidget(self.btn_folder, 2, 1)
        tg.addWidget(self.folder_edit, 2, 2)
        tg.addWidget(self.chk_sub, 2, 3)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Boşsa: Kaydet adımındaki konum / özgün dosyanın klasörü")
        btn_out = QPushButton("Çıktı klasörü…")
        btn_out.clicked.connect(self.pick_out)
        tg.addWidget(btn_out, 3, 1)
        tg.addWidget(self.out_edit, 3, 2, 1, 2)
        tg.setColumnStretch(2, 1)
        root.addLayout(tg)
        for r in (self.r_doc, self.r_files, self.r_folder):
            r.toggled.connect(lambda _c: self._update_targets())

        # çalıştır
        run = QHBoxLayout()
        self.btn_run = QPushButton(icon("play", "on_accent"), "Çalıştır")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.run)
        self.btn_stop = QPushButton(icon("stop"), "Durdur")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.status = QLabel("Hazır.")
        self.status.setObjectName("hint")
        run.addWidget(self.btn_run)
        run.addWidget(self.btn_stop)
        run.addWidget(self.bar, 1)
        root.addLayout(run)
        root.addWidget(self.status)

        # sonuçlar
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Dosya", "Durum", "Sayfa", "Boyut", "Süre", "Ayrıntı"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(130)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.open_result(r))
        root.addWidget(self.table)
        rb = QHBoxLayout()
        self.btn_open = QPushButton("Sonucu uygulamada aç")
        self.btn_open.clicked.connect(lambda: self.open_result(self.table.currentRow()))
        self.btn_dir = QPushButton(icon("folder"), "Çıktı klasörünü aç")
        self.btn_dir.clicked.connect(self.open_output_folder)
        self.btn_rep = QPushButton("Raporu kaydet…")
        self.btn_rep.clicked.connect(lambda: self.save_report())
        for b in (self.btn_open, self.btn_dir, self.btn_rep):
            b.setEnabled(False)
            rb.addWidget(b)
        rb.addStretch(1)
        close = QPushButton("Kapat")
        close.clicked.connect(self.close)
        rb.addWidget(close)
        root.addLayout(rb)

    # -- zincir düzenleme --------------------------------------------------------
    def _selected_step(self) -> Optional[wfm.Step]:
        r = self.chain.currentRow()
        return self.wf.steps[r] if 0 <= r < len(self.wf.steps) else None

    def _rebuild_chain(self, select: Optional[int] = None):
        keep = self.chain.currentRow() if select is None else select
        self._loading = True
        self.chain.blockSignals(True)
        self.chain.clear()
        for i, st in enumerate(self.wf.steps):
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, id(st))
            card = StepCard(i + 1, st)
            card.toggled.connect(lambda on, s=st: self._toggle(s, on))
            card.remove.connect(lambda s=st: self.remove_step(s))
            it.setSizeHint(QSize(0, 58))
            self.chain.addItem(it)
            self.chain.setItemWidget(it, card)
        self.chain.blockSignals(False)
        self._loading = False
        if self.wf.steps:
            self.chain.setCurrentRow(max(0, min(keep, len(self.wf.steps) - 1)))
        else:
            self._on_select(-1)
        self._refresh_warnings()

    def add_step(self, key: str, row: Optional[int] = None) -> wfm.Step:
        st = self.wf.add(key, None, row)
        self._mark_dirty()
        self._rebuild_chain(self.wf.steps.index(st))
        return st

    def remove_step(self, step: wfm.Step):
        if step in self.wf.steps:
            i = self.wf.steps.index(step)
            self.wf.steps.remove(step)
            self._mark_dirty()
            self._rebuild_chain(i)

    def _toggle(self, step: wfm.Step, on: bool):
        step.enabled = on
        self._mark_dirty()
        self._refresh_cards()
        self._refresh_warnings()

    def _reorder_from_list(self):
        order = {id(s): s for s in self.wf.steps}
        ids = [self.chain.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.chain.count())]
        if sorted(ids) == sorted(order) and [order[i] for i in ids] != self.wf.steps:
            sel = self._selected_step()
            self.wf.steps = [order[i] for i in ids]
            self._mark_dirty()
            self._rebuild_chain(self.wf.steps.index(sel) if sel in self.wf.steps else 0)
        else:
            self._rebuild_chain()

    def clear_chain(self):
        self.wf.steps = []
        self._mark_dirty()
        self._rebuild_chain()

    def _on_select(self, _row: int):
        if self._loading:
            return
        st = self._selected_step()
        self.form.set_step(st)
        self.set_title.setText(st.stype.title if st else "Ayarlar")
        self.set_desc.setText(st.stype.desc if st else "")
        self.btn_reset.setEnabled(st is not None)

    def reset_selected(self):
        st = self._selected_step()
        if st:
            st.params = st.stype.defaults()
            self._mark_dirty()
            self.form.set_step(st)
            self._refresh_cards()
            self._refresh_warnings()

    def _on_params_changed(self):
        self._mark_dirty()
        self._refresh_cards()
        self._refresh_warnings()

    def _refresh_cards(self):
        for i, st in enumerate(self.wf.steps):
            card = self.chain.itemWidget(self.chain.item(i))
            if card is not None:
                card.set_step(st)

    def _refresh_warnings(self):
        w = self.wf.validate()
        self.warn.setText("\n".join(("⚠ " if lvl == "uyarı" else "ℹ ") + t for lvl, t in w))

    # -- şablonlar -----------------------------------------------------------------
    def _refresh_templates(self, select: Optional[str] = None):
        self.cmb.blockSignals(True)
        self.cmb.clear()
        self.cmb.addItem(_NEW, None)
        for n in self.lib.names():
            self.cmb.addItem(n + ("  (hazır)" if self.lib.is_builtin(n) else ""), n)
        i = self.cmb.findData(select if select is not None else (self.wf.name if self.wf.name in self.lib.names() else None))
        self.cmb.setCurrentIndex(max(0, i))
        self.cmb.blockSignals(False)
        self._update_template_buttons()

    def _update_template_buttons(self):
        name = self.cmb.currentData()
        user = name is not None and not self.lib.is_builtin(name)
        self.btn_del.setEnabled(user)
        self.btn_save.setEnabled(user or name is None)

    def _on_template_picked(self, _i):
        name = self.cmb.currentData()
        if name is None:
            self.load_workflow(wfm.Workflow("Yeni iş akışı"))
        else:
            self.load_workflow(self.lib.get(name))

    def load_workflow(self, wf: wfm.Workflow):
        self.wf = wf
        self._dirty = False
        self.name_edit.blockSignals(True)
        self.name_edit.setText("" if wf.builtin else wf.name)
        self.name_edit.blockSignals(False)
        self._refresh_templates(wf.name if wf.name in self.lib.names() else None)
        self._rebuild_chain(0)

    def _on_name(self, text: str):
        self.wf.name = text.strip() or self.wf.name
        self._mark_dirty()

    def _mark_dirty(self):
        self._dirty = True
        self._update_template_buttons()

    def save_template(self, ask: bool = False, name: Optional[str] = None) -> bool:
        name = name or self.name_edit.text().strip()
        cur = self.cmb.currentData()
        if ask or not name or self.lib.is_builtin(name):
            default = name if name and not self.lib.is_builtin(name) else (cur + " (kopya)" if cur else "Yeni şablon")
            name = self.ask_name(default)
            if not name:
                return False
        try:
            self.lib.save(self.wf, name)
        except ValueError as ex:
            QMessageBox.warning(self, "Kaydedilemedi", str(ex))
            return False
        self._dirty = False
        self.name_edit.blockSignals(True)
        self.name_edit.setText(name)
        self.name_edit.blockSignals(False)
        self._refresh_templates(name)
        self._toast(f"Şablon kaydedildi: {name}")
        return True

    def ask_name(self, default: str) -> str:
        txt, ok = QInputDialog.getText(self, "Şablon adı", "Bu zincir için bir ad girin:", text=default)
        return txt.strip() if ok else ""

    def delete_template(self, confirmed: Optional[bool] = None) -> bool:
        name = self.cmb.currentData()
        if name is None or self.lib.is_builtin(name):
            return False
        if confirmed is None:
            confirmed = QMessageBox.question(self, "Şablonu sil", f"'{name}' şablonu silinsin mi?") == QMessageBox.StandardButton.Yes
        if not confirmed:
            return False
        self.lib.delete(name)
        self.load_workflow(wfm.Workflow("Yeni iş akışı"))
        return True

    def export_template(self, path: Optional[str] = None) -> bool:
        if path is None:
            path, _f = QFileDialog.getSaveFileName(self, "Şablonu dışa aktar", (self.wf.name or "zincir") + ".json", "Şablon (*.json)")
        if not path:
            return False
        with open(path, "w", encoding="utf-8") as f:
            f.write(wfm.WorkflowLibrary.export_json(self.wf))
        return True

    def import_template(self, path: Optional[str] = None) -> bool:
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self, "Şablonu içe aktar", "", "Şablon (*.json)")
        if not path:
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                wf = wfm.WorkflowLibrary.import_json(f.read())
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, "İçe aktarılamadı", str(ex))
            return False
        self.load_workflow(wf)
        self._dirty = True
        return True

    def _restore_last(self):
        try:
            d = json.loads(self._main.settings.value("workflow_last", "") or "null")
            if d:
                self.wf = wfm.Workflow.from_dict(d)
                self.name_edit.setText(self.wf.name)
        except (ValueError, TypeError):
            pass

    # -- hedef ---------------------------------------------------------------------
    def _update_targets(self):
        s = getattr(self._main, "active_session", None)
        self.r_doc.setEnabled(s is not None)
        self.lbl_doc.setText(f"{s.title} ({s.pdf.page_count} sayfa) · işaretler dahil işlenir, özgün belge değişmez"
                             if s is not None else "Açık belge yok")
        if s is None and self.r_doc.isChecked():
            self.r_files.setChecked(True)
        self.lbl_files.setText(f"{len(self._files)} dosya seçili" if self._files else "Dosya seçilmedi")
        self.btn_files.setEnabled(self.r_files.isChecked())
        self.btn_folder.setEnabled(self.r_folder.isChecked())
        self.folder_edit.setEnabled(self.r_folder.isChecked())
        self.chk_sub.setEnabled(self.r_folder.isChecked())

    def pick_files(self):
        paths, _f = QFileDialog.getOpenFileNames(self, "İşlenecek dosyalar", "", "PDF ve resimler (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)")
        if paths:
            self._files = paths
            self._update_targets()

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "İşlenecek klasör", self.folder_edit.text())
        if d:
            self.folder_edit.setText(d)

    def pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Çıktı klasörü", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def build_sources(self) -> List[wfm.Source]:
        if self.r_doc.isChecked():
            s = self._main.active_session
            tmp = s.pdf._annotated_copy(s.annotations, self._main.font_ctx)
            try:
                data = tmp.write()
            finally:
                tmp.close()
            path = s.path if s.path and os.path.isfile(s.path) else None
            return [wfm.Source(s.title or "belge.pdf", path, data, protect_original=True)]
        if self.r_files.isChecked():
            return [wfm.Source(os.path.basename(p), p) for p in self._files if os.path.isfile(p)]
        folder = self.folder_edit.text().strip()
        if not os.path.isdir(folder):
            return []
        return wfm.collect_files(folder, self.chk_sub.isChecked(), wfm.save_suffix_of(self.wf))

    # -- çalıştırma ------------------------------------------------------------------
    def ask_passwords(self) -> Optional[str]:
        """Parola adımı 'çalıştırırken sor' ise açma parolasını iki kez ister. None = vazgeçildi."""
        for _ in range(3):
            a, ok = QInputDialog.getText(self, "Açma parolası", "Çıktı belgeleri için açma parolası\n(boş bırakırsanız parola konmaz):",
                                         QLineEdit.EchoMode.Password)
            if not ok:
                return None
            if not a:
                return ""
            b, ok = QInputDialog.getText(self, "Parolayı doğrula", "Parolayı tekrar girin:", QLineEdit.EchoMode.Password)
            if not ok:
                return None
            if a == b:
                return a
            QMessageBox.warning(self, "Parolalar uyuşmuyor", "İki parola aynı değil, tekrar deneyin.")
        return None

    def run(self) -> bool:
        if self._task is not None:
            return False
        if not self.wf.enabled_steps():
            QMessageBox.information(self, "Zincir boş", "Önce zincire en az bir adım ekleyin.")
            return False
        sources = self.build_sources()
        if not sources:
            QMessageBox.information(self, "İşlenecek dosya yok", "Seçilen hedefte işlenecek PDF/resim bulunamadı.")
            return False
        overrides = {}
        if any(s.type == "password" and s.params["ask"] for s in self.wf.enabled_steps()):
            pw = self.ask_passwords()
            if pw is None:
                return False
            overrides["user_password"] = pw
        self._main.settings.setValue("workflow_last", json.dumps(self.wf.to_dict(), ensure_ascii=False))
        self.table.setRowCount(0)
        self.report = None
        default_out = self.out_edit.text().strip() or (workspace.out_dir("workflow") or "")
        task = _WfTask(self.wf.copy(), sources, default_out, getattr(self._main, "font_ctx", None), overrides)
        task.sig.progress.connect(self._on_progress)
        task.sig.result.connect(self._on_result)
        task.sig.done.connect(self._on_done)
        task.sig.failed.connect(self._on_failed)
        self._task = task
        self._set_running(True)
        self.status.setText(f"{len(sources)} dosya işleniyor…")
        QThreadPool.globalInstance().start(task)
        return True

    def stop(self):
        if self._task is not None:
            self._task.cancel()
            self.status.setText("Durduruluyor… (sürmekte olan dosya bitince)")
            self.btn_stop.setEnabled(False)

    def _set_running(self, on: bool):
        self.btn_run.setEnabled(not on)
        self.btn_stop.setEnabled(on)
        for w in (self.palette, self.chain, self.form, self.cmb, self.name_edit, self.btn_save, self.btn_saveas, self.btn_del,
                  self.r_doc, self.r_files, self.r_folder, self.btn_files, self.btn_folder, self.folder_edit, self.chk_sub,
                  self.out_edit):
            w.setEnabled(not on)
        if not on:
            self._update_targets()
            self._update_template_buttons()

    def _on_progress(self, frac: float, msg: str):
        self.bar.setValue(int(max(0.0, min(1.0, frac)) * 1000))
        self.status.setText(msg)

    def _on_result(self, r: wfm.FileResult):
        row = self.table.rowCount()
        self.table.insertRow(row)
        mark = {"ok": "✓ Tamam", "hata": "✕ Hata", "iptal": "■ Durduruldu"}.get(r.status, r.status)
        size = f"{docsec.human_size(r.size_before)} → {docsec.human_size(r.size_after)}" if r.status == "ok" else docsec.human_size(r.size_before)
        detail = r.message or " · ".join(s.message for s in r.steps if s.message)
        cells = [r.name, mark, str(r.pages or ""), size, f"{r.seconds:.1f} sn", detail]
        t = theme.current()
        for c, txt in enumerate(cells):
            it = QTableWidgetItem(txt)
            it.setToolTip(detail if c == 5 else r.output or r.source)
            if c == 1:
                it.setForeground(QColor({"ok": t["accent_text"], "hata": t["danger"]}.get(r.status, t["warning"])))
            self.table.setItem(row, c, it)
        self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, r)
        self.table.scrollToBottom()

    def _on_done(self, rep: wfm.BatchReport):
        self.report = rep
        self._task = None
        self._set_running(False)
        self.bar.setValue(1000 if not rep.cancelled else self.bar.value())
        self.status.setText(rep.summary())
        for b in (self.btn_open, self.btn_dir, self.btn_rep):
            b.setEnabled(True)
        self._toast(rep.summary(), "warning" if rep.failed or rep.cancelled else "success")

    def _on_failed(self, msg: str):
        self._task = None
        self._set_running(False)
        self.status.setText("İş akışı çalıştırılamadı.")
        QMessageBox.warning(self, "İş akışı hatası", msg)

    # -- sonuç işlemleri ----------------------------------------------------------------
    def _result_at(self, row: int) -> Optional[wfm.FileResult]:
        it = self.table.item(row, 0) if 0 <= row < self.table.rowCount() else None
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def open_result(self, row: int) -> bool:
        r = self._result_at(row)
        if r is None or not r.output or not os.path.isfile(r.output):
            return False
        self._main.open_paths([r.output])
        return True

    def open_output_folder(self) -> bool:
        outs = [r.output for r in (self.report.results if self.report else []) if r.output and os.path.isfile(r.output)]
        if not outs:
            return False
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(outs[0])))
        return True

    def save_report(self, path: Optional[str] = None) -> bool:
        if not self.report:
            return False
        if path is None:
            path, _f = QFileDialog.getSaveFileName(self, "Raporu kaydet", "is_akisi_raporu.csv", "CSV (*.csv);;Metin (*.txt)")
        if not path:
            return False
        text = self.report.to_text() if path.lower().endswith(".txt") else self.report.to_csv()
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(text)
        return True

    def _toast(self, text: str, kind: str = "success"):
        t = getattr(self._main, "toasts", None)
        if t is not None:
            t.show(text, kind)

    def showEvent(self, e):                           # noqa: N802
        super().showEvent(e)
        self._update_targets()

    def closeEvent(self, e):                          # noqa: N802
        if self._task is not None:
            QMessageBox.information(self, "İş sürüyor", "İş akışı çalışırken pencere kapatılamaz. Önce 'Durdur'a basın.")
            e.ignore()
            return
        self._main.settings.setValue("workflow_last", json.dumps(self.wf.to_dict(), ensure_ascii=False))
        super().closeEvent(e)
