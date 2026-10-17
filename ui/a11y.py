"""
ui/a11y.py
==========
Erişilebilirlik denetimi penceresi: kontrol listesi (✓ ⚠ ✕), düzeltilebilenler için
onay kutuları + tek tıkla düzeltme (dil, başlık, yer imleri, OCR) ve rapor kaydı.
Denetim ve OCR arka planda çalışır (belgenin bağımsız kopyası üzerinde).
"""

from __future__ import annotations

import os
from typing import Callable, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

import a11y
import ocr
from ui import theme
from ui.convert import BackgroundJob
from ui.icons import icon

_COLOR = {a11y.PASS: "good", a11y.WARN: "warning", a11y.FAIL: "danger", a11y.INFO: "text_muted"}


class A11yDialog(QDialog):
    def __init__(self, main, session, on_changed: Callable[[], None]):
        super().__init__(main)
        self.setWindowTitle("Erişilebilirlik denetimi")
        self.resize(640, 700)
        self._main = main
        self._s = session
        self._on_changed = on_changed
        self._job: Optional[BackgroundJob] = None
        self.report: Optional[a11y.A11yReport] = None
        self._ocr_pages = []

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)
        title = QLabel("Erişilebilirlik denetimi")
        title.setObjectName("propTitle")
        v.addWidget(title)
        self.summary = QLabel("Denetleniyor…")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        v.addWidget(self.bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setWordWrap(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.header().setStretchLastSection(True)
        v.addWidget(self.tree, 1)

        v.addWidget(QLabel("<b>Tek tıkla düzeltilebilenler</b>"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.chk: Dict[str, QCheckBox] = {}
        for r, key in enumerate(("lang", "title", "bookmarks", "ocr")):
            c = QCheckBox(a11y.FIX_LABEL[key])
            c.setChecked(True)
            self.chk[key] = c
            grid.addWidget(c, r, 0)
        self.lang = QComboBox()
        self.lang.setEditable(True)
        for code, name in a11y.LANGUAGES:
            self.lang.addItem(f"{code} — {name}", code)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Belge başlığı")
        grid.addWidget(self.lang, 0, 1)
        grid.addWidget(self.title_edit, 1, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        self.note = QLabel("Düzeltmeler Ctrl+Z ile geri alınamaz; kaydetmeden önce gözden geçirin. "
                           "OCR, taranmış sayfaları metinli sayfalarla değiştirir.")
        self.note.setObjectName("hint")
        self.note.setWordWrap(True)
        v.addWidget(self.note)

        row = QHBoxLayout()
        self.btn_fix = QPushButton(icon("check", "on_accent"), "Seçilenleri düzelt")
        self.btn_fix.setObjectName("primary")
        self.btn_fix.clicked.connect(self.fix_selected)
        self.btn_rescan = QPushButton(icon("reset"), "Yeniden denetle")
        self.btn_rescan.setObjectName("secondary")
        self.btn_rescan.clicked.connect(self.rescan)
        self.btn_save = QPushButton(icon("save"), "Raporu kaydet…")
        self.btn_save.setObjectName("secondary")
        self.btn_save.clicked.connect(self.save_report)
        close = QPushButton("Kapat")
        close.clicked.connect(self.close)
        row.addWidget(self.btn_fix)
        row.addWidget(self.btn_rescan)
        row.addWidget(self.btn_save)
        row.addStretch(1)
        row.addWidget(close)
        v.addLayout(row)
        self._show_fixes(None)
        self.rescan()

    # -- denetim -------------------------------------------------------------
    def _busy(self, on: bool, text: str = ""):
        self.bar.setVisible(on)
        if on:
            self.bar.setRange(0, 0)
            self.summary.setText(text)
        for w in (self.btn_fix, self.btn_rescan, self.btn_save):
            w.setEnabled(not on)

    def rescan(self):
        s = self._s
        try:
            snap = ocr.open_snapshot(s.pdf.doc, s.pdf.lock)
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Belge okunamadı:\n{ex}")
            return
        path = s.path or ""

        def job(progress, cancelled):
            try:
                return a11y.audit(snap, path, cancelled)
            finally:
                snap.close()

        self._busy(True, "Denetleniyor…")
        self._run(job, self._on_report)

    def _run(self, job, on_done):
        self._job = BackgroundJob(job)
        self._job.signals.done.connect(on_done)
        self._job.signals.failed.connect(self._on_failed)
        self._job.start()

    def _on_failed(self, msg):
        self._busy(False)
        self.summary.setText("")
        if msg:
            QMessageBox.critical(self, "Hata", msg)

    def _on_report(self, rep: a11y.A11yReport):
        self._busy(False)
        if rep.cancelled:
            return
        self.report = rep
        self.summary.setText(f"<b>{rep.summary()}</b>")
        self.tree.clear()
        for c in rep.checks:
            top = QTreeWidgetItem([f"{c.icon}  {c.title}"])
            top.setForeground(0, theme.qcolor(_COLOR[c.status]))
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setData(0, Qt.ItemDataRole.UserRole, c.key)
            self.tree.addTopLevelItem(top)
            top.addChild(QTreeWidgetItem([c.detail]))
            for it in c.items:
                top.addChild(QTreeWidgetItem([it]))
            top.setExpanded(c.status in (a11y.FAIL, a11y.WARN))
        self._show_fixes(rep)

    def _show_fixes(self, rep: Optional[a11y.A11yReport]):
        fixable = {c.fix: c for c in rep.fixable()} if rep else {}
        for key, box in self.chk.items():
            box.setVisible(key in fixable)
        self.lang.setVisible("lang" in fixable)
        self.title_edit.setVisible("title" in fixable)
        self.btn_fix.setEnabled(bool(fixable))
        if "lang" in fixable:
            i = self.lang.findData(fixable["lang"].data.get("suggest", "tr-TR"))
            self.lang.setCurrentIndex(max(i, 0))
        if "title" in fixable:
            self.title_edit.setText(fixable["title"].data.get("suggest", ""))
        self.note.setVisible(bool(fixable))

    # -- düzeltme ------------------------------------------------------------
    def selected_fixes(self):
        return [k for k, b in self.chk.items() if not b.isHidden() and b.isChecked()]

    def fix_selected(self):
        rep = self.report
        keys = self.selected_fixes()
        if not rep or not keys:
            return
        simple = [k for k in keys if k != "ocr"]
        done = []
        if simple:
            code = self.lang.currentData() or self.lang.currentText().split("—")[0].strip()
            toc = rep.get("headings").data.get("toc") if rep.get("headings") else None
            with self._s.pdf.lock:
                done = a11y.apply_fixes(self._s.pdf.doc, simple, lang=code, title=self.title_edit.text(),
                                        toc=toc)
        if "ocr" in keys and rep.get("scanned"):
            self._start_ocr(rep.get("scanned").data.get("pages", []), done)
        else:
            self._finish(done)

    def _start_ocr(self, pages, done):
        tessdata = ocr.find_tessdata()
        if tessdata is None:
            QMessageBox.warning(self, "OCR kurulu değil", ocr.setup_message())
            self._finish(done)
            return
        lang = ocr.pick_language(tessdata, None)
        try:
            snap = ocr.open_snapshot(self._s.pdf.doc, self._s.pdf.lock)
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Belge okunamadı:\n{ex}")
            self._finish(done)
            return

        def job(progress, cancelled):
            out = []
            try:
                for n, p in enumerate(pages):
                    if cancelled():
                        break
                    pm = snap[p].get_pixmap(dpi=ocr.DEFAULT_DPI, alpha=False)
                    out.append((p, pm.pdfocr_tobytes(language=lang, tessdata=tessdata)))
                    progress(n + 1, len(pages))
            finally:
                snap.close()
            return out

        def finished(results):
            self._busy(False)
            if results:
                with self._s.pdf.lock:
                    n = a11y.ocr_replace_pages(self._s.pdf.doc, results)
                self._s.pdf._invalidate()
                done.append(f"{n} sayfaya OCR uygulandı")
            self._finish(done)

        self._busy(True, f"OCR çalışıyor ({len(pages)} sayfa)…")
        self._job = BackgroundJob(job)
        self._job.signals.progress.connect(lambda n, t: (self.bar.setRange(0, t), self.bar.setValue(n)))
        self._job.signals.done.connect(finished)
        self._job.signals.failed.connect(self._on_failed)
        self._job.start()

    def _finish(self, done):
        if done:
            self._on_changed()
            self._main.toasts.show("Düzeltildi: " + "; ".join(done), "success")
        self.rescan()

    # -- rapor ---------------------------------------------------------------
    def save_report(self):
        if not self.report:
            return
        name = os.path.basename(self._s.path or "belge.pdf")
        default = os.path.splitext(self._s.path or "belge")[0] + "_erisilebilirlik.html"
        path, _ = QFileDialog.getSaveFileName(self, "Raporu kaydet", default,
                                              "HTML (*.html);;Metin (*.txt)")
        if not path:
            return
        text = (a11y.report_text(self.report, name) if path.lower().endswith(".txt")
                else a11y.report_html(self.report, name))
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self._main.toasts.show("Rapor kaydedildi", "success")

    def closeEvent(self, e):
        if self._job:
            self._job.cancel()
        super().closeEvent(e)
