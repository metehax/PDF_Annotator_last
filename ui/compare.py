"""
ui/compare.py
=============
Karşılaştırma modunun "Değişiklikler" paneli: metin farkının sayfa sayfa
listesi, tür süzgeci ve önceki/sonraki gezinti. Panel yalnızca listeler ve
sinyal yollar; vurgulama ve sayfaya gitme MainWindow'da (ComparePane.goto).
"""

from __future__ import annotations

import os
import time
from typing import List, Optional

from PySide6.QtCore import QMarginsF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

import textdiff
from textdiff import Change, DiffResult
from ui import theme
from ui.icons import icon

_MARK = {"add": "+", "del": "−", "mod": "≠"}
_COLOR = {"add": "good", "del": "danger", "mod": "warning"}


def html_to_pdf(html_text: str, path: str) -> int:
    """Rapor HTML'ini A4 PDF'e yazar (QTextDocument + QPrinter; ek paket yok). Sayfa sayısını döndürür."""
    pr = QPrinter(QPrinter.PrinterMode.HighResolution)
    pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    pr.setOutputFileName(path)
    pr.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                 QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter))
    doc = QTextDocument()
    doc.setHtml(html_text)
    doc.print_(pr)
    return doc.pageCount()


class CompareDiffPanel(QWidget):
    changeActivated = Signal(object)           # Change
    refreshRequested = Signal()
    exitRequested = Signal()
    filtersChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panelBody")
        self._result: Optional[DiffResult] = None
        self._shown: List[Change] = []
        self._last_c, self._last_t = None, 0.0
        self.names = ("", "")                  # (eski, yeni) belge adları — rapor başlığı için
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 6)
        v.setSpacing(6)

        self.btn_exit = QPushButton(icon("close"), "Karşılaştırmadan çık")
        self.btn_exit.setObjectName("secondary")
        self.btn_exit.setToolTip("Tek belge görünümüne döner")
        self.btn_exit.clicked.connect(self.exitRequested.emit)
        v.addWidget(self.btn_exit)

        self.summary = QLabel("")
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.hide()
        v.addWidget(self.progress)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.chk = {}
        for kind, label in (("add", "Eklenen"), ("del", "Silinen"), ("mod", "Değişen")):
            c = QCheckBox(label)
            c.setChecked(True)
            c.toggled.connect(self._on_filter)
            self.chk[kind] = c
            row.addWidget(c)
        row.addStretch(1)
        v.addLayout(row)

        self.chk_case = QCheckBox("Büyük/küçük harfi yoksay")
        self.chk_case.toggled.connect(lambda _c: self.refreshRequested.emit())
        v.addWidget(self.chk_case)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setWordWrap(True)
        self.tree.setIndentation(12)
        self.tree.setUniformRowHeights(False)
        self.tree.itemClicked.connect(self._on_item)
        self.tree.currentItemChanged.connect(lambda cur, _prev: self._on_item(cur))
        v.addWidget(self.tree, 1)

        nav = QHBoxLayout()
        self.btn_prev = QPushButton(icon("chevron_up"), "Önceki")
        self.btn_prev.setObjectName("secondary")
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next = QPushButton(icon("chevron_down"), "Sonraki")
        self.btn_next.setObjectName("secondary")
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.btn_run = QPushButton(icon("reset"), "Yeniden karşılaştır")
        self.btn_run.setObjectName("secondary")
        self.btn_run.clicked.connect(self.refreshRequested.emit)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        v.addLayout(nav)
        v.addWidget(self.btn_run)
        self.btn_report = QPushButton(icon("download"), "Raporu kaydet…")
        self.btn_report.setObjectName("secondary")
        self.btn_report.setToolTip("Eski | yeni tablosunu HTML ya da PDF olarak kaydeder")
        self.btn_report.clicked.connect(self.save_report)
        v.addWidget(self.btn_report)
        self._sync_buttons()

    @staticmethod
    def _summary_html(res: DiffResult) -> str:
        """Özet satırı: sayılar renkli ve kalın (eklenen yeşil, silinen kırmızı, değişen sarı)."""
        if not res.changes:
            return f"<b style='color:{theme.current()['good']}'>Metinler aynı</b>"
        t = theme.current()
        return (f"<span style='font-size:13px'><b style='color:{t['good']}'>+{res.count('add')}</b> eklenen · "
                f"<b style='color:{t['danger']}'>−{res.count('del')}</b> silinen · "
                f"<b style='color:{t['warning']}'>≠{res.count('mod')}</b> değişen</span>")

    # -- durum ---------------------------------------------------------------
    @property
    def ignore_case(self) -> bool:
        return self.chk_case.isChecked()

    def kinds(self) -> set:
        return {k for k, c in self.chk.items() if c.isChecked()}

    def visible_changes(self) -> List[Change]:
        return list(self._shown)

    def set_message(self, text: str):
        self._result = None
        self._shown = []
        self.tree.clear()
        self.summary.setText(text)
        self.progress.hide()
        self._sync_buttons()

    def set_busy(self, done: int = 0, total: int = 0):
        self.summary.setText("Metinler karşılaştırılıyor…")
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.progress.show()

    def show_result(self, res: DiffResult):
        self._result = res
        self.progress.hide()
        if res.error:
            side = "Sol" if res.error == "no_text_a" else "Sağ"
            self.set_message(f"{side} belgede metin katmanı yok (taranmış olabilir). "
                             "Önce OCR ile metni tanıtın.")
            return
        self._fill()

    # -- liste ---------------------------------------------------------------
    def _fill(self):
        res = self._result
        self.tree.clear()
        self._shown = []
        if res is None:
            return
        kinds = self.kinds()
        self.summary.setText(self._summary_html(res))
        pages = {}
        for c in res.changes:
            if c.kind in kinds:
                pages.setdefault(c.page, []).append(c)
        for page, items in sorted(pages.items()):
            head = QTreeWidgetItem([f"Sayfa {page + 1} · {len(items)} değişiklik"])
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(head)
            for c in items:
                self._shown.append(c)
                head.addChild(self._make_item(c))
            head.setExpanded(True)
        self._sync_buttons()

    def _make_item(self, c: Change) -> QTreeWidgetItem:
        if c.kind == "add":
            body = textdiff.snippet(c.text_b)
        elif c.kind == "del":
            body = textdiff.snippet(c.text_a)
        else:
            body = f"{textdiff.snippet(c.text_a, 34)} → {textdiff.snippet(c.text_b, 34)}"
        pa = c.focus_a()[0] if c.a_rects else None
        pb = c.focus_b()[0] if c.b_rects else None
        where = f" (eski s.{pa + 1})" if pa is not None and pb is not None and pa != pb else ""
        it = QTreeWidgetItem([f"{_MARK[c.kind]}  {body}{where}"])
        it.setForeground(0, QBrush(QColor(theme.qcolor(_COLOR[c.kind]))))
        tip = {"add": f"Eklendi: {c.text_b}", "del": f"Silindi: {c.text_a}",
               "mod": f"Eski: {c.text_a}\nYeni: {c.text_b}"}[c.kind]
        it.setToolTip(0, tip[:600])
        it.setData(0, Qt.ItemDataRole.UserRole, c)
        return it

    def _on_filter(self, _checked=False):
        self._fill()
        self.filtersChanged.emit()

    def _on_item(self, item, _col=0):
        if item is None:
            return
        c = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(c, Change):
            return
        # tıklama hem currentItemChanged hem itemClicked üretir: ikinciyi yut
        now = time.monotonic()
        if c is self._last_c and now - self._last_t < 0.2:
            return
        self._last_c, self._last_t = c, now
        self.changeActivated.emit(c)

    # -- gezinti -------------------------------------------------------------
    def _leaves(self) -> List[QTreeWidgetItem]:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            out.extend(top.child(j) for j in range(top.childCount()))
        return out

    def step(self, delta: int):
        leaves = self._leaves()
        if not leaves:
            return
        cur = self.tree.currentItem()
        idx = leaves.index(cur) if cur in leaves else (-1 if delta > 0 else len(leaves))
        nxt = leaves[(idx + delta) % len(leaves)]
        self.tree.setCurrentItem(nxt)               # currentItemChanged → changeActivated

    # -- rapor ---------------------------------------------------------------
    def set_names(self, name_a: str, name_b: str):
        self.names = (name_a, name_b)

    def report_html(self) -> str:
        """Son sonucun raporu (süzgeçten bağımsız: tüm değişiklikler)."""
        return textdiff.report_html(self._result, self.names[0], self.names[1], self.ignore_case)

    def write_report(self, path: str) -> str:
        """`.pdf` uzantısında PDF, değilse HTML yazar; yazılan yolu döndürür."""
        text = self.report_html()
        if path.lower().endswith(".pdf"):
            html_to_pdf(text, path)
        else:
            if not path.lower().endswith((".html", ".htm")):
                path += ".html"
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        return path

    def save_report(self):
        if self._result is None:
            return None
        base = os.path.splitext(self.names[1] or "karsilastirma")[0] + "_fark"
        path, flt = QFileDialog.getSaveFileName(self, "Karşılaştırma raporunu kaydet", base + ".html",
                                                "HTML (*.html);;PDF (*.pdf)")
        if not path:
            return None
        if "PDF" in flt and not path.lower().endswith(".pdf"):
            path = os.path.splitext(path)[0] + ".pdf"
        try:
            return self.write_report(path)
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Rapor kaydedilemedi:\n{ex}")
            return None

    def _sync_buttons(self):
        self.btn_report.setEnabled(self._result is not None and not self._result.error)
        has = bool(self._shown)
        self.btn_prev.setEnabled(has)
        self.btn_next.setEnabled(has)
