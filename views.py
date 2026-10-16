"""
views.py
========
Çizim yüzeyleri: ana PDF görünümü (PDFView) ve karşılaştırma modu
panelleri (ComparePane / ComparePaneView).

Sorumluluklar:
    * Fare olaylarını aktif araca (ToolState.tool) göre yönetmek: çizim,
      seçim/taşıma, sağ-tık menüsü.
    * Serbest çizimde (ink) Catmull-Rom -> kübik Bézier yumuşatmasını HEM
      canlı önizlemede HEM son nesnede uygulamak (models.py'deki aynı
      fonksiyonu kullanarak ekran ve PDF çıktısı birebir örtüşsün).
    * Seçili, yeniden boyutlandırılabilir bir işaret (şekil/metin/resim)
      için gizmo.SelectionGizmo'yu konumlandırmak ve resizeRequested
      sinyalini yaymak.
    * Sayfa render'ını PDFDocument'in LRU önbelleği + asenkron render
      görevi (QThreadPool) üzerinden, önbellekte hazır bir pixmap yoksa
      geçici bir yer tutucuyla göstermek — sonuç geldiğinde sinyalle
      ana iş parçacığında güncellemek.
    * Karşılaştırma modunda iki bağımsız, salt-okunur belge/sayfa paneli
      ve altın açı numaralandırmayı korumak.
"""

from __future__ import annotations

import bisect
import math
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QPoint, QPointF, QRectF, QSizeF,
    QThreadPool, QTimer, QVariantAnimation, Qt, Signal,
)
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem,
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout, QWidget,
)

from gizmo import SelectionGizmo
from models import (
    Annotation, HighlightAnnotation, ImageAnnotation, InkAnnotation,
    LineAnnotation, RedactionAnnotation, ShapeAnnotation,
    ToolState, arrow_wing_points, catmull_rom_to_beziers,
)


# ---------------------------------------------------------------------------
# Ana çizim yüzeyi — sürekli kaydırmalı çok sayfalı görünüm
# ---------------------------------------------------------------------------
PAGE_GAP = 16.0                # sayfalar arası boşluk (pt)
DOC_MARGIN = 24.0              # belge çevresindeki boşluk (pt)
ZOOM_MIN, ZOOM_MAX = 0.1, 8.0
MAX_RENDER_PIXELS = 40_000_000  # tek sayfa render'ı için piksel üst sınırı
KEEP_NEIGHBOURS = 2            # görünür alanın dışında render'ı tutulan sayfa


class PageItem(QGraphicsItem):
    """Tek bir sayfanın "kâğıdı": gölge + zemin rengi + render edilmiş
    görüntü. İşaretler, arama vurguları ve düzenleme kutuları bu öğenin
    çocuklarıdır; böylece koordinatları doğrudan sayfa (PDF pt) birimidir."""

    SHADOW = 5.0

    def __init__(self, index: int, w: float, h: float):
        super().__init__()
        self.index = index
        self.w, self.h = w, h
        self.paper = QColor("#ffffff")
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.bg = QGraphicsPixmapItem(self)
        self.bg.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.bg.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
        self.bg.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.bg.setZValue(-1000)
        self.render_key = None        # (sayfa_rev, invert, ölçek) — ekrandaki
        self.pending_key = None       # yolda olan render isteği
        self.ann_items: List[QGraphicsItem] = []
        self.search_items: List[QGraphicsItem] = []
        self.edit_items: List[QGraphicsItem] = []

    def page_rect(self) -> QRectF:
        return QRectF(0, 0, self.w, self.h)

    def boundingRect(self) -> QRectF:
        s = self.SHADOW
        return QRectF(-s, -s, self.w + 2 * s, self.h + 2 * s)

    def paint(self, painter, option, widget=None):
        r = self.page_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        # yumuşak gölge: birkaç saydam katman
        for i, alpha in ((3.0, 10), (2.0, 16), (1.0, 26)):
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(r.adjusted(-i, -i + 1.2, i, i + 1.2), 2 + i, 2 + i)
        painter.setBrush(self.paper)
        painter.drawRect(r)

    def set_pixmap(self, pm: QPixmap, key) -> None:
        self.bg.setPixmap(pm)
        if pm.width():
            self.bg.setScale(self.w / pm.width())
        self.render_key = key

    def drop_pixmap(self) -> None:
        if self.render_key is not None:
            self.bg.setPixmap(QPixmap())
        self.render_key = None
        self.pending_key = None


class PDFView(QGraphicsView):
    annotationCreated = Signal(object)             # Annotation
    textRequested = Signal(QRectF)                  # metin kutusu istendi
    numberRequested = Signal(QPointF)
    editTextRequested = Signal(QPointF)             # 'Metin Düzenle' aracıyla tıklandı
    cropRequested = Signal(QRectF)
    imagePlaceRequested = Signal(QRectF)            # resim aracıyla çizilen kutu
    itemsMoved = Signal()
    resizeRequested = Signal(object, QRectF, QRectF)  # ann, eski_rect, yeni_rect
    contextMenuRequested = Signal(object, object)
    selectionAnnotationChanged = Signal(object)      # seçili Annotation | None
    currentPageChanged = Signal(int)                 # kaydırma / tıklama ile
    zoomChanged = Signal(float)

    # Tüm konum sinyalleri (textRequested, numberRequested, …) SAYFA
    # koordinatlarıyla yayılır; hangi sayfa olduğu `current_page`'dir ve
    # sinyalden hemen önce currentPageChanged ile bildirilir.

    def __init__(self, state: ToolState, threadpool: Optional[QThreadPool] = None):
        super().__init__()
        self.state = state
        self.threadpool = threadpool or QThreadPool.globalInstance()
        self.scene_obj = QGraphicsScene(self)
        self.scene_obj.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.setScene(self.scene_obj)
        self.setRenderHints(QPainter.RenderHint.Antialiasing |
                            QPainter.RenderHint.SmoothPixmapTransform)
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QColor("#2b2d31"))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        self.item_ann_map: Dict[QGraphicsItem, Annotation] = {}
        self.ann_item_map: Dict[int, QGraphicsItem] = {}
        self.item_page_map: Dict[QGraphicsItem, int] = {}

        self._session = None
        self._invert = False
        self._pages: List[PageItem] = []
        self._tops: List[float] = []
        self._layout_sig = None
        self._current = 0
        self._programmatic_scroll = False
        self._zoom = 1.0
        self._gizmo_target: Optional[Annotation] = None
        self._search_state = ({}, None)

        self.gizmo = SelectionGizmo()
        self.scene_obj.addItem(self.gizmo)
        self.gizmo.hide()
        self.gizmo.resizeFinished.connect(self._on_gizmo_resize)
        self.scene_obj.selectionChanged.connect(self._on_selection_changed)

        self._panning = False
        self._space_down = False
        self._pan_last = QPointF()
        self._drawing = False
        self._active_page: Optional[PageItem] = None
        self._start = QPointF()
        self._temp_item = None
        self._ink_points: list = []
        self._hl_fixed_y = None
        self._line_end = QPointF()

        # Render'lar kaydırma/zoom durulunca istenir (her pikselde değil)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._update_visible_renders)
        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self._schedule_render())

        # Yumuşak kaydırma ve zoom animasyonları
        self._scroll_anim = QVariantAnimation(self)
        self._scroll_anim.setDuration(170)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scroll_anim.valueChanged.connect(
            lambda v: self.verticalScrollBar().setValue(int(round(v))))
        self._zoom_anim = QVariantAnimation(self)
        self._zoom_anim.setDuration(150)
        self._zoom_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._zoom_anim.valueChanged.connect(self._on_zoom_anim)
        self._zoom_anchor = QPointF()
        self._zoom_target = 1.0

        # PySide6, QThreadPool'a verilen bir QRunnable'ın Python nesnesini
        # canlı tutmayı garanti etmez; bitene kadar burada referans tutuyoruz.
        self._pending_render_tasks: list = []

    # =====================================================================
    # Belge / sayfa yerleşimi
    # =====================================================================
    @property
    def current_page(self) -> int:
        return self._current

    @property
    def _page_index(self) -> Optional[int]:      # eski API uyumluluğu
        return self._current if self._session is not None else None

    def _ensure_document(self, session, invert: bool) -> bool:
        """Belge veya sayfa yerleşimi değiştiyse sahneyi yeniden kurar.
        Yeniden kurulduysa True döner."""
        if invert != self._invert:
            self._invert = invert
            for p in self._pages:
                p.paper = QColor("#1b1b1d") if invert else QColor("#ffffff")
                p.drop_pixmap()
                p.update()
            self._schedule_render(0)
        sig = None if session is None else (id(session), session.pdf.layout_rev,
                                             session.pdf.page_count)
        if session is self._session and sig == self._layout_sig:
            return False
        self._rebuild(session)
        self._layout_sig = sig
        return True

    def _rebuild(self, session) -> None:
        scene = self.scene_obj
        # scene.clear() seçili öğeleri silerken selectionChanged tetikler;
        # henüz değiştirilmemiş (C++ tarafında silinmiş) gizmo'ya erişilmesin.
        scene.blockSignals(True)
        scene.clear()
        scene.blockSignals(False)
        self.item_ann_map.clear()
        self.ann_item_map.clear()
        self.item_page_map.clear()
        self._pages = []
        self._tops = []
        self._temp_item = None
        self._drawing = False

        self.gizmo = SelectionGizmo()
        scene.addItem(self.gizmo)
        self.gizmo.hide()
        self.gizmo.resizeFinished.connect(self._on_gizmo_resize)
        self._gizmo_target = None

        self._session = session
        if session is None:
            self._current = 0
            scene.setSceneRect(QRectF(0, 0, 1, 1))
            return

        n = session.pdf.page_count
        sizes = [session.pdf.page_size(i) for i in range(n)]
        max_w = max((w for w, _ in sizes), default=595.0)
        y = DOC_MARGIN
        for i, (w, h) in enumerate(sizes):
            p = PageItem(i, w, h)
            if self._invert:
                p.paper = QColor("#1b1b1d")
            p.setPos(-w / 2, y)
            scene.addItem(p)
            self._pages.append(p)
            self._tops.append(y)
            y += h + PAGE_GAP
        bottom = y - PAGE_GAP + DOC_MARGIN
        scene.setSceneRect(QRectF(-max_w / 2 - DOC_MARGIN, 0, max_w + 2 * DOC_MARGIN, bottom))
        self._current = max(0, min(self._current, n - 1))
        for i in range(n):
            self._populate_annotations(i)
        self._apply_search_state(center=False)
        self._draw_edit_boxes()
        self._schedule_render(0)

    def show_page(self, session, index: Optional[int], invert: bool = False,
                  scroll: bool = True) -> None:
        """Belgeyi (gerekirse) kurar ve `index` sayfasına gider."""
        if session is not self._session:
            self._current = index or 0
        self._ensure_document(session, invert)
        if session is None or not self._pages:
            return
        index = max(0, min(index or 0, len(self._pages) - 1))
        changed = index != self._current
        self._current = index
        if scroll:
            self.scroll_to_page(index)
        if changed:
            self._draw_edit_boxes()

    # eski API: goto_page / sekme değişimi vb.
    def render_page(self, session, page_index: Optional[int], invert: bool = False) -> None:
        self.show_page(session, page_index, invert)

    def refresh_page(self, index: int) -> None:
        """Bir sayfanın işaretlerini (ve gerekirse görüntüsünü) tazeler;
        kaydırma konumuna dokunmaz."""
        if self._session is None:
            return
        if self._ensure_document(self._session, self._invert):
            return
        if not (0 <= index < len(self._pages)):
            return
        self._populate_annotations(index)
        self._draw_edit_boxes()
        self._schedule_render(0)

    def refresh_current_page(self) -> None:
        self.refresh_page(self._current)

    def set_invert(self, invert: bool) -> None:
        self._ensure_document(self._session, invert)

    def page_rect_in_scene(self, index: int) -> QRectF:
        p = self._pages[index]
        return QRectF(p.pos(), QSizeF(p.w, p.h))

    def _page_index_at_y(self, y: float) -> int:
        if not self._tops:
            return 0
        i = bisect.bisect_right(self._tops, y) - 1
        return max(0, min(i, len(self._tops) - 1))

    def _page_at(self, scene_pt: QPointF) -> Optional[PageItem]:
        if not self._pages:
            return None
        p = self._pages[self._page_index_at_y(scene_pt.y())]
        return p if self.page_rect_in_scene(p.index).contains(scene_pt) else None

    def _set_current(self, index: int, emit: bool = True) -> None:
        if index == self._current:
            return
        self._current = index
        self._draw_edit_boxes()
        if emit:
            self.currentPageChanged.emit(index)

    def _on_scrolled(self, _v=None) -> None:
        self._schedule_render()
        if not self._pages or self._drawing or self._programmatic_scroll:
            return
        vr = self.viewport().rect()
        probe = self.mapToScene(QPoint(vr.center().x(), int(vr.height() * 0.4)))
        idx = self._page_index_at_y(probe.y())
        vbar = self.verticalScrollBar()
        if vbar.value() >= vbar.maximum() and vbar.maximum() > 0:
            # en altta: görünür alana tepesi girmiş son sayfa
            bottom = self.mapToScene(vr.bottomLeft()).y()
            idx = self._page_index_at_y(bottom)
        self._set_current(idx)

    def scroll_to_page(self, index: int, emit: bool = False) -> None:
        if not (0 <= index < len(self._pages)):
            return
        self._scroll_anim.stop()
        r = self.page_rect_in_scene(index)
        vr = self.viewport().rect()
        vbar, hbar = self.verticalScrollBar(), self.horizontalScrollBar()
        top_in_view = self.mapFromScene(r.topLeft()).y()
        # Sinyaller susturulmaz (QGraphicsView kaymayı bu sinyalle uygular);
        # bunun yerine sayfa algılaması geçici olarak kapatılır.
        self._programmatic_scroll = True
        try:
            vbar.setValue(vbar.value() + top_in_view - 12)
        finally:
            self._programmatic_scroll = False
        if r.width() * self._zoom <= vr.width():
            centre_x = self.mapFromScene(QPointF(0, r.top())).x()
            hbar.setValue(hbar.value() + centre_x - vr.width() // 2)
        if emit:
            self._set_current(index)
        else:
            self._current = index
        self._schedule_render(0)

    # =====================================================================
    # Render (görünür sayfalar, zoom'a göre çözünürlük, asenkron)
    # =====================================================================
    def _schedule_render(self, delay: int = 70) -> None:
        if self._session is None:
            return
        self._render_timer.start(delay)

    def _target_scale(self) -> float:
        s = self._zoom * self.devicePixelRatioF()
        # 2^(k/4) adımlarına yuvarla: küçük zoom değişimlerinde yeniden render yok
        q = 2 ** (math.ceil(math.log2(max(s, 0.25)) * 4) / 4)
        return min(q, 10.0)

    def _visible_range(self):
        vis = self.mapToScene(self.viewport().rect()).boundingRect()
        return self._page_index_at_y(vis.top()), self._page_index_at_y(vis.bottom())

    def _update_visible_renders(self) -> None:
        if self._session is None or not self._pages:
            return
        first, last = self._visible_range()
        n = len(self._pages)
        target = self._target_scale()
        order = [self._current] + [i for i in range(first, last + 1) if i != self._current]
        order += [i for i in (last + 1, first - 1, last + 2) if 0 <= i < n]
        for i in order:
            if 0 <= i < n:
                self._ensure_rendered(self._pages[i], target)
        lo, hi = first - KEEP_NEIGHBOURS, last + KEEP_NEIGHBOURS
        for p in self._pages:
            if (p.index < lo or p.index > hi) and p.render_key is not None:
                p.drop_pixmap()

    def _ensure_rendered(self, p: PageItem, target: float) -> None:
        pdf = self._session.pdf
        cap = math.sqrt(MAX_RENDER_PIXELS / max(1.0, p.w * p.h))
        scale = min(target, cap)
        key = (pdf.page_rev(p.index), self._invert, round(scale, 4))
        if p.render_key == key or p.pending_key == key:
            return
        p.pending_key = key
        session = self._session
        task = pdf.make_render_task(p.index, self._invert, scale)
        self._pending_render_tasks.append(task)

        def _cleanup():
            if task in self._pending_render_tasks:
                self._pending_render_tasks.remove(task)

        def on_finished(idx, qimg, _p=p, _key=key, _session=session):
            _cleanup()
            if (self._session is _session and idx < len(self._pages)
                    and self._pages[idx] is _p and _p.pending_key == _key):
                _p.pending_key = None
                _p.set_pixmap(QPixmap.fromImage(qimg), _key)

        def on_failed(_idx, _msg, _p=p, _key=key):
            _cleanup()
            if _p.pending_key == _key:
                _p.pending_key = None

        task.signals.finished.connect(on_finished)
        task.signals.failed.connect(on_failed)
        self.threadpool.start(task)

    # =====================================================================
    # Yakınlaştırma
    # =====================================================================
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, z: float, anchor: Optional[QPointF] = None) -> None:
        """Zoom'u değiştirir; `anchor` (viewport koordinatı) altındaki nokta
        yerinde kalır. Verilmezse görünümün ortası sabit tutulur."""
        z = max(ZOOM_MIN, min(ZOOM_MAX, z))
        if anchor is None:
            anchor = QPointF(self.viewport().rect().center())
        a = anchor.toPoint()
        scene_anchor = self.mapToScene(a)
        self._zoom = z
        self.setTransform(QTransform.fromScale(z, z))
        d = self.mapFromScene(scene_anchor) - a
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + d.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + d.y())
        self.zoomChanged.emit(z)
        self._schedule_render(120)

    def animate_zoom(self, z: float, anchor: Optional[QPointF] = None) -> None:
        z = max(ZOOM_MIN, min(ZOOM_MAX, z))
        self._zoom_anchor = anchor if anchor is not None else QPointF(self.viewport().rect().center())
        self._zoom_target = z
        self._zoom_anim.stop()
        self._zoom_anim.setStartValue(float(self._zoom))
        self._zoom_anim.setEndValue(float(z))
        self._zoom_anim.start()

    def _on_zoom_anim(self, v) -> None:
        self.set_zoom(float(v), self._zoom_anchor)

    def fit_width(self, index: Optional[int] = None) -> None:
        if not self._pages:
            return
        p = self._pages[self._current if index is None else index]
        avail = self.viewport().width() - 32
        if p.w > 0:
            self.set_zoom(avail / p.w)
            self.scroll_to_page(p.index)

    def fit_page(self, index: Optional[int] = None) -> None:
        if not self._pages:
            return
        p = self._pages[self._current if index is None else index]
        vr = self.viewport().rect()
        if p.w > 0 and p.h > 0:
            self.set_zoom(min((vr.width() - 32) / p.w, (vr.height() - 32) / p.h))
            self.scroll_to_page(p.index)

    # =====================================================================
    # İşaret <-> Qt öğesi eşlemesi
    # =====================================================================
    def _populate_annotations(self, index: int) -> None:
        p = self._pages[index]
        for gitem in p.ann_items:
            ann = self.item_ann_map.pop(gitem, None)
            if ann is not None and self.ann_item_map.get(id(ann)) is gitem:
                self.ann_item_map.pop(id(ann), None)
            self.item_page_map.pop(gitem, None)
            if gitem.scene() is not None:
                self.scene_obj.removeItem(gitem)
        p.ann_items = []
        for ann in self._session.annotations.get(index, []):
            self._add_annotation_item(ann, p)

    def _add_annotation_item(self, ann: Annotation, page: Optional[PageItem] = None) -> QGraphicsItem:
        page = page or self._pages[self._current]
        gitem = ann.create_item()
        gitem.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                       QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        gitem.setParentItem(page)
        page.ann_items.append(gitem)
        self.item_ann_map[gitem] = ann
        self.ann_item_map[id(ann)] = gitem
        self.item_page_map[gitem] = page.index
        return gitem

    def page_of_item(self, gitem) -> Optional[int]:
        return self.item_page_map.get(gitem)

    def page_of_annotation(self, ann) -> Optional[int]:
        gitem = self.ann_item_map.get(id(ann))
        return self.item_page_map.get(gitem) if gitem is not None else None

    def _on_selection_changed(self) -> None:
        items = [it for it in self.scene_obj.selectedItems() if it is not self.gizmo]
        sel_ann = self.item_ann_map.get(items[0]) if len(items) == 1 else None
        if sel_ann is not None and sel_ann.is_resizable():
            self.gizmo.setParentItem(items[0].parentItem())
            self.gizmo.set_aspect_lock_default(isinstance(sel_ann, ImageAnnotation))
            self.gizmo.set_rect(sel_ann.get_rect())
            self.gizmo.show()
            self._gizmo_target = sel_ann
        else:
            self.gizmo.hide()
            self._gizmo_target = None
        self.selectionAnnotationChanged.emit(sel_ann)

    def _on_gizmo_resize(self, old_rect: QRectF, new_rect: QRectF) -> None:
        if self._gizmo_target is not None:
            self.resizeRequested.emit(self._gizmo_target, old_rect, new_rect)

    # =====================================================================
    # 'Metin Düzenle' kutuları ve arama vurguları
    # =====================================================================
    def _draw_edit_boxes(self) -> None:
        """'Metin Düzenle' aracı açıkken GEÇERLİ sayfadaki taranmış
        satır/paragraf kutularını çizer (diğer sayfalardakileri siler)."""
        for p in self._pages:
            for it in p.edit_items:
                if it.scene() is not None:
                    self.scene_obj.removeItem(it)
            p.edit_items = []
        if self.state.tool != "edit" or self._session is None or not self._pages:
            return
        p = self._pages[self._current]
        entry = self._session.pdf.edit_cache.get((p.index, bool(self.state.edit_force_ocr)))
        if not entry:
            return
        key = "blocks" if self.state.edit_mode == "block" else "lines"
        pen = QPen(QColor("#3aa0ff"), 0.8, Qt.PenStyle.DashLine)
        for it in entry[key]:
            x0, y0, x1, y1 = it.rect
            box = QGraphicsRectItem(QRectF(x0, y0, x1 - x0, y1 - y0), p)
            box.setPen(pen)
            box.setBrush(QBrush(QColor(58, 160, 255, 28)))
            box.setZValue(40)
            box.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            p.edit_items.append(box)

    def set_all_search_highlights(self, results: Dict[int, list], active=None,
                                  center: bool = False) -> None:
        """results: sayfa -> [fitz.Rect]; active: (sayfa, sıra) ya da None."""
        self._search_state = (results or {}, active)
        self._apply_search_state(center)

    def set_search_highlights(self, rects: list, active_index: Optional[int] = None) -> None:
        """Eski API: yalnızca geçerli sayfanın vurguları."""
        active = (self._current, active_index) if active_index is not None else None
        self.set_all_search_highlights({self._current: rects} if rects else {}, active,
                                       center=active is not None)

    def _apply_search_state(self, center: bool) -> None:
        for p in self._pages:
            for it in p.search_items:
                if it.scene() is not None:
                    self.scene_obj.removeItem(it)
            p.search_items = []
        results, active = self._search_state
        active_item = None
        for page, rects in results.items():
            if not (0 <= page < len(self._pages)):
                continue
            p = self._pages[page]
            for i, r in enumerate(rects):
                is_active = active == (page, i)
                item = QGraphicsRectItem(QRectF(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0), p)
                base = QColor("#ff9800") if is_active else QColor("#ffeb3b")
                fill = QColor(base)
                fill.setAlphaF(0.45)
                item.setBrush(QBrush(fill))
                item.setPen(QPen(base.darker(130), 1.5))
                item.setZValue(500)
                item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                p.search_items.append(item)
                if is_active:
                    active_item = item
        if center and active_item is not None:
            self.centerOn(active_item)
            self._on_scrolled()

    # =====================================================================
    # Fare / klavye etkileşimi
    # =====================================================================
    def _snap_band(self, page: PageItem, pt: QPointF, force_free: bool):
        y = pt.y()
        lines = self._session.pdf.text_lines(page.index) if self.state.snap and not force_free else []
        if lines:
            best, best_d = None, 6.0
            for r in lines:
                if r.y0 - best_d <= y <= r.y1 + best_d:
                    d = abs((r.y0 + r.y1) / 2 - y)
                    if d < best_d or best is None:
                        best, best_d = r, d
            if best is not None:
                return best.y0, best.y1
        half = self.state.hl_thickness / 2
        return y - half, y + half

    @property
    def page_lines(self) -> list:                   # eski API uyumluluğu
        if self._session is None or not self._pages:
            return []
        return self._session.pdf.text_lines(self._current)

    def _on_context_menu(self, pos):
        pt = self.mapToScene(pos)
        page = self._page_at(pt)
        if page is not None:
            self._set_current(page.index)
        item = self.itemAt(pos)
        self.contextMenuRequested.emit(item, self.mapToGlobal(pos))

    def _local(self, page: PageItem, scene_pt: QPointF) -> QPointF:
        lp = page.mapFromScene(scene_pt)
        return QPointF(min(max(lp.x(), 0.0), page.w), min(max(lp.y(), 0.0), page.h))

    def _add_temp(self, item) -> None:
        item.setParentItem(self._active_page)
        item.setZValue(900)
        self._temp_item = item

    def _start_pan(self, e) -> None:
        self._panning = True
        self._pan_last = e.position()
        self._scroll_anim.stop()
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton or \
                (e.button() == Qt.MouseButton.LeftButton and self._space_down):
            self._start_pan(e)
            return

        scene_pt = self.mapToScene(e.position().toPoint())
        page = self._page_at(scene_pt)
        if page is not None:
            self._set_current(page.index)
        tool = self.state.tool

        if tool == "select":
            super().mousePressEvent(e)
            return
        if page is None:
            return
        pt = self._local(page, scene_pt)
        self._active_page = page

        if tool == "text":
            if e.button() == Qt.MouseButton.LeftButton:
                w = 220.0
                h = max(40.0, self.state.font_size * 1.6)
                self.textRequested.emit(QRectF(pt.x(), pt.y(), w, h))
            return

        if tool == "number":
            if e.button() == Qt.MouseButton.LeftButton:
                self.numberRequested.emit(pt)
            return

        if tool == "edit":
            if e.button() == Qt.MouseButton.LeftButton:
                self.editTextRequested.emit(pt)
            return

        if e.button() != Qt.MouseButton.LeftButton:
            return

        self._drawing = True
        self._start = pt

        if tool == "ink":
            self._ink_points = [(pt.x(), pt.y())]
            path = QPainterPath()
            path.moveTo(pt)
            item = QGraphicsPathItem(path)
            item.setPen(self._make_pen(self.state.stroke_color, self.state.pen_width,
                                       self.state.pen_opacity))
            self._add_temp(item)

        elif tool == "line":
            self._line_end = pt
            item = QGraphicsPathItem(QPainterPath())
            item.setPen(self._make_pen(self.state.stroke_color, self.state.pen_width,
                                       self.state.pen_opacity))
            self._add_temp(item)

        elif tool in ("rect", "oval"):
            item = QGraphicsEllipseItem() if tool == "oval" else QGraphicsRectItem()
            fc = QColor(self.state.fill_color)
            fc.setAlphaF(self.state.fill_opacity)
            item.setBrush(QBrush(fc))
            item.setPen(QPen(self.state.stroke_color, self.state.pen_width))
            self._add_temp(item)

        elif tool == "redact":
            item = QGraphicsRectItem()
            item.setBrush(QBrush(QColor(self.state.redact_color)))
            item.setPen(QPen(QColor("#ff4d4d"), 1.5, Qt.PenStyle.DashLine))
            self._add_temp(item)

        elif tool == "crop":
            item = QGraphicsRectItem()
            fc = QColor("#3a86ff"); fc.setAlphaF(0.12)
            item.setBrush(QBrush(fc))
            item.setPen(QPen(QColor("#3a86ff"), 1.5, Qt.PenStyle.DashLine))
            self._add_temp(item)

        elif tool == "image":
            item = QGraphicsRectItem()
            fc = QColor("#2ec4b6"); fc.setAlphaF(0.12)
            item.setBrush(QBrush(fc))
            item.setPen(QPen(QColor("#2ec4b6"), 1.5, Qt.PenStyle.DashLine))
            self._add_temp(item)

        elif tool == "highlight":
            force_free = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._hl_fixed_y = self._snap_band(page, pt, force_free)
            item = QGraphicsRectItem()
            c = QColor(self.state.hl_color)
            c.setAlphaF(self.state.fill_opacity)
            item.setBrush(QBrush(c))
            item.setPen(QPen(Qt.PenStyle.NoPen))
            self._add_temp(item)
        else:
            self._drawing = False

    @staticmethod
    def _make_pen(color, width, opacity):
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        c = QColor(color)
        c.setAlphaF(opacity)
        pen.setColor(c)
        return pen

    def _ink_preview_path(self) -> QPainterPath:
        """Sürükleme sırasında da NİHAİ eğriyle birebir aynı Catmull-Rom ->
        Bézier yumuşatmasını kullanır, ki kullanıcı çizerken ile bıraktığında
        gördüğü şekil arasında fark olmasın."""
        path = QPainterPath()
        pts = self._ink_points
        if not pts:
            return path
        segs = catmull_rom_to_beziers(pts) if len(pts) >= 3 else []
        path.moveTo(*pts[0])
        if segs:
            for _p0, c1, c2, p3 in segs:
                path.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(*p3))
        else:
            for p in pts[1:]:
                path.lineTo(*p)
        return path

    def mouseMoveEvent(self, e):
        if self._panning:
            delta = e.position() - self._pan_last
            self._pan_last = e.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            return

        if not self._drawing or self._active_page is None:
            super().mouseMoveEvent(e)
            return

        pt = self._local(self._active_page, self.mapToScene(e.position().toPoint()))
        tool = self.state.tool

        if tool == "ink":
            self._ink_points.append((pt.x(), pt.y()))
            self._temp_item.setPath(self._ink_preview_path())

        elif tool == "line":
            end = pt
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                dx, dy = pt.x() - self._start.x(), pt.y() - self._start.y()
                dist = math.hypot(dx, dy) or 1.0
                angle = math.atan2(dy, dx)
                step = math.radians(45)
                snapped = round(angle / step) * step
                end = QPointF(self._start.x() + dist * math.cos(snapped),
                              self._start.y() + dist * math.sin(snapped))
            self._line_end = end
            path = QPainterPath()
            path.moveTo(self._start)
            path.lineTo(end)
            if self.state.line_arrow:
                w1, w2 = arrow_wing_points((self._start.x(), self._start.y()), (end.x(), end.y()),
                                           size=max(10.0, self.state.pen_width * 3.5))
                path.moveTo(end); path.lineTo(*w1)
                path.moveTo(end); path.lineTo(*w2)
            self._temp_item.setPath(path)

        elif tool in ("rect", "oval", "redact", "crop", "image"):
            self._temp_item.setRect(QRectF(self._start, pt).normalized())

        elif tool == "highlight":
            y0, y1 = self._hl_fixed_y
            x0, x1 = sorted((self._start.x(), pt.x()))
            self._temp_item.setRect(QRectF(x0, y0, x1 - x0, y1 - y0))

    def mouseReleaseEvent(self, e):
        if self._panning and e.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._panning = False
            if self._space_down:
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.viewport().unsetCursor()
                self._restore_tool_cursor()
            return

        if not self._drawing or self._active_page is None:
            super().mouseReleaseEvent(e)
            if self.state.tool == "select":
                self.itemsMoved.emit()
            return

        self._drawing = False
        pt = self._local(self._active_page, self.mapToScene(e.position().toPoint()))
        tool = self.state.tool
        ann = None

        if tool == "ink":
            if len(self._ink_points) >= 1:
                ann = InkAnnotation(self._ink_points, self.state.stroke_color,
                                    self.state.pen_width, self.state.pen_opacity)
        elif tool == "line":
            end = self._line_end
            if math.hypot(end.x() - self._start.x(), end.y() - self._start.y()) > 2:
                ann = LineAnnotation((self._start.x(), self._start.y()), (end.x(), end.y()),
                                     self.state.stroke_color, self.state.pen_width,
                                     self.state.pen_opacity, self.state.line_arrow)
        elif tool in ("rect", "oval"):
            rect = QRectF(self._start, pt).normalized()
            if rect.width() > 2 and rect.height() > 2:
                ann = ShapeAnnotation(rect, tool, self.state.fill_color, self.state.stroke_color,
                                      self.state.pen_width, self.state.fill_opacity)
        elif tool == "redact":
            rect = QRectF(self._start, pt).normalized()
            if rect.width() > 2 and rect.height() > 2:
                ann = RedactionAnnotation(rect, self.state.redact_color)
        elif tool == "crop":
            rect = QRectF(self._start, pt).normalized()
            self._clear_temp()
            if rect.width() > 2 and rect.height() > 2:
                self.cropRequested.emit(rect)
            self._ink_points = []
            self._hl_fixed_y = None
            return
        elif tool == "image":
            rect = QRectF(self._start, pt).normalized()
            self._clear_temp()
            if rect.width() > 4 and rect.height() > 4:
                self.imagePlaceRequested.emit(rect)
            self._ink_points = []
            self._hl_fixed_y = None
            return
        elif tool == "highlight":
            y0, y1 = self._hl_fixed_y
            x0, x1 = sorted((self._start.x(), pt.x()))
            if x1 - x0 > 2:
                ann = HighlightAnnotation(QRectF(x0, y0, x1 - x0, y1 - y0), self.state.hl_color,
                                          self.state.fill_opacity)

        self._clear_temp()
        self._ink_points = []
        self._hl_fixed_y = None

        if ann is not None:
            self.annotationCreated.emit(ann)

    def _clear_temp(self):
        if self._temp_item is not None:
            if self._temp_item.scene() is not None:
                self.scene_obj.removeItem(self._temp_item)
            self._temp_item = None

    def _restore_tool_cursor(self):
        tool = self.state.tool
        cursor = (Qt.CursorShape.IBeamCursor if tool in ("text", "edit", "number")
                  else Qt.CursorShape.CrossCursor if tool != "select"
                  else Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(cursor)

    def keyPressEvent(self, e):
        if self.scene_obj.focusItem() is None:
            key = e.key()
            if key == Qt.Key.Key_Space and not e.isAutoRepeat() and not self._drawing:
                self._space_down = True
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
                return
            if key == Qt.Key.Key_Space:
                return
            if key == Qt.Key.Key_Home and self._pages:
                self.scroll_to_page(0, emit=True)
                return
            if key == Qt.Key.Key_End and self._pages:
                self.scroll_to_page(len(self._pages) - 1, emit=True)
                return
            if key in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                step = int(self.viewport().height() * 0.9)
                self._smooth_scroll_by(step if key == Qt.Key.Key_PageDown else -step)
                return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat() and self._space_down:
            self._space_down = False
            if not self._panning:
                self._restore_tool_cursor()
            return
        super().keyReleaseEvent(e)

    def focusOutEvent(self, e):
        if self._space_down:
            self._space_down = False
            self._restore_tool_cursor()
        super().focusOutEvent(e)

    def _smooth_scroll_by(self, dy: int) -> None:
        vbar = self.verticalScrollBar()
        start = vbar.value()
        if self._scroll_anim.state() == QAbstractAnimation.State.Running:
            target = int(self._scroll_anim.endValue()) + dy
        else:
            target = start + dy
        target = max(vbar.minimum(), min(vbar.maximum(), target))
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(float(start))
        self._scroll_anim.setEndValue(float(target))
        self._scroll_anim.start()

    def wheelEvent(self, e):
        mods = e.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            dy = e.angleDelta().y()
            if dy == 0:
                return
            base = self._zoom_target if self._zoom_anim.state() == QAbstractAnimation.State.Running \
                else self._zoom
            target = base * (1.0015 ** dy)
            if e.pixelDelta().isNull():
                self.animate_zoom(target, e.position())
            else:                                   # dokunmatik yüzey: doğrudan
                self.set_zoom(target, e.position())
            e.accept()
            return
        if not e.pixelDelta().isNull() or mods & Qt.KeyboardModifier.ShiftModifier:
            super().wheelEvent(e)                   # trackpad / yatay kaydırma
            return
        self._smooth_scroll_by(int(-e.angleDelta().y() / 120 * 110))
        e.accept()

    def viewportEvent(self, e):
        if e.type() == QEvent.Type.NativeGesture and \
                e.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.set_zoom(self._zoom * (1.0 + e.value()), e.position())
            return True
        return super().viewportEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._schedule_render()


# ---------------------------------------------------------------------------
# Karşılaştırma modu — bağımsız belge/sayfa seçimli, salt-okunur panel.
# Çizim araçlarına kapalıdır (iki farklı belge/sayfa aynı anda gösterildiği
# için genel çizim anlamsızlaşır) ama NUMARALANDIRMA özel olarak
# desteklenir: kullanıcı iki belge arasında karşılık gelen noktaları
# işaretleyebilsin diye.
# ---------------------------------------------------------------------------
class ComparePaneView(QGraphicsView):
    numberClicked = Signal(QPointF)

    def __init__(self, scene, state_provider: Callable[[], ToolState]):
        super().__init__(scene)
        self.state_provider = state_provider
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._panning = False
        self._pan_last = QPointF()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_last = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        state = self.state_provider()
        if state is not None and state.tool == "number" and e.button() == Qt.MouseButton.LeftButton:
            pt = self.mapToScene(e.position().toPoint())
            self.numberClicked.emit(pt)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._panning:
            delta = e.position() - self._pan_last
            self._pan_last = e.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        # Ana görünümden farklı olarak Ctrl GEREKMEZ: karşılaştırmada asıl
        # istenen davranış imlecin üstünde olduğu paneli tek başına
        # yakınlaştırmaktır.
        factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class ComparePane(QWidget):
    def __init__(self, sessions_provider: Callable[[], list], state_provider: Callable[[], ToolState],
                 number_callback: Callable[["ComparePane", QPointF], None],
                 night_mode_provider: Optional[Callable[[], bool]] = None):
        super().__init__()
        self.sessions_provider = sessions_provider
        self.night_mode_provider = night_mode_provider or (lambda: False)
        self.session = None
        self.page = 0

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)

        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._on_combo_change)
        v.addWidget(self.combo)

        self.scene = QGraphicsScene()
        self.gview = ComparePaneView(self.scene, state_provider)
        self.gview.setRenderHints(QPainter.RenderHint.Antialiasing |
                                  QPainter.RenderHint.SmoothPixmapTransform)
        self.gview.numberClicked.connect(lambda pt: number_callback(self, pt))
        v.addWidget(self.gview, 1)

        nav = QWidget()
        h = QHBoxLayout(nav)
        h.setContentsMargins(0, 0, 0, 0)
        self.btn_prev = QPushButton("◀")
        self.btn_prev.clicked.connect(lambda: self._change_page(-1))
        self.lbl = QLabel("0 / 0")
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_next = QPushButton("▶")
        self.btn_next.clicked.connect(lambda: self._change_page(1))
        self.btn_fit = QPushButton("⤢")
        self.btn_fit.setToolTip("Sayfaya sığdır (yakınlaştırmayı sıfırla)")
        self.btn_fit.clicked.connect(lambda: self._render(fit=True))
        h.addWidget(self.btn_prev)
        h.addWidget(self.lbl, 1)
        h.addWidget(self.btn_next)
        h.addWidget(self.btn_fit)
        v.addWidget(nav)

    def refresh_sessions(self):
        prev_title = self.combo.currentText()
        sessions = self.sessions_provider()
        self.combo.blockSignals(True)
        self.combo.clear()
        for s in sessions:
            self.combo.addItem(s.title)
        idx = self.combo.findText(prev_title)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        elif sessions:
            self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)
        self._on_combo_change(self.combo.currentIndex())

    def _on_combo_change(self, idx):
        sessions = self.sessions_provider()
        if 0 <= idx < len(sessions):
            self.session = sessions[idx]
            self.page = min(self.page, max(0, self.session.pdf.page_count - 1))
        else:
            self.session = None
        self._render(fit=True)

    def _change_page(self, delta):
        if not self.session:
            return
        self.page = max(0, min(self.page + delta, self.session.pdf.page_count - 1))
        self._render(fit=True)

    def _render(self, fit=False):
        current_transform = self.gview.transform()
        self.scene.clear()
        if not self.session:
            self.lbl.setText("0 / 0")
            return
        invert = self.night_mode_provider()
        pix = self.session.pdf.render_pixmap(self.page, invert=invert)
        item = self.scene.addPixmap(pix)
        w, h = self.session.pdf.page_size(self.page)
        if pix.width():
            item.setScale(w / pix.width())
        self.scene.setSceneRect(0, 0, w, h)
        for ann in self.session.annotations.get(self.page, []):
            gi = ann.create_item()
            gi.setFlags(QGraphicsItem.GraphicsItemFlag(0))   # salt okunur önizleme
            self.scene.addItem(gi)
        self.lbl.setText(f"{self.page + 1} / {self.session.pdf.page_count}")
        if fit:
            self.gview.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        else:
            self.gview.setTransform(current_transform)
