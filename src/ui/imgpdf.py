"""
ui/imgpdf.py
============
"Görselleri PDF'e çevir" penceresi: çoklu seçim / sürükle-bırak, sıralama, sayfa boyutu / yön /
kenar boşluğu / kalite; tek PDF ya da her görsel ayrı PDF. Çevirme `scan.images_to_pdfs` ile
arka planda yapılır; sonuç uygulamada açılır.
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QListView,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QRadioButton, QSpinBox,
    QVBoxLayout,
)

import scan
from ui.convert import BackgroundJob
from ui.icons import icon
from ui.scanner import PAGE_SIZE_ITEMS, _fit_side, _to_pixmap, icon_from

OPEN_MAX = 10             # "ayrı PDF" çıktısında uygulamada en çok bu kadarı açılır


class _DropList(QListWidget):
    """Sıralanabilir liste; dışarıdan (Gezgin) dosya bırakmayı da kabul eder."""
    filesDropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def _urls(self, e):
        return [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()] if e.mimeData().hasUrls() else []

    def dragEnterEvent(self, e):
        if self._urls(e):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self._urls(e):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        files = self._urls(e)
        if files:
            e.acceptProposedAction()
            self.filesDropped.emit(files)
        else:
            super().dropEvent(e)


class ImagesPdfDialog(QDialog):
    def __init__(self, main, paths: Sequence[str] = ()):
        super().__init__(main)
        self.setWindowTitle("Görselleri PDF'e çevir")
        self.resize(760, 640)
        self._main = main
        self._job: Optional[BackgroundJob] = None
        self.results: List[str] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)
        title = QLabel("Görselleri PDF'e çevir")
        title.setObjectName("propTitle")
        v.addWidget(title)
        hint = QLabel("Görselleri buraya sürükleyip bırakın ya da Ekle'yi kullanın; sırayı sürükleyerek veya Öne/Sona düğmeleriyle değiştirin.")
        hint.setObjectName("valueLbl")
        hint.setWordWrap(True)
        v.addWidget(hint)

        row = QHBoxLayout()
        self.list = _DropList()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setMovement(QListView.Movement.Snap)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setIconSize(QSize(96, 120))
        self.list.setGridSize(QSize(120, 160))
        self.list.setSpacing(4)
        self.list.filesDropped.connect(self.add_files)
        self.list.itemSelectionChanged.connect(self._enable)
        row.addWidget(self.list, 1)
        col = QVBoxLayout()
        self.btn_add = QPushButton(icon("plus"), "Ekle…")
        self.btn_del = QPushButton(icon("trash"), "Kaldır")
        self.btn_up = QPushButton(icon("arrow_up"), "Öne")
        self.btn_dn = QPushButton(icon("arrow_down"), "Sona")
        self.btn_name = QPushButton("Ada göre")
        self.btn_add.clicked.connect(self._add_dialog)
        self.btn_del.clicked.connect(self.remove_selected)
        self.btn_up.clicked.connect(lambda: self.move_selected(-1))
        self.btn_dn.clicked.connect(lambda: self.move_selected(1))
        self.btn_name.clicked.connect(self.sort_by_name)
        for b in (self.btn_add, self.btn_del, self.btn_up, self.btn_dn, self.btn_name):
            col.addWidget(b)
        col.addStretch(1)
        row.addLayout(col)
        v.addLayout(row, 1)

        mode = QHBoxLayout()
        self.r_one = QRadioButton("Tek PDF")
        self.r_sep = QRadioButton("Her görsel ayrı PDF")
        self.r_one.setChecked(True)
        mode.addWidget(self.r_one)
        mode.addWidget(self.r_sep)
        mode.addStretch(1)
        v.addLayout(mode)

        opt = QHBoxLayout()
        opt.addWidget(QLabel("Sayfa boyutu"))
        self.cb_size = QComboBox()
        for t, k in PAGE_SIZE_ITEMS:
            self.cb_size.addItem(t, k)
        opt.addWidget(self.cb_size)
        opt.addWidget(QLabel("Yön"))
        self.cb_orient = QComboBox()
        for t, k in (("Otomatik", "otomatik"), ("Dikey", "dikey"), ("Yatay", "yatay")):
            self.cb_orient.addItem(t, k)
        opt.addWidget(self.cb_orient)
        opt.addWidget(QLabel("Kenar boşluğu"))
        self.sp_margin = QSpinBox()
        self.sp_margin.setRange(0, 100)
        self.sp_margin.setSuffix(" pt")
        opt.addWidget(self.sp_margin)
        opt.addWidget(QLabel("Kalite"))
        self.sp_quality = QSpinBox()
        self.sp_quality.setRange(30, 100)
        self.sp_quality.setValue(85)
        opt.addWidget(self.sp_quality)
        opt.addStretch(1)
        v.addLayout(opt)
        self.cb_size.currentIndexChanged.connect(self._enable)

        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("valueLbl")
        foot.addWidget(self.status, 1)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(160, 8)
        self.bar.hide()
        foot.addWidget(self.bar)
        self.btn_stop = QPushButton(icon("stop"), "Durdur")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_stop.hide()
        self.btn_close = QPushButton("Kapat")
        self.btn_close.clicked.connect(self.close)
        self.btn_run = QPushButton(icon("file_plus", "on_accent"), "PDF oluştur…")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.generate)
        for b in (self.btn_stop, self.btn_close, self.btn_run):
            foot.addWidget(b)
        v.addLayout(foot)

        if paths:
            self.add_files(list(paths))
        self._enable()

    # -- liste -----------------------------------------------------------------
    @property
    def paths(self) -> List[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def _add_dialog(self):
        flt = "Görseller (" + " ".join("*" + e for e in scan.IMAGE_EXTS) + ")"
        files, _ = QFileDialog.getOpenFileNames(self, "Görsel ekle", "", flt)
        if files:
            self.add_files(files)

    def add_files(self, files: Sequence[str]) -> int:
        """Görselleri listeye ekler (aynı dosya iki kez eklenebilir); desteklenmeyenleri atlar."""
        added, skipped = 0, []
        for p in files:
            if os.path.isdir(p):
                names = sorted(os.listdir(p))
                added += self.add_files([os.path.join(p, n) for n in names
                                         if os.path.splitext(n)[1].lower() in scan.IMAGE_EXTS])
                continue
            if os.path.splitext(p)[1].lower() not in scan.IMAGE_EXTS or not os.path.isfile(p):
                skipped.append(os.path.basename(p))
                continue
            try:
                pm = _to_pixmap(_fit_side(scan.load_image(p, 240), 200))
            except Exception:
                skipped.append(os.path.basename(p))
                continue
            it = QListWidgetItem(icon_from(pm), os.path.basename(p))
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setToolTip(p)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.list.addItem(it)
            added += 1
        if skipped:
            self.status.setText(f"Atlandı (görsel değil/okunamadı): {', '.join(skipped[:4])}"
                                + (" …" if len(skipped) > 4 else ""))
        self._enable()
        return added

    def remove_selected(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))
        self._enable()

    def move_selected(self, delta: int):
        """delta<0: seçilenleri bir adım öne, >0: bir adım sona."""
        rows = sorted(self.list.row(i) for i in self.list.selectedItems())
        if not rows:
            return
        n = self.list.count()
        if (delta < 0 and rows[0] == 0) or (delta > 0 and rows[-1] == n - 1):
            return
        order = rows if delta < 0 else rows[::-1]
        for r in order:
            it = self.list.takeItem(r)
            self.list.insertItem(r + delta, it)
            it.setSelected(True)
        self._enable()

    def sort_by_name(self):
        items = [self.list.takeItem(0) for _ in range(self.list.count())]
        for it in sorted(items, key=lambda i: os.path.basename(i.data(Qt.ItemDataRole.UserRole)).lower()):
            self.list.addItem(it)
        self._enable()

    def _enable(self, *_):
        busy = self._job is not None
        n = self.list.count()
        sel = len(self.list.selectedItems())
        self.btn_run.setEnabled(n > 0 and not busy)
        self.btn_del.setEnabled(sel > 0 and not busy)
        self.btn_up.setEnabled(sel > 0 and not busy)
        self.btn_dn.setEnabled(sel > 0 and not busy)
        self.btn_name.setEnabled(n > 1 and not busy)
        self.btn_add.setEnabled(not busy)
        self.list.setEnabled(not busy)
        for w in (self.r_one, self.r_sep, self.cb_size, self.sp_quality):
            w.setEnabled(not busy)
        self.cb_orient.setEnabled(not busy and self.cb_size.currentData() != "orijinal")
        self.sp_margin.setEnabled(not busy and self.cb_size.currentData() != "orijinal")

    # -- çevirme ----------------------------------------------------------------
    def generate(self):
        paths = self.paths
        if not paths:
            return None
        base = os.path.dirname(paths[0])
        if self.r_sep.isChecked():
            out = QFileDialog.getExistingDirectory(self, "PDF'lerin kaydedileceği klasör", base)
        else:
            out, _ = QFileDialog.getSaveFileName(self, "PDF olarak kaydet",
                                                 os.path.join(base, "gorseller.pdf"), "PDF (*.pdf)")
            if out and not out.lower().endswith(".pdf"):
                out += ".pdf"
        return self.start_export(out) if out else None

    def start_export(self, out: str):
        """`out`: tek PDF'te dosya yolu, ayrı PDF'te klasör."""
        paths = self.paths
        ayri = self.r_sep.isChecked()
        opts = dict(sayfa_boyutu=self.cb_size.currentData(), yon=self.cb_orient.currentData(),
                    kenar_bosluk_pt=self.sp_margin.value(), jpeg_kalite=self.sp_quality.value())

        def job(progress, cancelled):
            return scan.images_to_pdfs(paths, out, ayri, progress=progress, cancelled=cancelled, **opts)

        self.results = []
        self.status.setText("Çevriliyor…")
        self.bar.setRange(0, len(paths))
        self.bar.setValue(0)
        self.bar.show()
        self.btn_stop.show()
        self.btn_run.hide()
        self._job = BackgroundJob(job)
        self._job.signals.progress.connect(lambda a, b: self.bar.setValue(a))
        self._job.signals.done.connect(self._on_done)
        self._job.signals.failed.connect(self._on_failed)
        self._enable()
        self._job.start()
        return self._job

    def _finish_job(self):
        self._job = None
        self.bar.hide()
        self.btn_stop.hide()
        self.btn_run.show()
        self._enable()

    def _on_done(self, files):
        self._finish_job()
        self.results = list(files)
        self.status.setText(f"Tamamlandı: {len(files)} PDF")
        try:
            self._main.open_paths(self.results[:OPEN_MAX])
            extra = len(self.results) - OPEN_MAX
            self._main.toasts.show(
                f"{len(self.results)} PDF oluşturuldu." + (f" İlk {OPEN_MAX} tanesi açıldı." if extra > 0 else ""),
                "success")
        except Exception:
            pass
        self.accept()

    def _on_failed(self, msg: str):
        self._finish_job()
        if msg:
            self.status.setText("✕ " + msg)
            QMessageBox.critical(self, "Hata", f"PDF oluşturulamadı:\n{msg}")
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
