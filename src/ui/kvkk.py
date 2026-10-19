"""
ui/kvkk.py
==========
"Kişisel verileri bul ve karart" penceresi.

Belgeyi arka planda tarar (pii.py), bulunanları türüne göre gruplanmış,
işaretlenebilir bir listede gösterir ve sayfada vurgular. "Seçilenleri
karart" her biri için kalıcı bir sansür kutusu (RedactionAnnotation) ekler;
tümü tek bir geri alma adımıdır. Dışa aktarırken altındaki metin PDF'ten
gerçekten silinir.
"""

from __future__ import annotations

from typing import Dict, List

import pymupdf as fitz
from PySide6.QtCore import QRectF, QSize, Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
    QPushButton, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout,
)

import ocr
import pii
from models import AddAnnotationCommand, RedactionAnnotation
from ui.ocrdialog import _OcrTask
from ui.icons import icon
from ui.redactopts import RedactOptions

_HIT_ROLE = Qt.ItemDataRole.UserRole + 10


class KvkkDialog(QDialog):
    def __init__(self, main, session):
        super().__init__(main)
        self.setWindowTitle("Kişisel verileri bul ve karart")
        self.setWindowIcon(icon("privacy", "accent"))
        self.setModal(False)
        self.resize(560, 620)
        self._main = main
        self._session = session
        self._hits: List[pii.Hit] = []
        self._task = None

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)
        title = QLabel("Kişisel verileri bul ve karart")
        title.setObjectName("propTitle")
        v.addWidget(title)
        intro = QLabel("Belgedeki kişisel verileri (KVKK) bulur. Seçtikleriniz siyah kutuyla "
                       "kapatılır ve dışa aktarırken altındaki metin PDF'ten kalıcı olarak silinir.")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        v.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        self.kind_checks: Dict[str, QCheckBox] = {}
        for i, (key, label) in enumerate(pii.CATEGORIES.items()):
            chk = QCheckBox(label)
            chk.setChecked(True)
            self.kind_checks[key] = chk
            grid.addWidget(chk, i // 3, i % 3)
        v.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.scope = QComboBox()
        self.scope.addItem(f"Tüm belge ({session.pdf.page_count} sayfa)", "all")
        self.scope.addItem("Yalnızca bu sayfa", "current")
        row.addWidget(self.scope)
        self.chk_ocr = QCheckBox("Taranmış sayfalarda OCR kullan")
        self.chk_ocr.setToolTip("Sayfada gerçek metin yoksa (taranmış belge, resim) metin OCR ile okunur")
        self._tessdata = ocr.find_tessdata()
        self.chk_ocr.setChecked(self._tessdata is not None)
        self.chk_ocr.setEnabled(self._tessdata is not None)
        if self._tessdata is None:
            self.chk_ocr.setToolTip("OCR kurulu değil: " + ocr.setup_message())
        row.addWidget(self.chk_ocr, 1)
        self.btn_scan = QPushButton(icon("search", "on_accent"), "Tara")
        self.btn_scan.setObjectName("primary")
        self.btn_scan.clicked.connect(self._scan)
        row.addWidget(self.btn_scan)
        self.btn_stop = QPushButton("Durdur")
        self.btn_stop.setVisible(False)
        self.btn_stop.clicked.connect(self._stop)
        row.addWidget(self.btn_stop)
        v.addLayout(row)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        v.addWidget(self.bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Bulunan", "Sayfa"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(lambda cur, _prev: self._show_item(cur))
        v.addWidget(self.tree, 1)

        self.summary = QLabel("Taramak için 'Tara'ya basın.")
        self.summary.setObjectName("hint")
        v.addWidget(self.summary)

        self.redact_opts = RedactOptions(self._main)            # dolgu rengi + etiket: sansür aracıyla ortak
        v.addWidget(self.redact_opts)

        bottom = QHBoxLayout()
        self.btn_all = QPushButton("Tümünü seç")
        self.btn_all.clicked.connect(lambda: self._set_all(True))
        self.btn_none = QPushButton("Hiçbiri")
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        bottom.addWidget(self.btn_all)
        bottom.addWidget(self.btn_none)
        bottom.addStretch(1)
        self.btn_apply = QPushButton(icon("redact", "on_accent"), "Seçilenleri karart")
        self.btn_apply.setObjectName("primary")
        self.btn_apply.setIconSize(QSize(18, 18))
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply)
        close = QPushButton("Kapat")
        close.clicked.connect(self.close)
        bottom.addWidget(self.btn_apply)
        bottom.addWidget(close)
        v.addLayout(bottom)

    # -- tarama -----------------------------------------------------------------
    def _scan(self):
        s = self._session
        kinds = [k for k, c in self.kind_checks.items() if c.isChecked()]
        if not kinds:
            self.summary.setText("En az bir veri türü seçin.")
            return
        pages = [s.current_page] if self.scope.currentData() == "current" else list(range(s.pdf.page_count))
        ocr_env = None
        if self.chk_ocr.isChecked() and self._tessdata:
            ocr_env = (self._tessdata, ocr.pick_language(self._tessdata))
        try:
            snap = ocr.open_snapshot(s.pdf.doc, s.pdf.lock)
        except Exception as ex:
            self.summary.setText(f"Belge okunamadı: {ex}")
            return

        def job(progress, cancelled):
            hits = []
            try:
                for n, i in enumerate(pages):
                    if cancelled():
                        break
                    hits.extend(pii.scan_page(snap[i], kinds, ocr_env))
                    progress(n + 1, len(pages))
            finally:
                snap.close()
            return hits

        self._busy(True)
        task = _OcrTask(job)
        task.signals.progress.connect(lambda n, t: (self.bar.setRange(0, t), self.bar.setValue(n)))
        task.signals.done.connect(self._on_done)
        task.signals.failed.connect(self._on_failed)
        self._task = task
        QThreadPool.globalInstance().start(task)

    def _stop(self):
        if self._task is not None:
            self._task.cancel()

    def _busy(self, on):
        self.btn_scan.setVisible(not on)
        self.btn_stop.setVisible(on)
        self.bar.setVisible(on)
        self.bar.setRange(0, 0)
        for w in (self.scope, self.chk_ocr, *self.kind_checks.values()):
            w.setEnabled(not on and (w is not self.chk_ocr or self._tessdata is not None))
        if on:
            self.summary.setText("Taranıyor…")

    def _on_failed(self, msg):
        self._busy(False)
        self._task = None
        self.summary.setText(f"Tarama başarısız: {msg}")

    def _covered(self, hit) -> bool:
        r = QRectF(hit.rect[0], hit.rect[1], hit.rect[2] - hit.rect[0], hit.rect[3] - hit.rect[1])
        for a in self._session.annotations.get(hit.page, []):
            if isinstance(a, RedactionAnnotation) and a.rect.adjusted(-1, -1, 1, 1).contains(r):
                return True
        return False

    def _on_done(self, hits):
        self._busy(False)
        self._task = None
        self._hits = hits
        self.tree.blockSignals(True)
        self.tree.clear()
        groups: Dict[str, QTreeWidgetItem] = {}
        already = 0
        for h in hits:
            g = groups.get(h.kind)
            if g is None:
                g = QTreeWidgetItem([h.label, ""])
                g.setFlags(g.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                g.setCheckState(0, Qt.CheckState.Checked)
                f = g.font(0)
                f.setBold(True)
                g.setFont(0, f)
                self.tree.addTopLevelItem(g)
                groups[h.kind] = g
            it = QTreeWidgetItem([h.masked(), str(h.page + 1)])
            it.setData(0, _HIT_ROLE, h)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            covered = self._covered(h)
            if covered:
                already += 1
                it.setText(0, h.masked() + "  (zaten karartılmış)")
                it.setCheckState(0, Qt.CheckState.Unchecked)
                it.setDisabled(True)
            else:
                it.setCheckState(0, Qt.CheckState.Checked)
            it.setToolTip(0, f"{h.label}: {h.masked()}")
            g.addChild(it)
        for kind, g in groups.items():
            g.setText(0, f"{pii.CATEGORIES[kind]}  ({g.childCount()})")
        self.tree.expandAll()
        self.tree.blockSignals(False)
        if hits:
            extra = f", {already} tanesi zaten karartılmış" if already else ""
            self.summary.setText(f"{len(hits)} kişisel veri bulundu{extra}. Satıra tıklayınca sayfada gösterilir.")
        else:
            self.summary.setText("Seçilen türlerde kişisel veri bulunamadı.")
        self._highlight()
        self._update_apply()

    # -- liste ----------------------------------------------------------------
    def _checked_hits(self) -> List[pii.Hit]:
        out = []
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            h = item.data(0, _HIT_ROLE)
            if h is not None and not item.isDisabled() and item.checkState(0) == Qt.CheckState.Checked:
                out.append(h)
            it += 1
        return out

    def _set_all(self, on):
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, state)

    def _on_item_changed(self, _item, _col):
        self._update_apply()

    def _update_apply(self):
        n = len(self._checked_hits())
        self.btn_apply.setEnabled(n > 0)
        self.btn_apply.setText(f"Seçilenleri karart ({n})" if n else "Seçilenleri karart")

    def _by_page(self):
        out: Dict[int, list] = {}
        for h in self._hits:
            out.setdefault(h.page, []).append(fitz.Rect(h.rect))
        return out

    def _highlight(self, active=None, center=False):
        self._main.view.set_all_search_highlights(self._by_page(), active, center=center)

    def _show_item(self, item):
        if item is None:
            return
        h = item.data(0, _HIT_ROLE)
        if h is None or self._session is not self._main.active_session:
            return
        same_page = [x for x in self._hits if x.page == h.page]
        idx = next((i for i, x in enumerate(same_page) if x is h), 0)
        self._highlight((h.page, idx), center=True)
        s = self._session
        if s.current_page != h.page:
            s.current_page = h.page
            self._main._after_page_change(h.page)

    # -- karartma ----------------------------------------------------------
    def _apply(self):
        s = self._session
        hits = self._checked_hits()
        if not hits or s not in self._main.sessions:
            return
        color = self._main.state.redact_color
        label = self._main.state.redact_label
        s.undo_stack.beginMacro(f"{len(hits)} kişisel veriyi karart")
        for h in hits:
            x0, y0, x1, y1 = h.rect
            rect = QRectF(x0 - 1.5, y0 - 1.0, (x1 - x0) + 3.0, (y1 - y0) + 2.0)
            s.undo_stack.push(AddAnnotationCommand(s, h.page, RedactionAnnotation(rect, color, label=label),
                                                   on_change=self._main._on_session_change,
                                                   label="Karart"))
        s.undo_stack.endMacro()
        self._main.toasts.show(
            f"{len(hits)} alan karartıldı.<br><span style='color:gray'>Dışa aktarırken altındaki "
            f"metin kalıcı olarak silinir. Geri almak için Ctrl+Z.</span>", "success", timeout_ms=5000)
        self.close()

    def closeEvent(self, e):
        self._stop()
        self._main._update_search_highlight_for_page()
        super().closeEvent(e)
