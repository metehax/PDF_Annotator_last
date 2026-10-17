"""
ui/scanner.py
=============
Belge tarama penceresi (`ScanDialog`): fotoğraf ya da PDF sayfalarından kâğıdı bul, köşeleri elle
düzelt, filtre seç, çok sayfalı (isteğe bağlı aranabilir) PDF üret. Çekirdek `scan.py`'dedir;
ağır iş (işleme + PDF + OCR) `BackgroundJob`'da çalışır.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
import pymupdf as fitz
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QGraphicsEllipseItem,
    QGraphicsPixmapItem, QGraphicsPolygonItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
    QListView, QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSlider,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

import convert
import ocr
import scan
import workspace
from ui import theme
from ui.convert import BackgroundJob
from ui.icons import icon

PDF_DPI = 200            # PDF sayfaları bu çözünürlükte görüntüye çevrilir
WORK_SIDE = 1400         # düzenleme/önizleme görüntüsünün en uzun kenarı (px)
PAGE_SIZE_ITEMS = (("A4", "a4"), ("Letter", "letter"), ("Orijinal oran", "orijinal"))


# ---------------------------------------------------------------------------
# Kaynaklar
# ---------------------------------------------------------------------------
@dataclass(eq=False)
class Source:
    """Taranacak tek bir sayfa: görsel dosya ya da bir PDF'in `index`. sayfası (`data` = PDF baytları)."""
    kind: str                       # "image" | "pdf"
    path: str = ""
    data: bytes = b""
    index: int = 0
    label: str = ""


def expand_sources(items: Sequence[Union[str, Source]]) -> List[Source]:
    """Yol listesini (görsel / PDF) sayfa kaynaklarına açar. Okunamayanlarda `ValueError`."""
    out: List[Source] = []
    for it in items:
        if isinstance(it, Source):
            out.append(it)
            continue
        ext = os.path.splitext(it)[1].lower()
        name = os.path.basename(it)
        if ext in scan.IMAGE_EXTS:
            out.append(Source("image", path=it, label=name))
        elif ext == ".pdf":
            with open(it, "rb") as f:
                data = f.read()
            out.extend(pdf_sources(data, name))
        else:
            raise ValueError(f"Desteklenmeyen dosya: {name}")
    return out


def pdf_sources(data: bytes, name: str = "") -> List[Source]:
    with fitz.open("pdf", data) as d:
        if d.needs_pass:
            raise ValueError(f"{name or 'PDF'} parolalı; önce parolayı kaldırın.")
        n = d.page_count
    return [Source("pdf", data=data, index=i, label=f"{name} s.{i + 1}".strip()) for i in range(n)]


def load_source(src: Source, cache: Optional[Dict[int, "fitz.Document"]] = None,
                max_side: int = scan.MAX_SIDE) -> np.ndarray:
    """Kaynağı (h, w, 3) RGB uint8 olarak yükler. `cache`: aynı PDF'in belgesini yeniden açmamak için."""
    if src.kind == "image":
        return scan.load_image(src.path, max_side)
    doc = cache.get(id(src.data)) if cache is not None else None
    if doc is None:
        doc = fitz.open("pdf", src.data)
        if cache is not None:
            cache[id(src.data)] = doc
    page = doc[src.index]
    long_pt = max(page.rect.width, page.rect.height)
    dpi = min(PDF_DPI, max_side * 72.0 / max(long_pt, 1.0))
    pm = page.get_pixmap(dpi=max(10, int(dpi)), alpha=False)
    return np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, 3).copy()


def _to_pixmap(a: np.ndarray) -> QPixmap:
    a = np.ascontiguousarray(a)
    h, w = a.shape[:2]
    return QPixmap.fromImage(QImage(a.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy())


def _fit_side(a: np.ndarray, side: int) -> np.ndarray:
    import cv2
    h, w = a.shape[:2]
    k = min(1.0, side / max(h, w))
    if k >= 1.0:
        return a
    return cv2.resize(a, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------------------
# Köşe (kesir koordinatı: 0…1, döndürülmüş görüntüye göre) yardımcıları
# ---------------------------------------------------------------------------
FULL = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)


def is_full(c: np.ndarray) -> bool:
    return bool(np.abs(np.asarray(c) - FULL).max() < 0.003)


def to_px(c: np.ndarray, w: int, h: int) -> np.ndarray:
    return np.clip(np.asarray(c, np.float32) * [w, h], [0, 0], [w - 1, h - 1]).astype(np.float32)


def rotate_corners(c: np.ndarray, derece: int) -> np.ndarray:
    """Görüntü `derece` (90'ın katı, saat yönü) döndürülünce köşelerin yeni kesir koordinatları."""
    c = np.asarray(c, np.float32).copy()
    for _ in range((int(derece) // 90) % 4):
        c = np.stack([1 - c[:, 1], c[:, 0]], axis=1)
    return scan.order_points(c)


def default_corners(src: Source, img: np.ndarray) -> np.ndarray:
    """Fotoğrafta kâğıdı bulur; PDF sayfası (zaten düz) için tüm sayfa."""
    if src.kind != "image":
        return FULL.copy()
    h, w = img.shape[:2]
    return (scan.detect_corners(img) / [w, h]).astype(np.float32)


def render_page(src: Source, rot: int, corners: Optional[np.ndarray], filt: str, br: float, ct: float,
                cache: Optional[Dict[int, "fitz.Document"]] = None) -> np.ndarray:
    """Tek sayfanın nihai görüntüsü: yükle → döndür → köşelerden düzelt → filtre."""
    img = load_source(src, cache)
    if rot % 360:
        img = scan.rotate(img, rot)
    h, w = img.shape[:2]
    c = default_corners(src, img) if corners is None else corners
    if not is_full(c):
        img = scan.warp(img, to_px(c, w, h))
    return scan.apply_filter(img, filt, br, ct)


@dataclass(eq=False)
class ScanPage:
    src: Source
    rot: int = 0
    corners: Optional[np.ndarray] = None       # (4, 2) kesir; None = henüz algılanmadı
    filt: str = "otomatik"
    br: int = 0
    ct: int = 0

    def spec(self):
        return (self.src, self.rot, None if self.corners is None else self.corners.copy(),
                self.filt, self.br, self.ct)


# ---------------------------------------------------------------------------
# Köşe düzenleyici
# ---------------------------------------------------------------------------
class _Handle(QGraphicsEllipseItem):
    R = 11

    def __init__(self, view: "CornerView"):
        super().__init__(-self.R, -self.R, 2 * self.R, 2 * self.R)
        self._view = view
        self.setFlags(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges
                      | QGraphicsEllipseItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setZValue(10)
        t = theme.current()
        self.setPen(QPen(QColor("#ffffff"), 2))
        self.setBrush(QBrush(QColor(t["accent"])))

    def itemChange(self, change, value):
        if change == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionChange:
            r = self._view.img_rect
            return QPointF(min(max(value.x(), r.left()), r.right()), min(max(value.y(), r.top()), r.bottom()))
        if change == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionHasChanged:
            self._view._moved()
        return super().itemChange(change, value)


class CornerView(QGraphicsView):
    """Görüntü + 4 sürüklenebilir köşe kulpu + arası yarı saydam alan."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("scanCanvas")
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(theme.qcolor("canvas")))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.img_rect = QRectF()
        self._silent = False
        self._pix: Optional[QGraphicsPixmapItem] = None
        t = theme.current()
        self.poly = QGraphicsPolygonItem()
        pen = QPen(QColor(t["accent"]), 2)
        pen.setCosmetic(True)
        self.poly.setPen(pen)
        c = QColor(t["accent"])
        c.setAlpha(46)
        self.poly.setBrush(QBrush(c))
        self.poly.setZValue(5)
        self.scene().addItem(self.poly)
        self.handles = [_Handle(self) for _ in range(4)]
        for h in self.handles:
            self.scene().addItem(h)

    # -- veri --------------------------------------------------------------
    def set_image(self, pm: Optional[QPixmap]):
        if self._pix is not None:
            self.scene().removeItem(self._pix)
            self._pix = None
        if pm is None or pm.isNull():
            self.img_rect = QRectF()
            return
        self._pix = self.scene().addPixmap(pm)
        self._pix.setZValue(0)
        self.img_rect = QRectF(0, 0, pm.width(), pm.height())
        self.scene().setSceneRect(self.img_rect.adjusted(-24, -24, 24, 24))
        self._fit()

    def set_corners(self, c: np.ndarray):
        """Kesir koordinatlı 4 köşeyi kulplara yerleştirir (sinyal göndermez)."""
        w, h = self.img_rect.width(), self.img_rect.height()
        self._silent = True
        for hd, (x, y) in zip(self.handles, np.asarray(c, np.float32)):
            hd.setPos(float(x) * w, float(y) * h)
        self._silent = False
        self._update_poly()

    def corners(self) -> np.ndarray:
        """Kulpların kesir koordinatları (kulp sırasıyla)."""
        w, h = max(self.img_rect.width(), 1.0), max(self.img_rect.height(), 1.0)
        return np.array([[hd.pos().x() / w, hd.pos().y() / h] for hd in self.handles], np.float32)

    # -- iç ----------------------------------------------------------------
    def _update_poly(self):
        self.poly.setPolygon(QPolygonF([hd.pos() for hd in self.handles]))

    def _moved(self):
        self._update_poly()
        if not self._silent:
            self.changed.emit()

    def _fit(self):
        if not self.scene().sceneRect().isEmpty():
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def showEvent(self, e):
        super().showEvent(e)
        self._fit()


# ---------------------------------------------------------------------------
# Pencere
# ---------------------------------------------------------------------------
class ScanDialog(QDialog):
    def __init__(self, main, kaynaklar: Sequence[Union[str, Source]] = (), start: int = 0):
        super().__init__(main)
        self.setWindowTitle("Belge tara")
        self.resize(1180, 800)
        self._main = main
        self.pages: List[ScanPage] = []
        self.cur: Optional[ScanPage] = None
        self.preview_array: Optional[np.ndarray] = None
        self.result_path: Optional[str] = None
        self._work: Optional[np.ndarray] = None
        self._cache: Dict[int, "fitz.Document"] = {}
        self._job: Optional[BackgroundJob] = None
        self._loading = False
        self._tessdata = ocr.find_tessdata()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._refresh_preview)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        mid = QHBoxLayout()
        mid.setSpacing(12)
        root.addLayout(mid, 1)

        # -- orta: köşe düzenleyici / sonuç ----------------------------------
        center = QVBoxLayout()
        mid.addLayout(center, 1)
        bar = QHBoxLayout()
        self.btn_auto = QPushButton(icon("scan"), "Otomatik algıla")
        self.btn_auto.clicked.connect(self.auto_detect)
        self.btn_full = QPushButton(icon("fit_page"), "Tüm görsel")
        self.btn_full.clicked.connect(self.select_all)
        bar.addWidget(self.btn_auto)
        bar.addWidget(self.btn_full)
        bar.addStretch(1)
        self.btn_view_edit = QPushButton("Köşeler")
        self.btn_view_res = QPushButton("Sonuç")
        for b in (self.btn_view_edit, self.btn_view_res):
            b.setObjectName("segBtn")
            b.setCheckable(True)
            bar.addWidget(b)
        self.btn_view_edit.setChecked(True)
        self.btn_view_edit.clicked.connect(lambda: self._show_view(0))
        self.btn_view_res.clicked.connect(lambda: self._show_view(1))
        center.addLayout(bar)
        self.stack = QStackedWidget()
        self.view = CornerView()
        self.view.changed.connect(self._corners_edited)
        self.stack.addWidget(self.view)
        self.result_lbl = QLabel("Sayfa ekleyin")
        self.result_lbl.setObjectName("scanCanvas")
        self.result_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_lbl.setMinimumSize(200, 200)
        self.stack.addWidget(self.result_lbl)
        center.addWidget(self.stack, 1)
        self.hint = QLabel("Köşe kulplarını sürükleyerek kâğıdın sınırını ayarlayın.")
        self.hint.setObjectName("valueLbl")
        center.addWidget(self.hint)

        # -- sağ: filtre, ayarlar, seçenekler --------------------------------
        side = QVBoxLayout()
        side.setSpacing(6)
        side_w = QWidget()
        side_w.setFixedWidth(272)
        side_w.setLayout(side)
        side.setContentsMargins(0, 0, 0, 0)
        mid.addWidget(side_w)
        lbl = QLabel("FİLTRE")
        lbl.setObjectName("sectionTitle")
        side.addWidget(lbl)
        self.filters = QListWidget()
        self.filters.setObjectName("scanFilters")
        self.filters.setViewMode(QListView.ViewMode.IconMode)
        self.filters.setMovement(QListView.Movement.Static)
        self.filters.setResizeMode(QListView.ResizeMode.Adjust)
        self.filters.setIconSize(QSize(76, 96))
        self.filters.setGridSize(QSize(88, 124))
        self.filters.setWordWrap(True)
        self.filters.setSpacing(2)
        self.filters.setFixedHeight(264)
        for f in scan.FILTERS:
            it = QListWidgetItem(f.capitalize())
            it.setData(Qt.ItemDataRole.UserRole, f)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.filters.addItem(it)
        self.filters.currentRowChanged.connect(self._filter_picked)
        side.addWidget(self.filters)
        self.sl_br, self.lb_br = self._slider(side, "Parlaklık")
        self.sl_ct, self.lb_ct = self._slider(side, "Kontrast")
        rot = QHBoxLayout()
        self.btn_ccw = QPushButton(icon("rotate_ccw"), "Sola")
        self.btn_cw = QPushButton(icon("rotate_cw"), "Sağa")
        self.btn_reset = QPushButton("Sıfırla")
        self.btn_ccw.clicked.connect(lambda: self.rotate_page(-90))
        self.btn_cw.clicked.connect(lambda: self.rotate_page(90))
        self.btn_reset.clicked.connect(self._reset_adjust)
        for b in (self.btn_ccw, self.btn_cw, self.btn_reset):
            rot.addWidget(b)
        side.addLayout(rot)
        side.addSpacing(6)
        lbl = QLabel("ÇIKTI")
        lbl.setObjectName("sectionTitle")
        side.addWidget(lbl)
        row = QHBoxLayout()
        row.addWidget(QLabel("Sayfa boyutu"))
        self.cb_size = QComboBox()
        for t, k in PAGE_SIZE_ITEMS:
            self.cb_size.addItem(t, k)
        row.addWidget(self.cb_size, 1)
        side.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("JPEG kalitesi"))
        self.sp_quality = QSpinBox()
        self.sp_quality.setRange(30, 100)
        self.sp_quality.setValue(85)
        row.addWidget(self.sp_quality, 1)
        side.addLayout(row)
        self.chk_ocr = QCheckBox("Aranabilir yap (OCR)")
        if self._tessdata is None:
            self.chk_ocr.setEnabled(False)
            self.chk_ocr.setToolTip(ocr.setup_message())
        side.addWidget(self.chk_ocr)
        side.addStretch(1)

        # -- alt: sayfa şeridi -----------------------------------------------
        strip = QHBoxLayout()
        col = QVBoxLayout()
        self.btn_add = QPushButton(icon("plus"), "Sayfa ekle…")
        self.btn_del = QPushButton(icon("trash"), "Sil")
        self.btn_add.clicked.connect(self._add_dialog)
        self.btn_del.clicked.connect(self.remove_page)
        mv = QHBoxLayout()
        self.btn_left = QPushButton(icon("chevron_left"), "")
        self.btn_right = QPushButton(icon("chevron_right"), "")
        self.btn_left.setToolTip("Sayfayı sola taşı")
        self.btn_right.setToolTip("Sayfayı sağa taşı")
        self.btn_left.clicked.connect(lambda: self.move_page(-1))
        self.btn_right.clicked.connect(lambda: self.move_page(1))
        mv.addWidget(self.btn_left)
        mv.addWidget(self.btn_right)
        for w in (self.btn_add, self.btn_del):
            col.addWidget(w)
        col.addLayout(mv)
        strip.addLayout(col)
        self.strip = QListWidget()
        self.strip.setObjectName("scanStrip")
        self.strip.setViewMode(QListView.ViewMode.IconMode)
        self.strip.setFlow(QListView.Flow.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setMovement(QListView.Movement.Snap)
        self.strip.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.strip.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.strip.setIconSize(QSize(72, 92))
        self.strip.setGridSize(QSize(88, 118))
        self.strip.setSpacing(4)
        self.strip.setFixedHeight(132)
        self.strip.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.strip.currentRowChanged.connect(self._page_picked)
        self.strip.model().rowsMoved.connect(self._sync_order)
        strip.addWidget(self.strip, 1)
        root.addLayout(strip)

        # -- taban -----------------------------------------------------------
        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("valueLbl")
        foot.addWidget(self.status, 1)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(180, 8)
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
        for w in (self.btn_stop, self.btn_close, self.btn_run):
            foot.addWidget(w)
        root.addLayout(foot)

        if kaynaklar:
            self.add_sources(kaynaklar)
            if self.pages:
                self.strip.setCurrentRow(min(max(start, 0), len(self.pages) - 1))
        self._enable()

    # -- küçük yapı taşları ---------------------------------------------------
    def _slider(self, layout, title):
        row = QHBoxLayout()
        row.addWidget(QLabel(title))
        lb = QLabel("0")
        lb.setObjectName("valueLbl")
        row.addStretch(1)
        row.addWidget(lb)
        layout.addLayout(row)
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(-100, 100)
        sl.valueChanged.connect(self._adjust_changed)
        layout.addWidget(sl)
        return sl, lb

    def _enable(self):
        has = self.cur is not None
        busy = self._job is not None
        for w in (self.btn_auto, self.btn_full, self.btn_ccw, self.btn_cw, self.btn_reset, self.btn_del,
                  self.filters, self.sl_br, self.sl_ct):
            w.setEnabled(has and not busy)
        n = len(self.pages)
        row = self.strip.currentRow()
        self.btn_left.setEnabled(has and not busy and row > 0)
        self.btn_right.setEnabled(has and not busy and 0 <= row < n - 1)
        self.btn_add.setEnabled(not busy)
        self.strip.setEnabled(not busy)
        self.btn_run.setEnabled(n > 0 and not busy)
        for w in (self.cb_size, self.sp_quality):
            w.setEnabled(not busy)
        self.chk_ocr.setEnabled(self._tessdata is not None and not busy)

    def _show_view(self, i: int):
        self.stack.setCurrentIndex(i)
        self.btn_view_edit.setChecked(i == 0)
        self.btn_view_res.setChecked(i == 1)
        self._fit_result()

    # -- sayfa ekle / sil / sırala -------------------------------------------
    def _add_dialog(self):
        flt = "Görsel ve PDF (" + " ".join("*" + e for e in scan.IMAGE_EXTS) + " *.pdf)"
        paths, _ = QFileDialog.getOpenFileNames(self, "Sayfa ekle", "", flt)
        if paths:
            self.add_sources(paths)

    def add_sources(self, kaynaklar: Sequence[Union[str, Source]]):
        added = []
        for k in kaynaklar:
            try:
                srcs = expand_sources([k])
            except Exception as ex:
                QMessageBox.warning(self, "Eklenemedi", f"{k if isinstance(k, str) else k.label}\n{ex}")
                continue
            for s in srcs:
                p = ScanPage(s, filt="otomatik")
                try:
                    thumb = _to_pixmap(_fit_side(load_source(s, self._cache, 240), 160))
                except Exception as ex:
                    QMessageBox.warning(self, "Eklenemedi", f"{s.label}\n{ex}")
                    continue
                it = QListWidgetItem(icon_from(thumb), s.label[-14:] if s.label else "")
                it.setData(Qt.ItemDataRole.UserRole, p)
                it.setToolTip(s.label)
                it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                self.strip.addItem(it)
                self.pages.append(p)
                added.append(p)
        if added and self.cur is None:
            self.strip.setCurrentRow(0)
        self._enable()
        return added

    def remove_page(self):
        row = self.strip.currentRow()
        if row < 0:
            return
        it = self.strip.takeItem(row)
        self.pages.remove(it.data(Qt.ItemDataRole.UserRole))
        if not self.pages:
            self.cur = None
            self._work = None
            self.view.set_image(None)
            self.result_lbl.setPixmap(QPixmap())
            self.result_lbl.setText("Sayfa ekleyin")
            self.preview_array = None
        elif self.strip.currentRow() < 0:
            self.strip.setCurrentRow(min(row, len(self.pages) - 1))
        self._enable()

    def move_page(self, delta: int):
        row = self.strip.currentRow()
        new = row + delta
        if row < 0 or not (0 <= new < self.strip.count()):
            return
        self.strip.blockSignals(True)
        it = self.strip.takeItem(row)
        self.strip.insertItem(new, it)
        self.strip.setCurrentRow(new)
        self.strip.blockSignals(False)
        self._sync_order()

    def _sync_order(self, *_):
        self.pages = [self.strip.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.strip.count())]
        self._enable()

    # -- sayfa seçimi ----------------------------------------------------------
    def _page_picked(self, row: int):
        if row < 0 or row >= self.strip.count():
            return
        self._load_page(self.strip.item(row).data(Qt.ItemDataRole.UserRole))

    def _load_page(self, p: ScanPage):
        self.cur = p
        self._loading = True
        try:
            img = load_source(p.src, self._cache)
            if p.rot % 360:
                img = scan.rotate(img, p.rot)
            self._work = _fit_side(img, WORK_SIDE)
            h, w = self._work.shape[:2]
            if p.corners is None:
                p.corners = default_corners(p.src, self._work)
            self.view.set_image(_to_pixmap(self._work))
            self.view.set_corners(p.corners)
            self.filters.setCurrentRow(scan.FILTERS.index(p.filt))
            self.sl_br.setValue(p.br)
            self.sl_ct.setValue(p.ct)
            self.lb_br.setText(str(p.br))
            self.lb_ct.setText(str(p.ct))
        except Exception as ex:
            self._work = None
            QMessageBox.warning(self, "Sayfa açılamadı", f"{p.src.label}\n{ex}")
        finally:
            self._loading = False
        self._refresh_preview()
        self._enable()

    # -- düzenleme eylemleri ------------------------------------------------------
    def auto_detect(self):
        if self.cur is None or self._work is None:
            return
        h, w = self._work.shape[:2]
        c = (scan.detect_corners(self._work) / [w, h]).astype(np.float32)
        self._set_corners(c)

    def select_all(self):
        if self.cur is not None:
            self._set_corners(FULL.copy())

    def _set_corners(self, c: np.ndarray):
        self.cur.corners = np.asarray(c, np.float32).copy()
        self.view.set_corners(self.cur.corners)
        self._refresh_preview()

    def rotate_page(self, derece: int):
        p = self.cur
        if p is None:
            return
        c = rotate_corners(p.corners if p.corners is not None else FULL, derece)
        p.rot = (p.rot + derece) % 360
        p.corners = c
        self._load_page(p)

    def _corners_edited(self):
        if self.cur is not None and not self._loading:
            self.cur.corners = self.view.corners()
            self._timer.start()

    def _filter_picked(self, row: int):
        if self.cur is None or self._loading or row < 0:
            return
        self.cur.filt = scan.FILTERS[row]
        self._refresh_preview(cards=False)

    def _adjust_changed(self):
        self.lb_br.setText(str(self.sl_br.value()))
        self.lb_ct.setText(str(self.sl_ct.value()))
        if self.cur is None or self._loading:
            return
        self.cur.br, self.cur.ct = self.sl_br.value(), self.sl_ct.value()
        self._timer.start()

    def _reset_adjust(self):
        self.sl_br.setValue(0)
        self.sl_ct.setValue(0)

    # -- önizleme -----------------------------------------------------------------
    def _warped_work(self) -> Optional[np.ndarray]:
        if self._work is None or self.cur is None or self.cur.corners is None:
            return None
        h, w = self._work.shape[:2]
        c = self.cur.corners
        return self._work if is_full(c) else scan.warp(self._work, to_px(c, w, h))

    def _refresh_preview(self, cards: bool = True):
        self._timer.stop()
        p = self.cur
        warped = self._warped_work()
        if warped is None:
            return
        self.preview_array = scan.apply_filter(warped, p.filt, p.br, p.ct)
        self.result_lbl.setText("")
        self._fit_result()
        item = self.strip.currentItem()
        if item is not None:
            item.setIcon(icon_from(_to_pixmap(_fit_side(self.preview_array, 160))))
        if cards:
            small = _fit_side(warped, 220)
            self.filters.blockSignals(True)
            for i, f in enumerate(scan.FILTERS):
                self.filters.item(i).setIcon(icon_from(_to_pixmap(scan.apply_filter(small, f))))
            self.filters.blockSignals(False)

    def _fit_result(self):
        a = self.preview_array
        if a is None:
            return
        pm = _to_pixmap(a)
        sz = self.result_lbl.size() - QSize(16, 16)
        self.result_lbl.setPixmap(pm.scaled(sz, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.stack.currentIndex() == 1:
            self._fit_result()

    # -- PDF üretimi ---------------------------------------------------------------
    def generate(self):
        if not self.pages:
            return None
        first = self.pages[0].src
        stem = os.path.splitext(os.path.basename(first.path))[0] + "_tarama" if first.path else "tarama"
        fallback = os.path.dirname(first.path) if first.path else os.path.join(os.path.expanduser("~"), "Documents")
        base = workspace.join_out("scans", stem, fallback)
        out, _ = QFileDialog.getSaveFileName(self, "PDF olarak kaydet", base + ".pdf", "PDF (*.pdf)")
        if not out:
            return None
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        return self.start_export(out)

    def start_export(self, out: str):
        specs = [p.spec() for p in self.pages]
        size = self.cb_size.currentData()
        quality = self.sp_quality.value()
        do_ocr = self.chk_ocr.isChecked() and self._tessdata is not None
        tessdata = self._tessdata
        lang = ocr.pick_language(tessdata, None) if do_ocr else ""
        n = len(specs)
        total = n * (2 if do_ocr else 1) + 1

        def job(progress, cancelled):
            cache: Dict[int, "fitz.Document"] = {}
            arrays = []
            try:
                for i, (src, rot, corners, filt, br, ct) in enumerate(specs):
                    if cancelled():
                        raise convert.Cancelled()
                    arrays.append(render_page(src, rot, corners, filt, br, ct, cache))
                    progress(i + 1, total)
            finally:
                for d in cache.values():
                    d.close()
            if cancelled():
                raise convert.Cancelled()
            if not do_ocr:
                scan.to_pdf(arrays, out, size, 0, quality)
                progress(total, total)
                return out
            doc = scan.to_pdf(arrays, None, size, 0, quality)
            tmp = out + ".ocr.part"
            try:
                done = ocr.make_searchable_pdf(doc, tmp, lang, tessdata,
                                               progress=lambda a, b: progress(n + a, total),
                                               cancelled=cancelled)
            finally:
                doc.close()
            if not done:
                self._rm(tmp)
                raise convert.Cancelled()
            os.replace(tmp, out)
            progress(total, total)
            return out

        self.result_path = None
        self.status.setText("PDF hazırlanıyor…")
        self.bar.setRange(0, total)
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

    @staticmethod
    def _rm(path: str):
        try:
            os.remove(path)
        except OSError:
            pass

    def _finish_job(self):
        self._job = None
        self.bar.hide()
        self.btn_stop.hide()
        self.btn_run.show()
        self._enable()

    def _on_done(self, out):
        self._finish_job()
        self.result_path = out
        self.status.setText("Tamamlandı: " + os.path.basename(out))
        try:
            self._main.open_paths([out])
            self._main.toasts.show("Tarama PDF'i oluşturuldu.", "success")
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
        """Kapanış (X, Esc, accept): çalışan işi durdur, açık PDF belgelerini bırak."""
        if self._job is not None:
            self._job.cancel()
        for d in self._cache.values():
            d.close()
        self._cache.clear()
        super().done(r)


def icon_from(pm: QPixmap) -> QIcon:
    return QIcon(pm)
