"""
main_window.py
===============
Ana pencere: üst araç çubuğu, sekmeli çoklu belge yönetimi (QTabBar),
kenetlenebilir paneller (QDockWidget — sol: Küçük Resimler/İçindekiler/Ara,
sağ: Özellikler/Katmanlar), alt yakınlaştırma/durum çubuğu, QUndoStack /
QUndoGroup entegrasyonu, filigran & resim ekleme diyalogları.

Bu dosya tüm parçaları birbirine bağlar; iş mantığının çoğu models.py ve
pdf_engine.py'de yaşar, views.py ise canvas etkileşimlerini yönetir.
"""

from __future__ import annotations

import copy
import os
from typing import Dict, List, Optional, Tuple

import pymupdf as fitz

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import (
    QAction, QColor, QDesktopServices, QFont, QIcon, QImage, QKeySequence, QPixmap,
    QUndoGroup,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDialogButtonBox, QDockWidget, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox,
    QSplitter, QStackedWidget, QTabBar, QTabWidget, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from models import (
    AddAnnotationCommand, DocumentSession, HighlightAnnotation,
    ImageAnnotation, InkAnnotation, LineAnnotation, MoveAnnotationCommand,
    NumberAnnotation, RedactionAnnotation, RemoveAnnotationCommand,
    ResizeAnnotationCommand, ShapeAnnotation, TextAnnotation, ToolState,
    WatermarkConfig, ZOrderCommand, number_to_color,
)
from pdf_engine import (
    IMAGE_EXTS, PDFDocument, image_to_pdf_document, is_image_path,
    load_image_bytes_from_path, qimage_to_png_bytes,
    resolve_font_ctx, save_project_json, load_project_json,
)
from views import ComparePane, PDFView
import ocr
from fonts import DEFAULT_FAMILY, FONT_FAMILIES, register_app_fonts

_IMG_PATTERNS = " ".join("*" + e for e in IMAGE_EXTS)
OPEN_FILTER = (f"PDF ve Resimler (*.pdf {_IMG_PATTERNS});;PDF (*.pdf);;"
               f"Resimler ({_IMG_PATTERNS})")

TOOLS = [
    ("select", "Seç", "🖱"),
    ("text", "Metin", "🅣"),
    ("edit", "Metin Düzenle", "✏"),
    ("ink", "Kalem", "✎"),
    ("line", "Çizgi / Ok", "↗"),
    ("rect", "Dörtgen", "▭"),
    ("oval", "Oval", "◯"),
    ("highlight", "Fosforlu", "🖍"),
    ("redact", "Gizle (Sansür)", "⬛"),
    ("image", "Resim", "🖼"),
    ("number", "Numarala", "🔢"),
    ("crop", "Kırp / Yakala", "⛶"),
]


# ---------------------------------------------------------------------------
# Metin ekleme diyaloğu (yazı + font + renk + punto, canlı önizleme)
# ---------------------------------------------------------------------------
def ocr_text_width(text: str, family: str, size: float) -> float:
    """Çok satırlı metnin en geniş satırının genişliği (punto)."""
    from fonts import resolve_font_file
    path = resolve_font_file(family)
    try:
        font = fitz.Font(fontfile=path) if path else fitz.Font("helv")
        return max(font.text_length(l, fontsize=size) for l in text.split("\n"))
    except Exception:
        return len(text) * size * 0.55


class TextDialog(QDialog):
    def __init__(self, family: str, size: float, color: QColor, parent=None,
                 text: str = "", title: str = "Metin Ekle", info: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self._color = QColor(color)

        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.font_combo = QComboBox()
        for fam in FONT_FAMILIES:
            self.font_combo.addItem(fam)
        idx = self.font_combo.findText(family)
        self.font_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Yazı tipi:", self.font_combo)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(4, 300)
        self.size_spin.setValue(int(size))
        form.addRow("Punto:", self.size_spin)

        self.color_btn = QPushButton()
        self.color_btn.setFixedHeight(26)
        self.color_btn.clicked.connect(self._pick_color)
        form.addRow("Renk:", self.color_btn)
        lay.addLayout(form)

        if info:
            info_lbl = QLabel(info)
            info_lbl.setWordWrap(True)
            info_lbl.setObjectName("hint")
            lay.addWidget(info_lbl)
        lay.addWidget(QLabel("Yazı:"))
        self.edit = QPlainTextEdit()
        self.edit.setPlainText(text)
        self.edit.setMinimumHeight(110)
        lay.addWidget(self.edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.font_combo.currentTextChanged.connect(self._refresh_preview)
        self.size_spin.valueChanged.connect(self._refresh_preview)
        self._refresh_preview()

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "Yazı rengi")
        if c.isValid():
            self._color = c
            self._refresh_preview()

    def _refresh_preview(self, *_):
        self.color_btn.setStyleSheet(f"background:{self._color.name()};")
        f = QFont(self.font_combo.currentText())
        f.setPointSize(min(28, max(8, self.size_spin.value())))
        self.edit.setFont(f)
        self.edit.setStyleSheet(f"color:{self._color.name()};")

    def result_values(self):
        return (self.edit.toPlainText(), self.font_combo.currentText(),
                float(self.size_spin.value()), QColor(self._color))


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
        self.btn_run = QPushButton("🔍 Metni Oku")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self._run_text)
        self.btn_pdf = QPushButton("📄 Aranabilir PDF Kaydet…")
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
        self.btn_copy = QPushButton("📋 Kopyala")
        self.btn_copy.clicked.connect(self._copy)
        self.btn_txt = QPushButton("💾 TXT Kaydet…")
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
                QMessageBox.information(self, "Tamam", f"Aranabilir PDF kaydedildi:\n{path}")
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



# ---------------------------------------------------------------------------
# Filigran diyaloğu
# ---------------------------------------------------------------------------
class WatermarkDialog(QDialog):
    def __init__(self, initial: WatermarkConfig, page_count: int, current_page: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filigran Ekle")
        self.setMinimumWidth(380)
        self._cfg = copy.deepcopy(initial)
        self._page_count = page_count
        self._current_page = current_page

        form = QFormLayout(self)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Metin", "Resim"])
        self.mode_combo.setCurrentIndex(0 if self._cfg.mode == "text" else 1)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        form.addRow("Tür:", self.mode_combo)

        self.text_edit = QLineEdit(self._cfg.text)
        form.addRow("Metin:", self.text_edit)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 300)
        self.font_size_spin.setValue(int(self._cfg.font_size))
        form.addRow("Punto:", self.font_size_spin)

        self.color_btn = QPushButton()
        self.color_btn.setFixedHeight(26)
        self._set_color_btn(self._cfg.color)
        self.color_btn.clicked.connect(self._pick_color)
        form.addRow("Renk:", self.color_btn)

        self.image_btn = QPushButton("🖼 Görsel Seç…")
        self.image_btn.clicked.connect(self._pick_image)
        self.image_preview = QLabel("(seçilmedi)")
        self.image_preview.setFixedHeight(60)
        form.addRow("Görsel:", self.image_btn)
        form.addRow("", self.image_preview)
        self._image_bytes = self._cfg.image_bytes

        self.image_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.image_scale_slider.setRange(2, 100)
        self.image_scale_slider.setValue(int(self._cfg.image_scale * 100))
        form.addRow("Görsel Ölçek (%):", self.image_scale_slider)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(2, 100)
        self.opacity_slider.setValue(int(self._cfg.opacity * 100))
        form.addRow("Saydamlık (%):", self.opacity_slider)

        self.rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self.rotation_slider.setRange(-90, 90)
        self.rotation_slider.setValue(int(self._cfg.rotation))
        self.rotation_lbl = QLabel(f"{self._cfg.rotation:.0f}°")
        self.rotation_slider.valueChanged.connect(
            lambda v: self.rotation_lbl.setText(f"{v}°"))
        rot_row = QWidget(); rl = QHBoxLayout(rot_row); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.rotation_slider, 1); rl.addWidget(self.rotation_lbl)
        form.addRow("Döndürme (-90° / +90°):", rot_row)

        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["Tekli (Ortada)", "Döşenmiş (Tüm Sayfa)"])
        self.layout_combo.setCurrentIndex(0 if self._cfg.layout == "single" else 1)
        form.addRow("Yerleşim:", self.layout_combo)

        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["Aktif Sayfa", "Sayfa Aralığı", "Tüm Belge"])
        self.scope_combo.setCurrentIndex({"current": 0, "range": 1, "all": 2}[self._cfg.scope])
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        form.addRow("Kapsam:", self.scope_combo)

        self.range_row = QWidget()
        rr = QHBoxLayout(self.range_row); rr.setContentsMargins(0, 0, 0, 0)
        self.start_spin = QSpinBox(); self.start_spin.setRange(1, max(1, page_count))
        self.start_spin.setValue(self._cfg.page_start)
        self.end_spin = QSpinBox(); self.end_spin.setRange(1, max(1, page_count))
        self.end_spin.setValue(self._cfg.page_end if self._cfg.page_end else page_count)
        rr.addWidget(QLabel("Başlangıç:")); rr.addWidget(self.start_spin)
        rr.addWidget(QLabel("Bitiş:")); rr.addWidget(self.end_spin)
        form.addRow("", self.range_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._on_mode_changed(self.mode_combo.currentIndex())
        self._on_scope_changed(self.scope_combo.currentIndex())

    def _set_color_btn(self, color: QColor):
        self.color_btn.setStyleSheet(f"background:{color.name()};")
        self._color = QColor(color)

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "Filigran rengi")
        if c.isValid():
            self._set_color_btn(c)

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Filigran Görseli Seç", "",
                                              "Görseller (*.png *.jpg *.jpeg *.bmp *.svg)")
        if not path:
            return
        try:
            self._image_bytes = load_image_bytes_from_path(path)
            pm = QPixmap.fromImage(QImage.fromData(self._image_bytes))
            self.image_preview.setPixmap(pm.scaledToHeight(56, Qt.TransformationMode.SmoothTransformation))
        except Exception as ex:
            QMessageBox.warning(self, "Uyarı", f"Görsel yüklenemedi:\n{ex}")

    def _on_mode_changed(self, idx):
        is_text = idx == 0
        self.text_edit.setEnabled(is_text)
        self.font_size_spin.setEnabled(is_text)
        self.color_btn.setEnabled(is_text)
        self.image_btn.setEnabled(not is_text)
        self.image_scale_slider.setEnabled(not is_text)

    def _on_scope_changed(self, idx):
        self.range_row.setVisible(idx == 1)

    def get_config(self) -> WatermarkConfig:
        mode = "text" if self.mode_combo.currentIndex() == 0 else "image"
        scope = ["current", "range", "all"][self.scope_combo.currentIndex()]
        layout = "single" if self.layout_combo.currentIndex() == 0 else "tiled"
        return WatermarkConfig(
            mode=mode, text=self.text_edit.text(), font_size=float(self.font_size_spin.value()),
            color=QColor(self._color), opacity=self.opacity_slider.value() / 100.0,
            rotation=float(self.rotation_slider.value()), image_bytes=self._image_bytes,
            image_scale=self.image_scale_slider.value() / 100.0, layout=layout,
            tile_spacing=1.6, scope=scope, page_start=self.start_spin.value(),
            page_end=self.end_spin.value(),
        )


# ---------------------------------------------------------------------------
# Ana pencere
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF İşaretleme Aracı — Profesyonel")
        self.resize(1560, 940)
        self.setMinimumWidth(680)

        self.state = ToolState()
        self.threadpool = QThreadPool.globalInstance()
        self.sessions: List[DocumentSession] = []
        self.active_session: Optional[DocumentSession] = None
        self.font_ctx = resolve_font_ctx()
        self._edit_task: Optional[_OcrTask] = None
        self._lang_warned = False
        self.undo_group = QUndoGroup(self)
        self.night_mode = False
        self.dark_mode = True

        self._color_buttons_by_attr: Dict[str, list] = {}
        self._tool_buttons = []
        self._tool_pages: Dict[str, int] = {}
        self._zoom = 1.0

        # Karşılaştırma "Eşleştir modu" durumu
        self._pair_counter = 1
        self._pair_pending = None   # None ya da (pane, numara, renk)

        # Arama durumu
        self._search_results: Dict[int, list] = {}
        self._search_flat: List[Tuple[int, int]] = []   # (sayfa, o sayfadaki-indeks)
        self._search_pos = -1
        self._pending_search_tasks = []

        self._build_ui()
        self._apply_style()
        self._set_ui_enabled(False)
        self._select_tool("select", self.btn_select)

    # =====================================================================
    # UI kurulumu
    # =====================================================================
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top_bar = self._build_top_bar()
        tb_scroll = QScrollArea()
        tb_scroll.setWidget(top_bar)
        tb_scroll.setWidgetResizable(True)
        tb_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        tb_scroll.setFixedHeight(top_bar.sizeHint().height() + 14)
        root.addWidget(tb_scroll)

        self.doc_tabbar = QTabBar()
        self.doc_tabbar.setTabsClosable(True)
        self.doc_tabbar.setExpanding(False)
        self.doc_tabbar.setMovable(True)
        self.doc_tabbar.setObjectName("doctabs")
        self.doc_tabbar.currentChanged.connect(self._on_tab_changed)
        self.doc_tabbar.tabCloseRequested.connect(self.close_session)
        self.doc_tabbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doc_tabbar.customContextMenuRequested.connect(self._on_doctab_context_menu)
        root.addWidget(self.doc_tabbar)

        body = QHBoxLayout()
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(8)
        body.addWidget(self._build_tool_column())
        body.addWidget(self._build_canvas_stack(), 1)
        body_wrap = QWidget()
        body_wrap.setLayout(body)
        root.addWidget(body_wrap, 1)

        root.addWidget(self._build_bottom_bar())

        self.status = QLabel("PDF açmak için 'Aç' düğmesine tıklayın.")
        self.status.setObjectName("status")
        self.status.setContentsMargins(12, 6, 12, 6)
        root.addWidget(self.status)

        self.setCentralWidget(central)

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._build_left_dock())
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._build_right_dock())

        self._build_shortcuts()

    # -- ortak küçük yapı taşları ------------------------------------------
    def _framed(self, widget, title):
        frame = QFrame()
        frame.setObjectName("sectionFrame")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        cap = QLabel(title)
        cap.setObjectName("sectionTitle")
        lay.addWidget(cap)
        lay.addWidget(widget, 1)
        return frame

    def _toolbar_group(self, title, widgets):
        frame = QFrame()
        frame.setObjectName("tbGroup")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(8, 4, 8, 6)
        outer.setSpacing(3)
        cap = QLabel(title)
        cap.setObjectName("tbGroupTitle")
        outer.addWidget(cap)
        row = QHBoxLayout()
        row.setSpacing(6)
        for w in widgets:
            row.addWidget(w)
        outer.addLayout(row)
        return frame

    def _slider_row(self, label, lo, hi, val, setter, suffix=""):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setFixedWidth(84)
        h.addWidget(lbl)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setMinimum(lo); s.setMaximum(hi); s.setValue(val)
        h.addWidget(s, 1)
        val_lbl = QLabel(f"{val}{suffix}")
        val_lbl.setFixedWidth(36)
        h.addWidget(val_lbl)

        def on_change(v):
            setter(v)
            val_lbl.setText(f"{v}{suffix}")

        s.valueChanged.connect(on_change)
        return row

    def _spin_row(self, label, spin):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setFixedWidth(84)
        h.addWidget(lbl)
        h.addWidget(spin, 1)
        return row

    def _combo_row(self, label, items, on_change):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setFixedWidth(84)
        h.addWidget(lbl)
        combo = QComboBox()
        for text, data in items:
            combo.addItem(text, data)
        combo.currentIndexChanged.connect(lambda _i: on_change(combo.currentData()))
        h.addWidget(combo, 1)
        return row

    def _set_edit_mode(self, mode):
        self.state.edit_mode = mode
        self._refresh_current_page()

    def _refresh_current_page(self):
        s = self.active_session
        if s:
            self.view.render_page(s, s.current_page, invert=self.night_mode)

    def _font_row(self):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Yazı tipi")
        lbl.setFixedWidth(84)
        h.addWidget(lbl)
        combo = QComboBox()
        for fam in FONT_FAMILIES:
            combo.addItem(fam)
        combo.setCurrentText(self.state.font_family)
        combo.currentTextChanged.connect(lambda t: setattr(self.state, "font_family", t))
        h.addWidget(combo, 1)
        self.font_combo_panel = combo
        return row

    def _color_row(self, label, attr):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setFixedWidth(84)
        h.addWidget(lbl)
        btn = QPushButton()
        btn.setObjectName("colorbtn")
        btn.setFixedHeight(26)
        color = getattr(self.state, attr)
        btn.setStyleSheet(f"background:{color.name()};")
        btn.clicked.connect(lambda: self._pick_color(attr))
        h.addWidget(btn, 1)
        self._color_buttons_by_attr.setdefault(attr, []).append(btn)
        return row

    def _checkbox_row(self, label, attr, tooltip=""):
        chk = QCheckBox(label)
        chk.setChecked(bool(getattr(self.state, attr)))
        if tooltip:
            chk.setToolTip(tooltip)
        chk.toggled.connect(lambda v: setattr(self.state, attr, v))
        return chk

    def _hint(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setObjectName("hint")
        return lbl

    # -- üst çubuk ----------------------------------------------------------
    def _build_top_bar(self):
        bar = QWidget()
        bar.setObjectName("toolbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(0)

        self.btn_open = QPushButton("📂 Aç")
        self.btn_open.setObjectName("primary")
        self.btn_open.clicked.connect(self.open_pdf)

        self.btn_merge = QPushButton("🔗 Birleştir")
        self.btn_merge.clicked.connect(self.merge_pdfs)

        self.btn_split = QToolButton()
        self.btn_split.setText("✂ Ayır")
        self.btn_split.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        split_menu = QMenu(self.btn_split)
        split_menu.addAction("🗂 Her sayfayı ayrı PDF yap (klasöre)", self.split_all_pages)
        split_menu.addAction("✂ Sayfa aralığını yeni PDF olarak çıkar…", self.extract_page_range)
        self.btn_split.setMenu(split_menu)

        self.btn_export = QToolButton()
        self.btn_export.setText("⇩ Dışa Aktar")
        self.btn_export.setObjectName("primary")
        self.btn_export.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        export_menu = QMenu(self.btn_export)
        export_menu.addAction("📄 PDF olarak kaydet", self.save_pdf)
        export_menu.addAction("🖼 Resim olarak kaydet (orijinal çözünürlük)", self.save_as_image)
        export_menu.addAction("🖥 Filigranlı PDF olarak kaydet…", self.save_pdf_with_watermark)
        export_menu.addSeparator()
        export_menu.addAction("🖼 Bu sayfayı PNG", lambda: self.export_image_current("png"))
        export_menu.addAction("🖼 Bu sayfayı JPEG", lambda: self.export_image_current("jpg"))
        export_menu.addAction("🗂 Tüm sayfaları PNG (klasöre)", lambda: self.export_all_pages_images("png"))
        export_menu.addSeparator()
        export_menu.addAction("💾 Proje Kaydet (JSON)", self.save_project)
        export_menu.addAction("📁 Proje Aç (JSON)", self.open_project)
        self.btn_export.setMenu(export_menu)

        lay.addWidget(self._toolbar_group(
            "DOSYA", [self.btn_open, self.btn_merge, self.btn_split, self.btn_export]))

        self.act_undo = self.undo_group.createUndoAction(self, "Geri Al")
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_redo = self.undo_group.createRedoAction(self, "Yinele")
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.btn_undo = QPushButton("↶ Geri")
        self.btn_undo.clicked.connect(self.act_undo.trigger)
        self.btn_undo.setEnabled(False)
        self.btn_redo = QPushButton("↷ Yinele")
        self.btn_redo.clicked.connect(self.act_redo.trigger)
        self.btn_redo.setEnabled(False)
        self.undo_group.canUndoChanged.connect(self.btn_undo.setEnabled)
        self.undo_group.canRedoChanged.connect(self.btn_redo.setEnabled)
        self.addAction(self.act_undo)
        self.addAction(self.act_redo)
        lay.addWidget(self._toolbar_group("DÜZENLE", [self.btn_undo, self.btn_redo]))

        self.btn_watermark = QPushButton("🖥 Filigran")
        self.btn_watermark.setToolTip("Filigran ekleyip yeni bir PDF olarak kaydet")
        self.btn_watermark.clicked.connect(self.save_pdf_with_watermark)
        lay.addWidget(self._toolbar_group("FİLİGRAN", [self.btn_watermark]))

        self.btn_ocr = QPushButton("🔍 OCR")
        self.btn_ocr.setToolTip("Sayfadaki metni OCR ile oku / aranabilir PDF üret")
        self.btn_ocr.clicked.connect(self.open_ocr_dialog)
        lay.addWidget(self._toolbar_group("OCR", [self.btn_ocr]))

        self.btn_theme = QPushButton("☀ Açık Tema")
        self.btn_theme.clicked.connect(self.toggle_theme)
        self.btn_night = QPushButton("🌙 Gece Modu")
        self.btn_night.setCheckable(True)
        self.btn_night.setToolTip("PDF piksellerini ters çevirerek gece okumasını kolaylaştırır")
        self.btn_night.toggled.connect(self.toggle_night_mode)
        self.btn_compare = QPushButton("⚏ Karşılaştır")
        self.btn_compare.setCheckable(True)
        self.btn_compare.toggled.connect(self.toggle_compare_mode)
        lay.addWidget(self._toolbar_group("GÖRÜNÜM", [self.btn_theme, self.btn_night, self.btn_compare]))

        lay.addStretch(1)
        return bar

    # -- sol: dikey araç sütunu ----------------------------------------------
    def _build_tool_column(self):
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        for key, label, icon in TOOLS:
            btn = QToolButton()
            btn.setText(f"{icon}\n{label}")
            btn.setCheckable(True)
            btn.setObjectName("toolbtn")
            btn.setMinimumHeight(52)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _, k=key, b=btn: self._select_tool(k, b))
            self._tool_buttons.append((key, btn))
            v.addWidget(btn)
        v.addStretch(1)
        frame = self._framed(col, "ARAÇLAR")
        frame.setFixedWidth(96)
        self.btn_select = dict(self._tool_buttons)["select"]
        return frame

    # -- orta: normal görünüm / karşılaştırma ---------------------------------
    def _build_canvas_stack(self):
        self.view = PDFView(self.state, self.threadpool)
        self.view.annotationCreated.connect(self.add_annotation)
        self.view.textRequested.connect(self.on_text_requested)
        self.view.numberRequested.connect(self.on_number_requested)
        self.view.editTextRequested.connect(self.on_edit_text_requested)
        self.view.cropRequested.connect(self.on_crop_requested)
        self.view.imagePlaceRequested.connect(self.on_image_place_requested)
        self.view.itemsMoved.connect(self.sync_moved_items)
        self.view.resizeRequested.connect(self.on_resize_requested)
        self.view.contextMenuRequested.connect(self.show_item_context_menu)
        normal_frame = self._framed(self.view, "SAYFA")

        self.pane_left = ComparePane(lambda: self.sessions, lambda: self.state,
                                     self.on_number_requested_in_pane,
                                     night_mode_provider=lambda: self.night_mode)
        self.pane_right = ComparePane(lambda: self.sessions, lambda: self.state,
                                      self.on_number_requested_in_pane,
                                      night_mode_provider=lambda: self.night_mode)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.pane_left)
        splitter.addWidget(self.pane_right)
        compare_frame = self._framed(splitter, "KARŞILAŞTIRMA (salt okunur)")

        self.canvas_stack = QStackedWidget()
        self.canvas_stack.addWidget(normal_frame)     # index 0
        self.canvas_stack.addWidget(compare_frame)    # index 1
        return self.canvas_stack

    # -- alt: yakınlaştırma / görünüm çubuğu ----------------------------------
    def _build_bottom_bar(self):
        bar = QWidget()
        bar.setObjectName("bottombar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 4, 10, 4)
        h.setSpacing(8)

        self.btn_prev = QPushButton("◀")
        self.btn_prev.clicked.connect(lambda: self.goto_page(self.active_session.current_page - 1)
                                      if self.active_session else None)
        self.lbl_page = QLabel("0 / 0")
        self.lbl_page.setObjectName("pagelbl")
        self.btn_next = QPushButton("▶")
        self.btn_next.clicked.connect(lambda: self.goto_page(self.active_session.current_page + 1)
                                      if self.active_session else None)
        h.addWidget(self.btn_prev); h.addWidget(self.lbl_page); h.addWidget(self.btn_next)

        h.addWidget(self._vsep())

        self.btn_rot_ccw = QPushButton("↺ 90°")
        self.btn_rot_ccw.setToolTip("Sayfayı saatin tersine döndür")
        self.btn_rot_ccw.clicked.connect(lambda: self._rotate_current_page(-90))
        self.btn_rot_cw = QPushButton("↻ 90°")
        self.btn_rot_cw.setToolTip("Sayfayı saat yönünde döndür")
        self.btn_rot_cw.clicked.connect(lambda: self._rotate_current_page(90))
        h.addWidget(self.btn_rot_ccw); h.addWidget(self.btn_rot_cw)

        h.addWidget(self._vsep())

        self.btn_add_page = QPushButton("+ Sayfa")
        self.btn_add_page.setToolTip("Aktif sayfadan sonra boş sayfa ekler")
        self.btn_add_page.clicked.connect(
            lambda: self._insert_blank_page(self.active_session.current_page + 1)
            if self.active_session else None)
        h.addWidget(self.btn_add_page)

        h.addStretch(1)

        self.btn_fit_width = QPushButton("↔ Genişliğe Sığdır")
        self.btn_fit_width.clicked.connect(self.fit_width)
        self.btn_fit_page = QPushButton("⤢ Tam Sayfa")
        self.btn_fit_page.clicked.connect(self.fit_page)
        h.addWidget(self.btn_fit_width); h.addWidget(self.btn_fit_page)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 400)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(160)
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider_changed)
        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setFixedWidth(46)
        h.addWidget(self.zoom_slider); h.addWidget(self.lbl_zoom)

        return bar

    def _vsep(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setObjectName("sep")
        return line

    # -- sol dock: Küçük Resimler / İçindekiler / Ara --------------------------
    def _build_left_dock(self):
        dock = QDockWidget("Belge Paneli", self)
        dock.setObjectName("leftDock")
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                         QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        tabs = QTabWidget()

        self.thumb_list = QListWidget()
        self.thumb_list.setIconSize(QSize(120, 156))
        self.thumb_list.setSpacing(8)
        self.thumb_list.currentRowChanged.connect(self._on_thumb_selected)
        self.thumb_list.setObjectName("thumbs")
        self.thumb_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumb_list.customContextMenuRequested.connect(self._on_thumb_context_menu)
        tabs.addTab(self.thumb_list, "Küçük Resimler")

        self.toc_tree = QTreeWidget()
        self.toc_tree.setHeaderHidden(True)
        self.toc_tree.itemClicked.connect(self._on_toc_item_clicked)
        tabs.addTab(self.toc_tree, "İçindekiler")

        search_widget = QWidget()
        sv = QVBoxLayout(search_widget)
        sv.setContentsMargins(6, 6, 6, 6)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Belgede ara… (Enter)")
        self.search_edit.returnPressed.connect(self.run_search)
        sv.addWidget(self.search_edit)
        srow = QHBoxLayout()
        self.btn_search = QPushButton("🔍 Bul")
        self.btn_search.clicked.connect(self.run_search)
        self.btn_search_prev = QPushButton("◀")
        self.btn_search_prev.clicked.connect(self.goto_prev_search_hit)
        self.btn_search_next = QPushButton("▶")
        self.btn_search_next.clicked.connect(self.goto_next_search_hit)
        srow.addWidget(self.btn_search); srow.addWidget(self.btn_search_prev); srow.addWidget(self.btn_search_next)
        sv.addLayout(srow)
        self.search_results_list = QListWidget()
        self.search_results_list.itemClicked.connect(self._on_search_result_clicked)
        sv.addWidget(self.search_results_list, 1)
        self.lbl_search_status = QLabel("")
        self.lbl_search_status.setObjectName("hint")
        sv.addWidget(self.lbl_search_status)
        tabs.addTab(search_widget, "Ara")
        self.search_tab_index = tabs.indexOf(search_widget)

        self.left_tabs = tabs
        dock.setWidget(tabs)
        dock.setMinimumWidth(230)
        return dock

    # -- sağ dock: Özellikler / Katmanlar --------------------------------------
    def _build_right_dock(self):
        dock = QDockWidget("Özellikler", self)
        dock.setObjectName("rightDock")
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                         QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        tabs = QTabWidget()
        tabs.addTab(self._build_properties_stack(), "Özellikler")
        tabs.addTab(self._build_layers_tab(), "Katmanlar")
        self.side_tabs = tabs
        dock.setWidget(tabs)
        dock.setMinimumWidth(230)
        return dock

    def _build_properties_stack(self):
        self.prop_stack = QStackedWidget()

        def page(*rows):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(10, 10, 10, 10)
            v.setSpacing(10)
            for r in rows:
                v.addWidget(r)
            v.addStretch(1)
            return w

        idx = 0
        self.prop_stack.addWidget(page(
            self._hint("Ögeyi sürükleyerek taşıyabilirsiniz. Seçince "
                      "çıkan 8 kulptan yeniden boyutlandırabilirsiniz.\n"
                      "Silmek için Del tuşuna basın ya da üzerinde sağ tıklayın."),
        ))
        self._tool_pages["select"] = idx; idx += 1

        self.prop_stack.addWidget(page(
            self._font_row(),
            self._color_row("Renk", "text_color"),
            self._slider_row("Punto", 8, 96, int(self.state.font_size),
                             lambda v: setattr(self.state, "font_size", float(v))),
            self._hint("Sayfada bir noktaya tıklayın; açılan pencerede yazıyı, "
                      "yazı tipini, rengi ve puntoyu ayarlayın. Kutunun boyutunu "
                      "sonradan kulplarla değiştirebilirsiniz."),
        ))
        self._tool_pages["text"] = idx; idx += 1

        self.prop_stack.addWidget(page(
            self._combo_row("Seçim", [("Satır", "line"), ("Paragraf", "block")],
                            lambda v: self._set_edit_mode(v)),
            self._checkbox_row("Taranmış sayfa (OCR kullan)", "edit_force_ocr",
                               "Sayfada gerçek metin olsa bile OCR ile okur"),
            self._hint("Sayfadaki mavi kutulardan birine tıklayın: metin açılan pencerede "
                      "düzenlenir. Eski metin silinir, yerine yenisi yazılır. Sayfada gerçek "
                      "metin varsa doğrudan o okunur (font, punto ve renk dahil); taranmış "
                      "(resim) sayfalarda OCR otomatik devreye girer (Türkçe + İngilizce)."),
        ))
        self._tool_pages["edit"] = idx; idx += 1

        self.prop_stack.addWidget(page(
            self._color_row("Renk", "stroke_color"),
            self._slider_row("Kalınlık", 1, 30, int(self.state.pen_width),
                             lambda v: setattr(self.state, "pen_width", float(v))),
            self._slider_row("Opaklık", 10, 100, int(self.state.pen_opacity * 100),
                             lambda v: setattr(self.state, "pen_opacity", v / 100.0), "%"),
            self._hint("Çizgi otomatik olarak yumuşatılır (Bézier)."),
        ))
        self._tool_pages["ink"] = idx; idx += 1

        self.prop_stack.addWidget(page(
            self._color_row("Renk", "stroke_color"),
            self._slider_row("Kalınlık", 1, 20, int(self.state.pen_width),
                             lambda v: setattr(self.state, "pen_width", float(v))),
            self._slider_row("Opaklık", 10, 100, int(self.state.pen_opacity * 100),
                             lambda v: setattr(self.state, "pen_opacity", v / 100.0), "%"),
            self._checkbox_row("Ok ucu", "line_arrow"),
            self._hint("Shift: 45° açı kilidi."),
        ))
        self._tool_pages["line"] = idx; idx += 1

        shape_page = page(
            self._color_row("Dolgu", "fill_color"),
            self._color_row("Kenar", "stroke_color"),
            self._slider_row("Kenar Kal.", 0, 15, int(self.state.pen_width),
                             lambda v: setattr(self.state, "pen_width", float(v))),
            self._slider_row("Dolgu Opk.", 5, 100, int(self.state.fill_opacity * 100),
                             lambda v: setattr(self.state, "fill_opacity", v / 100.0), "%"),
            self._hint("⚠ Sadece görsel bir katmandır; altındaki metin "
                      "silinmez. Kalıcı gizleme için 'Gizle (Sansür)' aracını kullanın."),
        )
        self.prop_stack.addWidget(shape_page)
        self._tool_pages["rect"] = idx
        self._tool_pages["oval"] = idx
        idx += 1

        self.prop_stack.addWidget(page(
            self._color_row("Renk", "hl_color"),
            self._slider_row("Bant Kal.", 4, 40, int(self.state.hl_thickness),
                             lambda v: setattr(self.state, "hl_thickness", float(v))),
            self._slider_row("Opaklık", 10, 100, int(self.state.fill_opacity * 100),
                             lambda v: setattr(self.state, "fill_opacity", v / 100.0), "%"),
            self._checkbox_row("Satıra yapış", "snap"),
            self._hint("Satır yoksa bant Bant-Kalınlığı ile yatay kilitlenir. "
                      "Shift: yapışmayı geçici kapatır.\n\n⚠ Bu da sadece görseldir."),
        ))
        self._tool_pages["highlight"] = idx; idx += 1

        self.prop_stack.addWidget(page(
            self._color_row("Kutu Rengi", "redact_color"),
            self._hint("🔒 Dışa aktarırken kutunun altındaki metin/görsel "
                      "PDF'ten KALICI olarak silinir. Kırmızı kesikli çerçeve "
                      "ile gösterilir. Dikkatli çizin."),
        ))
        self._tool_pages["redact"] = idx; idx += 1

        self.prop_stack.addWidget(page(
            self._slider_row("Opaklık", 5, 100, int(self.state.image_opacity * 100),
                             lambda v: setattr(self.state, "image_opacity", v / 100.0), "%"),
            self._checkbox_row("En-boy oranını koru", "image_keep_aspect"),
            self._hint("Sayfada bir dikdörtgen çizerek resmin yerleştirileceği "
                      "alanı belirleyin; ardından dosya/pano seçim penceresi açılır.\n\n"
                      "Yeniden boyutlandırırken: varsayılan oran KORUNUR, "
                      "Shift basılıyken SERBEST olur."),
        ))
        self._tool_pages["image"] = idx; idx += 1

        start_spin = QSpinBox()
        start_spin.setRange(1, 9999)
        start_spin.setValue(int(self.state.number_start))
        start_spin.valueChanged.connect(self._on_number_start_changed)
        self.lbl_next_number = QLabel("Sıradaki: 1")
        self.lbl_next_number.setObjectName("nextNumber")
        reset_btn = QPushButton("🔁 Sayacı Sıfırla")
        reset_btn.clicked.connect(self.reset_number_counter)

        self.chk_pair = QCheckBox("Eşleştir modu (karşılaştırmada)")
        self.chk_pair.setToolTip("Açıkken: bir panele koyduğun numarayı diğer "
                                 "panele de aynı numara/renkle koyabilirsin.")
        self.chk_pair.toggled.connect(self._on_pair_toggled)
        reset_pair_btn = QPushButton("🔁 Eşleştirme Sayacını Sıfırla")
        reset_pair_btn.clicked.connect(self.reset_pair_counter)

        self.prop_stack.addWidget(page(
            self._spin_row("Başlangıç", start_spin),
            self._slider_row("Punto", 8, 60, int(self.state.number_size),
                             lambda v: setattr(self.state, "number_size", float(v))),
            self._color_row("Renk", "number_color"),
            self._checkbox_row("Her numarada farklı renk", "number_multicolor"),
            self.lbl_next_number,
            reset_btn,
            self._hint("Sayfaya tıkladıkça sıradaki numara yerleştirilir ve "
                      "sayaç otomatik artar. 'Her numarada farklı renk' açıkken "
                      "her sayı HER ZAMAN aynı rengi alır (altın açı)."),
            self.chk_pair,
            reset_pair_btn,
            self._hint("Eşleştir modu — İKİ PDF karşılaştırırken:\n"
                      "1) Bir panele numara koy.\n2) Diğer panele koy → aynı numara/renk.\n"
                      "3) Sayaç kendiliğinden artar."),
        ))
        self._tool_pages["number"] = idx; idx += 1

        self.prop_stack.addWidget(page(
            self._hint("🖼 Bir alan sürükleyip bırakın; açılan pencereden PNG "
                      "olarak kaydedebilir ya da panoya kopyalayabilirsiniz.\n\n"
                      "Bu araç PDF'i DEĞİŞTİRMEZ — yalnızca seçilen bölgeyi "
                      "yüksek çözünürlükte görsel olarak çıkarır."),
        ))
        self._tool_pages["crop"] = idx; idx += 1

        return self.prop_stack

    def _build_layers_tab(self):
        self.layers_list = QListWidget()
        self.layers_list.setObjectName("layers")
        self.layers_list.itemClicked.connect(self._on_layer_clicked)
        return self.layers_list

    def _build_shortcuts(self):
        def act(seq, fn):
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(fn)
            self.addAction(a)

        act("Ctrl+O", self.open_pdf)
        act("Ctrl+S", self.save_document)
        act("Ctrl+F", self._focus_search)
        act("Right", lambda: self.goto_page(self.active_session.current_page + 1)
            if self.active_session else None)
        act("Left", lambda: self.goto_page(self.active_session.current_page - 1)
            if self.active_session else None)
        act(QKeySequence.StandardKey.Delete, self.delete_selected)

    # =====================================================================
    # Tema (renk şeması) + Gece Modu (PDF piksel ters çevirme)
    # =====================================================================
    _THEMES = {
        "dark": dict(
            bg="#1e1f22", fg="#e6e6e6", toolbar="#2b2d31", border="#111",
            label="#b9bbbe", status_fg="#9aa0a6", page_fg="#fff",
            btn="#3a3d43", btn_border="#4a4d55", btn_hover="#484c54",
            accent="#5865f2", accent_hover="#4752e0",
            slider_groove="#4a4d55", thumbs_bg="#232428", thumbs_item="#3a3d43",
            frame_bg="#26282c", view_bg="#2b2d31", hint="#8a8f98",
        ),
        "light": dict(
            bg="#f4f5f7", fg="#202225", toolbar="#ffffff", border="#d8dadf",
            label="#5a5f66", status_fg="#6a6f76", page_fg="#202225",
            btn="#eceef1", btn_border="#c9cdd3", btn_hover="#dfe2e6",
            accent="#5865f2", accent_hover="#4752e0",
            slider_groove="#c9cdd3", thumbs_bg="#eceef1", thumbs_item="#ffffff",
            frame_bg="#ffffff", view_bg="#dfe3e8", hint="#7a7f87",
        ),
    }

    def _stylesheet(self, t):
        return f"""
            QMainWindow, QWidget {{ background:{t['bg']}; color:{t['fg']};
                font-family:'Segoe UI','Arial'; font-size:13px; }}
            #toolbar, #bottombar {{ background:{t['toolbar']}; border-bottom:1px solid {t['border']}; }}
            #tbGroup {{ background:transparent; border-right:1px solid {t['border']}; }}
            #tbGroupTitle {{ color:{t['label']}; font-size:10px; font-weight:700; letter-spacing:1px; }}
            #sectionFrame {{ background:{t['frame_bg']}; border:1px solid {t['border']}; border-radius:8px; }}
            #sectionTitle {{ color:{t['label']}; font-size:10px; font-weight:700;
                letter-spacing:1px; padding:2px 2px 4px 2px; }}
            #hint {{ color:{t['hint']}; font-size:11px; }}
            #nextNumber {{ font-weight:700; color:{t['accent']}; }}
            QLabel {{ color:{t['label']}; }}
            #status {{ background:{t['toolbar']}; color:{t['status_fg']}; border-top:1px solid {t['border']}; }}
            #pagelbl {{ min-width:56px; qproperty-alignment:AlignCenter; color:{t['page_fg']}; }}
            QPushButton {{ background:{t['btn']}; border:1px solid {t['btn_border']};
                border-radius:6px; padding:6px 10px; color:{t['fg']}; }}
            QPushButton:hover {{ background:{t['btn_hover']}; }}
            QPushButton:disabled {{ color:{t['border']}; }}
            QPushButton#primary {{ background:{t['accent']}; border:none; font-weight:600; color:#fff; }}
            QPushButton#primary:hover {{ background:{t['accent_hover']}; }}
            QPushButton#colorbtn {{ border:1px solid {t['btn_border']}; border-radius:5px; }}
            QPushButton:checked {{ background:{t['accent']}; color:#fff; }}
            QToolButton {{ background:{t['btn']}; border:1px solid {t['btn_border']};
                border-radius:6px; padding:6px 10px; color:{t['fg']}; }}
            QToolButton::menu-indicator {{ image:none; }}
            QToolButton:hover {{ background:{t['btn_hover']}; }}
            QToolButton#toolbtn:checked {{ background:{t['accent']}; border:1px solid {t['accent']};
                font-weight:700; color:#fff; }}
            QFrame#sep {{ color:{t['btn_border']}; max-width:1px; }}
            QSlider::groove:horizontal {{ height:4px; background:{t['slider_groove']}; border-radius:2px; }}
            QSlider::handle:horizontal {{ width:14px; background:{t['accent']}; border-radius:7px; margin:-6px 0; }}
            QCheckBox {{ color:{t['fg']}; }}
            QSpinBox, QLineEdit {{ background:{t['btn']}; border:1px solid {t['btn_border']}; border-radius:5px;
                padding:3px; color:{t['fg']}; }}
            QComboBox {{ background:{t['btn']}; border:1px solid {t['btn_border']}; border-radius:5px;
                padding:3px; color:{t['fg']}; }}
            QListWidget#thumbs {{ background:{t['thumbs_bg']}; border:none; }}
            QListWidget#thumbs::item {{ background:{t['thumbs_item']};
                border:1px solid {t['btn_border']}; border-radius:4px; margin:2px; }}
            QListWidget#thumbs::item:selected {{ border:2px solid {t['accent']}; }}
            QListWidget#layers {{ background:{t['frame_bg']}; border:none; }}
            QListWidget#layers::item {{ border-bottom:1px solid {t['border']}; }}
            QTabWidget::pane {{ border:1px solid {t['border']}; border-radius:8px; background:{t['frame_bg']}; }}
            QTabBar::tab {{ background:{t['btn']}; color:{t['fg']}; padding:6px 10px;
                border-top-left-radius:6px; border-top-right-radius:6px; }}
            QTabBar::tab:selected {{ background:{t['accent']}; color:#fff; }}
            QTabBar#doctabs::tab {{ padding:6px 16px; }}
            QDockWidget {{ color:{t['fg']}; titlebar-close-icon: none; }}
            QDockWidget::title {{ background:{t['toolbar']}; padding:4px 8px; border-bottom:1px solid {t['border']}; }}
            QTreeWidget {{ background:{t['frame_bg']}; border:none; color:{t['fg']}; }}
            QMenu {{ background:{t['toolbar']}; color:{t['fg']}; border:1px solid {t['border']}; }}
            QMenu::item:selected {{ background:{t['accent']}; color:#fff; }}
        """

    def _apply_style(self):
        self.setStyleSheet(self._stylesheet(self._THEMES["dark" if self.dark_mode else "light"]))
        self.view.setBackgroundBrush(QColor(self._THEMES["dark" if self.dark_mode else "light"]["view_bg"]))

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self._apply_style()
        self.btn_theme.setText("☀ Açık Tema" if self.dark_mode else "🌙 Koyu Tema")

    def toggle_night_mode(self, checked: bool):
        self.night_mode = checked
        self.view.refresh_current_page()
        self.pane_left._render()
        self.pane_right._render()

    def _set_ui_enabled(self, on):
        for w in (self.btn_export, self.btn_split, self.btn_merge, self.btn_prev, self.btn_next,
                  self.btn_fit_width, self.btn_fit_page, self.btn_add_page, self.btn_compare,
                  self.btn_rot_ccw, self.btn_rot_cw, self.btn_watermark, self.zoom_slider,
                  self.btn_search, self.btn_search_prev, self.btn_search_next, self.search_edit):
            w.setEnabled(on)
        for _, b in self._tool_buttons:
            b.setEnabled(on)

    # =====================================================================
    # Araç / renk seçimi
    # =====================================================================
    def _select_tool(self, tool, btn):
        was_edit = self.state.tool == "edit"
        self.state.tool = tool
        if (tool == "edit" or was_edit) and self.active_session:
            self._refresh_current_page()
            if tool == "edit":
                self._scan_current_page_for_edit()
        for _, b in self._tool_buttons:
            b.setChecked(b is btn)
        if tool in self._tool_pages:
            self.prop_stack.setCurrentIndex(self._tool_pages[tool])
        if tool == "number":
            self._refresh_number_label()
        cursor = (Qt.CursorShape.IBeamCursor if tool in ("text", "edit", "number")
                  else Qt.CursorShape.CrossCursor if tool != "select"
                  else Qt.CursorShape.ArrowCursor)
        self.view.viewport().setCursor(cursor)

    def _pick_color(self, attr):
        current = getattr(self.state, attr)
        color = QColorDialog.getColor(current, self, "Renk seç")
        if color.isValid():
            setattr(self.state, attr, color)
            for btn in self._color_buttons_by_attr.get(attr, []):
                btn.setStyleSheet(f"background:{color.name()};")

    # =====================================================================
    # Belge oturumları (QTabBar tabanlı çoklu PDF)
    # =====================================================================
    def _open_path_as_session(self, path):
        pdf = PDFDocument(path)
        session = DocumentSession(pdf, path)
        self.undo_group.addStack(session.undo_stack)
        self.sessions.append(session)
        return session

    def open_pdf(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "PDF / Resim Aç (birden fazla seçilebilir)",
                                                 "", OPEN_FILTER)
        if not paths:
            return
        last_idx = None
        for p in paths:
            try:
                self._open_path_as_session(p)
                last_idx = len(self.sessions) - 1
            except Exception as ex:
                QMessageBox.critical(self, "Hata", f"'{p}' açılamadı:\n{ex}")
        if last_idx is None:
            return
        self._set_ui_enabled(True)
        self.refresh_doc_tabs()
        self.switch_session(last_idx)

    def refresh_doc_tabs(self):
        self.doc_tabbar.blockSignals(True)
        while self.doc_tabbar.count():
            self.doc_tabbar.removeTab(0)
        for s in self.sessions:
            i = self.doc_tabbar.addTab(s.title)
            self.doc_tabbar.setTabToolTip(i, s.path)
        if self.active_session in self.sessions:
            self.doc_tabbar.setCurrentIndex(self.sessions.index(self.active_session))
        self.doc_tabbar.blockSignals(False)

    def _on_doctab_context_menu(self, pos):
        idx = self.doc_tabbar.tabAt(pos)
        if not (0 <= idx < len(self.sessions)):
            return
        session = self.sessions[idx]
        menu = QMenu(self)
        act_folder = menu.addAction("📂 Klasörde Göster")
        act_rename = menu.addAction("🔤 Sekme Adını Değiştir")
        act_copy = menu.addAction("📋 Dosya Yolunu Kopyala")
        menu.addSeparator()
        act_close = menu.addAction("✕ Kapat")
        chosen = menu.exec(self.doc_tabbar.mapToGlobal(pos))
        if chosen == act_folder:
            folder = os.path.dirname(os.path.abspath(session.path))
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
                QMessageBox.warning(self, "Uyarı", f"Klasör açılamadı:\n{folder}")
        elif chosen == act_rename:
            new_name, ok = QInputDialog.getText(self, "Sekme Adını Değiştir", "Yeni ad:", text=session.title)
            if ok and new_name.strip():
                session.title = new_name.strip()
                self.refresh_doc_tabs()
                if session is self.active_session:
                    self.setWindowTitle(f"PDF İşaretleme Aracı — {session.title}")
        elif chosen == act_copy:
            QApplication.clipboard().setText(session.path)
            self.status.setText("Dosya yolu panoya kopyalandı.")
        elif chosen == act_close:
            self.close_session(idx)

    def _on_tab_changed(self, index):
        if 0 <= index < len(self.sessions) and self.sessions[index] is not self.active_session:
            self.switch_session(index)

    def switch_session(self, idx):
        self.active_session = self.sessions[idx]
        self.undo_group.setActiveStack(self.active_session.undo_stack)
        self._build_thumbnails()
        self._build_toc()
        self.goto_page(self.active_session.current_page)
        self.setWindowTitle(f"PDF İşaretleme Aracı — {self.active_session.title}")
        self._refresh_number_label()
        self.refresh_doc_tabs()
        if hasattr(self, "pane_left"):
            self.pane_left.refresh_sessions()
            self.pane_right.refresh_sessions()

    def close_session(self, idx):
        if not (0 <= idx < len(self.sessions)):
            return
        closing = self.sessions[idx]
        was_active = closing is self.active_session
        self.sessions.pop(idx)
        self.undo_group.removeStack(closing.undo_stack)
        closing.close()
        if self._pair_pending and self._pair_pending[0].session is closing:
            self._pair_pending = None
            self._refresh_number_label()
        if not self.sessions:
            self.active_session = None
            self._set_ui_enabled(False)
            self.thumb_list.clear()
            self.toc_tree.clear()
            self.view.render_page(None, None)
            self.lbl_page.setText("0 / 0")
            self.status.setText("Tüm belgeler kapatıldı.")
            self.refresh_doc_tabs()
            return
        if was_active:
            new_idx = min(idx, len(self.sessions) - 1)
            self.refresh_doc_tabs()
            self.switch_session(new_idx)
        else:
            self.refresh_doc_tabs()

    # =====================================================================
    # Dosya: kaydet / dışa aktar / birleştir / ayır / proje
    # =====================================================================
    def save_document(self):
        """Ctrl+S: resim açıldıysa resim olarak, PDF açıldıysa PDF olarak kaydet."""
        s = self.active_session
        if s and s.pdf.is_image:
            self.save_as_image()
        else:
            self.save_pdf()

    def save_as_image(self):
        s = self.active_session
        if not s:
            return
        ext = os.path.splitext(s.path)[1].lower() if s.pdf.is_image else ".png"
        if ext not in IMAGE_EXTS or ext == ".gif":
            ext = ".png"
        filt = ("PNG (*.png);;JPEG (*.jpg *.jpeg);;BMP (*.bmp);;TIFF (*.tif *.tiff);;WEBP (*.webp)")
        default = os.path.splitext(s.path)[0] + "_isaretli" + ext
        path, _ = QFileDialog.getSaveFileName(self, "Resim Olarak Kaydet", default, filt)
        if not path:
            return
        if not is_image_path(path) or path.lower().endswith(".gif"):
            path += ext
        try:
            if s.pdf.page_count == 1:
                s.pdf.export_image(0, s.annotations.get(0, []), self.font_ctx, path)
                saved = [path]
            else:
                root, e = os.path.splitext(path)
                saved = []
                for i in range(s.pdf.page_count):
                    out = f"{root}_sayfa{i + 1}{e}"
                    s.pdf.export_image(i, s.annotations.get(i, []), self.font_ctx, out)
                    saved.append(out)
            self.status.setText(f"Kaydedildi: {saved[0]}" + (f" (+{len(saved) - 1})" if len(saved) > 1 else ""))
            QMessageBox.information(self, "Tamam", "Resim başarıyla kaydedildi.")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")

    def save_pdf(self):
        s = self.active_session
        if not s:
            return
        default = os.path.splitext(s.path)[0] + "_isaretli.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "PDF Olarak Kaydet", default, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            s.pdf.export_pdf(path, s.annotations, self.font_ctx)
            self.status.setText(f"Kaydedildi: {path}")
            QMessageBox.information(self, "Tamam", "PDF başarıyla kaydedildi.")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")

    def open_ocr_dialog(self):
        s = self.active_session
        if not s:
            QMessageBox.information(self, "OCR", "Önce bir PDF açın.")
            return
        OcrDialog(self, s, self).exec()

    def save_pdf_with_watermark(self):
        s = self.active_session
        if not s:
            return
        dlg = WatermarkDialog(self.state.watermark, s.pdf.page_count, s.current_page, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cfg = dlg.get_config()
        self.state.watermark = cfg
        default = os.path.splitext(s.path)[0] + "_filigranli.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Filigranlı PDF Olarak Kaydet", default, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            s.pdf.export_pdf(path, s.annotations, self.font_ctx, watermark=cfg)
            self.status.setText(f"Filigranlı PDF kaydedildi: {path}")
            QMessageBox.information(self, "Tamam", "Filigranlı PDF başarıyla kaydedildi.")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")

    def export_image_current(self, ext):
        s = self.active_session
        if not s:
            return
        filt = "PNG Görseli (*.png)" if ext == "png" else "JPEG Görseli (*.jpg)"
        default = os.path.splitext(s.path)[0] + f"_sayfa{s.current_page + 1}.{ext}"
        path, _ = QFileDialog.getSaveFileName(self, "Görsel Olarak Dışa Aktar", default, filt)
        if not path:
            return
        if not path.lower().endswith("." + ext):
            path += "." + ext
        try:
            s.pdf.export_image(s.current_page, s.annotations[s.current_page], self.font_ctx, path)
            self.status.setText(f"Dışa aktarıldı: {path}")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Dışa aktarılamadı:\n{ex}")

    def export_all_pages_images(self, ext):
        s = self.active_session
        if not s:
            return
        folder = QFileDialog.getExistingDirectory(self, "Klasör Seç")
        if not folder:
            return
        base = os.path.splitext(os.path.basename(s.path))[0]
        try:
            for i in range(s.pdf.page_count):
                out = os.path.join(folder, f"{base}_sayfa{i + 1}.{ext}")
                s.pdf.export_image(i, s.annotations.get(i, []), self.font_ctx, out)
            self.status.setText(f"Tüm sayfalar dışa aktarıldı: {folder}")
            QMessageBox.information(self, "Tamam", f"{s.pdf.page_count} sayfa '{folder}' klasörüne kaydedildi.")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Dışa aktarılamadı:\n{ex}")

    def merge_pdfs(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Birleştirilecek PDF / resimleri seçin (sırayla)", "", OPEN_FILTER)
        if len(files) < 2:
            if files:
                QMessageBox.information(self, "Bilgi", "Birleştirmek için en az 2 PDF seçin.")
            return
        out_path, _ = QFileDialog.getSaveFileName(self, "Birleşik PDF'i Kaydet", "birlesik.pdf", "PDF (*.pdf)")
        if not out_path:
            return
        if not out_path.lower().endswith(".pdf"):
            out_path += ".pdf"
        try:
            merged = fitz.open()
            for f in files:
                src = image_to_pdf_document(f)[0] if is_image_path(f) else fitz.open(f)
                merged.insert_pdf(src)
                src.close()
            merged.save(out_path)
            merged.close()
            self._open_path_as_session(out_path)
            self._set_ui_enabled(True)
            self.refresh_doc_tabs()
            self.switch_session(len(self.sessions) - 1)
            self.status.setText(f"{len(files)} PDF birleştirildi: {out_path}")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Birleştirilemedi:\n{ex}")

    def split_all_pages(self):
        s = self.active_session
        if not s:
            return
        folder = QFileDialog.getExistingDirectory(self, "Klasör Seç")
        if not folder:
            return
        base = os.path.splitext(os.path.basename(s.path))[0]
        try:
            annotated = s.pdf._annotated_copy(s.annotations, self.font_ctx)
            for i in range(annotated.page_count):
                single = fitz.open()
                single.insert_pdf(annotated, from_page=i, to_page=i)
                single.save(os.path.join(folder, f"{base}_sayfa{i + 1}.pdf"))
                single.close()
            annotated.close()
            self.status.setText(f"{s.pdf.page_count} sayfa ayrı PDF olarak kaydedildi: {folder}")
            QMessageBox.information(self, "Tamam", f"Sayfalar '{folder}' klasörüne kaydedildi.")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Ayrılamadı:\n{ex}")

    def extract_page_range(self):
        s = self.active_session
        if not s:
            return
        n = s.pdf.page_count
        start, ok1 = QInputDialog.getInt(self, "Aralık Çıkar", "Başlangıç sayfa no:", 1, 1, n)
        if not ok1:
            return
        end, ok2 = QInputDialog.getInt(self, "Aralık Çıkar", "Bitiş sayfa no:", n, start, n)
        if not ok2:
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Aralığı Yeni PDF Olarak Kaydet",
            os.path.splitext(s.path)[0] + f"_s{start}-{end}.pdf", "PDF (*.pdf)")
        if not out_path:
            return
        try:
            annotated = s.pdf._annotated_copy(s.annotations, self.font_ctx)
            part = fitz.open()
            part.insert_pdf(annotated, from_page=start - 1, to_page=end - 1)
            part.save(out_path)
            part.close()
            annotated.close()
            self.status.setText(f"{start}-{end}. sayfalar kaydedildi: {out_path}")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Çıkarılamadı:\n{ex}")

    def save_project(self):
        s = self.active_session
        if not s:
            return
        default = os.path.splitext(s.path)[0] + ".pdfproj.json"
        path, _ = QFileDialog.getSaveFileName(self, "Proje Kaydet", default, "PDF Proje (*.json)")
        if not path:
            return
        try:
            save_project_json(path, s)
            self.status.setText(f"Proje kaydedildi: {path}")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Proje kaydedilemedi:\n{ex}")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Proje Aç", "", "PDF Proje (*.json)")
        if not path:
            return
        try:
            d = load_project_json(path)
            source_pdf = d.get("source_pdf")
            if not source_pdf or not os.path.exists(source_pdf):
                source_pdf, _ = QFileDialog.getOpenFileName(
                    self, "Kaynak dosya bulunamadı — lütfen seçin", "", OPEN_FILTER)
                if not source_pdf:
                    return
            session = self._open_path_as_session(source_pdf)
            session.load_project_dict(d)
            for page, rot in session.rotations.items():
                if 0 <= page < session.pdf.page_count:
                    session.pdf.set_absolute_rotation(page, rot)
            self._set_ui_enabled(True)
            self.refresh_doc_tabs()
            self.switch_session(len(self.sessions) - 1)
            self.status.setText(f"Proje açıldı: {path}")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Proje açılamadı:\n{ex}")

    # =====================================================================
    # Sayfa yönetimi (ekle / sil / kopyala / taşı / döndür)
    # =====================================================================
    def _reindex_annotations(self, session, old_count, transform):
        order = [session.annotations.get(i, []) for i in range(old_count)]
        order = transform(order)
        session.annotations = {i: lst for i, lst in enumerate(order)}
        # Sayfa yapısı değişti; eski geri-al kayıtları artık geçersiz sayfa
        # indekslerine işaret edebilir.
        session.undo_stack.clear()

    def _delete_page(self, idx):
        s = self.active_session
        if not s:
            return
        if s.pdf.page_count <= 1:
            QMessageBox.warning(self, "Uyarı", "Belgede tek sayfa var, silinemez.")
            return
        old_count = s.pdf.page_count
        s.pdf.delete_page(idx)
        self._reindex_annotations(s, old_count, lambda order: (order.pop(idx), order)[1])
        s.current_page = min(s.current_page, s.pdf.page_count - 1)
        self._build_thumbnails()
        self.goto_page(s.current_page)
        self.status.setText(f"{idx + 1}. sayfa silindi.")

    def _insert_blank_page(self, idx):
        s = self.active_session
        if not s:
            return
        old_count = s.pdf.page_count
        w, h = s.pdf.page_size(0) if old_count else (595, 842)
        idx = max(0, min(idx, old_count))
        s.pdf.insert_blank_page(idx, w, h)
        self._reindex_annotations(s, old_count, lambda order: (order.insert(idx, []), order)[1])
        self._build_thumbnails()
        self.goto_page(idx)
        self.status.setText("Boş sayfa eklendi.")

    def _duplicate_page(self, idx):
        s = self.active_session
        if not s:
            return
        old_count = s.pdf.page_count
        s.pdf.duplicate_page(idx)

        def _t(order):
            order.insert(idx + 1, copy.deepcopy(order[idx]))
            return order

        self._reindex_annotations(s, old_count, _t)
        self._build_thumbnails()
        self.goto_page(idx + 1)
        self.status.setText("Sayfa kopyalandı.")

    def _move_page(self, frm, to):
        s = self.active_session
        if not s:
            return
        old_count = s.pdf.page_count
        s.pdf.move_page(frm, to)

        def _t(order):
            item = order.pop(frm)
            order.insert(to, item)
            return order

        self._reindex_annotations(s, old_count, _t)
        self._build_thumbnails()
        self.goto_page(to)
        self.status.setText("Sayfa taşındı.")

    def _rotate_current_page(self, delta):
        s = self.active_session
        if not s:
            return
        self._rotate_page(s.current_page, delta)

    def _rotate_page(self, idx, delta):
        s = self.active_session
        if not s:
            return
        if s.annotations.get(idx):
            reply = QMessageBox.question(
                self, "Sayfa Döndür",
                "Bu sayfada işaretler var. Döndürme sonrası konumları kayabilir.\n"
                "Devam edilsin mi?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        s.pdf.rotate_page(idx, delta)
        s.rotations[idx] = s.pdf.page_rotation(idx)
        self._build_thumbnails()
        self.goto_page(idx)
        self.status.setText("Sayfa döndürüldü.")

    def _on_thumb_context_menu(self, pos):
        s = self.active_session
        if not s:
            return
        row = self.thumb_list.indexAt(pos).row()
        if row < 0:
            return
        menu = QMenu(self)
        act_before = menu.addAction("➕ Öncesine Boş Sayfa Ekle")
        act_after = menu.addAction("➕ Sonrasına Boş Sayfa Ekle")
        act_dup = menu.addAction("📄 Sayfayı Kopyala")
        menu.addSeparator()
        act_up = menu.addAction("⬆ Yukarı Taşı")
        act_down = menu.addAction("⬇ Aşağı Taşı")
        menu.addSeparator()
        act_rot_cw = menu.addAction("↻ Saat Yönünde Döndür")
        act_rot_ccw = menu.addAction("↺ Tersine Döndür")
        menu.addSeparator()
        act_del = menu.addAction("🗑 Sayfayı Sil")
        chosen = menu.exec(self.thumb_list.viewport().mapToGlobal(pos))
        if chosen == act_before:
            self._insert_blank_page(row)
        elif chosen == act_after:
            self._insert_blank_page(row + 1)
        elif chosen == act_dup:
            self._duplicate_page(row)
        elif chosen == act_up and row > 0:
            self._move_page(row, row - 1)
        elif chosen == act_down and row < s.pdf.page_count - 1:
            self._move_page(row, row + 1)
        elif chosen == act_rot_cw:
            self._rotate_page(row, 90)
        elif chosen == act_rot_ccw:
            self._rotate_page(row, -90)
        elif chosen == act_del:
            self._delete_page(row)

    # =====================================================================
    # Küçük resimler / İçindekiler / sayfa gösterimi / yakınlaştırma
    # =====================================================================
    def _build_thumbnails(self):
        s = self.active_session
        self.thumb_list.blockSignals(True)
        self.thumb_list.clear()
        if s:
            for i in range(s.pdf.page_count):
                pix = s.pdf.thumbnail(i)
                item = QListWidgetItem(QIcon(pix), f"{i + 1}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.thumb_list.addItem(item)
        self.thumb_list.blockSignals(False)

    def _build_toc(self):
        self.toc_tree.clear()
        s = self.active_session
        if not s:
            return
        toc = s.pdf.toc()
        if not toc:
            item = QTreeWidgetItem(["(İçindekiler yok)"])
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.toc_tree.addTopLevelItem(item)
            return
        stack: List[Tuple[int, QTreeWidgetItem]] = []
        for level, title, page in toc:
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, page)
            while stack and stack[-1][0] >= level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(item)
            else:
                self.toc_tree.addTopLevelItem(item)
            stack.append((level, item))
        self.toc_tree.expandAll()

    def _on_toc_item_clicked(self, item, _col):
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page:
            self.goto_page(int(page) - 1)

    def _on_thumb_selected(self, row):
        if row >= 0 and self.active_session and row != self.active_session.current_page:
            self.goto_page(row)

    def goto_page(self, index):
        s = self.active_session
        if not s:
            return
        index = max(0, min(index, s.pdf.page_count - 1))
        s.current_page = index
        self.view.render_page(s, index, invert=self.night_mode)
        self.lbl_page.setText(f"{index + 1} / {s.pdf.page_count}")
        if self.thumb_list.currentRow() != index:
            self.thumb_list.blockSignals(True)
            self.thumb_list.setCurrentRow(index)
            self.thumb_list.blockSignals(False)
        self._apply_zoom_percent(self.zoom_slider.value())
        self.refresh_layers_panel()
        self._update_search_highlight_for_page()
        if self.state.tool == "edit":
            self._scan_current_page_for_edit()

    def fit_width(self):
        s = self.active_session
        if not s:
            return
        w, _ = s.pdf.page_size(s.current_page)
        vp = self.view.viewport().width() - 24
        if w > 0:
            self._zoom = vp / w
            self._apply_zoom_transform()
            self._sync_zoom_slider()

    def fit_page(self):
        s = self.active_session
        if not s:
            return
        self.view.fitInView(self.view.scene_obj.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.view.transform().m11()
        self._sync_zoom_slider()

    def _sync_zoom_slider(self):
        pct = max(10, min(400, int(round(self._zoom * 100))))
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(pct)
        self.zoom_slider.blockSignals(False)
        self.lbl_zoom.setText(f"{pct}%")

    def _apply_zoom_transform(self):
        self.view.resetTransform()
        self.view.scale(self._zoom, self._zoom)

    def _on_zoom_slider_changed(self, value):
        self._apply_zoom_percent(value)

    def _apply_zoom_percent(self, pct):
        self._zoom = pct / 100.0
        self._apply_zoom_transform()
        self.lbl_zoom.setText(f"{pct}%")

    # =====================================================================
    # Arama (Ctrl+F)
    # =====================================================================
    def _focus_search(self):
        if not self.active_session:
            return
        self.left_tabs.setCurrentIndex(self.search_tab_index)
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def run_search(self):
        s = self.active_session
        query = self.search_edit.text().strip()
        if not s or not query:
            return
        self.lbl_search_status.setText("Aranıyor…")
        self.search_results_list.clear()
        task = s.pdf.make_search_task(query)
        self._pending_search_tasks.append(task)

        def cleanup():
            if task in self._pending_search_tasks:
                self._pending_search_tasks.remove(task)

        def on_finished(result, _s=s):
            cleanup()
            if _s is not self.active_session:
                return
            self._apply_search_results(result)

        def on_failed(_msg):
            cleanup()
            self.lbl_search_status.setText("Arama başarısız oldu.")

        task.signals.finished.connect(on_finished)
        task.signals.failed.connect(on_failed)
        self.threadpool.start(task)

    def _apply_search_results(self, result: Dict[int, list]):
        self._search_results = result
        self._search_flat = []
        self.search_results_list.clear()
        for page in sorted(result.keys()):
            hits = result[page]
            for local_idx in range(len(hits)):
                self._search_flat.append((page, local_idx))
            item = QListWidgetItem(f"Sayfa {page + 1} — {len(hits)} eşleşme")
            item.setData(Qt.ItemDataRole.UserRole, page)
            self.search_results_list.addItem(item)
        total = len(self._search_flat)
        self.lbl_search_status.setText(f"{total} eşleşme bulundu." if total else "Eşleşme bulunamadı.")
        self._search_pos = -1
        if total:
            self.goto_next_search_hit()
        else:
            self.view.set_search_highlights([])

    def _on_search_result_clicked(self, item):
        page = item.data(Qt.ItemDataRole.UserRole)
        if page is not None:
            self.goto_page(int(page))
            hits = self._search_results.get(int(page), [])
            self.view.set_search_highlights(hits, 0 if hits else None)

    def goto_next_search_hit(self):
        if not self._search_flat:
            return
        self._search_pos = (self._search_pos + 1) % len(self._search_flat)
        self._show_search_hit()

    def goto_prev_search_hit(self):
        if not self._search_flat:
            return
        self._search_pos = (self._search_pos - 1) % len(self._search_flat)
        self._show_search_hit()

    def _show_search_hit(self):
        page, local_idx = self._search_flat[self._search_pos]
        if not self.active_session or self.active_session.current_page != page:
            self.goto_page(page)
        hits = self._search_results.get(page, [])
        self.view.set_search_highlights(hits, local_idx)
        self.lbl_search_status.setText(f"{self._search_pos + 1} / {len(self._search_flat)}")

    def _update_search_highlight_for_page(self):
        s = self.active_session
        if not s or not self._search_results:
            return
        hits = self._search_results.get(s.current_page, [])
        active = None
        if self._search_flat and 0 <= self._search_pos < len(self._search_flat):
            p, li = self._search_flat[self._search_pos]
            active = li if p == s.current_page else None
        self.view.set_search_highlights(hits, active)

    # =====================================================================
    # Annotation ekle / sil / taşı / boyutlandır (QUndoStack üzerinden)
    # =====================================================================
    def _on_session_change(self, session, page):
        """Tüm QUndoCommand'ların ortak geri çağrısı: ilgili görünümleri
        tazeler (ana sayfa + karşılaştırma panelleri + katmanlar)."""
        for pane in (self.pane_left, self.pane_right):
            if pane.session is session and pane.page == page:
                pane._render()
        if self.active_session is session and self.view._page_index == page:
            self.view.render_page(session, page, invert=self.night_mode)
            self.refresh_layers_panel()
        session.dirty = True

    def add_annotation(self, ann):
        s = self.active_session
        if not s:
            return
        cmd = AddAnnotationCommand(s, s.current_page, ann, on_change=self._on_session_change,
                                    label="İşaret Ekle")
        s.undo_stack.push(cmd)
        self.status.setText("İşaret eklendi.")

    def on_text_requested(self, rect: QRectF):
        dlg = TextDialog(self.state.font_family, self.state.font_size,
                         self.state.text_color, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text, family, size, color = dlg.result_values()
        if not text.strip():
            return
        # Son seçimler bir sonraki metin için hatırlanır.
        self.state.font_family = family
        self.state.font_size = size
        self.state.text_color = color
        if hasattr(self, "font_combo_panel"):
            self.font_combo_panel.setCurrentText(family)
        for btn in self._color_buttons_by_attr.get("text_color", []):
            btn.setStyleSheet(f"background:{color.name()};")
        # Kutu yüksekliği seçilen puntoya göre ayarlanır (satır sayısı kadar).
        lines = max(1, text.count("\n") + 1)
        rect = QRectF(rect.x(), rect.y(), rect.width(), max(rect.height(), size * 1.4 * lines))
        self.add_annotation(TextAnnotation(rect, text, color, size, family))

    # =====================================================================
    # Metin Düzenle (gerçek metin ya da OCR ile okunan metni değiştirme)
    # =====================================================================
    def _ocr_env(self, need_ocr: bool):
        """(tessdata, dil) döner. OCR gerekiyorsa ve kurulu değilse uyarır, None döner."""
        tessdata = ocr.find_tessdata()
        if tessdata is None:
            if need_ocr:
                QMessageBox.warning(self, "OCR kurulu değil", ocr.setup_message())
                return None
            return None, "eng"
        miss = ocr.missing_languages(tessdata)
        if miss and not self._lang_warned:
            self._lang_warned = True
            QMessageBox.information(
                self, "Dil verisi eksik",
                "Şu dil dosyaları bulunamadı: " + ", ".join(f"{m}.traineddata" for m in miss) +
                f"\nOCR yalnızca kurulu dillerle ({', '.join(ocr.installed_languages(tessdata))}) çalışacak.\n"
                f"Türkçe + İngilizce için ikisini de şuraya koyun:\n{ocr.APP_TESSDATA}")
        return tessdata, ocr.pick_language(tessdata)

    def _scan_current_page_for_edit(self, then_click=None):
        """Geçerli sayfanın metin satırlarını arka planda çıkarır (gerekirse OCR)
        ve önbelleğe alır. then_click: tarama bitince işlenecek tıklama noktası."""
        s = self.active_session
        if not s or self._edit_task is not None:
            return
        page = s.current_page
        force = bool(self.state.edit_force_ocr)
        if (page, force) in s.pdf.edit_cache:
            if then_click is not None:
                self._edit_at_point(then_click)
            return
        with s.pdf.lock:
            has_native = bool(s.pdf.doc[page].get_text("text").strip())
        need_ocr = force or not has_native
        env = self._ocr_env(need_ocr)
        if need_ocr and env is None:
            return
        tessdata, lang = env if env else (None, "eng")
        try:
            with s.pdf.lock:
                snap = fitz.open()
                snap.insert_pdf(s.pdf.doc, from_page=page, to_page=page)
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Sayfa okunamadı:\n{ex}")
            return

        def job(_progress, _cancelled):
            try:
                return ocr.extract_items(snap[0], tessdata, lang, force_ocr=force)
            finally:
                snap.close()

        task = _OcrTask(job)
        self._edit_task = task
        self.status.setText("Sayfadaki metin okunuyor…" + (" (OCR)" if need_ocr else ""))
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)

        def finish():
            self._edit_task = None
            QApplication.restoreOverrideCursor()

        def done(entry):
            finish()
            cur = self.active_session
            if cur is not s or s.pdf.page_count <= page:
                return
            s.pdf.edit_cache[(page, force)] = entry
            src = "gerçek metin" if entry["source"] == "native" else "OCR"
            self.status.setText(f"{len(entry['lines'])} satır bulundu ({src}). Düzenlemek için mavi kutuya tıklayın.")
            if cur.current_page == page and self.state.tool == "edit":
                self._refresh_current_page()
                if then_click is not None:
                    self._edit_at_point(then_click)

        def failed(msg):
            finish()
            self.status.setText("Metin okunamadı.")
            QMessageBox.critical(self, "Metin okunamadı", msg)

        task.signals.done.connect(done)
        task.signals.failed.connect(failed)
        self.threadpool.start(task)

    def on_edit_text_requested(self, pt: QPointF):
        s = self.active_session
        if not s:
            return
        if (s.current_page, bool(self.state.edit_force_ocr)) in s.pdf.edit_cache:
            self._edit_at_point(pt)
        else:
            self._scan_current_page_for_edit(then_click=pt)

    @staticmethod
    def _guess_family(font_name: str) -> str:
        n = (font_name or "").lower()
        if "times" in n or "serif" in n and "sans" not in n or "georgia" in n or "garamond" in n:
            return "Times New Roman"
        if "calibri" in n or "carlito" in n:
            return "Calibri"
        if "roboto" in n:
            return "Roboto"
        return "Arial"

    def _edit_at_point(self, pt: QPointF):
        s = self.active_session
        if not s:
            return
        page = s.current_page
        entry = s.pdf.edit_cache.get((page, bool(self.state.edit_force_ocr)))
        if not entry:
            return
        items = entry["blocks" if self.state.edit_mode == "block" else "lines"]
        hits = []
        for it in items:
            x0, y0, x1, y1 = it.rect
            if x0 - 2 <= pt.x() <= x1 + 2 and y0 - 2 <= pt.y() <= y1 + 2:
                hits.append((max(1.0, (x1 - x0) * (y1 - y0)), it))
        if not hits:
            self.status.setText("Bu noktada okunan bir metin yok. Mavi kutulardan birine tıklayın.")
            return
        item = min(hits, key=lambda t: t[0])[1]
        x0, y0, x1, y1 = item.rect

        try:
            with s.pdf.lock:
                bg, fg = ocr.sample_colors(s.pdf.doc[page], item.rect)
        except Exception:
            bg, fg = (255, 255, 255), (0, 0, 0)
        text_rgb = item.color if item.color is not None else fg
        color = QColor(*text_rgb)
        family = self._guess_family(item.font)
        info = ("Yazı, font ve rengi değiştirebilirsiniz. Tamam'a basınca eski metin "
                "silinir, yenisi yazılır. Metni tamamen boşaltırsanız yalnızca silinir.")
        dlg = TextDialog(family, item.size, color, self, text=item.text,
                         title="Metni Düzenle", info=info)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_text, family, size, color = dlg.result_values()

        pad = 0.75
        cover = QRectF(x0 - pad, y0 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad)
        erase = RedactionAnnotation(cover, QColor(*bg), quiet=True)
        stack = s.undo_stack
        stack.beginMacro("Metni Düzenle")
        try:
            stack.push(AddAnnotationCommand(s, page, erase, on_change=self._on_session_change,
                                            label="Orijinal Metni Sil"))
            if new_text.strip():
                lines = max(1, new_text.count("\n") + 1)
                if self.state.edit_mode == "block":
                    width = x1 - x0
                else:
                    width = max(x1 - x0, ocr_text_width(new_text, family, size) + 2)
                height = max(y1 - y0, size * 1.3 * lines)
                text_rect = QRectF(x0, y0, width, height)
                stack.push(AddAnnotationCommand(
                    s, page, TextAnnotation(text_rect, new_text, color, size, family),
                    on_change=self._on_session_change, label="Metin Ekle"))
        finally:
            stack.endMacro()
        self.status.setText("Metin güncellendi. Geri almak için Ctrl+Z.")

    def on_number_requested(self, scene_pt: QPointF):
        s = self.active_session
        if not s:
            return
        if s.number_counter is None:
            s.number_counter = int(self.state.number_start)
        n = s.number_counter
        color = number_to_color(n) if self.state.number_multicolor else self.state.number_color
        ann = NumberAnnotation(scene_pt.x(), scene_pt.y(), n, color, self.state.number_size)

        def setter(v, _s=s):
            _s.number_counter = v
            self._refresh_number_label()

        cmd = AddAnnotationCommand(s, s.current_page, ann, on_change=self._on_session_change,
                                    counter_before=n, counter_after=n + 1, counter_setter=setter,
                                    label=f"Numara {n}")
        s.undo_stack.push(cmd)
        self.status.setText(f"Numara {n} yerleştirildi.")

    def on_number_requested_in_pane(self, pane, scene_pt: QPointF):
        session = pane.session
        if session is None:
            return
        page = pane.page
        self.undo_group.setActiveStack(session.undo_stack)

        if not self.state.number_pair_mode:
            if session.number_counter is None:
                session.number_counter = int(self.state.number_start)
            n = session.number_counter
            color = number_to_color(n) if self.state.number_multicolor else self.state.number_color
            ann = NumberAnnotation(scene_pt.x(), scene_pt.y(), n, color, self.state.number_size)

            def setter(v, _s=session):
                _s.number_counter = v
                self._refresh_number_label()

            cmd = AddAnnotationCommand(session, page, ann, on_change=self._on_session_change,
                                        counter_before=n, counter_after=n + 1, counter_setter=setter,
                                        label=f"Numara {n}")
            session.undo_stack.push(cmd)
            self.status.setText(f"Numara {n} yerleştirildi.")
            return

        # --- Eşleştir modu ---
        pend = self._pair_pending
        if pend is None:
            n = self._pair_counter
            color = number_to_color(n) if self.state.number_multicolor else self.state.number_color
            ann = NumberAnnotation(scene_pt.x(), scene_pt.y(), n, color, self.state.number_size)

            def setter(v):
                self._pair_pending = v
                self._refresh_number_label()

            cmd = AddAnnotationCommand(session, page, ann, on_change=self._on_session_change,
                                        counter_before=None, counter_after=(pane, n, color),
                                        counter_setter=setter, label=f"Eşleştirme {n} (1/2)")
            session.undo_stack.push(cmd)
            self.status.setText(f"Eşleştirme: {n} numarası kondu, aynısını diğer panele koyun.")
        else:
            first_pane, n, color = pend
            if pane is first_pane:
                self.status.setText("Önce DİĞER panele aynı numarayı koyun (ya da Eşleştir'i kapatın).")
                return
            ann = NumberAnnotation(scene_pt.x(), scene_pt.y(), n, color, self.state.number_size)

            def setter(v, _fp=first_pane, _n=n, _c=color):
                if v[0] == "redo2":
                    self._pair_counter = _n + 1
                    self._pair_pending = None
                else:
                    self._pair_counter = _n
                    self._pair_pending = (_fp, _n, _c)
                self._refresh_number_label()

            cmd = AddAnnotationCommand(session, page, ann, on_change=self._on_session_change,
                                        counter_before=("undo2",), counter_after=("redo2",),
                                        counter_setter=setter, label=f"Eşleştirme {n} (2/2)")
            session.undo_stack.push(cmd)
            self.status.setText(f"{n} numaralı çift tamamlandı. Sıradaki: {self._pair_counter}")

    def reset_pair_counter(self):
        self._pair_counter = int(self.state.number_start)
        self._pair_pending = None
        self._refresh_number_label()
        self.status.setText(f"Eşleştirme sayacı sıfırlandı. Sıradaki: {self._pair_counter}")

    def _on_number_start_changed(self, v):
        self.state.number_start = v
        self._refresh_number_label()

    def _on_pair_toggled(self, checked):
        self.state.number_pair_mode = checked
        self._pair_pending = None
        if checked:
            self._pair_counter = int(self.state.number_start)
        self._refresh_number_label()

    def reset_number_counter(self):
        if self.active_session:
            self.active_session.number_counter = int(self.state.number_start)
            self._refresh_number_label()

    def _refresh_number_label(self):
        if not hasattr(self, "lbl_next_number"):
            return
        if self.state.number_pair_mode:
            self.lbl_next_number.setText(f"Sıradaki (eşleştirme): {self._pair_counter}")
            return
        s = self.active_session
        if s is None:
            self.lbl_next_number.setText("Sıradaki: —")
            return
        n = s.number_counter if s.number_counter is not None else int(self.state.number_start)
        self.lbl_next_number.setText(f"Sıradaki: {n}")

    # -- kırpma ------------------------------------------------------------
    def on_crop_requested(self, rect: QRectF):
        s = self.active_session
        if not s:
            return
        try:
            clip = fitz.Rect(rect.left(), rect.top(), rect.right(), rect.bottom())
            with s.pdf.lock:
                page = s.pdf.doc[s.current_page]
                pix = page.get_pixmap(matrix=fitz.Matrix(4.0, 4.0), clip=clip, alpha=False)
                qimg = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format.Format_RGB888).copy()
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kırpılamadı:\n{ex}")
            return
        self._show_crop_dialog(qimg)

    def _show_crop_dialog(self, qimage: QImage):
        dlg = QDialog(self)
        dlg.setWindowTitle("Kırpılan Alan")
        v = QVBoxLayout(dlg)
        pm = QPixmap.fromImage(qimage)
        preview = QLabel()
        max_w = 480
        preview.setPixmap(pm.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
                          if pm.width() > max_w else pm)
        v.addWidget(preview)
        info = QLabel(f"{pm.width()} × {pm.height()} piksel")
        info.setObjectName("hint")
        v.addWidget(info)
        row = QHBoxLayout()
        btn_copy = QPushButton("📋 Panoya Kopyala")
        btn_save = QPushButton("💾 PNG Olarak Kaydet")
        btn_close = QPushButton("Kapat")
        row.addWidget(btn_copy); row.addWidget(btn_save); row.addWidget(btn_close)
        v.addLayout(row)

        def do_copy():
            QApplication.clipboard().setImage(qimage)
            self.status.setText("Kırpılan alan panoya kopyalandı.")

        def do_save():
            path, _ = QFileDialog.getSaveFileName(self, "Kırpılan Alanı Kaydet", "kirpma.png", "PNG (*.png)")
            if path:
                if not path.lower().endswith(".png"):
                    path += ".png"
                qimage.save(path)
                self.status.setText(f"Kaydedildi: {path}")

        btn_copy.clicked.connect(do_copy)
        btn_save.clicked.connect(do_save)
        btn_close.clicked.connect(dlg.accept)
        dlg.exec()

    # -- resim ekleme --------------------------------------------------------
    def on_image_place_requested(self, rect: QRectF):
        s = self.active_session
        if not s:
            return
        menu = QMenu(self)
        act_file = menu.addAction("📁 Dosyadan Seç…")
        act_clip = menu.addAction("📋 Panodan Yapıştır")
        chosen = menu.exec(self.view.mapToGlobal(self.view.rect().center()))
        image_bytes = None
        if chosen == act_file:
            path, _ = QFileDialog.getOpenFileName(self, "Resim Seç", "",
                                                  "Görseller (*.png *.jpg *.jpeg *.bmp *.svg)")
            if not path:
                return
            try:
                image_bytes = load_image_bytes_from_path(path)
            except Exception as ex:
                QMessageBox.critical(self, "Hata", f"Görsel yüklenemedi:\n{ex}")
                return
        elif chosen == act_clip:
            img = QApplication.clipboard().image()
            if img.isNull():
                QMessageBox.information(self, "Bilgi", "Panoda bir görsel bulunamadı.")
                return
            image_bytes = qimage_to_png_bytes(img)
        else:
            return

        qimg = QImage()
        qimg.loadFromData(image_bytes)
        if self.state.image_keep_aspect and qimg.width() and qimg.height():
            ar = qimg.height() / qimg.width()
            rect = QRectF(rect.left(), rect.top(), rect.width(), rect.width() * ar)

        ann = ImageAnnotation(rect, image_bytes, opacity=self.state.image_opacity,
                              keep_aspect=self.state.image_keep_aspect)
        self.add_annotation(ann)

    # -- yeniden boyutlandırma -----------------------------------------------
    def on_resize_requested(self, ann, old_rect: QRectF, new_rect: QRectF):
        s = self.active_session
        if not s:
            return
        cmd = ResizeAnnotationCommand(s, s.current_page, ann, old_rect, new_rect,
                                      on_change=self._on_session_change)
        s.undo_stack.push(cmd)

    # -- taşıma ------------------------------------------------------------
    def sync_moved_items(self):
        s = self.active_session
        if not s:
            return
        moved_any = False
        for gitem, ann in list(self.view.item_ann_map.items()):
            pos = gitem.pos()
            if pos.x() != 0 or pos.y() != 0:
                dx, dy = pos.x(), pos.y()
                cmd = MoveAnnotationCommand(s, s.current_page, ann, dx, dy,
                                            on_change=self._on_session_change)
                s.undo_stack.push(cmd)
                moved_any = True
        if moved_any:
            self.status.setText("Öge taşındı.")

    # -- silme / katman sırası ------------------------------------------------
    def _delete_item(self, gitem):
        s = self.active_session
        ann = self.view.item_ann_map.get(gitem)
        if not s or ann is None:
            return
        cmd = RemoveAnnotationCommand(s, s.current_page, ann, on_change=self._on_session_change)
        s.undo_stack.push(cmd)
        self.status.setText("Öge silindi.")

    def delete_selected(self):
        for gitem in list(self.view.scene_obj.selectedItems()):
            if gitem is self.view.gizmo:
                continue
            self._delete_item(gitem)

    def show_item_context_menu(self, gitem, global_pos):
        if gitem is None or gitem not in self.view.item_ann_map:
            return
        menu = QMenu(self)
        act_front = menu.addAction("⬆ En Öne Getir")
        act_back = menu.addAction("⬇ En Arkaya Gönder")
        menu.addSeparator()
        act_del = menu.addAction("🗑 Sil")
        chosen = menu.exec(global_pos)
        s = self.active_session
        ann = self.view.item_ann_map.get(gitem)
        if chosen == act_del:
            self._delete_item(gitem)
        elif chosen == act_front and s and ann:
            s.undo_stack.push(ZOrderCommand(s, s.current_page, ann, True, on_change=self._on_session_change))
        elif chosen == act_back and s and ann:
            s.undo_stack.push(ZOrderCommand(s, s.current_page, ann, False, on_change=self._on_session_change))

    # =====================================================================
    # Katmanlar paneli
    # =====================================================================
    def _ann_label(self, ann):
        if isinstance(ann, TextAnnotation):
            return f"🅣  {ann.text.replace(chr(10), ' ')[:16]}"
        if isinstance(ann, InkAnnotation):
            return "✎  Kalem çizimi"
        if isinstance(ann, LineAnnotation):
            return "↗  Çizgi / Ok"
        if isinstance(ann, ShapeAnnotation):
            return "▭  Dörtgen" if ann.kind == "rect" else "◯  Oval"
        if isinstance(ann, HighlightAnnotation):
            return "🖍  Fosforlu"
        if isinstance(ann, RedactionAnnotation):
            return "🧽  Silinen orijinal metin" if getattr(ann, "quiet", False) else "⬛  Sansür (kalıcı)"
        if isinstance(ann, NumberAnnotation):
            return f"🔢  Numara {ann.number}"
        if isinstance(ann, ImageAnnotation):
            return "🖼  Resim"
        return "Öge"

    def refresh_layers_panel(self):
        if not hasattr(self, "layers_list"):
            return
        self.layers_list.clear()
        s = self.active_session
        anns = s.annotations.get(s.current_page, []) if s else []
        for ann in anns:
            list_item = QListWidgetItem()
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(8, 4, 4, 4)
            lbl = QLabel(self._ann_label(ann))
            h.addWidget(lbl, 1)
            btn = QPushButton("🗑")
            btn.setFixedWidth(28)
            btn.clicked.connect(lambda _, a=ann: self._delete_annotation_by_ref(a))
            h.addWidget(btn)
            list_item.setData(Qt.ItemDataRole.UserRole, ann)
            list_item.setSizeHint(row.sizeHint())
            self.layers_list.addItem(list_item)
            self.layers_list.setItemWidget(list_item, row)
        if not anns:
            empty = QListWidgetItem("Bu sayfada henüz işaret yok.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.layers_list.addItem(empty)

    def _on_layer_clicked(self, list_item):
        ann = list_item.data(Qt.ItemDataRole.UserRole)
        if ann is None:
            return
        for gitem, a in self.view.item_ann_map.items():
            gitem.setSelected(a is ann)
            if a is ann:
                self.view.centerOn(gitem)

    def _delete_annotation_by_ref(self, ann):
        gitem = None
        for k, v in self.view.item_ann_map.items():
            if v is ann:
                gitem = k
                break
        if gitem is not None:
            self._delete_item(gitem)

    # =====================================================================
    # Karşılaştırma modu
    # =====================================================================
    def toggle_compare_mode(self, checked):
        self.canvas_stack.setCurrentIndex(1 if checked else 0)
        for key, b in self._tool_buttons:
            if checked:
                b.setEnabled(key == "number")
            else:
                b.setEnabled(self.active_session is not None)
        if checked:
            if self.state.tool != "number":
                self._select_tool("number", dict(self._tool_buttons)["number"])
            self.pane_left.refresh_sessions()
            self.pane_right.refresh_sessions()
            if len(self.sessions) > 1 and self.pane_right.combo.count() > 1:
                self.pane_right.combo.setCurrentIndex(1)
        else:
            self._select_tool("select", self.btn_select)

    # =====================================================================
    # Kapatma
    # =====================================================================
    def closeEvent(self, event):
        for s in self.sessions:
            s.close()
        super().closeEvent(event)


def main():
    import sys
    app = QApplication(sys.argv)
    register_app_fonts()
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
