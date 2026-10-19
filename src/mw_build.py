"""
mw_build.py
===========
Arayüz kurulumu: menüler, üst çubuk, yan panel, çizim alanı, durum çubuğu, özellik sayfaları, kısayollar ve ortak satır yardımcıları.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations

from typing import Optional


from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIntValidator, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMenu, QPushButton, QSizePolicy, QSlider, QSpinBox, QSplitter, QStackedWidget, QTabBar,
    QToolButton, QTreeWidget, QVBoxLayout, QWidget,
)

from views import ComparePane, PDFView
from fonts import FONT_FAMILIES
from models import RedactionAnnotation
from ui import theme as ui_theme
from ui.icons import icon, pixmap as icon_pixmap
from ui.overlays import FloatingBar
from ui.comments import CommentsPanel
from ui.compare import CompareDiffPanel
import textdiff
import forms
from ui.formui import FormsPanel
from ui.redactopts import RedactOptions
from ui.sidepanel import SidePanel
from ui.widgets import StatusMessage, ThumbnailDelegate
from ui.ocrdialog import _OcrTask
from mw_common import CANVAS_TOP_INSET, TOOLS, TOOL_KEYS, TOOL_NAMES


class BuildMixin:
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
        A(m_file, "save", "Kopya olarak kaydet…", self.save_document, "Ctrl+S")
        m_exp = m_file.addMenu(icon("download"), "Dışa aktar")
        self._doc_controls.append(m_exp.menuAction())
        A(m_exp, "file", "PDF olarak kaydet…", self.save_pdf, "Ctrl+Shift+S")
        A(m_exp, "compress", "Sıkıştırarak kaydet…", self.save_compressed)
        A(m_exp, "image", "Resim olarak kaydet…", self.save_as_image)
        A(m_exp, "watermark", "Filigranlı PDF olarak kaydet…", self.save_pdf_with_watermark)
        m_exp.addSeparator()
        A(m_exp, "image", "Bu sayfayı PNG", lambda: self.export_image_current("png"))
        A(m_exp, "image", "Bu sayfayı JPEG", lambda: self.export_image_current("jpg"))
        A(m_exp, "images", "Tüm sayfaları PNG (klasöre)", lambda: self.export_all_pages_images("png"))
        m_share = m_file.addMenu(icon("share"), "Paylaş")
        self._doc_controls.append(m_share.menuAction())
        A(m_share, "cloud", "Bulut klasörüne kaydet…", self.share_cloud)
        A(m_share, "folder_open", "Dosya konumunu aç", self.share_reveal)
        m_file.addSeparator()
        m_in = m_file.addMenu(icon("scan"), "Tara ve içe aktar")
        A(m_in, "scan", "Fotoğraftan belge tara…", self.scan_images, needs_doc=False)
        A(m_in, "image_pdf", "Görselleri PDF'e çevir…", self.images_to_pdf, needs_doc=False)
        A(m_in, "phone", "Telefonla aktar (QR)…", self.open_share, needs_doc=False)
        m_split = m_file.addMenu(icon("merge"), "Birleştir ve böl")
        A(m_split, "merge", "Birleştir…", self.merge_pdfs, needs_doc=False)
        A(m_split, "split", "Her sayfayı ayrı PDF yap…", self.split_all_pages)
        A(m_split, "scissors", "Sayfa aralığını çıkar…", self.extract_page_range)
        m_file.addSeparator()
        A(m_file, "printer", "Yazdır…", self.print_document, "Ctrl+P")
        m_file.addSeparator()
        A(m_file, "project", "Projeyi kaydet (JSON)…", self.save_project)
        A(m_file, "folder", "Proje aç (JSON)…", self.open_project, needs_doc=False)
        m_file.addSeparator()
        A(m_file, "close", "Sekmeyi kapat", lambda: self.close_session(self.doc_tabbar.currentIndex()),
          "Ctrl+W")
        A(m_file, "exit", "Çıkış", self.close, "Ctrl+Q", needs_doc=False)

        m_edit = QMenu("Düzenle", self)
        self.act_undo = self.undo_group.createUndoAction(self, "Geri al")
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_undo.setIcon(icon("undo"))
        self.act_redo = self.undo_group.createRedoAction(self, "Yinele")
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.act_redo.setIcon(icon("redo"))
        self.addAction(self.act_undo)
        self.addAction(self.act_redo)
        m_edit.addAction(self.act_undo)
        m_edit.addAction(self.act_redo)
        m_edit.addSeparator()
        A(m_edit, "copy", "Kopyala", self.copy_selected, QKeySequence.StandardKey.Copy)
        A(m_edit, "scissors", "Kes", self.cut_selected, QKeySequence.StandardKey.Cut)
        A(m_edit, "clipboard", "Yapıştır", self.paste_annotations, QKeySequence.StandardKey.Paste)
        A(m_edit, "select", "Sayfadaki tüm işaretleri seç", self.select_all_annotations, QKeySequence.StandardKey.SelectAll)
        m_edit.addSeparator()
        A(m_edit, "trash", "Seçileni sil", self.delete_selected, QKeySequence.StandardKey.Delete)
        m_edit.addSeparator()
        A(m_edit, "search", "Bul…", self._focus_search, "Ctrl+F")
        A(m_edit, "sliders", "Komut paleti…", self.open_palette, "Ctrl+K", needs_doc=False)
        A(m_edit, "settings", "Ayarlar…", self.open_preferences, "Ctrl+,", needs_doc=False)

        m_view = QMenu("Görünüm", self)
        A(m_view, "zoom_in", "Yakınlaştır", lambda: self.view.animate_zoom(self.view.zoom() * 1.25), "Ctrl+=")
        A(m_view, "zoom_out", "Uzaklaştır", lambda: self.view.animate_zoom(self.view.zoom() / 1.25), "Ctrl+-")
        A(m_view, "one_to_one", "Gerçek boyut (%100)", lambda: self.view.animate_zoom(1.0), "Ctrl+1")
        A(m_view, "fit_width", "Genişliğe sığdır", self.fit_width, "Ctrl+2")
        A(m_view, "fit_page", "Tam sayfa", self.fit_page, "Ctrl+0")
        m_view.addSeparator()
        A(m_view, "fit_page", "Tam ekran", self.toggle_fullscreen, "F11", needs_doc=False)
        A(m_view, "chevron_right", "Sonraki belge sekmesi", lambda: self._cycle_tab(1), "Ctrl+Tab", needs_doc=False)
        A(m_view, "chevron_left", "Önceki belge sekmesi", lambda: self._cycle_tab(-1), "Ctrl+Shift+Tab", needs_doc=False)
        A(m_view, "grid", "Kenar paneli", self._toggle_side_panel, "Ctrl+B", needs_doc=False)
        A(m_view, "comment", "Yorumlar paneli", self._show_comments_panel, "Ctrl+Shift+M")
        self.act_night = A(m_view, "contrast", "Gece modu", self.toggle_night_mode, checkable=True)
        self.act_redact_final = A(m_view, "redact", "Sansürün nihai görünümü", self.set_redact_final_view, checkable=True,
                                  needs_doc=False)
        self.act_redact_final.setChecked(RedactionAnnotation.final_view)
        self.act_compare = A(m_view, "compare", "Karşılaştırma modu", self.toggle_compare_mode,
                             checkable=True)
        A(m_view, "compare", "Metin farkını göster", self.compare_documents)
        A(m_view, "chevron_down", "Sonraki metin değişikliği", lambda: self.diff_panel.step(1), "F8")
        A(m_view, "chevron_up", "Önceki metin değişikliği", lambda: self.diff_panel.step(-1), "Shift+F8")
        m_view.addSeparator()
        A(m_view, "moon", "Açık / koyu tema", self.toggle_theme, "Ctrl+Shift+L", needs_doc=False)

        m_doc = QMenu("Belge", self)
        m_pg = m_doc.addMenu(icon("pages"), "Sayfa")
        self._doc_controls.append(m_pg.menuAction())
        A(m_pg, "file_plus", "Sonrasına boş sayfa ekle", lambda: self._insert_blank_page(page() + 1))
        A(m_pg, "file_copy", "Sayfayı kopyala", lambda: self._duplicate_page(page()))
        A(m_pg, "trash", "Sayfayı sil", lambda: self._delete_page(page()))
        m_pg.addSeparator()
        A(m_pg, "rotate_cw", "Saat yönünde döndür", lambda: self._rotate_current_page(90), "Ctrl+R")
        A(m_pg, "rotate_ccw", "Saatin tersine döndür", lambda: self._rotate_current_page(-90),
          "Ctrl+Shift+R")
        m_pg.addSeparator()
        A(m_pg, "crop", "Sayfa kenarlarını kırp…", self.open_crop_pages)
        m_hf = m_doc.addMenu(icon("headfoot"), "Numara, üstbilgi ve filigran")
        self._doc_controls.append(m_hf.menuAction())
        A(m_hf, "headfoot", "Sayfa numarası, üstbilgi ve altbilgi…",
          lambda: self.save_pdf_with_headfoot(False))
        A(m_hf, "number", "Bates numaralandır…", lambda: self.save_pdf_with_headfoot(True))
        A(m_hf, "watermark", "Filigran ekle…", self.save_pdf_with_watermark)
        A(m_doc, "ocr", "OCR (metin tanıma)…", self.open_ocr_dialog)
        m_cv = m_doc.addMenu(icon("convert"), "Dönüştür ve düzleştir")
        self._doc_controls.append(m_cv.menuAction())
        A(m_cv, "convert", "Word'e dönüştür (.docx)…", lambda: self.open_convert("docx"))
        A(m_cv, "calc", "Excel'e dönüştür (tablolar, .xlsx)…", lambda: self.open_convert("xlsx"))
        A(m_cv, "flatten", "Düzleştir ve kaydet…", self.open_flatten)
        A(m_cv, "scan", "Sayfaları tarayıcıda düzelt…", self.scan_document)
        m_sec = m_doc.addMenu(icon("lock"), "Güvenlik ve gizlilik")
        self._doc_controls.append(m_sec.menuAction())
        A(m_sec, "lock", "Parola koruması…", self.open_password)
        A(m_sec, "shield", "Güvenlik denetimi…", self.open_security_check)
        A(m_sec, "privacy", "Kişisel verileri bul ve karart (KVKK)…", self.open_kvkk, "Ctrl+Shift+K")
        m_doc.addSeparator()
        A(m_doc, "info", "Belge bilgileri…", self.open_doc_info, "Ctrl+D")
        A(m_doc, "eye", "Erişilebilirlik denetimi…", self.open_a11y)
        A(m_doc, "workflow", "Görsel iş akışı (adım zinciri)…", self.open_workflow, "Ctrl+Shift+W", needs_doc=False)

        m_form = QMenu("Form", self)
        A(m_form, "form", "Formlar paneli", lambda: self.side.show_page("forms"))
        A(m_form, "plus", "Yeni form alanı (araç)", lambda: self._tool_shortcut("form"))
        A(m_form, "edit_text", "Seçili alanın özellikleri…",
          lambda: self.edit_form_field(self.forms_panel.current_field()))
        A(m_form, "trash", "Seçili alanı sil",
          lambda: self.delete_form_field(self.forms_panel.current_field()))
        m_form.addSeparator()
        A(m_form, "reset", "Formu sıfırla", self.reset_form)
        A(m_form, "calc", "Alanları yeniden hesapla", self.recalculate_form)

        m_sign = QMenu("İmza", self)
        A(m_sign, "sign", "İmza bas (araç)", lambda: self._tool_shortcut("sign"))
        A(m_sign, "plus", "Yeni elektronik imza…", self.new_signature, needs_doc=False)
        A(m_sign, "stamp", "Damga kütüphanesi…", self.open_stamp_library, needs_doc=False)
        A(m_sign, "form", "İmza alanı oluştur", self.start_signature_field)
        m_sign.addSeparator()
        A(m_sign, "lock", "Dijital olarak imzala (.pfx)…", self.sign_digitally)
        A(m_sign, "shield", "İmzaları doğrula…", self.verify_signatures)

        m_help = QMenu("Yardım", self)
        A(m_help, "info", "Klavye kısayolları", self._show_shortcuts, "F1", needs_doc=False)
        m_help.addSeparator()
        A(m_help, "update", "Güncellemeleri denetle…", lambda: self.check_updates(manual=True), needs_doc=False)
        A(m_help, "app", "Hakkında", self._show_about, needs_doc=False)

        # sağ üstteki "Dışa Aktar" düğmesinin menüsü
        self.export_menu = QMenu(self)
        for entry in (
            ("file", "PDF olarak kaydet…", self.save_pdf),
            ("compress", "Sıkıştırarak kaydet…", self.save_compressed),
            ("image", "Resim olarak kaydet (orijinal boyut)", self.save_as_image),
            ("watermark", "Filigranlı PDF olarak kaydet…", self.save_pdf_with_watermark),
            ("headfoot", "Numaralı / üstbilgili PDF kaydet…",
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

        self.btn_share = QToolButton()
        self.btn_share.setObjectName("secondaryTb")
        self.btn_share.setIcon(icon("share"))
        self.btn_share.setIconSize(QSize(18, 18))
        self.btn_share.setText("Paylaş")
        self.btn_share.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_share.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_share.setCursor(Qt.CursorShape.PointingHandCursor)
        share_menu = QMenu(self.btn_share)
        share_menu.addAction(icon("phone"), "Telefona gönder…", self.open_share_send)
        a_cloud = share_menu.addAction(icon("cloud"), "Bulut klasörüne kaydet…", self.share_cloud)
        a_loc = share_menu.addAction(icon("folder_open"), "Dosya konumunu aç", self.share_reveal)
        self._doc_controls += [a_cloud, a_loc]
        self.btn_share.setMenu(share_menu)
        h.addWidget(self.btn_share)
        h.addSpacing(4)

        self.btn_settings = QToolButton()
        self.btn_settings.setObjectName("secondaryTb")
        self.btn_settings.setIcon(icon("settings"))
        self.btn_settings.setIconSize(QSize(18, 18))
        self.btn_settings.setText("Ayarlar")
        self.btn_settings.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_settings.setToolTip("Ayarlar (Ctrl+,)")
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(lambda: self.open_preferences())
        h.addWidget(self.btn_settings)
        h.addSpacing(4)

        self.btn_save = QPushButton(icon("save", "on_accent"), "Kopya kaydet")
        self.btn_save.setObjectName("primary")
        self.btn_save.setIconSize(QSize(18, 18))
        self.btn_save.setToolTip("İşaretli kopyayı yeni dosya olarak kaydeder; özgün dosya değişmez (Ctrl+S)")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_document)
        h.addWidget(self.btn_save)
        self._doc_controls += [self.btn_export, self.btn_save]
        self.apply_view_prefs()
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
        self.diff_panel.exitRequested.connect(lambda: self.act_compare.setChecked(False))
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

        self.status = StatusMessage(self._status_default)
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

        self.redact_opts = RedactOptions(self)
        self.chk_redact_final = QCheckBox("Nihai görünüm (tam dolgu, kenarsız)")
        self.chk_redact_final.setToolTip("Yalnız ekrandaki görünümü değiştirir; dışa aktarılan PDF her zaman tam dolgudur.")
        self.chk_redact_final.setChecked(RedactionAnnotation.final_view)
        self.chk_redact_final.toggled.connect(self.set_redact_final_view)
        redact_warn = QLabel("Kaydedince altındaki metin silinir")
        redact_warn.setObjectName("redactWarn")
        self.prop_stack.addWidget(page(
            self.redact_opts,
            self._color_row("Özel renk", "redact_color"),
            self.chk_redact_final,
            redact_warn,
            self._hint("Kaydedince altındaki metin ve resim PDF'ten KALICI silinir. Düzenlerken kutu "
                       "yumuşak (yarı saydam) görünür; çıktıda tam dolgudur. Dikkatli çizin.", warn=True),
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
