"""
ui/ocrdialog.py
===============
Arka plan işçisi (`_OcrTask`: uzun işleri arayüzü dondurmadan çalıştırır) ve OCR diyaloğu.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, List, Optional, Tuple

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
)

import ocr
from ui.icons import icon

if TYPE_CHECKING:
    from main_window import MainWindow


# ---------------------------------------------------------------------------
# OCR: arka plan işçisi + diyalog
# ---------------------------------------------------------------------------
class _OcrSignals(QObject):
    progress = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)


class _OcrTask(QRunnable):
    """OCR'ı arayüzü dondurmadan çalıştırır. Belgenin bağımsız bir kopyası
    üzerinde çalışır, bu yüzden ana belgeye ve render iş parçacıklarına dokunmaz."""

    def __init__(self, job):
        super().__init__()
        self.signals = _OcrSignals()
        self._job = job
        self._cancel = False
        self.setAutoDelete(False)

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            result = self._job(self.signals.progress.emit, lambda: self._cancel)
            self.signals.done.emit(result)
        except Exception as ex:  # kullanıcıya iletilir
            self.signals.failed.emit(str(ex))


class OcrDialog(QDialog):
    def __init__(self, main: "MainWindow", session, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OCR — Metin Tanıma")
        self.resize(640, 560)
        self._main = main
        self._session = session
        self._task: Optional[_OcrTask] = None
        self._pages_done: List[int] = []

        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.scope = QComboBox()
        self.scope.addItem(f"Bu sayfa ({session.current_page + 1})", "current")
        self.scope.addItem(f"Tüm belge ({session.pdf.page_count} sayfa)", "all")
        form.addRow("Kapsam:", self.scope)
        self.lang_edit = QLineEdit("tur+eng")
        self.lang_edit.setToolTip("Tesseract dil kodları, + ile birleştirilir (ör. tur+eng)")
        form.addRow("Dil:", self.lang_edit)
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(100, 600)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(ocr.DEFAULT_DPI)
        form.addRow("Çözünürlük (DPI):", self.dpi_spin)
        lay.addLayout(form)

        row = QHBoxLayout()
        self.btn_run = QPushButton(icon("ocr", "on_accent"), "Metni Oku")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self._run_text)
        self.btn_pdf = QPushButton(icon("file"), "Aranabilir PDF Kaydet…")
        self.btn_pdf.setObjectName("secondary")
        self.btn_pdf.setToolTip("Tüm belgeyi (işaretlerinizle birlikte) OCR metin katmanıyla yeni bir PDF olarak kaydeder")
        self.btn_pdf.clicked.connect(self._run_pdf)
        self.btn_cancel = QPushButton("Durdur")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel)
        row.addWidget(self.btn_run)
        row.addWidget(self.btn_pdf)
        row.addWidget(self.btn_cancel)
        lay.addLayout(row)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)

        self.out = QPlainTextEdit()
        self.out.setPlaceholderText("Okunan metin burada görünecek.")
        lay.addWidget(self.out, 1)

        row2 = QHBoxLayout()
        self.btn_copy = QPushButton(icon("copy"), "Kopyala")
        self.btn_copy.clicked.connect(self._copy)
        self.btn_txt = QPushButton(icon("save"), "TXT Kaydet…")
        self.btn_txt.clicked.connect(self._save_txt)
        row2.addWidget(self.btn_copy)
        row2.addWidget(self.btn_txt)
        row2.addStretch(1)
        close = QPushButton("Kapat")
        close.clicked.connect(self.close)
        row2.addWidget(close)
        lay.addLayout(row2)

    # -- yardımcılar ---------------------------------------------------------
    def _prepare(self) -> Optional[Tuple[str, str]]:
        tessdata = ocr.find_tessdata()
        if tessdata is None:
            QMessageBox.warning(self, "OCR kurulu değil", ocr.setup_message())
            return None
        lang = ocr.pick_language(tessdata, self.lang_edit.text().strip() or None)
        self.lang_edit.setText(lang)
        return tessdata, lang

    def _busy(self, on: bool):
        for b in (self.btn_run, self.btn_pdf, self.scope, self.lang_edit, self.dpi_spin):
            b.setEnabled(not on)
        self.btn_cancel.setEnabled(on)
        self.bar.setVisible(on)
        if on:
            self.bar.setRange(0, 0)

    def _start(self, job, on_done):
        self._busy(True)
        task = _OcrTask(job)
        task.signals.progress.connect(self._on_progress)
        task.signals.done.connect(lambda r: (self._busy(False), on_done(r)))
        task.signals.failed.connect(self._on_failed)
        self._task = task
        QThreadPool.globalInstance().start(task)

    def _on_progress(self, n, total):
        self.bar.setRange(0, total)
        self.bar.setValue(n)

    def _on_failed(self, msg):
        self._busy(False)
        QMessageBox.critical(self, "OCR hatası", msg)

    def _cancel(self):
        if self._task:
            self._task.cancel()
        self._main.status.setText("OCR durduruluyor…")

    # -- metin okuma -----------------------------------------------------------
    def _run_text(self):
        prep = self._prepare()
        if not prep:
            return
        tessdata, lang = prep
        s = self._session
        if self.scope.currentData() == "current":
            pages = [s.current_page]
        else:
            pages = list(range(s.pdf.page_count))
        dpi = self.dpi_spin.value()
        try:
            snap = ocr.open_snapshot(s.pdf.doc, s.pdf.lock)
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Belge okunamadı:\n{ex}")
            return

        def job(progress, cancelled):
            try:
                texts = ocr.ocr_pages(snap, pages, lang, tessdata, dpi, progress, cancelled)
            finally:
                snap.close()
            return pages[:len(texts)], texts

        def done(res):
            done_pages, texts = res
            if len(pages) == 1:
                self.out.setPlainText(texts[0] if texts else "")
            else:
                self.out.setPlainText("\n\n".join(
                    f"--- Sayfa {p + 1} ---\n{t}" for p, t in zip(done_pages, texts)))
            n = sum(len(t) for t in texts)
            self._main.status.setText(f"OCR tamamlandı: {len(texts)} sayfa, {n} karakter.")
            if not n:
                QMessageBox.information(self, "OCR", "Metin bulunamadı. DPI değerini artırmayı deneyin.")

        self._start(job, done)

    # -- aranabilir PDF ----------------------------------------------------------
    def _run_pdf(self):
        prep = self._prepare()
        if not prep:
            return
        tessdata, lang = prep
        s = self._session
        default = os.path.splitext(s.path)[0] + "_ocr.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Aranabilir PDF Kaydet", default, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        dpi = self.dpi_spin.value()
        try:
            snap = s.pdf._annotated_copy(s.annotations, self._main.font_ctx)
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Belge hazırlanamadı:\n{ex}")
            return

        def job(progress, cancelled):
            try:
                return ocr.make_searchable_pdf(snap, path, lang, tessdata, dpi, progress, cancelled)
            finally:
                snap.close()

        def done(ok):
            if ok:
                self._main.status.setText(f"Aranabilir PDF kaydedildi: {path}")
                self._main._toast_saved("Aranabilir PDF kaydedildi", path)
            else:
                self._main.status.setText("OCR durduruldu; dosya yazılmadı.")

        self._start(job, done)

    # -- sonuç işlemleri -------------------------------------------------------------
    def _copy(self):
        QApplication.clipboard().setText(self.out.toPlainText())
        self._main.status.setText("Metin panoya kopyalandı.")

    def _save_txt(self):
        default = os.path.splitext(self._session.path)[0] + "_ocr.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Metni Kaydet", default, "Metin (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.out.toPlainText())
            self._main.status.setText(f"Kaydedildi: {path}")
        except OSError as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")

    def closeEvent(self, e):
        if self._task:
            self._task.cancel()
        super().closeEvent(e)
