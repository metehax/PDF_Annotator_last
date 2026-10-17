"""
ui/flatten.py
=============
"Düzleştir ve kaydet" penceresi: işaretleri, yorumları ve form alanlarını sayfa içeriğine gömer (artık düzenlenebilir
nesne kalmaz, yalnız görünüm); isteğe bağlı olarak sayfaları resme çevirir (metin kopyalanamaz). Belgenin işaretli bir
kopyası bayt olarak alınır, işlem `BackgroundJob`'da çalışır; açık belgeye dokunulmaz, sonuç yeni sekmede açılır.
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QSpinBox, QVBoxLayout,
)

import pdf_engine
from ui.convert import BackgroundJob
from ui.icons import icon

DPI_ITEMS = ((150, "150 dpi (küçük dosya)"), (200, "200 dpi (dengeli)"), (300, "300 dpi (keskin)"))


class FlattenDialog(QDialog):
    def __init__(self, main, session):
        super().__init__(main)
        self.setWindowTitle("Düzleştir ve kaydet")
        self.resize(560, 380)
        self._main = main
        self._s = session
        self._job: Optional[BackgroundJob] = None
        self.result_path: Optional[str] = None
        self.info: Optional[dict] = None

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)
        title = QLabel("Düzleştirilmiş kopya oluştur")
        title.setObjectName("propTitle")
        v.addWidget(title)
        hint = QLabel("İşaretler, yorumlar ve form alanları sayfa içeriğine gömülür: sonradan değiştirilemez, her görüntüleyicide "
                      "aynı görünür. Açık belge değişmez; sonuç yeni bir PDF olarak kaydedilir.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)

        self.r_bake = QRadioButton("İşaretleri, yorumları ve form alanlarını sayfaya göm (metin kalır)")
        self.r_img = QRadioButton("Sayfaları resme çevir (metin kopyalanamaz, aranamaz)")
        self.r_bake.setChecked(True)
        v.addWidget(self.r_bake)
        v.addWidget(self.r_img)
        row = QHBoxLayout()
        row.addSpacing(22)
        self.lbl_dpi = QLabel("Çözünürlük")
        self.cb_dpi = QComboBox()
        for d, t in DPI_ITEMS:
            self.cb_dpi.addItem(t, d)
        self.cb_dpi.setCurrentIndex(1)
        self.lbl_q = QLabel("Kalite")
        self.sp_q = QSpinBox()
        self.sp_q.setRange(30, 100)
        self.sp_q.setValue(85)
        for w in (self.lbl_dpi, self.cb_dpi, self.lbl_q, self.sp_q):
            row.addWidget(w)
        row.addStretch(1)
        v.addLayout(row)
        self.r_img.toggled.connect(self._mode_changed)

        row = QHBoxLayout()
        self.path = QLineEdit()
        self.btn_browse = QPushButton(icon("folder"), "Gözat…")
        self.btn_browse.setObjectName("secondary")
        self.btn_browse.clicked.connect(self._browse)
        row.addWidget(self.path, 1)
        row.addWidget(self.btn_browse)
        v.addLayout(row)
        base = os.path.splitext(session.path)[0] if session.path else os.path.join(os.path.expanduser("~"), "Documents", "belge")
        self.path.setText(base + "_duzlestirilmis.pdf")

        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        v.addWidget(self.bar)
        v.addStretch(1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        self.btn_stop = QPushButton(icon("stop"), "Durdur")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_stop.hide()
        self.btn_close = QPushButton("Kapat")
        self.btn_close.clicked.connect(self.close)
        self.btn_run = QPushButton(icon("save", "on_accent"), "Düzleştir ve kaydet")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.start)
        for b in (self.btn_stop, self.btn_close, self.btn_run):
            foot.addWidget(b)
        v.addLayout(foot)
        self._mode_changed()

    # -- arayüz -------------------------------------------------------------------
    def _mode_changed(self, *_):
        on = self.r_img.isChecked()
        for w in (self.lbl_dpi, self.cb_dpi, self.lbl_q, self.sp_q):
            w.setEnabled(on)

    def _browse(self):
        p, _ = QFileDialog.getSaveFileName(self, "Kaydet", self.path.text(), "PDF (*.pdf)")
        if p:
            self.path.setText(p if p.lower().endswith(".pdf") else p + ".pdf")

    def _busy(self, on: bool):
        for w in (self.r_bake, self.r_img, self.cb_dpi, self.sp_q, self.path, self.btn_browse, self.btn_run):
            w.setEnabled(not on)
        if not on:
            self._mode_changed()
        self.btn_stop.setVisible(on)
        self.btn_run.setVisible(not on)
        self.bar.setVisible(on)
        if on:
            self.bar.setRange(0, 0)

    # -- çalıştırma ---------------------------------------------------------------
    def start(self):
        out = self.path.text().strip()
        if not out:
            return None
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
            self.path.setText(out)
        s = self._s
        if s.path and os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(s.path)):
            QMessageBox.warning(self, "Aynı dosya", "Çıktı, açık belgenin kendisi olamaz; başka bir ad seçin.")
            return None
        if os.path.exists(out) and QMessageBox.question(
                self, "Dosya var", f"{os.path.basename(out)} zaten var. Üzerine yazılsın mı?"
        ) != QMessageBox.StandardButton.Yes:
            return None
        try:
            snap = s.pdf._annotated_copy(s.annotations, self._main.font_ctx)      # uygulamanın işaretleri içeriğe işlenir
            data = snap.write()
            snap.close()
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Belge hazırlanamadı:\n{ex}")
            return None
        as_images, dpi, q = self.r_img.isChecked(), self.cb_dpi.currentData(), self.sp_q.value()
        security = getattr(s, "security", None)

        def job(progress, cancelled):
            return pdf_engine.flatten_pdf(data, out, as_images, dpi, q, security, None, progress, cancelled)

        self.result_path = None
        self.status.setText("Düzleştiriliyor…")
        self._busy(True)
        self._job = BackgroundJob(job)
        self._job.signals.progress.connect(self._on_progress)
        self._job.signals.done.connect(lambda info: self._on_done(out, info))
        self._job.signals.failed.connect(self._on_failed)
        self._job.start()
        return self._job

    def _on_progress(self, done: int, total: int):
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)

    def _on_done(self, out: str, info: dict):
        self._job = None
        self._busy(False)
        self.result_path, self.info = out, info
        what = (f"{info['annots']} açıklama ve {info['widgets']} form alanı sayfaya gömüldü"
                if not info["images"] else f"{info['pages']} sayfa resme çevrildi")
        self.status.setText(f"Tamamlandı: {what}.")
        try:
            self._main.open_paths([out])
            self._main.toasts.show(f"Düzleştirilmiş kopya kaydedildi ({what}).", "success", timeout_ms=5000)
        except Exception:
            pass
        self.accept()

    def _on_failed(self, msg: str):
        self._job = None
        self._busy(False)
        if msg:
            self.status.setText("✕ " + msg)
            QMessageBox.critical(self, "Hata", f"Düzleştirilemedi:\n{msg}")
        else:
            self.status.setText("İptal edildi.")

    def stop(self):
        if self._job is not None:
            self._job.cancel()
            self.status.setText("Durduruluyor…")

    def done(self, r):
        if self._job is not None:
            self._job.cancel()
        super().done(r)
