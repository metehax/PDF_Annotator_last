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

import math
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QPointF, QRectF, QThreadPool, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from gizmo import SelectionGizmo
from models import (
    Annotation, HighlightAnnotation, ImageAnnotation, InkAnnotation,
    LineAnnotation, RedactionAnnotation, ShapeAnnotation,
    ToolState, arrow_wing_points, catmull_rom_to_beziers,
)
from pdf_engine import RENDER_SCALE


# ---------------------------------------------------------------------------
# Ana çizim yüzeyi
# ---------------------------------------------------------------------------
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

    def __init__(self, state: ToolState, threadpool: Optional[QThreadPool] = None):
        super().__init__()
        self.state = state
        self.threadpool = threadpool or QThreadPool.globalInstance()
        self.scene_obj = QGraphicsScene(self)
        self.setScene(self.scene_obj)
        self.setRenderHints(QPainter.RenderHint.Antialiasing |
                            QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#2b2d31"))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        self.item_ann_map: Dict[QGraphicsItem, Annotation] = {}
        self.ann_item_map: Dict[int, QGraphicsItem] = {}
        self.page_lines: list = []

        self._session = None
        self._page_index: Optional[int] = None
        self._invert = False
        self._bg_item = None
        self._gizmo_target: Optional[Annotation] = None
        self._search_items: List[QGraphicsRectItem] = []

        self.gizmo = SelectionGizmo()
        self.scene_obj.addItem(self.gizmo)
        self.gizmo.hide()
        self.gizmo.resizeFinished.connect(self._on_gizmo_resize)
        self.scene_obj.selectionChanged.connect(self._on_selection_changed)

        self._panning = False
        self._pan_last = QPointF()
        self._drawing = False
        self._start = QPointF()
        self._temp_item = None
        self._ink_points: list = []
        self._hl_fixed_y = None
        self._line_end = QPointF()

        # PySide6, QThreadPool'a verilen (setAutoDelete=True) bir QRunnable'ın
        # PYTHON tarafındaki nesnesini de canlı tutmayı garanti etmez; hiçbir
        # yerde referansı kalmazsa çöp toplayıcı sinyal nesnesini (QObject)
        # görev hâlâ çalışırken silebilir. Bu yüzden bitene kadar burada
        # güçlü bir referans tutuyoruz.
        self._pending_render_tasks: list = []

    # =====================================================================
    # Sayfa render (LRU önbellek + asenkron)
    # =====================================================================
    def _draw_edit_boxes(self, session, page_index: int) -> None:
        """'Metin Düzenle' aracı açıkken taranmış satır/paragraf kutularını çizer."""
        if self.state.tool != "edit":
            return
        entry = session.pdf.edit_cache.get((page_index, bool(self.state.edit_force_ocr)))
        if not entry:
            return
        key = "blocks" if self.state.edit_mode == "block" else "lines"
        pen = QPen(QColor("#3aa0ff"), 0.8, Qt.PenStyle.DashLine)
        for it in entry[key]:
            x0, y0, x1, y1 = it.rect
            box = QGraphicsRectItem(QRectF(x0, y0, x1 - x0, y1 - y0))
            box.setPen(pen)
            box.setBrush(QBrush(QColor(58, 160, 255, 28)))
            box.setZValue(40)
            box.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.scene_obj.addItem(box)

    def render_page(self, session, page_index: int, invert: bool = False) -> None:
        self._session = session
        self._page_index = page_index
        self._invert = invert

        scene = self.scene_obj
        # scene.clear() seçili öğeleri de sildiği için selectionChanged
        # sinyalini tetikler; bu da _on_selection_changed() içinde henüz
        # yenisiyle değiştirilmemiş (ve C++ tarafında zaten silinmiş) eski
        # gizmo'ya erişmeye çalışıp çökmeye yol açabilir. Temizlik boyunca
        # sinyalleri geçici olarak susturuyoruz.
        scene.blockSignals(True)
        scene.clear()
        scene.blockSignals(False)
        self.item_ann_map.clear()
        self.ann_item_map.clear()
        self._search_items = []

        self.gizmo = SelectionGizmo()
        scene.addItem(self.gizmo)
        self.gizmo.hide()
        self.gizmo.resizeFinished.connect(self._on_gizmo_resize)
        self._gizmo_target = None

        if session is None:
            self._bg_item = None
            return

        w, h = session.pdf.page_size(page_index)
        scene.setSceneRect(0, 0, w, h)
        self.page_lines = session.pdf.text_lines(page_index)

        self._bg_item = scene.addPixmap(QPixmap())
        self._bg_item.setZValue(-1)

        cached = None if invert else session.pdf.get_cached_pixmap(page_index)
        if cached is not None:
            self._apply_bg_pixmap(cached, w, h)
        else:
            placeholder = QPixmap(max(1, int(w * RENDER_SCALE)), max(1, int(h * RENDER_SCALE)))
            placeholder.fill(QColor("#3a3d43"))
            self._apply_bg_pixmap(placeholder, w, h)
            self._start_async_render(session, page_index, invert)

        for ann in session.annotations.get(page_index, []):
            self._add_annotation_item(ann)
        self._draw_edit_boxes(session, page_index)

    def _apply_bg_pixmap(self, pixmap: QPixmap, w: float, h: float) -> None:
        if self._bg_item is None:
            return
        self._bg_item.setPixmap(pixmap)
        if pixmap.width():
            self._bg_item.setScale(w / pixmap.width())

    def _start_async_render(self, session, page_index: int, invert: bool) -> None:
        task = session.pdf.make_render_task(page_index, invert)
        self._pending_render_tasks.append(task)

        def _cleanup():
            if task in self._pending_render_tasks:
                self._pending_render_tasks.remove(task)

        def on_finished(idx, qimg, _session=session, _invert=invert):
            _cleanup()
            if self._session is _session and self._page_index == idx and self._invert == _invert:
                pm = QPixmap.fromImage(qimg)
                if not _invert:
                    _session.pdf.cache_pixmap(idx, pm)
                w, h = _session.pdf.page_size(idx)
                self._apply_bg_pixmap(pm, w, h)

        def on_failed(_idx, _msg):
            _cleanup()

        task.signals.finished.connect(on_finished)
        task.signals.failed.connect(on_failed)
        self.threadpool.start(task)

    def refresh_current_page(self) -> None:
        if self._session is not None and self._page_index is not None:
            self.render_page(self._session, self._page_index, self._invert)

    # =====================================================================
    # İşaret <-> Qt öğesi eşlemesi
    # =====================================================================
    def _add_annotation_item(self, ann: Annotation) -> QGraphicsItem:
        gitem = ann.create_item()
        gitem.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                       QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.scene_obj.addItem(gitem)
        self.item_ann_map[gitem] = ann
        self.ann_item_map[id(ann)] = gitem
        return gitem

    def _on_selection_changed(self) -> None:
        items = [it for it in self.scene_obj.selectedItems() if it is not self.gizmo]
        sel_ann = self.item_ann_map.get(items[0]) if len(items) == 1 else None
        if sel_ann is not None and sel_ann.is_resizable():
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
    # Arama vurguları
    # =====================================================================
    def set_search_highlights(self, rects: list, active_index: Optional[int] = None) -> None:
        for it in self._search_items:
            self.scene_obj.removeItem(it)
        self._search_items = []
        for i, r in enumerate(rects):
            qr = QRectF(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0)
            item = QGraphicsRectItem(qr)
            base = QColor("#ff9800") if i == active_index else QColor("#ffeb3b")
            fill = QColor(base)
            fill.setAlphaF(0.45)
            item.setBrush(QBrush(fill))
            item.setPen(QPen(base.darker(130), 1.5))
            item.setZValue(500)
            self.scene_obj.addItem(item)
            self._search_items.append(item)
            if i == active_index:
                self.centerOn(item)

    # =====================================================================
    # Fare etkileşimi
    # =====================================================================
    def _snap_band(self, scene_pt, force_free):
        y = scene_pt.y()
        if self.state.snap and not force_free and self.page_lines:
            best, best_d = None, 6.0
            for r in self.page_lines:
                if r.y0 - best_d <= y <= r.y1 + best_d:
                    d = abs((r.y0 + r.y1) / 2 - y)
                    if d < best_d or best is None:
                        best, best_d = r, d
            if best is not None:
                return best.y0, best.y1
        half = self.state.hl_thickness / 2
        return y - half, y + half

    def _on_context_menu(self, pos):
        item = self.itemAt(pos)
        self.contextMenuRequested.emit(item, self.mapToGlobal(pos))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_last = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        pt = self.mapToScene(e.position().toPoint())
        tool = self.state.tool

        if tool == "select":
            super().mousePressEvent(e)
            return

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
            self._temp_item = QGraphicsPathItem(path)
            pen = self._make_pen(self.state.stroke_color, self.state.pen_width, self.state.pen_opacity)
            self._temp_item.setPen(pen)
            self.scene_obj.addItem(self._temp_item)

        elif tool == "line":
            self._line_end = pt
            self._temp_item = QGraphicsPathItem(QPainterPath())
            self._temp_item.setPen(self._make_pen(self.state.stroke_color, self.state.pen_width,
                                                   self.state.pen_opacity))
            self.scene_obj.addItem(self._temp_item)

        elif tool in ("rect", "oval"):
            self._temp_item = (QGraphicsEllipseItem() if tool == "oval" else QGraphicsRectItem())
            fc = QColor(self.state.fill_color)
            fc.setAlphaF(self.state.fill_opacity)
            self._temp_item.setBrush(QBrush(fc))
            self._temp_item.setPen(QPen(self.state.stroke_color, self.state.pen_width))
            self.scene_obj.addItem(self._temp_item)

        elif tool == "redact":
            self._temp_item = QGraphicsRectItem()
            self._temp_item.setBrush(QBrush(QColor(self.state.redact_color)))
            self._temp_item.setPen(QPen(QColor("#ff4d4d"), 1.5, Qt.PenStyle.DashLine))
            self.scene_obj.addItem(self._temp_item)

        elif tool == "crop":
            self._temp_item = QGraphicsRectItem()
            fc = QColor("#3a86ff"); fc.setAlphaF(0.12)
            self._temp_item.setBrush(QBrush(fc))
            self._temp_item.setPen(QPen(QColor("#3a86ff"), 1.5, Qt.PenStyle.DashLine))
            self.scene_obj.addItem(self._temp_item)

        elif tool == "image":
            self._temp_item = QGraphicsRectItem()
            fc = QColor("#2ec4b6"); fc.setAlphaF(0.12)
            self._temp_item.setBrush(QBrush(fc))
            self._temp_item.setPen(QPen(QColor("#2ec4b6"), 1.5, Qt.PenStyle.DashLine))
            self.scene_obj.addItem(self._temp_item)

        elif tool == "highlight":
            force_free = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._hl_fixed_y = self._snap_band(pt, force_free)
            self._temp_item = QGraphicsRectItem()
            c = QColor(self.state.hl_color)
            c.setAlphaF(self.state.fill_opacity)
            self._temp_item.setBrush(QBrush(c))
            self._temp_item.setPen(QPen(Qt.PenStyle.NoPen))
            self.scene_obj.addItem(self._temp_item)

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

        if not self._drawing:
            super().mouseMoveEvent(e)
            return

        pt = self.mapToScene(e.position().toPoint())
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
        if e.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        if not self._drawing:
            super().mouseReleaseEvent(e)
            if self.state.tool == "select":
                self.itemsMoved.emit()
            return

        self._drawing = False
        pt = self.mapToScene(e.position().toPoint())
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
            self.scene_obj.removeItem(self._temp_item)
            self._temp_item = None

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
        else:
            super().wheelEvent(e)


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
