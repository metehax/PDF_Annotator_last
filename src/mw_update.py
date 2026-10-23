"""
mw_update.py
============
Güncelleme: Yardım → Güncellemeleri denetle, açılışta sessiz denetim, indir ve kur. Çekirdek `updater.py`'dadır
(arayüzsüz). Adres tanımlı değilse (`appinfo.UPDATE_URL` boş) özellik kapalıdır; ağ hataları sessizdir
(yalnızca elle denetimde bildirilir).

MainWindow bu mixin'i miras alır.
"""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QTextBrowser, QVBoxLayout,
)

import appinfo
import convert
import updater
from ui.convert import BackgroundJob


def auto_enabled(settings) -> bool:
    return str(settings.value("update/auto", "true")).lower() not in ("false", "0")


class UpdateMixin:
    _update_job: Optional[BackgroundJob] = None
    _update_info: Optional["updater.UpdateInfo"] = None

    def update_url(self) -> str:
        return appinfo.UPDATE_URL

    def auto_check_updates(self):
        if self.update_url() and auto_enabled(self.settings):
            self.check_updates(manual=False)

    def check_updates(self, manual: bool = True):
        """Arka planda denetler. manual=True: sonuç her durumda bildirilir."""
        url = self.update_url()
        if not url:
            if manual:
                self.toasts.show("Güncelleme adresi tanımlı değil.", "info")
            return
        if self._update_job is not None:
            return
        job = self._update_job = BackgroundJob(lambda progress, cancelled: updater.check(url))

        def done(info):
            self._update_job = None
            self.settings.setValue("update/last", int(time.time()))
            self._update_info = info
            if info is None:
                if manual:
                    self.toasts.show(f"Güncelsiniz (sürüm {appinfo.VERSION}).", "success")
            else:
                self._offer_update(info)

        def failed(msg):
            self._update_job = None
            if manual:
                self.toasts.show(f"Güncelleme denetlenemedi: {msg}", "warning", timeout_ms=5000)

        job.signals.done.connect(done)
        job.signals.failed.connect(failed)
        job.start()

    def show_release_notes(self):
        info = self._update_info
        if info is None:
            self.toasts.show("Gösterilecek sürüm notu yok; önce güncellemeleri denetleyin.", "info")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Sürüm {info.version} — notlar")
        dlg.resize(620, 520)
        dlg.setSizeGripEnabled(True)
        v = QVBoxLayout(dlg)
        nb = QTextBrowser()
        nb.setOpenExternalLinks(True)
        nb.setMarkdown(info.notes or "Sürüm notu yok.")
        v.addWidget(nb, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        dlg.exec()

    # -- sunma / indirme ------------------------------------------------------------
    def _ask_update(self, info) -> bool:
        """Yeni sürüm penceresi: yeniden boyutlanır, sürüm notları okunaklı (Markdown) ve kaydırılabilir."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Yeni sürüm var")
        dlg.resize(620, 560)
        dlg.setSizeGripEnabled(True)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)
        mb = f" ({info.size / 1048576:.0f} MB)" if info.size else ""
        head = QLabel(f"<span style='font-size:16px'><b>{appinfo.APP_TITLE} {info.version}</b> hazır{mb}</span>"
                      f"<br><span style='color:gray'>Kurulu sürüm: {appinfo.VERSION}</span>")
        v.addWidget(head)
        if info.notes:
            v.addWidget(QLabel("Neler yeni:"))
            nb = QTextBrowser()
            nb.setOpenExternalLinks(True)
            nb.setMarkdown(info.notes)
            v.addWidget(nb, 1)
        else:
            v.addStretch(1)
        bb = QDialogButtonBox()
        yes = bb.addButton("İndir ve kur", QDialogButtonBox.ButtonRole.AcceptRole)
        yes.setObjectName("primary")
        later = bb.addButton("Sonra", QDialogButtonBox.ButtonRole.RejectRole)
        yes.clicked.connect(dlg.accept)
        later.clicked.connect(dlg.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(bb)
        v.addLayout(row)
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _offer_update(self, info):
        if self._ask_update(info):
            self.download_and_install(info)

    def download_and_install(self, info):
        prog = QProgressDialog("Güncelleme indiriliyor…", "İptal", 0, 100, self)
        prog.setWindowTitle("Güncelleme")
        prog.setMinimumDuration(0)
        prog.setAutoClose(False)
        prog.setAutoReset(False)
        prog.setValue(0)

        def work(progress, cancelled):
            try:
                return updater.download(info, progress, cancelled)
            except updater.Cancelled:
                raise convert.Cancelled("")

        job = BackgroundJob(work)
        self._update_job = job

        def on_progress(done, total):
            if total:
                prog.setValue(min(99, int(done * 100 / total)))

        def finish(path):
            self._update_job = None
            prog.close()
            self._run_installer(path)

        def fail(msg):
            self._update_job = None
            prog.close()
            if msg:
                QMessageBox.warning(self, "Güncelleme", msg)

        job.signals.progress.connect(on_progress)
        job.signals.done.connect(finish)
        job.signals.failed.connect(fail)
        prog.canceled.connect(job.cancel)
        job.start()
        self._update_progress = prog

    def _run_installer(self, path: str):
        try:
            updater.install(path)
        except OSError as ex:
            QMessageBox.warning(self, "Güncelleme", f"Kurucu başlatılamadı:\n{ex}")
            return
        QTimer.singleShot(200, self.close)           # kurucu uygulamayı kapatıp yeniden başlatır
