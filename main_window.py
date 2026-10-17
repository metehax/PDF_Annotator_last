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
import sys
from typing import Dict, List, Optional, Tuple

import pymupdf as fitz

from PySide6.QtCore import (
    QEvent, QPoint, QPointF, QRectF, QSettings, QSize, Qt, QThreadPool, QTimer, QUrl,
)
from PySide6.QtGui import (
    QPainter, QAction, QColor, QDesktopServices, QImage, QIntValidator, QKeySequence, QPixmap,
    QShortcut, QUndoGroup,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
    QMessageBox, QProgressDialog, QPushButton, QSizePolicy, QSlider, QSpinBox, QSplitter,
    QStackedWidget, QTabBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from models import (
    AddAnnotationCommand, BlurAnnotation, CropPagesCommand, DocumentSession, FormFieldCommand,
    FormValuesCommand, HighlightAnnotation, ImageAnnotation, InkAnnotation, LineAnnotation,
    MoveAnnotationCommand, NoteAnnotation, NoteStateCommand, NumberAnnotation,
    RedactionAnnotation, RemoveAnnotationCommand, ResizeAnnotationCommand, ShapeAnnotation,
    TextAnnotation, ToolState, ZOrderCommand, number_to_color,
)
from pdf_engine import (
    IMAGE_EXTS, PasswordRequired, PDFDocument, image_to_pdf_document, is_image_path,
    load_image_bytes_from_path, qimage_to_png_bytes,
    resolve_font_ctx, save_project_json, load_project_json,
)
from views import ComparePane, PDFView
import ocr
from fonts import FONT_FAMILIES, register_app_fonts
from ui import theme as ui_theme
from ui.icons import icon, pixmap as icon_pixmap
from ui.overlays import FloatingBar
import docsec
from headfoot import HeadFootConfig
from ui.docdialogs import CompressDialog, DocInfoDialog, PasswordDialog, SecurityCheckDialog
from ui.comments import CommentsPanel, ask_note_text
from ui.a11y import A11yDialog
from ui.compare import CompareDiffPanel
from ui.convert import ConvertDialog
from ui.share import ShareDialog
from ui.imgpdf import ImagesPdfDialog
from ui.scanner import ScanDialog, pdf_sources
import textdiff
import forms
from ui.formui import FormFieldDialog, FormFieldEditor, FormsPanel
from ui.kvkk import KvkkDialog
from ui.workflow import WorkflowDialog
from ui.pagetools import CropPagesDialog, HeadFootDialog
from ui.palette import Command, CommandPalette
from ui.signatures import DigitalSignDialog, ReportDialog, SignatureDialog, SignatureLibrary, report_html
from ui.stamps import SCALE as STAMP_SCALE, StampLibrary, StampLibraryDialog, image_png_bytes, \
    preview_icon, render_stamp, today
from ui.toast import ToastManager
from ui.sidepanel import SidePanel
from ui.welcome import WelcomeScreen
from ui.widgets import THUMB_ASPECT_ROLE, THUMB_ROLE, ThumbnailDelegate
from ui.textdialog import TextDialog, ocr_text_width
from ui.ocrdialog import OcrDialog, _OcrTask
from ui.watermark import WatermarkDialog

CANVAS_TOP_INSET = 66      # araç kapsülü için çizim alanının üstünde bırakılan boşluk (px)
RECENT_MAX = 8

_IMG_PATTERNS = " ".join("*" + e for e in IMAGE_EXTS)
OPEN_FILTER = (f"PDF ve Resimler (*.pdf {_IMG_PATTERNS});;PDF (*.pdf);;"
               f"Resimler ({_IMG_PATTERNS})")

# (anahtar, ad, ikon, açıklama) — None: araç rayında ayraç
TOOLS = [
    ("select", "Seç", "select", "İşaretleri seç, taşı ve boyutlandır"),
    None,
    ("text", "Metin", "text", "Sayfaya yazı ekle"),
    ("edit", "Metin Düzenle", "edit_text", "Sayfadaki mevcut metni değiştir"),
    None,
    ("ink", "Kalem", "ink", "Serbest çizim"),
    ("highlight", "Fosforlu", "highlight", "Satırları vurgula"),
    ("line", "Çizgi / Ok", "line", "Çizgi ya da ok çiz"),
    ("rect", "Dörtgen", "rect", "Dörtgen çiz"),
    ("oval", "Oval", "oval", "Oval çiz"),
    None,
    ("redact", "Gizle (Sansür)", "redact", "Altındaki içeriği kalıcı olarak sil"),
    ("blur", "Bulanıklaştır", "blur", "Bir alanı bulanıklaştır ya da mozaikle (kalıcı)"),
    ("image", "Resim", "image", "Sayfaya resim yerleştir"),
    ("number", "Numarala", "number", "Sıra numarası koy"),
    ("stamp", "Damga", "stamp", "Hazır ya da kendi damganızı basın"),
    ("sign", "İmza", "sign", "Kayıtlı elektronik imzanızı tek tıkla basın"),
    ("note", "Yapışkan Not", "note", "Sayfaya not ekle; Yorumlar panelinde görünür"),
    ("crop", "Kırp / Yakala", "crop", "Bir alanı görsel olarak yakala"),
    ("form", "Form Alanı", "form", "Doldurulabilir form alanı oluştur (metin, onay, liste, tarih…)"),
]
TOOL_NAMES = {t[0]: t[1] for t in TOOLS if t}
# Tek harfli araç kısayolları (yazı yazılan alanlarda devreye girmez)
TOOL_KEYS = {"select": "V", "text": "T", "edit": "E", "ink": "P", "highlight": "H", "line": "L",
             "rect": "R", "oval": "O", "redact": "X", "image": "I", "number": "N", "stamp": "S", "crop": "C",
             "blur": "B", "note": "M", "form": "F", "sign": "G"}
APP_ID = "PDFAnnotator.Belge"


class _OpenCancelled(Exception):
    """Kullanıcı parola sorusunu iptal etti."""


# ---------------------------------------------------------------------------
# Ana pencere
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF İşaretleme Aracı")
        self.setWindowIcon(icon("app", "accent"))
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
        self.settings = QSettings("PDFAnnotator", "PDFAnnotator")
        saved_theme = self.settings.value("theme", "")
        self.dark_mode = (saved_theme == "dark") if saved_theme in ("dark", "light") \
            else ui_theme.system_prefers_dark()

        self._color_buttons_by_attr: Dict[str, list] = {}
        self._tool_buttons = []
        self._tool_pages: Dict[str, int] = {}
        self._last_shape = "rect"
        self._last_side_page = "pages"
        self._side_was_open = True
        self._kvkk_dialog = None
        self._zoom = 1.0

        # Karşılaştırma "Eşleştir modu" durumu
        self._pair_counter = 1
        self._pair_pending = None   # None ya da (pane, numara, renk)

        # Arama durumu
        self._search_results: Dict[int, list] = {}
        self._search_flat: List[Tuple[int, int]] = []   # (sayfa, o sayfadaki-indeks)
        self._search_pos = -1
        self._pending_search_tasks = []

        self.stamp_lib = StampLibrary(self.settings)
        self.sig_lib = SignatureLibrary(self.settings)
        self._build_ui()
        self._apply_style()
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        if str(self.settings.value("sidePanelOpen", "true")).lower() == "false":
            self._side_was_open = False
        self._set_ui_enabled(False)
        self._select_tool("select", self.btn_select)

    # =====================================================================
    # UI kurulumu
    # =====================================================================
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._doc_controls = []          # yalnızca belge açıkken etkin olanlar

        root.addWidget(self._build_top_bar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.side = self._build_side_panel()
        body.addWidget(self.side)

        self.workspace = QWidget()
        self.workspace.setObjectName("workspace")
        ws = QVBoxLayout(self.workspace)
        ws.setContentsMargins(0, 0, 0, 0)
        self.center_stack = QStackedWidget()
        self.welcome = WelcomeScreen()
        self.welcome.openRequested.connect(self.open_pdf)
        self.welcome.recentRequested.connect(lambda p: self.open_paths([p]))
        self.center_stack.addWidget(self.welcome)
        self.center_stack.addWidget(self._build_canvas_stack())
        ws.addWidget(self.center_stack)
        body.addWidget(self.workspace, 1)
        body_wrap = QWidget()
        body_wrap.setLayout(body)
        root.addWidget(body_wrap, 1)

        root.addWidget(self._build_status_bar())
        self.setCentralWidget(central)

        self._build_overlays()
        self.workspace.installEventFilter(self)

        self._drop_overlay = QLabel("Açmak için bırakın", central)
        self._drop_overlay.setObjectName("dropOverlay")
        self._drop_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_overlay.hide()
        self.setAcceptDrops(True)

        self.toasts = ToastManager(self.workspace)
        self.palette = CommandPalette(central, self._palette_commands)

        self._build_shortcuts()
        self._refresh_recent()

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

    def _slider_row(self, label, lo, hi, val, setter, suffix=""):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(QLabel(label))
        s = QSlider(Qt.Orientation.Horizontal)
        s.setMinimum(lo); s.setMaximum(hi); s.setValue(val)
        s.setFixedWidth(96)
        h.addWidget(s)
        val_lbl = QLabel(f"{val}{suffix}")
        val_lbl.setObjectName("valueLbl")
        val_lbl.setMinimumWidth(30)
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
        h.setSpacing(6)
        h.addWidget(QLabel(label))
        spin.setFixedWidth(72)
        h.addWidget(spin)
        return row

    def _combo_row(self, label, items, on_change):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(QLabel(label))
        combo = QComboBox()
        for text, data in items:
            combo.addItem(text, data)
        combo.currentIndexChanged.connect(lambda _i: on_change(combo.currentData()))
        h.addWidget(combo)
        return row

    def _set_edit_mode(self, mode):
        self.state.edit_mode = mode
        self._refresh_current_page()

    def _refresh_current_page(self):
        if self.active_session:
            self.view.refresh_current_page()

    def _font_row(self):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(QLabel("Yazı tipi"))
        combo = QComboBox()
        for fam in FONT_FAMILIES:
            combo.addItem(fam)
        combo.setCurrentText(self.state.font_family)
        combo.setMinimumWidth(140)
        combo.currentTextChanged.connect(lambda t: setattr(self.state, "font_family", t))
        h.addWidget(combo)
        self.font_combo_panel = combo
        return row

    def _color_row(self, label, attr):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(QLabel(label))
        btn = QPushButton()
        btn.setObjectName("colorbtn")
        btn.setFixedSize(28, 22)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("Renk seç")
        color = getattr(self.state, attr)
        btn.setStyleSheet(f"background:{color.name()};")
        btn.clicked.connect(lambda: self._pick_color(attr))
        h.addWidget(btn)
        self._color_buttons_by_attr.setdefault(attr, []).append(btn)
        return row

    def _checkbox_row(self, label, attr, tooltip=""):
        chk = QCheckBox(label)
        chk.setChecked(bool(getattr(self.state, attr)))
        if tooltip:
            chk.setToolTip(tooltip)
        chk.toggled.connect(lambda v: setattr(self.state, attr, v))
        return chk

    def _hint(self, text, warn=False):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setObjectName("hintWarn" if warn else "hint")
        return lbl

    @staticmethod
    def _icon_button(name, tooltip, slot=None, checkable=False, text=""):
        btn = QPushButton(icon(name, "toggle" if checkable else "default"), text)
        btn.setObjectName("iconbtn" if not text else "")
        btn.setToolTip(tooltip)
        btn.setIconSize(QSize(18, 18))
        btn.setCheckable(checkable)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if slot is not None:
            (btn.toggled if checkable else btn.clicked).connect(slot)
        return btn

    def _vsep(self):
        line = QFrame()
        line.setObjectName("sep")
        line.setFixedWidth(1)
        return line

    # -- menüler ------------------------------------------------------------
    def _action(self, menu, icon_name, text, slot, shortcut=None, needs_doc=True,
                checkable=False):
        a = QAction(text, self)
        if icon_name:
            a.setIcon(icon(icon_name, "toggle" if checkable else "default"))
        a.setCheckable(checkable)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutVisibleInContextMenu(True)
            self.addAction(a)            # kısayol menü kapalıyken de çalışsın
        (a.toggled if checkable else a.triggered).connect(slot)
        if menu is not None:
            menu.addAction(a)
        if needs_doc:
            self._doc_controls.append(a)
        return a

    def _build_menus(self):
        A = self._action
        page = lambda: self.active_session.current_page if self.active_session else 0  # noqa: E731

        m_file = QMenu("Dosya", self)
        A(m_file, "open", "Aç…", self.open_pdf, "Ctrl+O", needs_doc=False)
        self.recent_menu = m_file.addMenu(icon("reset"), "Son açılanlar")
        m_file.addSeparator()
        A(m_file, "save", "Kaydet", self.save_document, "Ctrl+S")
        A(m_file, "file", "PDF olarak kaydet…", self.save_pdf, "Ctrl+Shift+S")
        A(m_file, "compress", "Sıkıştırarak kaydet…", self.save_compressed)
        A(m_file, "image", "Resim olarak kaydet…", self.save_as_image)
        A(m_file, "watermark", "Filigranlı PDF olarak kaydet…", self.save_pdf_with_watermark)
        m_exp = m_file.addMenu(icon("download"), "Dışa aktar")
        self._doc_controls.append(m_exp.menuAction())
        A(m_exp, "image", "Bu sayfayı PNG", lambda: self.export_image_current("png"))
        A(m_exp, "image", "Bu sayfayı JPEG", lambda: self.export_image_current("jpg"))
        A(m_exp, "images", "Tüm sayfaları PNG (klasöre)", lambda: self.export_all_pages_images("png"))
        m_file.addSeparator()
        A(m_file, "phone", "Telefonla aktar (QR)…", self.open_share, needs_doc=False)
        A(m_file, "scan", "Belge tara (görsellerden)…", self.scan_images, needs_doc=False)
        A(m_file, "images", "Görselleri PDF'e çevir…", self.images_to_pdf, needs_doc=False)
        A(m_file, "merge", "Birleştir…", self.merge_pdfs, needs_doc=False)
        A(m_file, "images", "Her sayfayı ayrı PDF yap…", self.split_all_pages)
        A(m_file, "scissors", "Sayfa aralığını çıkar…", self.extract_page_range)
        m_file.addSeparator()
        A(m_file, "printer", "Yazdır…", self.print_document, "Ctrl+P")
        m_file.addSeparator()
        A(m_file, "project", "Projeyi kaydet (JSON)…", self.save_project)
        A(m_file, "folder", "Proje aç (JSON)…", self.open_project, needs_doc=False)
        m_file.addSeparator()
        A(m_file, "close", "Sekmeyi kapat", lambda: self.close_session(self.doc_tabbar.currentIndex()),
          "Ctrl+W")
        A(m_file, None, "Çıkış", self.close, "Ctrl+Q", needs_doc=False)

        m_edit = QMenu("Düzenle", self)
        self.act_undo = self.undo_group.createUndoAction(self, "Geri al")
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_undo.setIcon(icon("undo"))
        self.act_redo = self.undo_group.createRedoAction(self, "Yinele")
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.act_redo.setIcon(icon("redo"))
        self.addAction(self.act_undo)
        self.addAction(self.act_redo)
        m_edit.addAction(self.act_undo)
        m_edit.addAction(self.act_redo)
        m_edit.addSeparator()
        A(m_edit, "trash", "Seçileni sil", self.delete_selected, QKeySequence.StandardKey.Delete)
        m_edit.addSeparator()
        A(m_edit, "search", "Bul…", self._focus_search, "Ctrl+F")
        A(m_edit, "sliders", "Komut paleti…", self.open_palette, "Ctrl+K", needs_doc=False)

        m_view = QMenu("Görünüm", self)
        A(m_view, "zoom_in", "Yakınlaştır", lambda: self.view.animate_zoom(self.view.zoom() * 1.25), "Ctrl+=")
        A(m_view, "zoom_out", "Uzaklaştır", lambda: self.view.animate_zoom(self.view.zoom() / 1.25), "Ctrl+-")
        A(m_view, None, "Gerçek boyut (%100)", lambda: self.view.animate_zoom(1.0), "Ctrl+1")
        A(m_view, "fit_width", "Genişliğe sığdır", self.fit_width, "Ctrl+2")
        A(m_view, "fit_page", "Tam sayfa", self.fit_page, "Ctrl+0")
        m_view.addSeparator()
        A(m_view, "grid", "Kenar paneli", self._toggle_side_panel, "Ctrl+B", needs_doc=False)
        A(m_view, "comment", "Yorumlar paneli", self._show_comments_panel, "Ctrl+Shift+M")
        self.act_night = A(m_view, "contrast", "Gece modu", self.toggle_night_mode, checkable=True)
        self.act_compare = A(m_view, "compare", "Karşılaştırma modu", self.toggle_compare_mode,
                             checkable=True)
        A(m_view, "compare", "Metin farkını göster (iki sürümü karşılaştır)", self.compare_documents)
        A(m_view, "chevron_down", "Sonraki metin değişikliği", lambda: self.diff_panel.step(1), "F8")
        A(m_view, "chevron_up", "Önceki metin değişikliği", lambda: self.diff_panel.step(-1), "Shift+F8")
        m_view.addSeparator()
        A(m_view, "moon", "Açık / koyu tema", self.toggle_theme, "Ctrl+Shift+L", needs_doc=False)

        m_doc = QMenu("Belge", self)
        A(m_doc, "file_plus", "Sonrasına boş sayfa ekle", lambda: self._insert_blank_page(page() + 1))
        A(m_doc, "file_copy", "Sayfayı kopyala", lambda: self._duplicate_page(page()))
        A(m_doc, "trash", "Sayfayı sil", lambda: self._delete_page(page()))
        m_doc.addSeparator()
        A(m_doc, "rotate_cw", "Saat yönünde döndür", lambda: self._rotate_current_page(90), "Ctrl+R")
        A(m_doc, "rotate_ccw", "Saatin tersine döndür", lambda: self._rotate_current_page(-90),
          "Ctrl+Shift+R")
        m_doc.addSeparator()
        A(m_doc, "crop", "Sayfaları kırp…", self.open_crop_pages)
        A(m_doc, "headfoot", "Sayfa numarası, üstbilgi ve altbilgi…",
          lambda: self.save_pdf_with_headfoot(False))
        A(m_doc, "headfoot", "Bates numaralandır…", lambda: self.save_pdf_with_headfoot(True))
        m_doc.addSeparator()
        A(m_doc, "ocr", "OCR (metin tanıma)…", self.open_ocr_dialog)
        A(m_doc, "watermark", "Filigran ekle…", self.save_pdf_with_watermark)
        m_doc.addSeparator()
        A(m_doc, "info", "Belge bilgileri…", self.open_doc_info, "Ctrl+D")
        A(m_doc, "lock", "Parola koruması…", self.open_password)
        A(m_doc, "shield", "Güvenlik denetimi…", self.open_security_check)
        A(m_doc, "scan", "Bu belgeyi tara/kırp…", self.scan_document)
        A(m_doc, "eye", "Erişilebilirlik denetimi…", self.open_a11y)
        A(m_doc, "download", "Word'e dönüştür (.docx)…", lambda: self.open_convert("docx"))
        A(m_doc, "calc", "Excel'e dönüştür (tablolar, .xlsx)…", lambda: self.open_convert("xlsx"))
        A(m_doc, "privacy", "Kişisel verileri bul ve karart (KVKK)…", self.open_kvkk, "Ctrl+Shift+K")
        A(m_doc, "stamp", "Damga kütüphanesi…", self.open_stamp_library, needs_doc=False)
        m_doc.addSeparator()
        A(m_doc, "workflow", "Görsel iş akışı (adım zinciri)…", self.open_workflow, "Ctrl+Shift+W", needs_doc=False)

        m_form = QMenu("Form", self)
        A(m_form, "form", "Formlar paneli", lambda: self.side.show_page("forms"))
        A(m_form, "plus", "Yeni form alanı (araç)", lambda: self._tool_shortcut("form"))
        A(m_form, "sliders", "Seçili alanın özellikleri…",
          lambda: self.edit_form_field(self.forms_panel.current_field()))
        A(m_form, "trash", "Seçili alanı sil",
          lambda: self.delete_form_field(self.forms_panel.current_field()))
        m_form.addSeparator()
        A(m_form, "reset", "Formu sıfırla", self.reset_form)
        A(m_form, "calc", "Alanları yeniden hesapla", self.recalculate_form)

        m_sign = QMenu("İmza", self)
        A(m_sign, "sign", "İmza bas (araç)", lambda: self._tool_shortcut("sign"))
        A(m_sign, "plus", "Yeni elektronik imza…", self.new_signature, needs_doc=False)
        A(m_sign, "form", "İmza alanı oluştur", self.start_signature_field)
        m_sign.addSeparator()
        A(m_sign, "lock", "Dijital olarak imzala (.pfx)…", self.sign_digitally)
        A(m_sign, "shield", "İmzaları doğrula…", self.verify_signatures)

        m_help = QMenu("Yardım", self)
        A(m_help, "info", "Klavye kısayolları", self._show_shortcuts, "F1", needs_doc=False)
        m_help.addSeparator()
        A(m_help, "file", "Windows'ta 'Birlikte aç' listesine ekle…", self._register_open_with,
          needs_doc=False)
        A(m_help, "close", "'Birlikte aç' listesinden kaldır", self._unregister_open_with,
          needs_doc=False)
        m_help.addSeparator()
        A(m_help, "app", "Hakkında", self._show_about, needs_doc=False)

        # sağ üstteki "Dışa Aktar" düğmesinin menüsü
        self.export_menu = QMenu(self)
        for entry in (
            ("file", "PDF olarak kaydet", self.save_pdf),
            ("compress", "Sıkıştırarak kaydet…", self.save_compressed),
            ("image", "Resim olarak kaydet (orijinal çözünürlük)", self.save_as_image),
            ("watermark", "Filigranlı PDF olarak kaydet…", self.save_pdf_with_watermark),
            ("headfoot", "Sayfa numaralı / üstbilgili PDF olarak kaydet…",
             lambda: self.save_pdf_with_headfoot(False)),
            ("headfoot", "Bates numaralı PDF olarak kaydet…", lambda: self.save_pdf_with_headfoot(True)),
            None,
            ("image", "Bu sayfayı PNG", lambda: self.export_image_current("png")),
            ("image", "Bu sayfayı JPEG", lambda: self.export_image_current("jpg")),
            ("images", "Tüm sayfaları PNG (klasöre)", lambda: self.export_all_pages_images("png")),
            None,
            ("project", "Projeyi kaydet (JSON)", self.save_project),
        ):
            if entry is None:
                self.export_menu.addSeparator()
                continue
            icon_name, text, slot = entry
            self.export_menu.addAction(icon(icon_name), text, slot)
        self._menus = [("Dosya", m_file), ("Düzenle", m_edit), ("Görünüm", m_view),
                       ("Belge", m_doc), ("Form", m_form), ("İmza", m_sign), ("Yardım", m_help)]
        return self._menus

    # -- üst çubuk ----------------------------------------------------------
    def _build_top_bar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(50)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 0, 10, 0)
        h.setSpacing(2)

        self._logo = QLabel()
        h.addWidget(self._logo)
        h.addSpacing(6)
        for title, menu in self._build_menus():
            b = QToolButton()
            b.setObjectName("menuBtn")
            b.setText(title)
            b.setMenu(menu)
            b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            h.addWidget(b)
        h.addSpacing(12)

        self.doc_tabbar = QTabBar()
        self.doc_tabbar.setObjectName("doctabs")
        self.doc_tabbar.setTabsClosable(True)
        self.doc_tabbar.setExpanding(False)
        self.doc_tabbar.setMovable(True)
        self.doc_tabbar.setDrawBase(False)
        self.doc_tabbar.setDocumentMode(True)
        self.doc_tabbar.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.doc_tabbar.setUsesScrollButtons(True)
        self.doc_tabbar.currentChanged.connect(self._on_tab_changed)
        self.doc_tabbar.tabCloseRequested.connect(self.close_session)
        self.doc_tabbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doc_tabbar.customContextMenuRequested.connect(self._on_doctab_context_menu)
        h.addWidget(self.doc_tabbar, 1)
        h.addSpacing(8)

        self.btn_undo = self._icon_button("undo", "Geri al (Ctrl+Z)", self.act_undo.trigger)
        self.btn_undo.setEnabled(False)
        self.btn_redo = self._icon_button("redo", "Yinele (Ctrl+Y)", self.act_redo.trigger)
        self.btn_redo.setEnabled(False)
        self.undo_group.canUndoChanged.connect(self.btn_undo.setEnabled)
        self.undo_group.canRedoChanged.connect(self.btn_redo.setEnabled)
        h.addWidget(self.btn_undo)
        h.addWidget(self.btn_redo)
        h.addSpacing(6)

        self.btn_export = QToolButton()
        self.btn_export.setObjectName("secondaryTb")
        self.btn_export.setIcon(icon("download"))
        self.btn_export.setIconSize(QSize(18, 18))
        self.btn_export.setText("Dışa Aktar")
        self.btn_export.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_export.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_export.setMenu(self.export_menu)
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        h.addWidget(self.btn_export)
        h.addSpacing(4)

        self.btn_save = QPushButton(icon("save", "on_accent"), "Kaydet")
        self.btn_save.setObjectName("primary")
        self.btn_save.setIconSize(QSize(18, 18))
        self.btn_save.setToolTip("Kaydet (Ctrl+S)")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_document)
        h.addWidget(self.btn_save)
        self._doc_controls += [self.btn_export, self.btn_save]
        return bar

    # -- sol: ikon şeridi + kayan panel ------------------------------------------
    def _build_side_panel(self):
        side = SidePanel()

        self.thumb_list = QListWidget()
        self.thumb_list.setObjectName("thumbs")
        self.thumb_list.setItemDelegate(ThumbnailDelegate(self.thumb_list))
        self.thumb_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumb_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.thumb_list.verticalScrollBar().setSingleStep(24)
        self.thumb_list.setMouseTracking(True)
        self.thumb_list.currentRowChanged.connect(self._on_thumb_selected)
        self._thumb_gen = 0
        self._thumb_tasks: list = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._load_visible_thumbs)
        self.thumb_list.verticalScrollBar().valueChanged.connect(lambda _v: self._thumb_timer.start(60))
        self.thumb_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumb_list.customContextMenuRequested.connect(self._on_thumb_context_menu)
        # genişlik değişince (panel açılıp kapanınca) satır yükseklikleri yeniden hesaplansın
        self.thumb_list.viewport().installEventFilter(self)
        side.add_page("pages", "grid", "Sayfalar", self.thumb_list)

        self.toc_tree = QTreeWidget()
        self.toc_tree.setHeaderHidden(True)
        self.toc_tree.itemClicked.connect(self._on_toc_item_clicked)
        side.add_page("toc", "list", "İçindekiler", self.toc_tree)

        search_widget = QWidget()
        search_widget.setObjectName("panelBody")
        sv = QVBoxLayout(search_widget)
        sv.setContentsMargins(10, 4, 10, 10)
        sv.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Belgede ara… (Enter)")
        self.search_edit.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self.run_search)
        sv.addWidget(self.search_edit)
        srow = QHBoxLayout()
        self.btn_search = QPushButton(icon("search"), "Bul")
        self.btn_search.setObjectName("secondary")
        self.btn_search.clicked.connect(self.run_search)
        self.btn_search_prev = self._icon_button("chevron_up", "Önceki eşleşme", self.goto_prev_search_hit)
        self.btn_search_next = self._icon_button("chevron_down", "Sonraki eşleşme", self.goto_next_search_hit)
        srow.addWidget(self.btn_search, 1)
        srow.addWidget(self.btn_search_prev)
        srow.addWidget(self.btn_search_next)
        sv.addLayout(srow)
        self.lbl_search_status = QLabel("")
        self.lbl_search_status.setObjectName("hint")
        sv.addWidget(self.lbl_search_status)
        self.search_results_list = QListWidget()
        self.search_results_list.itemClicked.connect(self._on_search_result_clicked)
        sv.addWidget(self.search_results_list, 1)
        side.add_page("search", "search", "Ara", search_widget)
        self._doc_controls += [self.btn_search, self.btn_search_prev, self.btn_search_next,
                               self.search_edit]

        side.add_page("layers", "layers", "Bu sayfadaki işaretler", self._build_layers_tab())

        self.comments = CommentsPanel()
        self.comments.gotoRequested.connect(self._on_comment_goto)
        self.comments.editRequested.connect(lambda _p, ann: self.edit_note(ann))
        self.comments.replyRequested.connect(lambda _p, ann: self.reply_note(ann))
        self.comments.toggleRequested.connect(lambda _p, ann: self.toggle_note_done(ann))
        self.comments.deleteRequested.connect(lambda p, ann: self._delete_annotation_by_ref(ann, p))
        self.comments.exportRequested.connect(self.export_comments)
        side.add_page("comments", "comment", "Yorumlar", self.comments)

        self.forms_panel = FormsPanel()
        self.forms_panel.gotoRequested.connect(self._on_form_goto)
        self.forms_panel.propsRequested.connect(self.edit_form_field)
        self.forms_panel.deleteRequested.connect(self.delete_form_field)
        self.forms_panel.resetRequested.connect(self.reset_form)
        self.forms_panel.recalcRequested.connect(self.recalculate_form)
        self.forms_panel.newRequested.connect(lambda: self._tool_shortcut("form"))
        self.forms_panel.highlightToggled.connect(lambda _v: self._refresh_form_overlay())
        side.add_page("forms", "form", "Formlar", self.forms_panel)

        self.btn_theme = side.add_bottom_button("sun", "Açık temaya geç", self.toggle_theme)
        side.pageChanged.connect(lambda k: setattr(self, "_last_side_page", k) if k else None)
        side.show_page("pages", animate=False)
        return side

    def _toggle_side_panel(self):
        if self.side.is_open():
            self.side.collapse()
        else:
            self.side.show_page(self._last_side_page or "pages")

    # -- orta: normal görünüm / karşılaştırma ---------------------------------
    def _build_canvas_stack(self):
        self.view = PDFView(self.state, self.threadpool)
        self.view.setViewportMargins(0, CANVAS_TOP_INSET, 0, 0)
        self.view.setAcceptDrops(False)
        self.view.viewport().setAcceptDrops(False)
        self.view.annotationCreated.connect(self.add_annotation)
        self.view.textRequested.connect(self.on_text_requested)
        self.view.numberRequested.connect(self.on_number_requested)
        self.view.stampRequested.connect(self.on_stamp_requested)
        self.view.signRequested.connect(self.on_sign_requested)
        self.view.noteRequested.connect(self.on_note_requested)
        self.view.noteEditRequested.connect(self.edit_note)
        self.view.editTextRequested.connect(self.on_edit_text_requested)
        self.view.cropRequested.connect(self.on_crop_requested)
        self.view.imagePlaceRequested.connect(self.on_image_place_requested)
        self.view.form_hit = self._form_hit
        self.view.formFieldClicked.connect(self.on_form_field_clicked)
        self.view.formFieldRequested.connect(self.on_form_field_requested)
        self.view.formFieldEditRequested.connect(
            lambda p, pt: self.edit_form_field(forms.field_at(self._form_fields, p, pt.x(), pt.y())))
        self.view.verticalScrollBar().valueChanged.connect(lambda _v: self._finish_form_editor())
        self.view.zoomChanged.connect(lambda _z: self._finish_form_editor())
        self.view.itemsMoved.connect(self.sync_moved_items)
        self.view.resizeRequested.connect(self.on_resize_requested)
        self.view.contextMenuRequested.connect(self.show_item_context_menu)
        self.view.currentPageChanged.connect(self._on_view_page_changed)
        self.view.zoomChanged.connect(self._sync_zoom_slider)
        self.view.selectionAnnotationChanged.connect(self._on_selection_ann)
        self.view.hoveredPageChanged.connect(self._on_hover_page)
        self.view.zoomChanged.connect(lambda _z: self._place_floating())
        self.view.verticalScrollBar().valueChanged.connect(lambda _v: self._place_floating())
        self.view.horizontalScrollBar().valueChanged.connect(lambda _v: self._place_floating())

        self.pane_left = ComparePane(lambda: self.sessions, lambda: self.state,
                                     self.on_number_requested_in_pane,
                                     night_mode_provider=lambda: self.night_mode)
        self.pane_right = ComparePane(lambda: self.sessions, lambda: self.state,
                                      self.on_number_requested_in_pane,
                                      night_mode_provider=lambda: self.night_mode)
        self.diff_panel = CompareDiffPanel()
        self.diff_panel.changeActivated.connect(self._goto_change)
        self.diff_panel.refreshRequested.connect(self._run_diff)
        self.diff_panel.filtersChanged.connect(self._apply_diff_marks)
        self._diff: Optional[textdiff.DiffResult] = None
        self._diff_task: Optional[_OcrTask] = None
        self._diff_token = 0
        self._diff_timer = QTimer(self)
        self._diff_timer.setSingleShot(True)
        self._diff_timer.setInterval(350)
        self._diff_timer.timeout.connect(self._run_diff)
        self.pane_left.sessionChanged.connect(self._schedule_diff)
        self.pane_right.sessionChanged.connect(self._schedule_diff)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.pane_left)
        splitter.addWidget(self.pane_right)
        splitter.addWidget(self.diff_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([420, 420, 300])
        compare_wrap = QWidget()
        compare_wrap.setObjectName("compareWrap")
        cw = QVBoxLayout(compare_wrap)
        cw.setContentsMargins(10, CANVAS_TOP_INSET, 10, 10)
        cw.addWidget(self._framed(splitter, "KARŞILAŞTIRMA (salt okunur)"))

        self.canvas_stack = QStackedWidget()
        self.canvas_stack.addWidget(self.view)         # index 0
        self.canvas_stack.addWidget(compare_wrap)      # index 1
        return self.canvas_stack

    # -- yüzen çubuklar ------------------------------------------------------------
    def _build_overlays(self):
        ws = self.workspace
        self.capsule = FloatingBar(ws, "capsule", margins=(6, 6, 6, 6), spacing=2)
        for entry in TOOLS:
            if entry is None:
                self.capsule.add_separator()
                continue
            key, label, icon_name, desc = entry
            if key == "oval":
                self._tool_buttons.append((key, self.btn_shape))
                continue
            if key == "rect":
                b = self.capsule.add_button("rect", "<b>Şekil</b> &nbsp;R / O<br>Dörtgen ya da oval çiz",
                                            checkable=True, size=36, icon_size=20,
                                            object_name="toolbtn")
                b.clicked.connect(lambda _=False, b=b: self._select_tool(self._last_shape, b))
                self.btn_shape = b
            else:
                b = self.capsule.add_button(icon_name, f"<b>{label}</b> &nbsp;{TOOL_KEYS[key]}<br>{desc}",
                                            checkable=True,
                                            size=36, icon_size=20, object_name="toolbtn")
                b.clicked.connect(lambda _=False, k=key, b=b: self._select_tool(k, b))
            self._tool_buttons.append((key, b))
        self.btn_select = dict(self._tool_buttons)["select"]

        self.prop_bar = FloatingBar(ws, "propBar", margins=(14, 6, 8, 6))
        self.prop_bar.add(self._build_properties_stack())

        self.sel_bar = FloatingBar(ws, "miniBar", margins=(4, 4, 4, 4))
        self.sel_bar.add_button("bring_front", "En öne getir", lambda: self._sel_zorder(True))
        self.sel_bar.add_button("send_back", "En arkaya gönder", lambda: self._sel_zorder(False))
        self.sel_bar.add_separator()
        self.sel_bar.add_button("trash", "Sil (Del)", self.delete_selected, role="danger")
        self.sel_bar.hide()
        self._sel_ann = None

        self.page_bar = FloatingBar(ws, "miniBar", margins=(4, 4, 4, 4))
        hp = lambda: self._hover_page  # noqa: E731
        self.page_bar.add_button("rotate_ccw", "Saatin tersine döndür", lambda: self._rotate_page(hp(), -90))
        self.page_bar.add_button("rotate_cw", "Saat yönünde döndür", lambda: self._rotate_page(hp(), 90))
        self.page_bar.add_separator()
        self.page_bar.add_button("file_plus", "Sonrasına boş sayfa ekle", lambda: self._insert_blank_page(hp() + 1))
        self.page_bar.add_button("file_copy", "Sayfayı kopyala", lambda: self._duplicate_page(hp()))
        self.page_bar.add_separator()
        self.page_bar.add_button("trash", "Sayfayı sil", lambda: self._delete_page(hp()), role="danger")
        self.page_bar.hide()
        self.page_bar.installEventFilter(self)
        self._hover_page = -1
        self._page_bar_timer = QTimer(self)
        self._page_bar_timer.setSingleShot(True)
        self._page_bar_timer.setInterval(300)
        self._page_bar_timer.timeout.connect(self._maybe_hide_page_bar)

    # -- alt durum çubuğu -------------------------------------------------------
    def _build_status_bar(self):
        bar = QFrame()
        bar.setObjectName("statusbar")
        bar.setFixedHeight(36)
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 0, 8, 0)
        h.setSpacing(2)

        self.status = QLabel("Başlamak için bir dosya açın ya da pencereye sürükleyin.")
        self.status.setObjectName("status")
        # uzun yollar sağdaki kontrolleri itmesin: sığmayan kısım kırpılır
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status.setMinimumWidth(0)
        h.addWidget(self.status, 1)

        self.btn_prev = self._icon_button(
            "chevron_left", "Önceki sayfa",
            lambda: self.goto_page(self.active_session.current_page - 1) if self.active_session else None)
        self.page_edit = QLineEdit("0")
        self.page_edit.setObjectName("pageEdit")
        self.page_edit.setFixedWidth(46)
        self.page_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_edit.setValidator(QIntValidator(1, 99999, self))
        self.page_edit.setToolTip("Sayfa numarasını yazıp Enter'a basın")
        self.page_edit.returnPressed.connect(
            lambda: self.goto_page(int(self.page_edit.text() or 1) - 1) if self.active_session else None)
        self.lbl_page_total = QLabel("/ 0")
        self.lbl_page_total.setObjectName("pageTotal")
        self.btn_next = self._icon_button(
            "chevron_right", "Sonraki sayfa",
            lambda: self.goto_page(self.active_session.current_page + 1) if self.active_session else None)
        for w in (self.btn_prev, self.page_edit, self.lbl_page_total, self.btn_next):
            h.addWidget(w)
        h.addWidget(self._vsep())

        self.btn_fit_width = self._icon_button("fit_width", "Genişliğe sığdır (Ctrl+2)", self.fit_width)
        self.btn_fit_page = self._icon_button("fit_page", "Tam sayfa (Ctrl+0)", self.fit_page)
        h.addWidget(self.btn_fit_width)
        h.addWidget(self.btn_fit_page)
        h.addWidget(self._vsep())

        self.btn_zoom_out = self._icon_button(
            "zoom_out", "Uzaklaştır (Ctrl -)", lambda: self.view.animate_zoom(self.view.zoom() / 1.25))
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 800)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider_changed)
        self.btn_zoom_in = self._icon_button(
            "zoom_in", "Yakınlaştır (Ctrl +)", lambda: self.view.animate_zoom(self.view.zoom() * 1.25))
        self.lbl_zoom = QToolButton()
        self.lbl_zoom.setObjectName("zoomBtn")
        self.lbl_zoom.setText("100%")
        self.lbl_zoom.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.lbl_zoom.setCursor(Qt.CursorShape.PointingHandCursor)
        zmenu = QMenu(self.lbl_zoom)
        for pct in (50, 75, 100, 125, 150, 200, 300, 400):
            zmenu.addAction(f"%{pct}", lambda p=pct: self.view.animate_zoom(p / 100.0))
        zmenu.addSeparator()
        zmenu.addAction(icon("fit_width"), "Genişliğe sığdır", self.fit_width)
        zmenu.addAction(icon("fit_page"), "Tam sayfa", self.fit_page)
        self.lbl_zoom.setMenu(zmenu)
        for w in (self.btn_zoom_out, self.zoom_slider, self.btn_zoom_in, self.lbl_zoom):
            h.addWidget(w)
        h.addWidget(self._vsep())

        self.btn_night = QToolButton()
        self.btn_night.setObjectName("iconbtn")
        self.btn_night.setDefaultAction(self.act_night)
        self.btn_night.setIconSize(QSize(18, 18))
        self.btn_night.setToolTip("Gece modu: PDF renklerini ters çevirir")
        self.btn_compare = QToolButton()
        self.btn_compare.setObjectName("iconbtn")
        self.btn_compare.setDefaultAction(self.act_compare)
        self.btn_compare.setIconSize(QSize(18, 18))
        self.btn_compare.setToolTip("İki belgeyi yan yana karşılaştır")
        h.addWidget(self.btn_night)
        h.addWidget(self.btn_compare)

        self._doc_controls += [self.btn_prev, self.btn_next, self.page_edit, self.btn_fit_width,
                               self.btn_fit_page, self.btn_zoom_out, self.zoom_slider,
                               self.btn_zoom_in, self.lbl_zoom]
        return bar

    def _build_properties_stack(self):
        self.prop_stack = QStackedWidget()

        def page(*rows):
            """Yatay özellik çubuğu sayfası. İpucu etiketleri çubuğa eklenmez;
            sondaki (i) düğmesinin ipucunda gösterilir (kontrol yoksa satır içi)."""
            w = QWidget()
            w.setObjectName("propPage")
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(14)
            title = QLabel()
            title.setObjectName("propTitle")
            h.addWidget(title)
            sep = QFrame()
            sep.setObjectName("barSep")
            sep.setFixedSize(1, 22)
            h.addWidget(sep)
            hints, warn, controls = [], False, 0
            for r in rows:
                if isinstance(r, QLabel) and r.objectName() in ("hint", "hintWarn"):
                    hints.append(r.text())
                    warn = warn or r.objectName() == "hintWarn"
                    continue
                h.addWidget(r)
                controls += 1
            if hints and controls == 0:
                inline = QLabel(hints[0].replace("\n", " "))
                inline.setObjectName("hint")
                inline.setWordWrap(True)
                inline.setMaximumWidth(520)
                h.addWidget(inline)
                hints = hints[1:]
            if hints:
                info = QToolButton()
                info.setObjectName("barBtn")
                info.setIcon(icon("warning" if warn else "info", "accent" if not warn else "default"))
                info.setIconSize(QSize(18, 18))
                info.setFixedSize(30, 30)
                info.setToolTip("<br><br>".join(t.replace("\n", "<br>") for t in hints))
                h.addWidget(info)
            w.title_label = title
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

        seg = QWidget()
        sh = QHBoxLayout(seg)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(2)
        self.btn_shape_rect = QPushButton(icon("rect", "toggle"), "Dörtgen")
        self.btn_shape_oval = QPushButton(icon("oval", "toggle"), "Oval")
        for b, k in ((self.btn_shape_rect, "rect"), (self.btn_shape_oval, "oval")):
            b.setCheckable(True)
            b.setObjectName("segBtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=k: self._select_tool(k, self.btn_shape))
            sh.addWidget(b)
        shape_page = page(
            seg,
            self._color_row("Dolgu", "fill_color"),
            self._color_row("Kenar", "stroke_color"),
            self._slider_row("Kenar Kal.", 0, 15, int(self.state.pen_width),
                             lambda v: setattr(self.state, "pen_width", float(v))),
            self._slider_row("Dolgu Opk.", 5, 100, int(self.state.fill_opacity * 100),
                             lambda v: setattr(self.state, "fill_opacity", v / 100.0), "%"),
            self._hint("Sadece görsel bir katmandır; altındaki metin "
                      "silinmez. Kalıcı gizleme için 'Gizle (Sansür)' aracını kullanın.", warn=True),
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
                      "Shift: yapışmayı geçici kapatır."),
            self._hint("Bu da sadece görseldir; altındaki metin silinmez.", warn=True),
        ))
        self._tool_pages["highlight"] = idx; idx += 1

        self.prop_stack.addWidget(page(
            self._color_row("Kutu Rengi", "redact_color"),
            self._hint("Dışa aktarırken kutunun altındaki metin/görsel "
                      "PDF'ten KALICI olarak silinir. Kırmızı kesikli çerçeve "
                      "ile gösterilir. Dikkatli çizin.", warn=True),
        ))
        self._tool_pages["redact"] = idx; idx += 1

        self.prop_stack.addWidget(page(
            self._combo_row("Biçim", [("Bulanık", "blur"), ("Mozaik", "pixel")],
                            lambda v: setattr(self.state, "blur_mode", v)),
            self._slider_row("Güç", 2, 40, int(self.state.blur_strength),
                             lambda v: setattr(self.state, "blur_strength", float(v))),
            self._hint("Bir alanı sürükleyip bırakın. Dışa aktarırken alan görüntü olarak "
                      "bulanıklaştırılır ve altındaki metin PDF'ten KALICI silinir; mavi "
                      "taralı kutu yalnızca düzenleme sırasında görünür. Okunmaması şart olan "
                      "veriler için yine de 'Gizle' aracı daha güvenlidir.", warn=True),
        ))
        self._tool_pages["blur"] = idx; idx += 1

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
        reset_btn = QPushButton(icon("reset"), "Sayacı Sıfırla")
        reset_btn.setObjectName("secondary")
        reset_btn.clicked.connect(self.reset_number_counter)

        self.chk_pair = QCheckBox("Eşleştir modu (karşılaştırmada)")
        self.chk_pair.setToolTip("Açıkken: bir panele koyduğun numarayı diğer "
                                 "panele de aynı numara/renkle koyabilirsin.")
        self.chk_pair.toggled.connect(self._on_pair_toggled)
        reset_pair_btn = QPushButton(icon("reset"), "Eşleştirme Sayacını Sıfırla")
        reset_pair_btn.setObjectName("secondary")
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
                      "1) Bir panele numara koy.\n2) Diğer panele koy: aynı numara/renk.\n"
                      "3) Sayaç kendiliğinden artar."),
        ))
        self._tool_pages["number"] = idx; idx += 1

        self.stamp_combo = QComboBox()
        self.stamp_combo.setIconSize(QSize(104, 26))
        self.stamp_combo.setMinimumWidth(150)
        self.stamp_combo.setToolTip("Basılacak damga")
        self._fill_stamp_combo()
        self.chk_stamp_sub = QCheckBox("Ad ve tarih")
        self.chk_stamp_sub.setChecked(str(self.settings.value("stampSub", "true")).lower() != "false")
        self.chk_stamp_sub.toggled.connect(lambda v: (self.settings.setValue("stampSub", bool(v)),
                                                      self.stamp_name.setEnabled(v)))
        import getpass
        self.stamp_name = QLineEdit(str(self.settings.value("author", "") or getpass.getuser()))
        self.stamp_name.setPlaceholderText("Ad Soyad")
        self.stamp_name.setFixedWidth(130)
        self.stamp_name.setEnabled(self.chk_stamp_sub.isChecked())
        self.stamp_name.editingFinished.connect(
            lambda: self.settings.setValue("author", self.stamp_name.text().strip()))
        self.chk_stamp_slant = QCheckBox("Eğik")
        self.chk_stamp_slant.setChecked(str(self.settings.value("stampSlant", "false")).lower() == "true")
        self.chk_stamp_slant.toggled.connect(lambda v: self.settings.setValue("stampSlant", bool(v)))
        btn_lib = QPushButton(icon("stamp"), "Kütüphane…")
        btn_lib.setObjectName("secondary")
        btn_lib.clicked.connect(self.open_stamp_library)
        self.prop_stack.addWidget(page(
            self.stamp_combo, self.chk_stamp_sub, self.stamp_name, self.chk_stamp_slant, btn_lib,
            self._hint("Sayfada damganın ortalanacağı yere tıklayın. Bastıktan sonra Seç aracıyla "
                      "taşıyıp köşelerinden boyutlandırabilirsiniz. 'Kütüphane…' ile logolu "
                      "kendi damgalarınızı oluşturabilirsiniz."),
        ))
        self._tool_pages["stamp"] = idx; idx += 1

        self.sig_combo = QComboBox()
        self.sig_combo.setIconSize(QSize(110, 32))
        self.sig_combo.setMinimumWidth(150)
        self.sig_combo.setToolTip("Basılacak imza")
        btn_sig_new = QPushButton(icon("plus"), "Yeni imza…")
        btn_sig_new.clicked.connect(self.new_signature)
        btn_sig_del = QPushButton(icon("trash"), "")
        btn_sig_del.setToolTip("Seçili imzayı kütüphaneden sil")
        btn_sig_del.clicked.connect(self.delete_signature)
        self.chk_sig_date = QCheckBox("Tarih ekle")
        self.chk_sig_date.setChecked(str(self.settings.value("signDate", "false")).lower() == "true")
        self.chk_sig_date.toggled.connect(lambda v: self.settings.setValue("signDate", bool(v)))
        self._fill_sig_combo()
        self.sig_combo.currentIndexChanged.connect(
            lambda _i: self.settings.setValue("signId", self.sig_combo.currentData() or ""))
        self.prop_stack.addWidget(page(
            self.sig_combo, btn_sig_new, btn_sig_del, self.chk_sig_date,
            self._hint("İmzanızı bir kez çizin, yazın ya da görselden alın; sonra sayfada imzanın "
                      "ortalanacağı yere tıklayın. Bu görsel (elektronik) imzadır; hukuki geçerli "
                      "dijital imza için İmza › Dijital olarak imzala."),
        ))
        self._tool_pages["sign"] = idx; idx += 1

        self.prop_stack.addWidget(page(
            self._hint("Bir alan sürükleyip bırakın; açılan pencereden PNG "
                      "olarak kaydedebilir ya da panoya kopyalayabilirsiniz.\n\n"
                      "Bu araç PDF'i DEĞİŞTİRMEZ — yalnızca seçilen bölgeyi "
                      "yüksek çözünürlükte görsel olarak çıkarır."),
        ))
        self._tool_pages["crop"] = idx; idx += 1

        self.prop_stack.addWidget(page(
            self._color_row("Not rengi", "note_color"),
            self._hint("Sayfada notun yerini tıklayın, metni yazın. Notu çift tıklayarak "
                      "düzenleyebilirsiniz. Tüm notlar sol şeritteki 'Yorumlar' panelinde "
                      "listelenir; yanıtlanır ve 'çözüldü' işaretlenir. PDF'e gerçek bir "
                      "not açıklaması olarak yazılır, başka okuyucularda da görünür."),
        ))
        self._tool_pages["note"] = idx; idx += 1

        self._form_kind_row = self._combo_row("Alan türü", [(t, k) for k, t in forms.FIELD_KINDS],
                                              lambda v: setattr(self.state, "form_kind", v))
        self.prop_stack.addWidget(page(
            self._form_kind_row,
            self._checkbox_row("Özellikleri sor", "form_ask",
                               "Kapalıysa alan varsayılan adla hemen oluşturulur"),
            self._hint("Sayfada bir kutu çizin (onay/radyo için tıklamak yeter). Mevcut bir alana "
                      "tıklarsanız özellikleri açılır. Doldurmak için Seç aracıyla alana tıklayın; "
                      "tüm alanlar sol şeritteki 'Formlar' panelinde listelenir."),
        ))
        self._tool_pages["form"] = idx; idx += 1

        for key, idx in self._tool_pages.items():
            pg = self.prop_stack.widget(idx)
            if not pg.title_label.text():
                pg.title_label.setText("Şekil" if key in ("rect", "oval") else TOOL_NAMES[key])
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

        for key, letter in TOOL_KEYS.items():
            sc = QShortcut(QKeySequence(letter), self)
            sc.activated.connect(lambda k=key: self._tool_shortcut(k))
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.activated.connect(self._on_escape)
        act("Right", lambda: self.goto_page(self.active_session.current_page + 1)
            if self.active_session else None)
        act("Left", lambda: self.goto_page(self.active_session.current_page - 1)
            if self.active_session else None)

    # =====================================================================
    # Tema (renk şeması) + Gece Modu (PDF piksel ters çevirme)
    # =====================================================================
    def _apply_style(self):
        self.setStyleSheet(ui_theme.apply(QApplication.instance(), "dark" if self.dark_mode else "light"))
        t = ui_theme.current()
        self.view.set_canvas_color(QColor(t["canvas"]))
        self.btn_theme.setIcon(icon("sun" if self.dark_mode else "moon"))
        self.btn_theme.setToolTip("Açık temaya geç" if self.dark_mode else "Koyu temaya geç")
        self._logo.setPixmap(icon_pixmap("app", 22, t["accent"], self.devicePixelRatioF()))
        for bar in self.findChildren(FloatingBar):
            bar.refresh_theme()
        self.welcome.refresh_theme()
        for w in self.findChildren(QWidget):
            w.update()

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.settings.setValue("theme", "dark" if self.dark_mode else "light")
        self._apply_style()

    def toggle_night_mode(self, checked: bool):
        self.night_mode = checked
        self.view.set_invert(checked)
        self.pane_left._render()
        self.pane_right._render()

    def _set_ui_enabled(self, on):
        for w in self._doc_controls:
            w.setEnabled(on)
        for _, b in self._tool_buttons:
            b.setEnabled(on)
        self.center_stack.setCurrentIndex(1 if on else 0)
        self.capsule.setVisible(on)
        for b in self.side.page_buttons():
            b.setEnabled(on)
        if on and not self.side.is_open() and self._side_was_open:
            self.side.show_page(self._last_side_page or "pages")
        elif not on:
            self._side_was_open = self.side.is_open() or getattr(self, "_side_was_open", True)
            self.side.collapse(animate=False)
        if not on:
            self.sel_bar.hide()
            self.page_bar.hide()
            self._update_page_label(-1, 0)
        self._layout_overlays()

    # =====================================================================
    # Yüzen çubuklar: araç kapsülü, özellik çubuğu, seçim ve sayfa çubukları
    # =====================================================================
    def eventFilter(self, obj, ev):
        et = ev.type()
        if obj is getattr(self, "workspace", None) and et == QEvent.Type.Resize:
            self._layout_overlays()
            if hasattr(self, "toasts"):
                self.toasts.relayout()
        elif obj is getattr(self, "page_bar", None) and et == QEvent.Type.Leave:
            self._page_bar_timer.start()
        elif et == QEvent.Type.Resize and hasattr(self, "thumb_list") and obj is self.thumb_list.viewport():
            if ev.oldSize().width() != ev.size().width():
                QTimer.singleShot(0, self.thumb_list.doItemsLayout)
                self._thumb_timer.start(80)
        return super().eventFilter(obj, ev)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._drop_overlay.isVisible():
            self._drop_overlay.setGeometry(self.centralWidget().rect())
        if self.palette.isVisible():
            self.palette.reposition()

    def _layout_overlays(self):
        if not hasattr(self, "capsule"):
            return
        W = self.workspace.width()
        self.capsule.fit()
        self.capsule.move(max(8, (W - self.capsule.width()) // 2), 10)
        self.capsule.raise_()
        self._update_prop_bar()
        self._place_floating()

    def _update_prop_bar(self):
        if not hasattr(self, "prop_bar"):
            return
        tool = self.state.tool
        show = (self.active_session is not None and tool != "select"
                and not self.act_compare.isChecked() and tool in self._tool_pages)
        if not show:
            self.prop_bar.hide()
            return
        cur = self._tool_pages[tool]
        # QStackedWidget en geniş sayfaya göre boyutlanır; yalnızca aktif sayfa sayılsın
        for i in range(self.prop_stack.count()):
            pol = QSizePolicy.Policy.Preferred if i == cur else QSizePolicy.Policy.Ignored
            self.prop_stack.widget(i).setSizePolicy(pol, pol)
        self.prop_stack.setCurrentIndex(cur)
        self.prop_stack.adjustSize()
        self.prop_bar.fit(max_width=self.workspace.width() - 24)
        W = self.workspace.width()
        self.prop_bar.move(max(12, (W - self.prop_bar.width()) // 2),
                           self.capsule.y() + self.capsule.height() + 8)
        self.prop_bar.show()
        self.prop_bar.raise_()

    def _to_workspace(self, scene_pt):
        vp = self.view.mapFromScene(scene_pt)
        return self.view.viewport().mapTo(self.workspace, vp)

    def _place_floating(self):
        if not hasattr(self, "sel_bar"):
            return
        if self._sel_ann is None and self._hover_page < 0:
            # kaydırma sırasında sık çağrılır: gösterilecek bir şey yoksa hemen çık
            if self.sel_bar.isVisible():
                self.sel_bar.hide()
            if self.page_bar.isVisible():
                self.page_bar.hide()
            return
        top_limit = CANVAS_TOP_INSET + 8
        if self.prop_bar.isVisible():
            top_limit = max(top_limit, self.prop_bar.geometry().bottom() + 8)
        W = self.workspace.width()
        # seçim çubuğu: seçili işaretin üstünde (yer yoksa altında)
        gitem = self.view.ann_item_map.get(id(self._sel_ann)) if self._sel_ann is not None else None
        if gitem is not None and gitem.scene() is not None and self.canvas_stack.currentIndex() == 0:
            r = gitem.sceneBoundingRect()
            self.sel_bar.fit()
            top = self._to_workspace(QPointF(r.center().x(), r.top()))
            bottom = self._to_workspace(QPointF(r.center().x(), r.bottom()))
            y = top.y() - self.sel_bar.height() - 10
            if y < top_limit:
                y = bottom.y() + 10
            x = min(max(8, top.x() - self.sel_bar.width() // 2), W - self.sel_bar.width() - 8)
            self.sel_bar.move(x, y)
            self.sel_bar.setVisible(top_limit <= y <= self.workspace.height() - self.sel_bar.height())
            self.sel_bar.raise_()
        else:
            self.sel_bar.hide()
        # sayfa çubuğu: üzerinde durulan sayfanın sağ üst köşesi
        s = self.active_session
        if self._hover_page >= 0 and s and self._hover_page < s.pdf.page_count \
                and self.state.tool == "select" and self.canvas_stack.currentIndex() == 0:
            r = self.view.page_rect_in_scene(self._hover_page)
            self.page_bar.fit()
            tr = self._to_workspace(r.topRight())
            br = self._to_workspace(r.bottomRight())
            x = min(tr.x() - self.page_bar.width() - 10, W - self.page_bar.width() - 8)
            y = max(tr.y() + 10, top_limit)
            visible = y + self.page_bar.height() < br.y() - 10
            self.page_bar.move(max(8, x), y)
            self.page_bar.setVisible(visible)
            self.page_bar.raise_()
        else:
            self.page_bar.hide()

    def _on_selection_ann(self, ann):
        self._sel_ann = ann if self.state.tool == "select" else None
        self._place_floating()

    def _sel_zorder(self, to_front):
        s = self.active_session
        ann = self._sel_ann
        if not s or ann is None:
            return
        page = self.view.page_of_annotation(ann)
        s.undo_stack.push(ZOrderCommand(s, s.current_page if page is None else page, ann, to_front,
                                        on_change=self._on_session_change))

    def _on_hover_page(self, idx):
        if idx >= 0:
            self._page_bar_timer.stop()
            if idx != self._hover_page:
                self._hover_page = idx
                self._place_floating()
            elif not self.page_bar.isVisible():
                self._place_floating()
        else:
            self._page_bar_timer.start()

    def _maybe_hide_page_bar(self):
        if self.page_bar.underMouse():
            return
        self._hover_page = -1
        self.page_bar.hide()

    def _toast_saved(self, text, path, folder=False):
        target = path if folder else os.path.dirname(os.path.abspath(path))

        def reveal():
            if not folder and sys.platform == "win32":
                import subprocess
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(target))

        self.toasts.show(f"{text}<br><span style='color:gray'>{os.path.basename(path) or path}</span>",
                         "success", action=("Klasörde göster", reveal))

    # -- araç kısayolları / komut paleti ----------------------------------------
    def _tool_shortcut(self, key):
        if not self.active_session or self.palette.isVisible():
            return
        if self.act_compare.isChecked() and key != "number":
            return
        self._select_tool(key, dict(self._tool_buttons)[key])

    def _on_escape(self):
        if self.palette.isVisible():
            self.palette.close_palette()
            return
        if getattr(self, "_form_editor", None) is not None:
            self._form_editor.cancel()
            return
        if not self.active_session:
            return
        self.view.scene_obj.clearSelection()
        if self.state.tool != "select" and not self.act_compare.isChecked():
            self._select_tool("select", self.btn_select)

    def open_palette(self):
        self.palette.open()

    def _palette_commands(self, query):
        cmds = []
        s = self.active_session
        q = query.strip().lower()
        digits = "".join(ch for ch in q if ch.isdigit())
        if s and digits and (q.isdigit() or q.startswith(("sayfa", "s ", "p "))):
            n = int(digits)
            if 1 <= n <= s.pdf.page_count:
                cmds.append(Command(f"Sayfaya git: {n}", lambda n=n: self.goto_page(n - 1),
                                    "Gezinme", "chevron_right"))
        if s:
            for entry in TOOLS:
                if entry is None:
                    continue
                key, label, icon_name, _desc = entry
                if self.act_compare.isChecked() and key != "number":
                    continue
                cmds.append(Command(f"{label} aracı", lambda k=key: self._tool_shortcut(k), "Araç",
                                    icon_name, TOOL_KEYS[key]))
            for key, title, icon_name in (("pages", "Sayfalar", "grid"), ("toc", "İçindekiler", "list"),
                                          ("search", "Ara", "search"), ("layers", "İşaretler", "layers"),
                                          ("forms", "Formlar", "form")):
                cmds.append(Command(f"{title} panelini göster", lambda k=key: self.side.show_page(k),
                                    "Panel", icon_name))

        def walk(menu, prefix):
            for a in menu.actions():
                if a.isSeparator():
                    continue
                sub = a.menu()
                if sub is not None:
                    if sub is self.recent_menu:
                        continue
                    walk(sub, a.text())
                    continue
                if not a.isEnabled() or not a.text():
                    continue
                text = a.text().replace("&", "").rstrip("…").strip()
                if a.isCheckable():
                    text += " (açık)" if a.isChecked() else ""
                cmds.append(Command(text, a.trigger, prefix, None,
                                    a.shortcut().toString(QKeySequence.SequenceFormat.NativeText),
                                    qicon=a.icon()))

        for title, menu in self._menus:
            walk(menu, title)
        for p in self._recent_paths()[:RECENT_MAX]:
            if os.path.exists(p):
                cmds.append(Command(f"Aç: {os.path.basename(p)}", lambda p=p: self.open_paths([p]),
                                    "Son açılanlar", "file" if p.lower().endswith(".pdf") else "image"))
        return cmds

    # -- Windows "Birlikte aç" kaydı ---------------------------------------------
    @staticmethod
    def _launcher():
        exe = sys.executable
        if os.path.basename(exe).lower() == "python.exe":
            cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(cand):
                exe = cand
        return exe, os.path.abspath(__file__)

    def _register_open_with(self):
        if sys.platform != "win32":
            self.toasts.show("Bu özellik yalnızca Windows'ta kullanılabilir.", "info")
            return
        exts = [".pdf"] + list(IMAGE_EXTS)
        ret = QMessageBox.question(
            self, "'Birlikte aç' listesine ekle",
            "PDF ve resim dosyalarına sağ tıklayıp <b>Birlikte aç</b> dediğinizde bu uygulama "
            "da listede görünsün mü?<br><br>Yalnızca sizin kullanıcı hesabınız için kayıt yapılır "
            "(yönetici izni gerekmez); varsayılan uygulamanız değişmez.<br>"
            f"<span style='color:gray'>Dosya türleri: {', '.join(exts)}</span>")
        if ret != QMessageBox.StandardButton.Yes:
            return
        import winreg
        exe, script = self._launcher()
        base = r"Software\Classes"
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{APP_ID}") as k:
                winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "PDF İşaretleme Aracı belgesi")
                winreg.SetValueEx(k, "FriendlyTypeName", 0, winreg.REG_SZ, "PDF İşaretleme Aracı belgesi")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{APP_ID}\DefaultIcon") as k:
                winreg.SetValueEx(k, None, 0, winreg.REG_SZ, f"{exe},0")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{APP_ID}\shell\open") as k:
                winreg.SetValueEx(k, "FriendlyAppName", 0, winreg.REG_SZ, "PDF İşaretleme Aracı")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{APP_ID}\shell\open\command") as k:
                winreg.SetValueEx(k, None, 0, winreg.REG_SZ, f'"{exe}" "{script}" "%1"')
            for ext in exts:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{ext}\OpenWithProgids") as k:
                    winreg.SetValueEx(k, APP_ID, 0, winreg.REG_NONE, b"")
            import ctypes
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
            self.toasts.show("'Birlikte aç' listesine eklendi. Bir dosyaya sağ tıklayıp deneyebilirsiniz.",
                             "success", timeout_ms=5000)
        except OSError as ex:
            QMessageBox.critical(self, "Hata", f"Kayıt yapılamadı:\n{ex}")

    def _unregister_open_with(self):
        if sys.platform != "win32":
            return
        import winreg
        base = r"Software\Classes"

        def delete_tree(root, path):
            try:
                with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
                    while True:
                        try:
                            sub = winreg.EnumKey(k, 0)
                        except OSError:
                            break
                        delete_tree(root, path + "\\" + sub)
                winreg.DeleteKey(root, path)
            except FileNotFoundError:
                pass

        delete_tree(winreg.HKEY_CURRENT_USER, rf"{base}\{APP_ID}")
        for ext in [".pdf"] + list(IMAGE_EXTS):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{base}\{ext}\OpenWithProgids", 0,
                                    winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, APP_ID)
            except FileNotFoundError:
                pass
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        self.toasts.show("'Birlikte aç' listesinden kaldırıldı.", "info")

    def _update_page_label(self, index, count):
        self.page_edit.setText(str(index + 1) if count else "")
        self.lbl_page_total.setText(f"/ {count}")

    # =====================================================================
    # Dosya açma: iletişim kutusu, son açılanlar, sürükle-bırak
    # =====================================================================
    def open_paths(self, paths):
        last_idx = None
        for p in paths:
            try:
                self._open_path_as_session(p)
                last_idx = len(self.sessions) - 1
            except _OpenCancelled:
                continue
            except Exception as ex:
                QMessageBox.critical(self, "Hata", f"'{p}' açılamadı:\n{ex}")
        if last_idx is None:
            return
        self._set_ui_enabled(True)
        self.refresh_doc_tabs()
        self.switch_session(last_idx)

    def _recent_paths(self):
        v = self.settings.value("recent", [])
        if isinstance(v, str):
            v = [v]
        return [p for p in (v or []) if isinstance(p, str)]

    def _add_recent(self, path):
        path = os.path.abspath(path)
        items = [p for p in self._recent_paths() if os.path.normcase(p) != os.path.normcase(path)]
        self.settings.setValue("recent", [path] + items[:RECENT_MAX - 1])
        self._refresh_recent()

    def _refresh_recent(self):
        paths = [p for p in self._recent_paths() if os.path.exists(p)]
        self.welcome.set_recent(paths)
        self.recent_menu.clear()
        for p in paths:
            self.recent_menu.addAction(icon("file" if p.lower().endswith(".pdf") else "image"),
                                       os.path.basename(p), lambda path=p: self.open_paths([path]))
        if not paths:
            a = self.recent_menu.addAction("(henüz yok)")
            a.setEnabled(False)

    @staticmethod
    def _dropped_paths(mime):
        if not mime.hasUrls():
            return []
        out = []
        for url in mime.urls():
            path = url.toLocalFile()
            if path and (path.lower().endswith(".pdf") or is_image_path(path)) and os.path.isfile(path):
                out.append(path)
        return out

    def dragEnterEvent(self, e):
        if self._dropped_paths(e.mimeData()):
            e.acceptProposedAction()
            self._drop_overlay.setGeometry(self.centralWidget().rect())
            self._drop_overlay.show()
            self._drop_overlay.raise_()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if self._dropped_paths(e.mimeData()):
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._drop_overlay.hide()

    def dropEvent(self, e):
        self._drop_overlay.hide()
        paths = self._dropped_paths(e.mimeData())
        if paths:
            e.acceptProposedAction()
            self.open_paths(paths)

    # =====================================================================
    # Yardım
    # =====================================================================
    def _show_shortcuts(self):
        rows = [
            ("Ctrl+O", "Dosya aç"), ("Ctrl+S", "Kaydet"), ("Ctrl+Shift+S", "PDF olarak kaydet"),
            ("Ctrl+W", "Sekmeyi kapat"), ("Ctrl+Z / Ctrl+Y", "Geri al / Yinele"),
            ("Del", "Seçileni sil"), ("Ctrl+F", "Bul"), ("Ctrl+B", "Kenar paneli"),
            ("Ctrl + tekerlek", "Yakınlaştır / uzaklaştır"), ("Ctrl+= / Ctrl+-", "Yakınlaştır / uzaklaştır"),
            ("Ctrl+0 / Ctrl+1 / Ctrl+2", "Tam sayfa / %100 / Genişliğe sığdır"),
            ("Boşluk + sürükle", "Sayfayı kaydır"), ("Orta tuş + sürükle", "Sayfayı kaydır"),
            ("Ctrl+K", "Komut paleti"), ("Esc", "Seç aracına dön / seçimi kaldır"),
            ("Ctrl+Shift+K", "Kişisel verileri bul ve karart"), ("S", "Damga aracı"),
            ("V T E P H L R O X B I N S M C", "Araçlar: Seç, Metin, Metin Düzenle, Kalem, Fosforlu, Çizgi, "
                                          "Dörtgen, Oval, Gizle, Bulanıklaştır, Resim, Numarala, Damga, "
                                          "Not, Kırp/Yakala"),
            ("Ctrl+Shift+M", "Yorumlar paneli"),
            ("F8 / Shift+F8", "Sonraki / önceki metin değişikliği (karşılaştırmada)"),
            ("Home / End", "İlk / son sayfa"), ("PgUp / PgDn", "Ekran ekran kaydır"),
            ("← / →", "Önceki / sonraki sayfa"), ("Ctrl+R / Ctrl+Shift+R", "Sayfayı döndür"),
        ]
        html = "<table cellspacing='0' cellpadding='5'>" + "".join(
            f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows) + "</table>"
        QMessageBox.information(self, "Klavye kısayolları", html)

    def _show_about(self):
        QMessageBox.about(self, "Hakkında",
                          "<b>PDF İşaretleme Aracı</b><br><br>PDF ve resimler için işaretleme, "
                          "düzenleme, OCR, filigran ve karşılaştırma aracı.<br>PySide6 + PyMuPDF")

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
        if tool in ("rect", "oval"):
            self._last_shape = tool
            self.btn_shape.setIcon(icon(tool))
            self.btn_shape_rect.setChecked(tool == "rect")
            self.btn_shape_oval.setChecked(tool == "oval")
        if tool in self._tool_pages:
            self.prop_stack.setCurrentIndex(self._tool_pages[tool])
        if tool != "select":
            self._sel_ann = None
            self._hover_page = -1
        self._update_prop_bar()
        self._place_floating()
        if tool == "number":
            self._refresh_number_label()
        cursor = (Qt.CursorShape.IBeamCursor if tool in ("text", "edit", "number", "note")
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
        password = None
        while True:
            try:
                pdf = PDFDocument(path, password)
                break
            except PasswordRequired as ex:
                msg = ("Parola yanlış, tekrar deneyin.\n\n" if ex.wrong else "") + \
                    f"'{os.path.basename(path)}' parolayla korunuyor. Parolayı girin:"
                pw, ok = QInputDialog.getText(self, "Parolalı belge", msg, QLineEdit.EchoMode.Password)
                if not ok:
                    raise _OpenCancelled()
                password = pw
        session = DocumentSession(pdf, path)
        session.security = None
        if password:
            # koruma kaydederken kendiliğinden kalkmasın: aynı açma parolası varsayılan
            session.security = docsec.SecurityOptions(user_password=password)
            QTimer.singleShot(300, lambda: self.toasts.show(
                "Belge parolalı. Kaydederken aynı parola korunur; değiştirmek için "
                "Belge → Parola koruması.", "info", timeout_ms=6000))
        session.undo_stack.cleanChanged.connect(lambda _c: self.refresh_doc_tabs())
        self._add_recent(path)
        self.undo_group.addStack(session.undo_stack)
        self.sessions.append(session)
        return session

    def open_pdf(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "PDF / Resim Aç (birden fazla seçilebilir)",
                                                 "", OPEN_FILTER)
        if paths:
            self.open_paths(paths)

    def refresh_doc_tabs(self):
        self.doc_tabbar.blockSignals(True)
        while self.doc_tabbar.count():
            self.doc_tabbar.removeTab(0)
        for s in self.sessions:
            i = self.doc_tabbar.addTab(("● " if self._is_dirty(s) else "") + s.title)
            sec = getattr(s, "security", None)
            self.doc_tabbar.setTabToolTip(
                i, s.path + ("\nKaydedilmemiş değişiklikler var" if self._is_dirty(s) else "")
                + (f"\nParola koruması: {sec.describe()}" if sec is not None and sec.active else ""))
        if self.active_session is not None:
            mark = "● " if self._is_dirty(self.active_session) else ""
            self.setWindowTitle(f"{mark}{self.active_session.title} — PDF İşaretleme Aracı")
        else:
            self.setWindowTitle("PDF İşaretleme Aracı")
        if self.active_session in self.sessions:
            self.doc_tabbar.setCurrentIndex(self.sessions.index(self.active_session))
        self.doc_tabbar.blockSignals(False)

    def _on_doctab_context_menu(self, pos):
        idx = self.doc_tabbar.tabAt(pos)
        if not (0 <= idx < len(self.sessions)):
            return
        session = self.sessions[idx]
        menu = QMenu(self)
        act_folder = menu.addAction(icon("folder"), "Klasörde Göster")
        act_rename = menu.addAction(icon("rename"), "Sekme Adını Değiştir")
        act_copy = menu.addAction(icon("copy"), "Dosya Yolunu Kopyala")
        menu.addSeparator()
        act_close = menu.addAction(icon("close"), "Kapat")
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
                    self.refresh_doc_tabs()
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
        self.refresh_doc_tabs()
        self._refresh_number_label()
        self.refresh_doc_tabs()
        if hasattr(self, "pane_left"):
            self.pane_left.refresh_sessions()
            self.pane_right.refresh_sessions()

    @staticmethod
    def _is_dirty(s):
        return bool(s.dirty) or not s.undo_stack.isClean()

    def _mark_dirty(self, s=None):
        s = s or self.active_session
        if s is not None:
            s.dirty = True
            self.refresh_doc_tabs()

    def _mark_saved(self, s=None):
        s = s or self.active_session
        if s is not None:
            s.dirty = False
            s.undo_stack.setClean()
            self.refresh_doc_tabs()

    def _confirm_discard(self, s) -> bool:
        """Kaydedilmemiş değişiklik varsa sorar. Devam edilebilirse True."""
        if not self._is_dirty(s):
            return True
        if s is not self.active_session and s in self.sessions:
            self.switch_session(self.sessions.index(s))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Kaydedilmemiş değişiklikler")
        box.setText(f"<b>{s.title}</b> belgesindeki değişiklikler kaydedilsin mi?")
        box.setInformativeText("Kaydetmezseniz işaretler ve sayfa değişiklikleri kaybolur.")
        btn_save = box.addButton("Kaydet", QMessageBox.ButtonRole.AcceptRole)
        btn_discard = box.addButton("Kaydetme", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("İptal", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_save)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_discard:
            return True
        if clicked is btn_save:
            self.save_document()
            return not self._is_dirty(s)
        return False

    def close_session(self, idx, confirm=True):
        if not (0 <= idx < len(self.sessions)):
            return
        if confirm and not self._confirm_discard(self.sessions[idx]):
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
            self._refresh_forms()
            self._set_ui_enabled(False)
            self.thumb_list.clear()
            self.toc_tree.clear()
            self.view.render_page(None, None)
            self._update_page_label(-1, 0)
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
            self._mark_saved(s)
            self._toast_saved("Resim kaydedildi" if len(saved) == 1 else f"{len(saved)} resim kaydedildi",
                              saved[0])
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
            s.pdf.export_pdf(path, s.annotations, self.font_ctx, security=getattr(s, "security", None))
            self.status.setText(f"Kaydedildi: {path}")
            self._mark_saved(s)
            self._toast_saved("PDF kaydedildi", path)
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")

    def open_ocr_dialog(self):
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
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
            s.pdf.export_pdf(path, s.annotations, self.font_ctx, watermark=cfg,
                             security=getattr(s, "security", None))
            self.status.setText(f"Filigranlı PDF kaydedildi: {path}")
            self._toast_saved("Filigranlı PDF kaydedildi", path)
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
            self._toast_saved(f"{s.pdf.page_count} sayfa dışa aktarıldı", folder, folder=True)
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Dışa aktarılamadı:\n{ex}")

    def merge_pdfs(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Birleştirilecek PDF / resimleri seçin (sırayla)", "", OPEN_FILTER)
        if len(files) < 2:
            if files:
                self.toasts.show("Birleştirmek için en az 2 dosya seçin.", "warning")
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
            self._toast_saved("Sayfalar ayrı PDF olarak kaydedildi", folder, folder=True)
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
            self._mark_saved(s)
            self._toast_saved("Proje kaydedildi", path)
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
        self._mark_dirty()
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
        self._mark_dirty()
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
        self._mark_dirty()
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
        self._mark_dirty()
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
        self._mark_dirty()
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
        self._page_menu(row, self.thumb_list.viewport().mapToGlobal(pos))

    def _page_menu(self, row, global_pos):
        s = self.active_session
        if not s:
            return
        menu = QMenu(self)
        act_before = menu.addAction(icon("file_plus"), "Öncesine Boş Sayfa Ekle")
        act_after = menu.addAction(icon("file_plus"), "Sonrasına Boş Sayfa Ekle")
        act_dup = menu.addAction(icon("file_copy"), "Sayfayı Kopyala")
        menu.addSeparator()
        act_up = menu.addAction(icon("arrow_up"), "Yukarı Taşı")
        act_down = menu.addAction(icon("arrow_down"), "Aşağı Taşı")
        menu.addSeparator()
        act_rot_cw = menu.addAction(icon("rotate_cw"), "Saat Yönünde Döndür")
        act_rot_ccw = menu.addAction(icon("rotate_ccw"), "Tersine Döndür")
        menu.addSeparator()
        act_del = menu.addAction(icon("trash", "danger"), "Sayfayı Sil")
        chosen = menu.exec(global_pos)
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
    _THUMB_LOADED = Qt.ItemDataRole.UserRole + 1

    # -- PDF formları ---------------------------------------------------------
    def _refresh_forms(self):
        """Alan listesini belgeden yeniden okur; paneli ve vurguları tazeler."""
        s = self.active_session
        fields = []
        if s is not None:
            with s.pdf.lock:
                fields = forms.list_fields(s.pdf.doc)
        self._form_fields = fields
        if hasattr(self, "forms_panel"):
            self.forms_panel.set_fields(fields)
        self._refresh_form_overlay()

    def _refresh_form_overlay(self):
        on = not hasattr(self, "forms_panel") or self.forms_panel.chk_highlight.isChecked()
        by_page = {}
        if on:
            for f in getattr(self, "_form_fields", []):
                r = f.rect
                by_page.setdefault(f.page, []).append(QRectF(r.x0, r.y0, r.width, r.height))
        self.view.set_form_overlay(by_page)

    def _form_hit(self, page, x, y):
        return forms.field_at(getattr(self, "_form_fields", []), page, x, y) is not None

    def _forms_changed(self, pages):
        s = self.active_session
        if not s:
            return
        for p in pages:
            if 0 <= p < s.pdf.page_count:
                s.pdf._invalidate_page(p)
        self._refresh_forms()
        for p in pages:
            if 0 <= p < s.pdf.page_count:
                self.view.refresh_page(p)

    def _push_form_values(self, values, label="Form Doldur"):
        s = self.active_session
        if not s:
            return
        s.undo_stack.push(FormValuesCommand(s, values, on_done=self._forms_changed, label=label))

    def on_form_field_clicked(self, page, pt):
        f = forms.field_at(self._form_fields, page, pt.x(), pt.y())
        if f is None:
            return
        if f.kind == "checkbox":
            self._push_form_values({f.name: "Off" if f.checked else f.on_state})
        elif f.kind == "radio":
            if not f.checked:
                self._push_form_values({f.name: f.on_state})
        elif f.kind == "calc":
            self.toasts.show(f"'{f.name}' hesaplanan bir alan: {f.value or 'boş'} "
                             f"({dict(forms.CALC_OPS).get(f.calc_op, '')}: {', '.join(f.calc_sources)})")
        elif f.kind == "signature":
            self.toasts.show(f"'{f.name}' bir imza alanı: Araçlar › Dijital imza ile imzalayın.")
        elif f.kind == "other" or f.readonly:
            self.toasts.show(f"'{f.name}' alanı bu uygulamada düzenlenemez.")
        else:
            self._open_form_editor(f)

    def _open_form_editor(self, f):
        self._finish_form_editor()
        prect = self.view.page_rect_in_scene(f.page)
        scene_r = QRectF(prect.x() + f.rect.x0, prect.y() + f.rect.y0, f.rect.width, f.rect.height)
        vr = self.view.mapFromScene(scene_r).boundingRect()
        ed = FormFieldEditor(f, self.view.viewport())
        ed.place(vr)
        ed.committed.connect(self._on_form_editor_commit)
        ed.cancelled.connect(self._close_form_editor)
        self._form_editor = ed
        ed.start()

    def _close_form_editor(self):
        ed = getattr(self, "_form_editor", None)
        self._form_editor = None
        if ed is not None:
            ed.hide()
            ed.deleteLater()

    def _finish_form_editor(self):
        ed = getattr(self, "_form_editor", None)
        if ed is not None:
            ed.finish()

    def _center_on_field(self, f):
        self.view.centerOn(self.view.page_rect_in_scene(f.page).topLeft()
                           + QPointF(f.rect.x0 + f.rect.width / 2, f.rect.y0))

    def _on_form_editor_commit(self, f, value, nav):
        self._close_form_editor()
        if value != f.value:
            self._push_form_values({f.name: value})
        if not nav:
            return
        order = [x for x in self._form_fields if x.kind in ("text", "date", "combo") and not x.readonly]
        if not order:
            return
        keys = [(x.page, x.nm) for x in order]
        i = keys.index((f.page, f.nm)) if (f.page, f.nm) in keys else -1
        nxt = order[(i + nav) % len(order)]
        self._goto_form_field(nxt)

    def _goto_form_field(self, f):
        if f.page != self.active_session.current_page:
            self.goto_page(f.page)
        self._center_on_field(f)
        if f.kind in ("text", "date", "combo") and not f.readonly:
            QTimer.singleShot(0, lambda: self._open_form_editor(f))

    def _on_form_goto(self, f):
        if self.state.tool != "select":
            self._tool_shortcut("select")
        self._goto_form_field(f)

    def ask_form_field(self, spec, creating=True):
        """Özellik penceresi; test betikleri bu yöntemi değiştirebilir. spec | None döner."""
        others = [f for f in self._form_fields if f.nm != spec.get("nm")]
        names = []
        for f in others:
            if f.name not in names:
                names.append(f.name)
        groups = sorted({f.name for f in others if f.kind == "radio"})
        dlg = FormFieldDialog(spec, names, groups, self, creating=creating)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return dlg.result_spec()

    def on_form_field_requested(self, page, rect):
        s = self.active_session
        if not s:
            return
        kind = self.state.form_kind
        if rect.width() < 6 or rect.height() < 6:
            w, h = forms.DEFAULT_SIZE[kind]
            rect = QRectF(rect.x(), rect.y(), w, h)
        with s.pdf.lock:
            doc = s.pdf.doc
            if kind == "radio":
                group = getattr(self, "_last_radio_group", None)
                groups = {f.name for f in self._form_fields if f.kind == "radio"}
                name = group if group in groups else forms.unique_name(doc, forms.KIND_BASE[kind])
                n = sum(1 for f in self._form_fields if f.name == name) + 1
                spec = {"name": name, "on_state": f"Secenek{n}"}
            else:
                spec = {"name": forms.unique_name(doc, forms.KIND_BASE[kind])}
        spec.update(kind=kind, rect=(rect.left(), rect.top(), rect.right(), rect.bottom()),
                    value="", font_size=10)
        if kind == "combo":
            spec["options"] = ["Seçenek 1", "Seçenek 2"]
        if kind == "date":
            spec["date_fmt"] = forms.DATE_FORMATS[0]
        if kind == "calc":
            spec.update(calc_op="SUM", calc_sources=[])
        if self.state.form_ask or kind == "calc":
            spec = self.ask_form_field(spec, creating=True)
            if spec is None:
                return
        if kind == "radio":
            self._last_radio_group = spec["name"]
        s.undo_stack.push(FormFieldCommand(s, page, None, spec, on_done=self._forms_changed,
                                           label=f"{forms.KIND_NAMES[kind]} ekle"))
        self.toasts.show(f"'{spec['name']}' alanı eklendi. Doldurmak için Seç aracıyla tıklayın.")

    def edit_form_field(self, f):
        s = self.active_session
        if not s or f is None:
            return
        if f.kind == "other":
            self.toasts.show("Bu alan türünün özellikleri düzenlenemez.")
            return
        with s.pdf.lock:
            old = forms.field_spec(s.pdf.doc, f.page, f.nm)
        if old is None:
            return
        if old["kind"] == "radio":
            old["value"] = old["on_state"] if f.checked else "Off"
        new = self.ask_form_field(dict(old), creating=False)
        if new is None or new == old:
            return
        if f.kind == "radio" and new["on_state"] != old["on_state"]:
            new["value"] = "Off"
        if new["name"] != old["name"]:
            users = [c.name for c in self._form_fields if c.kind == "calc" and old["name"] in c.calc_sources]
            if users:
                self.toasts.show(f"Not: {', '.join(users)} formülü eski adı ({old['name']}) kullanıyor; "
                                 "özelliklerinden kaynakları güncelleyin.")
        s.undo_stack.push(FormFieldCommand(s, f.page, old, new, on_done=self._forms_changed,
                                           label="Form alanını değiştir"))

    def delete_form_field(self, f):
        s = self.active_session
        if not s or f is None:
            return
        with s.pdf.lock:
            old = forms.field_spec(s.pdf.doc, f.page, f.nm)
        if old is None:
            return
        if old["kind"] == "radio":
            old["value"] = old["on_state"] if f.checked else "Off"
        s.undo_stack.push(FormFieldCommand(s, f.page, old, None, on_done=self._forms_changed,
                                           label="Form alanını sil"))
        self.toasts.show(f"'{f.name}' alanı silindi (Ctrl+Z ile geri alınır).")

    def reset_form(self):
        s = self.active_session
        if not s:
            return
        if not self._form_fields:
            self.toasts.show("Bu belgede form alanı yok.")
            return
        s.undo_stack.push(FormValuesCommand(s, reset=True, on_done=self._forms_changed,
                                            label="Formu Sıfırla"))
        self.toasts.show("Form sıfırlandı (Ctrl+Z ile geri alınır).")

    def recalculate_form(self):
        s = self.active_session
        if not s:
            return
        with s.pdf.lock:
            pages = forms.recalculate(s.pdf.doc)
        if pages:
            self._mark_dirty()
            self._forms_changed(pages)
        self.toasts.show("Hesaplanan alanlar güncel.")

    # -- yazdırma ---------------------------------------------------------------
    def print_document(self):
        s = self.active_session
        if not s:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        self._finish_form_editor()
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(s.title)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Yazdır")
        dlg.setOption(QPrintDialog.PrintDialogOption.PrintPageRange, True)
        dlg.setOption(QPrintDialog.PrintDialogOption.PrintCurrentPage, True)
        dlg.setMinMax(1, s.pdf.page_count)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        n = self.print_to(printer)
        if n:
            self.toasts.show(f"{n} sayfa yazıcıya gönderildi.")

    def print_to(self, printer, pages=None) -> int:
        """Belgeyi (işaretler ve form değerleriyle) yazıcıya basar; basılan sayfa sayısını döner."""
        from PySide6.QtGui import QPageLayout, QPainter
        from PySide6.QtPrintSupport import QPrinter
        s = self.active_session
        n = s.pdf.page_count
        if pages is None:
            rng = printer.printRange()
            if rng == QPrinter.PrintRange.PageRange and printer.fromPage() > 0:
                pages = list(range(printer.fromPage() - 1, min(printer.toPage(), n)))
            elif rng == QPrinter.PrintRange.CurrentPage:
                pages = [s.current_page]
            else:
                pages = list(range(n))
        if not pages:
            return 0
        tmp = s.pdf._annotated_copy(s.annotations, self.font_ctx)
        dpi = max(96, min(printer.resolution(), 300))
        prog = QProgressDialog("Yazdırılıyor…", "İptal", 0, len(pages), self)
        prog.setWindowTitle("Yazdır")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(400)
        painter = QPainter()
        done = 0
        try:
            for i, pidx in enumerate(pages):
                if prog.wasCanceled():
                    break
                page = tmp[pidx]
                landscape = page.rect.width > page.rect.height
                printer.setPageOrientation(QPageLayout.Orientation.Landscape if landscape
                                           else QPageLayout.Orientation.Portrait)
                if i == 0:
                    if not painter.begin(printer):
                        raise RuntimeError("Yazıcı başlatılamadı.")
                else:
                    printer.newPage()
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format.Format_RGB888)
                area = painter.viewport()
                sc = min(area.width() / img.width(), area.height() / img.height())
                w, h = img.width() * sc, img.height() * sc
                painter.drawImage(QRectF((area.width() - w) / 2, (area.height() - h) / 2, w, h), img)
                done += 1
                prog.setValue(i + 1)
                QApplication.processEvents()
        except Exception as e:
            QMessageBox.critical(self, "Yazdır", f"Yazdırma başarısız:\n{e}")
        finally:
            if painter.isActive():
                painter.end()
            tmp.close()
            prog.close()
        return done

    def _build_thumbnails(self):
        """Küçük resim listesini anında kurar (boş kâğıt simgeleriyle);
        gerçek görüntüler göründükçe arka planda üretilir."""
        self._close_form_editor()
        self._refresh_forms()
        s = self.active_session
        self._thumb_gen += 1
        self.thumb_list.blockSignals(True)
        self.thumb_list.clear()
        if s:
            for i in range(s.pdf.page_count):
                item = QListWidgetItem(f"{i + 1}")
                pw, ph = s.pdf.page_size(i)
                item.setData(THUMB_ASPECT_ROLE, (ph / pw) if pw else 1.414)
                self.thumb_list.addItem(item)
            self.thumb_list.setCurrentRow(s.current_page)
        self.thumb_list.blockSignals(False)
        self._thumb_timer.start(0)

    def _load_visible_thumbs(self):
        s = self.active_session
        lw = self.thumb_list
        if not s or lw.count() == 0:
            return
        vr = lw.viewport().rect()
        first = lw.indexAt(vr.topLeft() + QPoint(8, 8)).row()
        last = lw.indexAt(vr.bottomLeft() + QPoint(8, -8)).row()
        first = max(0, first)
        last = min(lw.count() - 1, (last if last >= 0 else first + 8) + 4)
        gen = self._thumb_gen
        for i in range(first, last + 1):
            item = lw.item(i)
            if item is None or item.data(self._THUMB_LOADED):
                continue
            item.setData(self._THUMB_LOADED, True)
            task = s.pdf.make_render_task(i, False, 0.25 * self.devicePixelRatioF() * 1.2)
            self._thumb_tasks.append(task)

            def on_done(idx, qimg, _task=task, _gen=gen, _s=s):
                if _task in self._thumb_tasks:
                    self._thumb_tasks.remove(_task)
                if _gen != self._thumb_gen or _s is not self.active_session:
                    return
                it = self.thumb_list.item(idx)
                if it is not None:
                    it.setData(THUMB_ROLE, QPixmap.fromImage(qimg))

            def on_fail(_idx, _msg, _task=task):
                if _task in self._thumb_tasks:
                    self._thumb_tasks.remove(_task)

            task.signals.finished.connect(on_done)
            task.signals.failed.connect(on_fail)
            self.threadpool.start(task)

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
        self.view.show_page(s, index, invert=self.night_mode)
        self._after_page_change(index)

    def _on_view_page_changed(self, index):
        """Kullanıcı kaydırınca ya da başka bir sayfaya tıklayınca."""
        s = self.active_session
        if not s or not (0 <= index < s.pdf.page_count) or index == s.current_page:
            return
        s.current_page = index
        self._after_page_change(index)

    def _after_page_change(self, index):
        s = self.active_session
        self._update_page_label(index, s.pdf.page_count)
        if self.thumb_list.currentRow() != index:
            self.thumb_list.blockSignals(True)
            self.thumb_list.setCurrentRow(index)
            self.thumb_list.blockSignals(False)
            item = self.thumb_list.item(index)
            if item is not None:
                self.thumb_list.scrollToItem(item)
        self.refresh_layers_panel()
        self._update_search_highlight_for_page()
        if self.state.tool == "edit":
            self._scan_current_page_for_edit()

    def fit_width(self):
        if self.active_session:
            self.view.fit_width()

    def fit_page(self):
        if self.active_session:
            self.view.fit_page()

    def _sync_zoom_slider(self, zoom=None):
        self._zoom = self.view.zoom() if zoom is None else zoom
        pct = int(round(self._zoom * 100))
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(max(self.zoom_slider.minimum(), min(self.zoom_slider.maximum(), pct)))
        self.zoom_slider.blockSignals(False)
        self.lbl_zoom.setText(f"{pct}%")

    def _on_zoom_slider_changed(self, value):
        self._apply_zoom_percent(value)

    def _apply_zoom_percent(self, pct):
        self.view.set_zoom(pct / 100.0)

    # =====================================================================
    # Arama (Ctrl+F)
    # =====================================================================
    def _focus_search(self):
        if not self.active_session:
            return
        self.side.show_page("search")
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
        self.view.set_all_search_highlights(result)
        if total:
            self.goto_next_search_hit()

    def _on_search_result_clicked(self, item):
        page = item.data(Qt.ItemDataRole.UserRole)
        if page is not None:
            page = int(page)
            if (page, 0) in self._search_flat:
                self._search_pos = self._search_flat.index((page, 0))
                self._show_search_hit()
            else:
                self.goto_page(page)

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
        self.view.set_all_search_highlights(self._search_results, (page, local_idx), center=True)
        s = self.active_session
        if s and s.current_page != page:
            s.current_page = page
            self._after_page_change(page)
        self.lbl_search_status.setText(f"{self._search_pos + 1} / {len(self._search_flat)}")

    def _update_search_highlight_for_page(self):
        """Görünüm tüm sayfaların vurgularını kendisi tutar; belge yeniden
        kurulduğunda (sekme değişimi vb.) güncel sonuçları yeniden verir."""
        if not self.active_session:
            return
        active = None
        if self._search_flat and 0 <= self._search_pos < len(self._search_flat):
            active = self._search_flat[self._search_pos]
        self.view.set_all_search_highlights(self._search_results or {}, active)

    # =====================================================================
    # Annotation ekle / sil / taşı / boyutlandır (QUndoStack üzerinden)
    # =====================================================================
    def _on_session_change(self, session, page):
        """Tüm QUndoCommand'ların ortak geri çağrısı: ilgili görünümleri
        tazeler (ana sayfa + karşılaştırma panelleri + katmanlar)."""
        for pane in (self.pane_left, self.pane_right):
            if pane.session is session and pane.page == page:
                pane._render()
        if self.active_session is session:
            self.view.refresh_page(page)
            if page == session.current_page:
                self.refresh_layers_panel()
            else:
                self.refresh_comments_panel()

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

    # -- damga ---------------------------------------------------------------
    def _fill_stamp_combo(self, select_key=None):
        if select_key is None and self.stamp_combo.count():
            cur = self.stamp_combo.currentData()
            select_key = cur.key() if cur else None
        if select_key is None:
            select_key = self.settings.value("stampKey", "")
        self.stamp_combo.blockSignals(True)
        self.stamp_combo.clear()
        for st in self.stamp_lib.all():
            self.stamp_combo.addItem(preview_icon(st, 22), "", st)
            self.stamp_combo.setItemData(self.stamp_combo.count() - 1, st.text, Qt.ItemDataRole.ToolTipRole)
            if st.key() == select_key:
                self.stamp_combo.setCurrentIndex(self.stamp_combo.count() - 1)
        self.stamp_combo.blockSignals(False)
        self.stamp_combo.currentIndexChanged.connect(
            lambda _i: self.settings.setValue("stampKey", self.stamp_combo.currentData().key())
            if self.stamp_combo.currentData() else None)

    def open_stamp_library(self):
        StampLibraryDialog(self.stamp_lib, self).exec()
        self._fill_stamp_combo()
        self._update_prop_bar()

    def on_stamp_requested(self, pt: QPointF):
        s = self.active_session
        st = self.stamp_combo.currentData()
        if not s or st is None:
            return
        sub = ""
        if self.chk_stamp_sub.isChecked():
            name = self.stamp_name.text().strip()
            sub = f"{name} · {today()}" if name else today()
        img = render_stamp(st, sub, self.chk_stamp_slant.isChecked())
        w, h = img.width() / STAMP_SCALE, img.height() / STAMP_SCALE
        pw, ph = s.pdf.page_size(s.current_page)
        if w > pw * 0.9:                       # çok dar sayfada sığdır
            k = pw * 0.9 / w
            w, h = w * k, h * k
        x = min(max(0.0, pt.x() - w / 2), max(0.0, pw - w))
        y = min(max(0.0, pt.y() - h / 2), max(0.0, ph - h))
        ann = ImageAnnotation(QRectF(x, y, w, h), image_png_bytes(img), 1.0, True,
                              source_path=f"stamp:{st.text}")
        s.undo_stack.push(AddAnnotationCommand(s, s.current_page, ann, on_change=self._on_session_change,
                                               label="Damga"))
        self.status.setText(f"'{st.text}' damgası basıldı. Taşımak için Seç aracını (V) kullanın.")

    # -- elektronik ve dijital imza ---------------------------------------------
    def _fill_sig_combo(self, select_id=None):
        select_id = select_id or self.settings.value("signId", "")
        self.sig_combo.blockSignals(True)
        self.sig_combo.clear()
        for it in self.sig_lib.items:
            self.sig_combo.addItem(SignatureLibrary.icon(it), "", it["id"])
            if it["id"] == select_id:
                self.sig_combo.setCurrentIndex(self.sig_combo.count() - 1)
        if not self.sig_lib.items:
            self.sig_combo.addItem("(imza yok)", None)
        self.sig_combo.blockSignals(False)

    def ask_signature(self):
        """Yeni imza penceresi; (png, etiket) ya da None. Testte sahtelenir."""
        dlg = SignatureDialog(self, str(self.settings.value("author", "") or ""))
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_png:
            return None
        return dlg.result_png, dlg.result_label

    def new_signature(self):
        res = self.ask_signature()
        if not res:
            return
        it = self.sig_lib.add(*res)
        self.settings.setValue("signId", it["id"])
        self._fill_sig_combo(it["id"])
        if self.active_session:
            self._tool_shortcut("sign")
        self.toasts.show("İmza kaydedildi. Sayfada imzanın konacağı yere tıklayın.")

    def delete_signature(self):
        sid = self.sig_combo.currentData()
        if sid:
            self.sig_lib.remove(sid)
            self._fill_sig_combo()

    def on_sign_requested(self, pt: QPointF):
        s = self.active_session
        if not s:
            return
        item = next((i for i in self.sig_lib.items if i["id"] == self.sig_combo.currentData()), None)
        if item is None:
            self.new_signature()
            return
        img = QImage.fromData(SignatureLibrary.png(item))
        if self.chk_sig_date.isChecked():
            img = self._sig_with_date(img)
        w = 150.0
        h = w * img.height() / max(1, img.width())
        if h > 70:
            w, h = w * 70 / h, 70.0
        pw, ph = s.pdf.page_size(s.current_page)
        x = min(max(0.0, pt.x() - w / 2), max(0.0, pw - w))
        y = min(max(0.0, pt.y() - h / 2), max(0.0, ph - h))
        ann = ImageAnnotation(QRectF(x, y, w, h), image_png_bytes(img), 1.0, True, source_path="sign:")
        s.undo_stack.push(AddAnnotationCommand(s, s.current_page, ann, on_change=self._on_session_change,
                                               label="İmza"))
        self.status.setText("İmza basıldı. Taşımak/boyutlandırmak için Seç aracını (V) kullanın.")

    @staticmethod
    def _sig_with_date(img: QImage) -> QImage:
        fh = max(18, img.height() // 5)
        out = QImage(img.width(), img.height() + fh + 6, QImage.Format.Format_ARGB32)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.drawImage(0, 0, img)
        f = p.font(); f.setPixelSize(fh); p.setFont(f)
        p.setPen(QColor(40, 40, 60))
        p.drawText(QRectF(0, img.height() + 3, img.width(), fh + 2), Qt.AlignmentFlag.AlignLeft, today())
        p.end()
        return out

    def start_signature_field(self):
        self._tool_shortcut("form")
        combo = self._form_kind_row.findChild(QComboBox)
        combo.setCurrentIndex(combo.findData("signature"))
        self.toasts.show("Sayfada imza alanının kutusunu çizin.")

    def ask_digital_sign(self, sig_fields):
        """İmzalama seçenekleri + çıktı yolu; dict ya da None. Testte sahtelenir."""
        dlg = DigitalSignDialog(self, sig_fields, self.settings)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        default = os.path.splitext(self.active_session.path)[0] + "_imzali.pdf"
        out, _ = QFileDialog.getSaveFileName(self, "İmzalı PDF'i kaydet", default, "PDF (*.pdf)")
        if not out:
            return None
        v = dlg.values()
        v["out"] = out if out.lower().endswith(".pdf") else out + ".pdf"
        return v

    def sign_digitally(self):
        import tempfile
        import digisign
        s = self.active_session
        if not s:
            return
        # Değişiklik yoksa özgün dosya artımlı imzalanır (önceki imzalar korunur)
        pristine = (not s.pdf.is_image and not s.dirty and s.undo_stack.isClean()
                    and not any(s.annotations.values()) and s.path.lower().endswith(".pdf")
                    and not getattr(s, "security", None))
        tmp = None
        try:
            if pristine:
                src = s.path
            else:
                fd, tmp = tempfile.mkstemp(suffix=".pdf")
                os.close(fd)
                s.pdf.export_pdf(tmp, s.annotations, self.font_ctx)
                src = tmp
            v = self.ask_digital_sign(digisign.empty_signature_fields(src))
            if not v:
                return
            box = None
            if v["mode"] == "box":
                pw, ph = s.pdf.page_size(s.current_page)
                box = (s.current_page, (pw - 230, ph - 100, pw - 40, ph - 40))
            who = digisign.sign_pdf(src, v["out"], v["pfx"], v["password"],
                                    field=v["field"] if v["mode"] == "field" else None, new_box=box,
                                    reason=v["reason"], location=v["location"])
            self._toast_saved(f"{who} adına dijital olarak imzalandı", v["out"])
        except Exception as ex:
            QMessageBox.critical(self, "İmzalanamadı", str(ex))
        finally:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)

    def show_report(self, title, html):
        ReportDialog(self, title, html).exec()

    def verify_signatures(self):
        import digisign
        s = self.active_session
        if not s or s.pdf.is_image:
            return
        try:
            reps = digisign.verify_pdf(s.path)
        except Exception as ex:
            QMessageBox.critical(self, "Doğrulanamadı", str(ex))
            return
        html = report_html(reps)
        if s.dirty or not s.undo_stack.isClean():
            html = ("<p style='color:#b26a00'>Not: Doğrulama diskteki dosyaya yapılır; açık belgedeki "
                    "kaydedilmemiş değişiklikler dahil değildir.</p>") + html
        self._last_sig_reports = reps
        self.show_report("İmza doğrulama", html)

    # -- belge güvenliği ve bilgileri ------------------------------------------
    def save_compressed(self):
        s = self.active_session
        if not s:
            return
        size = os.path.getsize(s.path) if os.path.exists(s.path) else 0
        dlg = CompressDialog(self, size)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        default = os.path.splitext(s.path)[0] + "_kucuk.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Sıkıştırılmış PDF'i Kaydet", default, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            s.pdf.export_pdf(path, s.annotations, self.font_ctx, security=getattr(s, "security", None),
                             compress=dlg.level())
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        new = os.path.getsize(path)
        self._mark_saved(s)
        if size:
            pct = round(100 * (1 - new / size))
            change = f"%{pct} küçüldü" if pct > 0 else "zaten sıkıştırılmıştı"
            text = f"Sıkıştırıldı: {docsec.human_size(size)} → {docsec.human_size(new)} ({change})"
        else:
            text = f"Kaydedildi: {docsec.human_size(new)}"
        self.status.setText(text)
        self._toast_saved(text, path)

    def open_password(self):
        s = self.active_session
        if not s:
            return
        dlg = PasswordDialog(self, getattr(s, "security", None))
        code = dlg.exec()
        if code == QDialog.DialogCode.Rejected:
            return
        s.security = dlg.result_options if code != 2 else None
        self._mark_dirty(s)
        if s.security is not None and s.security.active:
            self.toasts.show(f"Parola koruması ayarlandı ({s.security.describe()}). "
                             "Belgeyi kaydettiğinizde uygulanır.", "success", timeout_ms=5000)
        else:
            s.security = None
            self.toasts.show("Parola koruması kaldırıldı. Kaydettiğinizde belge parolasız olur.", "info")

    def open_doc_info(self):
        s = self.active_session
        if not s:
            return
        DocInfoDialog(self, s, lambda: self._mark_dirty(s)).exec()

    def open_security_check(self):
        s = self.active_session
        if not s:
            return

        def cleaned():
            s.pdf._invalidate()                  # sayfa içeriği değişmiş olabilir
            self._mark_dirty(s)
            self._build_thumbnails()
            self.goto_page(s.current_page)
            self.toasts.show("Seçilen içerik temizlendi. Kaydettiğinizde PDF'e yansır.", "success")

        SecurityCheckDialog(self, s, cleaned).exec()

    # -- Telefonla aktar (QR) ---------------------------------------------------
    def open_share(self):
        """Yerel ağda geçici sunucu + QR penceresi (tek örnek); pencere kapanınca sunucu durur."""
        dlg = getattr(self, "_share_dialog", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return dlg
        dlg = self._share_dialog = ShareDialog(self)
        dlg.show()
        return dlg

    # -- Belge tarama -----------------------------------------------------------
    def scan_images(self, paths=None):
        """Görsellerden (ya da PDF'lerden) tarama penceresi; yol verilmezse dosya seçtirir."""
        if not paths:
            flt = "Görsel ve PDF (" + " ".join("*" + e for e in IMAGE_EXTS) + " *.pdf)"
            paths, _ = QFileDialog.getOpenFileNames(self, "Taranacak dosyalar", "", flt)
        if not paths:
            return None
        dlg = self._scan_dialog = ScanDialog(self, list(paths))
        dlg.show()
        return dlg

    def images_to_pdf(self, paths=None):
        """Çoklu görseli tek PDF'e ya da her biri ayrı PDF'e çevirir (ayarlı, toplu yol)."""
        dlg = self._imgpdf_dialog = ImagesPdfDialog(self, list(paths or []))
        dlg.show()
        return dlg

    def scan_document(self):
        """Açık belgenin sayfalarını (200 dpi) tarama penceresinde aç: kırp, temizle, yeniden PDF yap."""
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return None
        try:
            snap = s.pdf._annotated_copy(s.annotations, self.font_ctx)
            data = snap.write()
            snap.close()
            srcs = pdf_sources(data, os.path.basename(s.path) if s.path else "belge")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Belge hazırlanamadı:\n{ex}")
            return None
        dlg = self._scan_dialog = ScanDialog(self, srcs, start=s.current_page)
        dlg.show()
        return dlg

    # -- Word / Excel dönüştürme ve erişilebilirlik ---------------------------
    def open_convert(self, fmt: str = "docx"):
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return None
        dlg = self._convert_dialog = ConvertDialog(self, s, fmt)
        dlg.exec()
        return dlg

    def open_a11y(self):
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return None

        def changed():
            s.pdf._invalidate()                  # OCR sayfaları değiştirmiş olabilir
            self._mark_dirty(s)
            self._build_thumbnails()
            self._build_toc()                    # yer imleri eklenmiş olabilir
            self.goto_page(s.current_page)

        dlg = self._a11y_dialog = A11yDialog(self, s, changed)
        dlg.exec()
        return dlg

    # -- KVKK ----------------------------------------------------------------
    def open_kvkk(self):
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return
        if self._kvkk_dialog is not None and self._kvkk_dialog.isVisible() \
                and self._kvkk_dialog._session is s:
            self._kvkk_dialog.raise_()
            self._kvkk_dialog.activateWindow()
            return
        self._kvkk_dialog = KvkkDialog(self, s)
        self._kvkk_dialog.show()

    # -- Görsel iş akışı ---------------------------------------------------------
    def open_workflow(self):
        """Adım zinciri penceresi (tek örnek); belge açık olmasa da dosya/klasör için kullanılabilir."""
        dlg = getattr(self, "_workflow_dialog", None)
        if dlg is None:
            dlg = self._workflow_dialog = WorkflowDialog(self)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

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
        self._show_crop_dialog(qimg, rect)

    def _show_crop_dialog(self, qimage: QImage, rect: QRectF = None):
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
        btn_copy = QPushButton(icon("clipboard"), "Panoya Kopyala")
        btn_copy.setObjectName("secondary")
        btn_save = QPushButton(icon("save", "on_accent"), "PNG Olarak Kaydet")
        btn_save.setObjectName("primary")
        btn_close = QPushButton("Kapat")
        row.addWidget(btn_copy); row.addWidget(btn_save); row.addWidget(btn_close)
        v.addLayout(row)
        if rect is not None:
            btn_page = QPushButton(icon("crop"), "Sayfayı bu alana kırp")
            btn_page.setObjectName("secondary")
            btn_page.setToolTip("Sayfanın görünen alanını bu bölgeyle sınırlar (Ctrl+Z ile geri alınır)")

            def do_page_crop():
                dlg.accept()
                self._apply_crops({self.active_session.current_page:
                                   fitz.Rect(rect.left(), rect.top(), rect.right(), rect.bottom())})

            btn_page.clicked.connect(do_page_crop)
            v.addWidget(btn_page)

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
        act_file = menu.addAction(icon("folder"), "Dosyadan Seç…")
        act_clip = menu.addAction(icon("clipboard"), "Panodan Yapıştır")
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
                self.toasts.show("Panoda bir görsel bulunamadı.", "warning")
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
        page = self.view.page_of_annotation(ann)
        cmd = ResizeAnnotationCommand(s, s.current_page if page is None else page, ann, old_rect, new_rect,
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
                page = self.view.page_of_item(gitem)
                cmd = MoveAnnotationCommand(s, s.current_page if page is None else page, ann, dx, dy,
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
        page = self.view.page_of_item(gitem)
        cmd = RemoveAnnotationCommand(s, s.current_page if page is None else page, ann,
                                      on_change=self._on_session_change)
        s.undo_stack.push(cmd)
        self.status.setText("Öge silindi.")

    def delete_selected(self):
        for gitem in list(self.view.scene_obj.selectedItems()):
            if gitem is self.view.gizmo:
                continue
            self._delete_item(gitem)

    def show_item_context_menu(self, gitem, global_pos):
        if gitem is None or gitem not in self.view.item_ann_map:
            # işaret değil: sayfanın kendisine sağ tıklandı
            if self.active_session and self.canvas_stack.currentIndex() == 0:
                self._page_menu(self.active_session.current_page, global_pos)
            return
        menu = QMenu(self)
        act_front = menu.addAction(icon("bring_front"), "En Öne Getir")
        act_back = menu.addAction(icon("send_back"), "En Arkaya Gönder")
        menu.addSeparator()
        act_del = menu.addAction(icon("trash", "danger"), "Sil")
        chosen = menu.exec(global_pos)
        s = self.active_session
        ann = self.view.item_ann_map.get(gitem)
        if chosen == act_del:
            self._delete_item(gitem)
        page = self.view.page_of_item(gitem)
        if page is None and s:
            page = s.current_page
        if chosen == act_front and s and ann:
            s.undo_stack.push(ZOrderCommand(s, page, ann, True, on_change=self._on_session_change))
        elif chosen == act_back and s and ann:
            s.undo_stack.push(ZOrderCommand(s, page, ann, False, on_change=self._on_session_change))

    # =====================================================================
    # Katmanlar paneli
    # =====================================================================
    def _ann_label(self, ann):
        """(ikon adı, etiket)"""
        if isinstance(ann, TextAnnotation):
            return "text", ann.text.replace(chr(10), " ")[:24] or "Metin"
        if isinstance(ann, InkAnnotation):
            return "ink", "Kalem çizimi"
        if isinstance(ann, LineAnnotation):
            return "line", "Çizgi / Ok"
        if isinstance(ann, ShapeAnnotation):
            return ("rect", "Dörtgen") if ann.kind == "rect" else ("oval", "Oval")
        if isinstance(ann, HighlightAnnotation):
            return "highlight", "Fosforlu"
        if isinstance(ann, RedactionAnnotation):
            return ("edit_text", "Silinen orijinal metin") if getattr(ann, "quiet", False) \
                else ("redact", "Sansür (kalıcı)")
        if isinstance(ann, BlurAnnotation):
            return "blur", "Bulanıklaştırma" if ann.mode == "blur" else "Mozaik"
        if isinstance(ann, NoteAnnotation):
            return "note", "Not: " + (ann.text.replace(chr(10), " ")[:20] or "(boş)")
        if isinstance(ann, NumberAnnotation):
            return "number", f"Numara {ann.number}"
        if isinstance(ann, ImageAnnotation):
            src = ann.source_path or ""
            if src.startswith("stamp:"):
                return "stamp", f"Damga: {src[6:]}"
            if src.startswith("sign:"):
                return "sign", "İmza"
            return "image", "Resim"
        return "layers", "Öge"

    def refresh_layers_panel(self):
        self.refresh_comments_panel()
        if not hasattr(self, "layers_list"):
            return
        self.layers_list.clear()
        s = self.active_session
        anns = s.annotations.get(s.current_page, []) if s else []
        for ann in anns:
            list_item = QListWidgetItem()
            row = QWidget()
            row.setObjectName("layerRow")
            h = QHBoxLayout(row)
            h.setContentsMargins(8, 2, 2, 2)
            h.setSpacing(8)
            icon_name, text = self._ann_label(ann)
            ico = QLabel()
            ico.setPixmap(icon_pixmap(icon_name, 16, scale=self.devicePixelRatioF()))
            h.addWidget(ico)
            lbl = QLabel(text)
            lbl.setObjectName("layerLabel")
            h.addWidget(lbl, 1)
            btn = self._icon_button("trash", "Sil", lambda _=False, a=ann: self._delete_annotation_by_ref(a))
            btn.setIcon(icon("trash", "danger"))
            btn.setIconSize(QSize(16, 16))
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

    def _delete_annotation_by_ref(self, ann, page=None):
        gitem = None
        for k, v in self.view.item_ann_map.items():
            if v is ann:
                gitem = k
                break
        if gitem is not None:
            self._delete_item(gitem)
        elif page is not None and self.active_session:       # öğesi henüz çizilmemiş sayfa
            s = self.active_session
            s.undo_stack.push(RemoveAnnotationCommand(s, page, ann, on_change=self._on_session_change))

    # =====================================================================
    # Yapışkan notlar ve Yorumlar paneli
    # =====================================================================
    def _show_comments_panel(self):
        self.side.show_page("comments")

    def refresh_comments_panel(self):
        if not hasattr(self, "comments"):
            return
        s = self.active_session
        notes = []
        if s:
            for pidx in sorted(s.annotations):
                notes += [(pidx, a) for a in s.annotations[pidx] if isinstance(a, NoteAnnotation)]
        self.comments.set_notes(notes)

    def _note_page(self, ann):
        s = self.active_session
        if s:
            for pidx, lst in s.annotations.items():
                if ann in lst:
                    return pidx
        return None

    def on_note_requested(self, pt: QPointF):
        s = self.active_session
        if not s:
            return
        text = ask_note_text(self, "Yeni not", "")
        if text is None or not text.strip():
            return
        pw, ph = s.pdf.page_size(s.current_page)
        x = min(max(0.0, pt.x()), max(0.0, pw - NoteAnnotation.SIZE))
        y = min(max(0.0, pt.y()), max(0.0, ph - NoteAnnotation.SIZE))
        ann = NoteAnnotation(x, y, text.strip(), QColor(self.state.note_color))
        s.undo_stack.push(AddAnnotationCommand(s, s.current_page, ann,
                                               on_change=self._on_session_change, label="Not Ekle"))
        self.status.setText("Not eklendi. Çift tıklayarak düzenleyebilir, Yorumlar panelinden yanıtlayabilirsiniz.")

    def _push_note_state(self, ann, new_state, label):
        s = self.active_session
        page = self._note_page(ann)
        if not s or page is None:
            return
        s.undo_stack.push(NoteStateCommand(s, page, ann, new_state,
                                           on_change=self._on_session_change, label=label))

    def edit_note(self, ann):
        text = ask_note_text(self, "Notu düzenle", ann.text)
        if text is None or not text.strip() or text.strip() == ann.text:
            return
        st = ann.snapshot()
        st["text"] = text.strip()
        self._push_note_state(ann, st, "Notu Düzenle")

    def reply_note(self, ann):
        text = ask_note_text(self, "Yanıtla", "", prompt=f"{ann.author} notuna yanıt")
        if text is None or not text.strip():
            return
        from models import default_author, _now_iso
        st = ann.snapshot()
        st["replies"].append(dict(author=default_author(), created=_now_iso(), text=text.strip()))
        self._push_note_state(ann, st, "Yanıt Ekle")

    def toggle_note_done(self, ann):
        st = ann.snapshot()
        st["done"] = not ann.done
        self._push_note_state(ann, st, "Çözüldü" if st["done"] else "Yeniden Aç")

    def _on_comment_goto(self, page, ann):
        self.goto_page(page)
        for gitem, a in self.view.item_ann_map.items():
            gitem.setSelected(a is ann)
            if a is ann:
                self.view.centerOn(gitem)

    def export_comments(self):
        s = self.active_session
        if not s:
            return
        notes = []
        for pidx in sorted(s.annotations):
            notes += [(pidx, a) for a in s.annotations[pidx] if isinstance(a, NoteAnnotation)]
        if not notes:
            return
        default = os.path.splitext(s.path)[0] + "_yorumlar.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Yorumları Kaydet", default, "Metin (*.txt)")
        if not path:
            return
        lines = [f"Yorumlar — {s.title}", ""]
        for pidx, n in notes:
            lines.append(f"[Sayfa {pidx + 1}] {n.author} · {n.created}{' · ÇÖZÜLDÜ' if n.done else ''}")
            lines.append(n.text)
            for r in n.replies:
                lines.append(f"    > {r.get('author', '')} · {r.get('created', '')}: {r.get('text', '')}")
            lines.append("")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self._toast_saved("Yorumlar kaydedildi", path)
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")

    # =====================================================================
    # Sayfa numarası / üstbilgi / Bates ve sayfa kırpma
    # =====================================================================
    def save_pdf_with_headfoot(self, bates: bool):
        s = self.active_session
        if not s:
            return
        initial = getattr(self, "_headfoot_cfg", None) or HeadFootConfig()
        dlg = HeadFootDialog(initial, s.pdf.page_count, os.path.basename(s.path), bates, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cfg = dlg.get_config()
        self._headfoot_cfg = cfg
        suffix = "_bates" if bates else "_numarali"
        default = os.path.splitext(s.path)[0] + suffix + ".pdf"
        path, _ = QFileDialog.getSaveFileName(self, "PDF Olarak Kaydet", default, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            s.pdf.export_pdf(path, s.annotations, self.font_ctx, headfoot=cfg,
                             security=getattr(s, "security", None),
                             source_name=os.path.basename(s.path))
            self.status.setText(f"Kaydedildi: {path}")
            self._toast_saved("PDF kaydedildi", path)
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")

    def open_crop_pages(self):
        s = self.active_session
        if not s:
            return

        def auto(idx):
            r = s.pdf.content_bbox(idx)
            if r is None:
                return None
            w, h = s.pdf.page_size(idx)
            return (r.y0, h - r.y1, r.x0, w - r.x1)

        dlg = CropPagesDialog(s.pdf.page_count, s.current_page, s.pdf.page_size(s.current_page),
                              auto, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        top, bottom, left, right = dlg.margins_pt()
        crops = {}
        for idx in dlg.pages():
            w, h = s.pdf.page_size(idx)
            if w - left - right < 20 or h - top - bottom < 20:
                continue
            crops[idx] = fitz.Rect(left, top, w - right, h - bottom)
        if not crops:
            QMessageBox.warning(self, "Kırp", "Kırpma değerleri sayfa boyutuna göre çok büyük.")
            return
        self._apply_crops(crops)

    def _apply_crops(self, crops):
        s = self.active_session
        if not s:
            return

        def done():
            self._mark_dirty()
            self._build_thumbnails()
            self.view.show_page(s, s.current_page, invert=self.night_mode)
            self.refresh_layers_panel()

        s.undo_stack.push(CropPagesCommand(s, crops, on_done=done))
        self.toasts.show(f"{len(crops)} sayfa kırpıldı (Ctrl+Z ile geri alınır)")

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
            self._schedule_diff()
        else:
            self._select_tool("select", self.btn_select)
            self._cancel_diff()
        self._update_prop_bar()
        self._place_floating()

    # -- metin farkı (iki sürüm) ---------------------------------------------
    def compare_documents(self):
        """Karşılaştırma modunu açar ve sol/sağ belgelerin metin farkını çıkarır."""
        if not self.act_compare.isChecked():
            self.act_compare.setChecked(True)
            self.toggle_compare_mode(True)
        self._run_diff()

    def _schedule_diff(self):
        if not self.act_compare.isChecked():
            return
        self._cancel_diff()
        self._diff_timer.start()

    def _cancel_diff(self):
        self._diff_timer.stop()
        self._diff_token += 1
        if self._diff_task is not None:
            self._diff_task.cancel()
            self._diff_task = None
        self._diff = None
        self.pane_left.set_marks({})
        self.pane_right.set_marks({})

    def _run_diff(self):
        self._cancel_diff()
        sa, sb = self.pane_left.session, self.pane_right.session
        if sa is None or sb is None or sa is sb:
            self.diff_panel.set_message("Metin farkı için sol ve sağ panelde iki FARKLI belge seçin "
                                        "(örn. eski ve yeni sürüm).")
            return
        token = self._diff_token
        ignore_case = self.diff_panel.ignore_case
        self.diff_panel.set_busy()

        def job(progress, cancelled):
            return textdiff.compare(sa.pdf, sb.pdf, ignore_case=ignore_case, check=cancelled,
                                    progress=progress)

        task = _OcrTask(job)
        task.signals.progress.connect(lambda d, t: token == self._diff_token
                                      and self.diff_panel.set_busy(d, t))
        task.signals.done.connect(lambda res: self._on_diff_done(token, res))
        task.signals.failed.connect(lambda msg: token == self._diff_token and
                                    self.diff_panel.set_message(f"Karşılaştırma yapılamadı: {msg}"))
        self._diff_task = task
        self.threadpool.start(task)

    def _on_diff_done(self, token: int, res):
        if token != self._diff_token or res.cancelled:
            return
        self._diff_task = None
        self._diff = res
        sa, sb = self.pane_left.session, self.pane_right.session
        self.diff_panel.set_names(*(os.path.basename(x.path) if x is not None and x.path else "" for x in (sa, sb)))
        self.diff_panel.show_result(res)
        self._apply_diff_marks()

    def _apply_diff_marks(self):
        if self._diff is None or self._diff.error:
            return
        left: dict = {}
        right: dict = {}
        for c in self.diff_panel.visible_changes():
            for page, r in c.a_rects:
                left.setdefault(page, []).append((*r, "del"))
            for page, r in c.b_rects:
                right.setdefault(page, []).append((*r, "add"))
        self.pane_left.set_marks(left)
        self.pane_right.set_marks(right)

    def _goto_change(self, c):
        fa, fb = c.focus_a(), c.focus_b()
        if fa:
            self.pane_left.goto(fa[0], fa[1])
        if fb:
            self.pane_right.goto(fb[0], fb[1])

    # =====================================================================
    # Kapatma
    # =====================================================================
    def closeEvent(self, event):
        for s in list(self.sessions):
            if not self._confirm_discard(s):
                event.ignore()
                return
        share = getattr(self, "_share_dialog", None)
        if share is not None:
            share.close()                        # telefon aktarım sunucusu durur
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("sidePanelOpen", self.side.is_open() or not self.sessions and self._side_was_open)
        for s in self.sessions:
            s.close()
        super().closeEvent(event)


def _send_to_running_instance(paths) -> bool:
    """Uygulama zaten açıksa dosyaları ona gönderir ("Birlikte aç" ile ikinci
    pencere açılmasın). Gönderildiyse True."""
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(_instance_key())
    if not sock.waitForConnected(300):
        return False
    sock.write(("\n".join(paths) + "\n").encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def _instance_key() -> str:
    import getpass
    return f"PDFAnnotator-{getpass.getuser()}"


def _listen_for_instances(win):
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(win)
    QLocalServer.removeServer(_instance_key())
    if not server.listen(_instance_key()):
        return None

    def on_conn():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        buf = bytearray()
        done = [False]

        def read():
            buf.extend(bytes(sock.readAll()))

        def finish():
            read()
            if done[0]:
                return
            done[0] = True
            paths = [p for p in buf.decode("utf-8", "replace").splitlines()
                     if p.strip() and os.path.isfile(p)]
            if paths:
                win.open_paths(paths)
            if win.isMinimized():
                win.showNormal()
            win.raise_()
            win.activateWindow()
            sock.deleteLater()

        sock.readyRead.connect(read)
        sock.disconnected.connect(finish)
        read()                               # bağlanmadan önce gelmiş veri
        if sock.state() != sock.LocalSocketState.ConnectedState:
            finish()

    server.newConnection.connect(on_conn)
    return server


def main():
    app = QApplication(sys.argv)
    files = [os.path.abspath(a) for a in sys.argv[1:] if os.path.isfile(a)]
    if _send_to_running_instance(files):
        return
    # Qt'nin kendi metinleri (Tamam/İptal, dosya penceresi vb.) Türkçe olsun
    from PySide6.QtCore import QLibraryInfo, QTranslator
    translator = QTranslator(app)
    if translator.load("qtbase_tr", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    register_app_fonts()
    win = MainWindow()
    win._instance_server = _listen_for_instances(win)
    win.show()
    if files:
        QTimer.singleShot(0, lambda: win.open_paths(files))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
