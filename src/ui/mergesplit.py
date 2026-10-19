"""
ui/mergesplit.py
================
Birleştir ve Böl pencereleri. Çekirdek `pdfops` (arayüzsüz); burada dosya listesi, sayfa aralığı
alanı ve tembel küçük resim önizlemesi (`PagePreview`) var. İş `BackgroundJob` ile arka planda.
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListView, QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QRadioButton,
    QSpinBox, QVBoxLayout,
)

import pdfops
import workspace
from pdf_engine import is_image_path
from ui.convert import BackgroundJob
from ui.icons import icon

PREVIEW_MAX = 60          # önizleme şeridinde en çok bu kadar küçük resim (kalanı "+N sayfa" notu)
FILE_FILTER = "PDF / resim (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)"


class PagePreview(QListWidget):
    """Seçili sayfaların küçük resim şeridi. İlk ve son sayfa büyük; render tembel (zamanlayıcıyla
    birer birer), böylece pencere donmaz."""

    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setSpacing(6)
        self.setIconSize(QSize(110, 140))
        self.setGridSize(QSize(130, 170))
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._path = ""
        self._queue: List[int] = []
        self._timer = QTimer(self)
        self._timer.setInterval(5)
        self._timer.timeout.connect(self._step)
        self.note = ""

    def set_pages(self, path: str, pages: Sequence[int]) -> int:
        """Gösterilen küçük resim sayısını döndürür."""
        self._timer.stop()
        self.clear()
        self._path = path
        pages = list(pages)
        shown = pages
        if len(pages) > PREVIEW_MAX:                    # baştan ve sondan göster, ortası atlanır
            h = PREVIEW_MAX // 2
            shown = pages[:h] + pages[-h:]
        self.note = f"{len(pages)} sayfa" + (f" (ilk/son {len(shown)} gösteriliyor)" if len(shown) < len(pages) else "")
        for k, p in enumerate(shown):
            edge = k == 0 or k == len(shown) - 1
            it = QListWidgetItem(f"{p + 1}")
            it.setData(Qt.ItemDataRole.UserRole, (p, edge))
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            if edge and len(shown) > 1:
                it.setText(f"{p + 1}  ●")
                it.setToolTip("İlk / son sayfa")
            self.addItem(it)
        self._queue = list(range(self.count()))
        if self._queue:
            self._timer.start()
        return self.count()

    def _step(self):
        if not self._queue:
            self._timer.stop()
            return
        i = self._queue.pop(0)
        it = self.item(i)
        if it is None:
            return
        p, edge = it.data(Qt.ItemDataRole.UserRole)
        try:
            img = QImage.fromData(pdfops.render_thumb(self._path, p, 300 if edge else 160))
            pm = QPixmap.fromImage(img).scaled(QSize(220, 280) if edge else QSize(110, 140),
                                               Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation)
            it.setIcon(QIcon(pm))
        except Exception:
            it.setText(f"{p + 1} ✕")

    def settle(self):
        """Bekleyen tüm küçük resimleri hemen çizer (test/yazdırma)."""
        while self._queue:
            self._step()


class _FileList(QListWidget):
    """Sürükle-bırak sıralanır; Gezgin'den dosya/klasör bırakmayı kabul eder."""

    def __init__(self, on_files):
        super().__init__()
        self._on_files = on_files
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def _urls(self, e):
        return [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()] if e.mimeData().hasUrls() else []

    def dragEnterEvent(self, e):
        e.acceptProposedAction() if self._urls(e) else super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        e.acceptProposedAction() if self._urls(e) else super().dragMoveEvent(e)

    def dropEvent(self, e):
        f = self._urls(e)
        if f:
            e.acceptProposedAction()
            self._on_files(f)
        else:
            super().dropEvent(e)


def expand_inputs(paths: Sequence[str], pdf_only: bool = False) -> List[str]:
    """Klasörleri (alt klasörsüz, ada göre sıralı) PDF/resim dosyalarına açar."""
    out: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            for n in sorted(os.listdir(p), key=str.lower):
                fp = os.path.join(p, n)
                if os.path.isfile(fp) and _ok(fp, pdf_only):
                    out.append(fp)
        elif os.path.isfile(p) and _ok(p, pdf_only):
            out.append(p)
    return out


def _ok(p: str, pdf_only: bool) -> bool:
    return p.lower().endswith(".pdf") or (not pdf_only and is_image_path(p))


class _BaseDialog(QDialog):
    """Ortak: dosya listesi + aralık alanı + önizleme + ilerleme çubuğu/durdurma."""
    PDF_ONLY = False

    def __init__(self, main, title: str, paths: Sequence[str] = ()):
        super().__init__(main)
        self.setWindowTitle(title)
        self.resize(980, 660)
        self._main = main
        self._job: Optional[BackgroundJob] = None
        self.results: List[str] = []
        self._counts = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("propTitle")
        v.addWidget(t)
        body = QHBoxLayout()
        v.addLayout(body, 1)
        left = QVBoxLayout()
        body.addLayout(left, 4)
        self.list = _FileList(self.add_files)
        self.list.currentRowChanged.connect(self._on_current)
        left.addWidget(self.list, 1)
        bar = QHBoxLayout()
        self.btn_add = QPushButton(icon("plus"), "Dosya ekle…")
        self.btn_folder = QPushButton("Klasörden ekle…")
        self.btn_del = QPushButton(icon("trash"), "Çıkar")
        self.btn_add.clicked.connect(self._add_dialog)
        self.btn_folder.clicked.connect(self._folder_dialog)
        self.btn_del.clicked.connect(self.remove_selected)
        for b in (self.btn_add, self.btn_folder, self.btn_del):
            bar.addWidget(b)
        bar.addStretch(1)
        left.addLayout(bar)
        self.extra = QFormLayout()
        left.addLayout(self.extra)
        right = QVBoxLayout()
        body.addLayout(right, 5)
        self.lbl_prev = QLabel("Önizleme")
        self.lbl_prev.setObjectName("valueLbl")
        right.addWidget(self.lbl_prev)
        self.preview = PagePreview()
        right.addWidget(self.preview, 1)
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
        self.btn_run = QPushButton("Başlat…")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.generate)
        for b in (self.btn_stop, self.btn_close, self.btn_run):
            foot.addWidget(b)
        v.addLayout(foot)

    # -- liste -------------------------------------------------------------------
    @property
    def paths(self) -> List[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def _add_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Dosya ekle", "", FILE_FILTER)
        if files:
            self.add_files(files)

    def _folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Klasör seç")
        if d:
            self.add_files([d])

    def add_files(self, files: Sequence[str]) -> int:
        added = 0
        bad = []
        for p in expand_inputs(files, self.PDF_ONLY):
            try:
                n = pdfops.page_count(p)
            except Exception:
                bad.append(os.path.basename(p))
                continue
            self._counts[p] = n
            self._append(p, n)
            added += 1
        if bad:
            self.status.setText("Açılamadı: " + ", ".join(bad[:4]))
        if added and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        self._enable()
        return added

    def _append(self, p: str, n: int):
        it = QListWidgetItem(f"{os.path.basename(p)}   ({n} sayfa)")
        it.setData(Qt.ItemDataRole.UserRole, p)
        it.setToolTip(p)
        self.list.addItem(it)

    def remove_selected(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))
        self._enable()
        self._on_current(self.list.currentRow())

    def _on_current(self, row: int):
        raise NotImplementedError

    def _enable(self):
        busy = self._job is not None
        self.btn_run.setEnabled(self.list.count() > 0 and not busy)
        for w in (self.btn_add, self.btn_folder, self.list):
            w.setEnabled(not busy)
        self.btn_del.setEnabled(not busy and bool(self.list.selectedItems()))

    def show_preview(self, path: str, pages: Sequence[int]):
        n = self.preview.set_pages(path, pages)
        self.lbl_prev.setText("Önizleme — " + self.preview.note)
        return n

    # -- iş ----------------------------------------------------------------------
    def _begin(self, job, total: int):
        self.results = []
        self.status.setText("Çalışıyor…")
        self.bar.setRange(0, max(1, total))
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
        self.results = list(files) if isinstance(files, (list, tuple)) else [files]
        self.status.setText(f"Tamamlandı: {len(self.results)} dosya")
        try:
            self._main.toasts.show(f"{len(self.results)} PDF oluşturuldu.", "success")
            self._main.open_paths(self.results[:5])
        except Exception:
            pass
        self.accept()

    def _on_failed(self, msg: str):
        self._finish_job()
        if msg:
            self.status.setText("✕ " + msg)
            QMessageBox.critical(self, "Hata", msg)
        else:
            self.status.setText("İptal edildi; dosya bırakılmadı.")

    def stop(self):
        if self._job is not None:
            self._job.cancel()
            self.status.setText("Durduruluyor…")

    def done(self, r):
        if self._job is not None:
            self._job.cancel()
        super().done(r)


class MergeDialog(_BaseDialog):
    def __init__(self, main, paths: Sequence[str] = ()):
        super().__init__(main, "PDF birleştir", ())
        self.btn_up = QPushButton(icon("arrow_up"), "Öne")
        self.btn_dn = QPushButton(icon("arrow_down"), "Sona")
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_dn.clicked.connect(lambda: self._move(1))
        self.extra.addRow(self.btn_up, self.btn_dn)
        self.ed_range = QLineEdit()
        self.ed_range.setPlaceholderText("Boş = tüm sayfalar · örn. 1-3, 5, 8-")
        self.ed_range.textChanged.connect(self._range_changed)
        self.extra.addRow("Sayfa aralığı (seçili dosya)", self.ed_range)
        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet("color:#d14")
        self.extra.addRow("", self.lbl_err)
        self.ed_name = QLineEdit("birlesik.pdf")
        self.extra.addRow("Çıktı adı", self.ed_name)
        self.btn_run.setText("Birleştir")
        if paths:
            self.add_files(paths)

    def _append(self, p, n):
        super()._append(p, n)
        self.list.item(self.list.count() - 1).setData(Qt.ItemDataRole.UserRole + 1, "")

    def _move(self, d: int):
        r = self.list.currentRow()
        t = r + d
        if r < 0 or not 0 <= t < self.list.count():
            return
        it = self.list.takeItem(r)
        self.list.insertItem(t, it)
        self.list.setCurrentRow(t)

    def sources(self):
        return [(self.list.item(i).data(Qt.ItemDataRole.UserRole),
                 self.list.item(i).data(Qt.ItemDataRole.UserRole + 1) or "")
                for i in range(self.list.count())]

    def _label(self, it):
        p = it.data(Qt.ItemDataRole.UserRole)
        r = it.data(Qt.ItemDataRole.UserRole + 1) or ""
        n = self._counts.get(p, 0)
        it.setText(f"{os.path.basename(p)}   ({n} sayfa" + (f" · seçili: {r}" if r.strip() else "") + ")")

    def _on_current(self, row: int):
        it = self.list.item(row) if row >= 0 else None
        self.ed_range.blockSignals(True)
        self.ed_range.setText((it.data(Qt.ItemDataRole.UserRole + 1) or "") if it else "")
        self.ed_range.blockSignals(False)
        self._refresh_preview()

    def _range_changed(self, text: str):
        it = self.list.currentItem()
        if it is None:
            return
        it.setData(Qt.ItemDataRole.UserRole + 1, text)
        self._label(it)
        self._refresh_preview()

    def selected_pages(self, it) -> Optional[List[int]]:
        p = it.data(Qt.ItemDataRole.UserRole)
        try:
            return pdfops.parse_ranges(it.data(Qt.ItemDataRole.UserRole + 1) or "", self._counts[p])
        except ValueError:
            return None

    def _refresh_preview(self):
        it = self.list.currentItem()
        if it is None:
            self.preview.set_pages("", [])
            self.lbl_err.setText("")
            self.lbl_prev.setText("Önizleme")
            return
        pages = self.selected_pages(it)
        if pages is None:
            try:
                pdfops.parse_ranges(it.data(Qt.ItemDataRole.UserRole + 1), self._counts[it.data(Qt.ItemDataRole.UserRole)])
            except ValueError as ex:
                self.lbl_err.setText(str(ex))
            self.preview.set_pages("", [])
            return
        self.lbl_err.setText("")
        self.show_preview(it.data(Qt.ItemDataRole.UserRole), pages)

    def generate(self):
        if self.list.count() < 1:
            return None
        first = self.paths[0]
        name = self.ed_name.text().strip() or "birlesik.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        default = workspace.join_out("projects", name, os.path.dirname(first))
        out, _ = QFileDialog.getSaveFileName(self, "Birleşik PDF'i kaydet", default, "PDF (*.pdf)")
        if not out:
            return None
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        return self.start_merge(out)

    def start_merge(self, out: str):
        src = self.sources()
        for p, r in src:                                 # aralıkları işe başlamadan doğrula
            try:
                pdfops.parse_ranges(r, self._counts[p])
            except ValueError as ex:
                self.lbl_err.setText(f"{os.path.basename(p)}: {ex}")
                return None

        def job(progress, cancelled):
            return [pdfops.merge(src, out, progress=progress, cancelled=cancelled)]
        return self._begin(job, len(src))


class SplitDialog(_BaseDialog):
    PDF_ONLY = True
    MODES = (("Aralıklarla (her aralık ayrı dosya)", "ranges"),
             ("Aralıklarla (seçilenler tek dosyada)", "ranges_one"),
             ("Her N sayfada bir", "every"),
             ("Yer imine göre", "bookmarks"),
             ("Her sayfa ayrı dosya", "pages"))

    def __init__(self, main, paths: Sequence[str] = ()):
        super().__init__(main, "PDF böl", ())
        self.cb_mode = QComboBox()
        for t, k in self.MODES:
            self.cb_mode.addItem(t, k)
        self.cb_mode.currentIndexChanged.connect(self._mode_changed)
        self.extra.addRow("Bölme kipi", self.cb_mode)
        self.ed_range = QLineEdit()
        self.ed_range.setPlaceholderText("örn. 1-3, 5, 8-10")
        self.ed_range.textChanged.connect(self._refresh_preview)
        self.extra.addRow("Sayfa aralıkları", self.ed_range)
        self.sp_every = QSpinBox()
        self.sp_every.setRange(1, 9999)
        self.sp_every.setValue(1)
        self.sp_every.valueChanged.connect(self._refresh_preview)
        self.extra.addRow("N", self.sp_every)
        self.ed_tpl = QLineEdit("{ad}_{n}")
        self.ed_tpl.setToolTip("{ad} kaynak adı · {n} sıra no · {aralik} aralık / yer imi başlığı")
        self.extra.addRow("Dosya adı şablonu", self.ed_tpl)
        self.r_sub = QRadioButton("Her PDF için ayrı alt klasör")
        self.extra.addRow("", self.r_sub)
        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet("color:#d14")
        self.extra.addRow("", self.lbl_err)
        self.btn_run.setText("Böl…")
        self._mode_changed()
        if paths:
            self.add_files(paths)

    def mode(self) -> str:
        return self.cb_mode.currentData()

    def _mode_changed(self, *_):
        m = self.mode()
        self.ed_range.setEnabled(m in ("ranges", "ranges_one"))
        self.sp_every.setEnabled(m == "every")
        self._refresh_preview()

    def options(self) -> dict:
        return dict(mode=self.mode(), ranges=self.ed_range.text(), every=self.sp_every.value(),
                    template=self.ed_tpl.text().strip() or "{ad}_{n}")

    def _on_current(self, row: int):
        self._refresh_preview()

    def plan_for(self, path: str):
        d = pdfops.open_source(path)
        try:
            o = self.options()
            return pdfops.plan_split(d, o["mode"], o["ranges"], o["every"])
        finally:
            d.close()

    def _refresh_preview(self, *_):
        it = self.list.currentItem()
        if it is None:
            self.lbl_err.setText("")
            return
        p = it.data(Qt.ItemDataRole.UserRole)
        try:
            plan = self.plan_for(p)
        except ValueError as ex:
            self.lbl_err.setText(str(ex))
            self.preview.set_pages("", [])
            return
        self.lbl_err.setText("")
        pages = [g[0] for _, g in plan] if self.mode() in ("every", "bookmarks", "pages", "ranges") \
            else plan[0][1]
        self.show_preview(p, pages)
        if self.mode() != "ranges_one":
            self.lbl_prev.setText(f"Önizleme — {len(plan)} dosya oluşacak (her birinin ilk sayfası)")

    def generate(self):
        if not self.paths:
            return None
        base = os.path.dirname(self.paths[0])
        d = QFileDialog.getExistingDirectory(self, "Parçaların kaydedileceği klasör",
                                             workspace.out_dir("projects") or base)
        return self.start_split(d) if d else None

    def start_split(self, out_dir: str):
        paths = self.paths
        o = self.options()
        sub = self.r_sub.isChecked() or len(paths) > 1

        def job(progress, cancelled):
            return pdfops.split_many(paths, out_dir, per_file_dir=sub, progress=progress,
                                     cancelled=cancelled, **o)
        return self._begin(job, len(paths))
