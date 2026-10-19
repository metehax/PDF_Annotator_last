"""
ui/convert.py
=============
PDF → Word / Excel dönüştürme penceresi ve küçük bir arka plan iş sınıfı
(`BackgroundJob`; erişilebilirlik penceresi de kullanır). Dönüştürme belgenin
işaretli bir kopyasından yapılır, arayüz donmaz.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QRadioButton, QVBoxLayout,
)

import convert
import workspace
from ui.icons import icon


class _Signals(QObject):
    progress = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)


class BackgroundJob(QRunnable):
    """`job(progress, cancelled)` işlevini havuzda çalıştırır; sonuç sinyalle döner."""

    def __init__(self, job: Callable):
        super().__init__()
        self.signals = _Signals()
        self._job = job
        self._cancel = False
        self.setAutoDelete(False)

    def cancel(self):
        self._cancel = True

    @property
    def cancelled(self) -> bool:
        return self._cancel

    def run(self):
        try:
            self.signals.done.emit(self._job(self.signals.progress.emit, lambda: self._cancel))
        except convert.Cancelled:
            self.signals.failed.emit("")                     # sessiz iptal
        except Exception as ex:
            self.signals.failed.emit(str(ex) or ex.__class__.__name__)

    def start(self):
        QThreadPool.globalInstance().start(self)


class ConvertDialog(QDialog):
    def __init__(self, main, session, fmt: str = "docx"):
        super().__init__(main)
        self.setWindowTitle("Word / Excel'e dönüştür")
        self.resize(560, 360)
        self._main = main
        self._s = session
        self._job: Optional[BackgroundJob] = None
        self.result: Optional[convert.ConvertResult] = None
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        title = QLabel("PDF'i düzenlenebilir belgeye dönüştür")
        title.setObjectName("propTitle")
        v.addWidget(title)

        row = QHBoxLayout()
        self.r_docx = QRadioButton("Word (.docx) — düzen korunarak")
        self.r_xlsx = QRadioButton("Excel (.xlsx) — sayfalardaki tablolar")
        (self.r_xlsx if fmt == "xlsx" else self.r_docx).setChecked(True)
        row.addWidget(self.r_docx)
        row.addWidget(self.r_xlsx)
        v.addLayout(row)

        form = QFormLayout()
        self.scope = QComboBox()
        self.scope.addItem(f"Tüm belge ({session.pdf.page_count} sayfa)", "all")
        self.scope.addItem(f"Yalnız bu sayfa ({session.current_page + 1})", "current")
        form.addRow("Kapsam:", self.scope)
        self.chk_num = QCheckBox("Sayıları hücrede sayı olarak yaz")
        self.chk_num.setChecked(True)
        self.dec = QComboBox()
        self.dec.addItem("Virgül ondalık (1.234,56)", ",")
        self.dec.addItem("Nokta ondalık (1,234.56)", ".")
        form.addRow("Sayılar:", self.chk_num)
        form.addRow("", self.dec)
        v.addLayout(form)

        out = QHBoxLayout()
        self.path = QLineEdit()
        self.btn_browse = QPushButton("Gözat…")
        self.btn_browse.clicked.connect(self._browse)
        out.addWidget(self.path, 1)
        out.addWidget(self.btn_browse)
        v.addWidget(QLabel("Kaydedilecek dosya:"))
        v.addLayout(out)

        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        v.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        v.addStretch(1)

        btns = QHBoxLayout()
        self.btn_open = QPushButton("Dosyayı aç")
        self.btn_open.clicked.connect(lambda: self._open(False))
        self.btn_folder = QPushButton("Klasörde göster")
        self.btn_folder.clicked.connect(lambda: self._open(True))
        self.btn_open.hide()
        self.btn_folder.hide()
        self.btn_run = QPushButton(icon("download", "on_accent"), "Dönüştür")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.start)
        self.btn_cancel = QPushButton("Durdur")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel)
        close = QPushButton("Kapat")
        close.clicked.connect(self.close)
        btns.addWidget(self.btn_open)
        btns.addWidget(self.btn_folder)
        btns.addStretch(1)
        btns.addWidget(self.btn_run)
        btns.addWidget(self.btn_cancel)
        btns.addWidget(close)
        v.addLayout(btns)

        self.r_docx.toggled.connect(self._format_changed)
        self._format_changed()

    # -- biçim ---------------------------------------------------------------
    @property
    def fmt(self) -> str:
        return "xlsx" if self.r_xlsx.isChecked() else "docx"

    def _format_changed(self):
        xl = self.fmt == "xlsx"
        self.chk_num.setVisible(xl)
        self.dec.setVisible(xl)
        stem = os.path.splitext(os.path.basename(self._s.path))[0] if self._s.path else "belge"
        fallback = os.path.dirname(self._s.path) if self._s.path else os.path.join(os.path.expanduser("~"), "Documents")
        base = workspace.join_out("converted", stem, fallback)
        self.path.setText(base + (".xlsx" if xl else ".docx"))
        self.hint.setText(
            "Her tablo ayrı bir Excel sayfasına yazılır; ilk satır başlık sayılır. Çizgisiz tablolar algılanamayabilir."
            if xl else
            "Metin, tablo, görsel ve yazı biçimi korunmaya çalışılır. Karmaşık düzenlerde Word'de küçük kaymalar olabilir.")

    def _browse(self):
        ext = self.fmt
        flt = "Word (*.docx)" if ext == "docx" else "Excel (*.xlsx)"
        p, _ = QFileDialog.getSaveFileName(self, "Kaydet", self.path.text(), flt)
        if p:
            self.path.setText(p if p.lower().endswith("." + ext) else p + "." + ext)

    # -- çalıştırma ----------------------------------------------------------
    def _busy(self, on: bool):
        for w in (self.r_docx, self.r_xlsx, self.scope, self.chk_num, self.dec, self.path,
                  self.btn_browse, self.btn_run):
            w.setEnabled(not on)
        self.btn_cancel.setEnabled(on)
        self.bar.setVisible(on)
        if on:
            self.bar.setRange(0, 0)

    def start(self):
        out = self.path.text().strip()
        if not out:
            return
        fmt = self.fmt
        if not out.lower().endswith("." + fmt):
            out += "." + fmt
            self.path.setText(out)
        if os.path.exists(out) and QMessageBox.question(
                self, "Dosya var", f"{os.path.basename(out)} zaten var. Üzerine yazılsın mı?"
        ) != QMessageBox.StandardButton.Yes:
            return
        s = self._s
        pages = [s.current_page] if self.scope.currentData() == "current" else None
        numbers, decimal = self.chk_num.isChecked(), self.dec.currentData()
        try:
            snap = s.pdf._annotated_copy(s.annotations, self._main.font_ctx)
            data = snap.write()
            snap.close()
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Belge hazırlanamadı:\n{ex}")
            return

        def job(progress, cancelled):
            if fmt == "docx":
                return convert.to_docx(data, out, pages, cancelled)
            return convert.to_xlsx(data, out, pages, numbers, decimal, progress, cancelled)

        self.result = None
        self.btn_open.hide()
        self.btn_folder.hide()
        self.status.setText("Dönüştürülüyor…")
        self._busy(True)
        self._job = BackgroundJob(job)
        self._job.signals.progress.connect(self._on_progress)
        self._job.signals.done.connect(self._on_done)
        self._job.signals.failed.connect(self._on_failed)
        self._job.start()

    def _on_progress(self, n, total):
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(n)

    def _on_done(self, res):
        self._busy(False)
        self.result = res
        what = f"{res.tables} tablo, " if self.fmt == "xlsx" else ""
        self.status.setText(f"✓ Tamamlandı: {what}{res.pages} sayfa → {os.path.basename(res.path)}"
                            + "".join(f"\n⚠ {n}" for n in res.notes))
        self.btn_open.show()
        self.btn_folder.show()
        self._main.toasts.show(f"Dönüştürüldü: {os.path.basename(res.path)}", "success")

    def _on_failed(self, msg):
        self._busy(False)
        self.status.setText("" if not msg else f"✕ {msg}")
        if not msg:
            self.status.setText("Dönüştürme durduruldu.")

    def _cancel(self):
        if self._job:
            self._job.cancel()
        self.status.setText("Durduruluyor…")

    def _open(self, folder: bool):
        if not self.result:
            return
        p = os.path.dirname(self.result.path) if folder else self.result.path
        QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def closeEvent(self, e):
        if self._job and self.btn_cancel.isEnabled():
            self._job.cancel()
        super().closeEvent(e)
