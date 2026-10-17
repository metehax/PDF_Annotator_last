"""
main_window.py
===============
Ana pencere: üst araç çubuğu, sekmeli çoklu belge yönetimi (QTabBar),
kenetlenebilir paneller (QDockWidget — sol: Küçük Resimler/İçindekiler/Ara,
sağ: Özellikler/Katmanlar), alt yakınlaştırma/durum çubuğu, QUndoStack /
QUndoGroup entegrasyonu. Yöntem grupları mw_*.py mixin dosyalarındadır.

Bu dosya tüm parçaları birbirine bağlar; iş mantığının çoğu models.py ve
pdf_engine.py'de yaşar, views.py ise canvas etkileşimlerini yönetir.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QUndoGroup
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from models import DocumentSession, RedactionAnnotation, ToolState, ZOrderCommand
from pdf_engine import IMAGE_EXTS, PasswordRequired, PDFDocument, is_image_path, resolve_font_ctx
from fonts import register_app_fonts
from ui import theme as ui_theme
from ui.icons import icon
import docsec
import workspace
from ui.palette import Command, CommandPalette
from ui.signatures import SignatureLibrary
from ui.stamps import StampLibrary
from ui.toast import ToastManager
from ui.welcome import WelcomeScreen
from ui.ocrdialog import _OcrTask

from mw_common import (
    APP_ID, CANVAS_TOP_INSET, OPEN_FILTER, RECENT_MAX, TOOLS, TOOL_KEYS, _OpenCancelled,
)
from mw_annot import AnnotMixin
from mw_build import BuildMixin
from mw_compare import CompareMixin
from mw_doctools import DocToolsMixin
from mw_export import ExportMixin
from mw_forms import FormsMixin
from mw_nav import NavMixin
from mw_notes import NotesMixin
from mw_ocr import OcrMixin
from mw_pages import PagesMixin
from mw_share import ShareMixin
from mw_sign import SignMixin
from mw_workspace import WorkspaceMixin


# ---------------------------------------------------------------------------
# Ana pencere
# ---------------------------------------------------------------------------
class MainWindow(
    BuildMixin, ExportMixin, NotesMixin, AnnotMixin, NavMixin, PagesMixin, DocToolsMixin, SignMixin, FormsMixin,
    OcrMixin, CompareMixin, WorkspaceMixin, ShareMixin, QMainWindow,
):
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
        workspace.configure(self.settings)
        RedactionAnnotation.final_view = str(self.settings.value("redactFinal", "false")).lower() == "true"
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


    def _set_edit_mode(self, mode):
        self.state.edit_mode = mode
        self._refresh_current_page()

    def _refresh_current_page(self):
        if self.active_session:
            self.view.refresh_current_page()


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
            self._set_canvas_inset(CANVAS_TOP_INSET)
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
        self._set_canvas_inset(self.prop_bar.geometry().bottom() + 8)      # sayfa, özellik çubuğunun altından başlasın

    def _set_canvas_inset(self, px: int):
        """Çizim alanının üst boşluğu: yüzen çubukların sayfanın ilk satırlarını örtmemesi için çubuk yüksekliğine uyar."""
        px = max(CANVAS_TOP_INSET, int(px))
        if getattr(self, "_canvas_inset", None) != px:
            self._canvas_inset = px
            self.view.setViewportMargins(0, px, 0, 0)

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

    def toggle_fullscreen(self):
        """F11: tam ekran aç/kapat."""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _cycle_tab(self, step: int):
        """Ctrl+Tab / Ctrl+Shift+Tab: açık belgeler arasında dolaş."""
        n = len(self.sessions)
        if n > 1:
            self.switch_session((self.doc_tabbar.currentIndex() + step) % n)

    def _status_default(self) -> str:
        """Durum çubuğunun kalıcı metni: belge yokken yönerge, varken seçili aracın kısa açıklaması."""
        if not getattr(self, "sessions", None):
            return "Başlamak için bir dosya açın ya da pencereye sürükleyin."
        if getattr(self, "act_compare", None) is not None and self.act_compare.isChecked():
            return "Karşılaştırma modu · salt okunur"
        tool = self.state.tool
        for t in TOOLS:
            if t and t[0] == tool:
                return f"{t[1]} · {t[3]} ({TOOL_KEYS[tool]})"
        return ""

    def _toast_saved(self, text, path, folder=False, note=""):
        target = path if folder else os.path.dirname(os.path.abspath(path))

        def reveal():
            if not folder and sys.platform == "win32":
                import subprocess
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(target))

        extra = f"<br><span style='color:gray'>{note}</span>" if note else ""
        self.toasts.show(f"{text}<br><span style='color:gray'>{os.path.basename(path) or path}</span>{extra}",
                         "success", action=("Klasörde göster", reveal), timeout_ms=6000 if note else 3200)

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
        self.status.reset()
        self._update_prop_bar()
        self._place_floating()
        if tool == "number":
            self._refresh_number_label()
        if tool == "redact":
            self._redact_first_use_hint()
        cursor = (Qt.CursorShape.IBeamCursor if tool in ("text", "edit", "number", "note")
                  else Qt.CursorShape.CrossCursor if tool != "select"
                  else Qt.CursorShape.ArrowCursor)
        self.view.viewport().setCursor(cursor)

    def _set_redact_color(self, color):
        """Sansür dolgu rengini ayarlar (hazır düğmeler / KVKK penceresi) ve renk düğmelerini günceller."""
        self.state.redact_color = QColor(color)
        for btn in self._color_buttons_by_attr.get("redact_color", []):
            btn.setStyleSheet(f"background:{self.state.redact_color.name()};")

    def set_redact_final_view(self, on: bool):
        """Sansürün ekrandaki "nihai görünümü" (tam dolgu, kenarsız). Yalnız görünümdür; çıktı her zaman tam dolgu."""
        on = bool(on)
        RedactionAnnotation.final_view = on
        self.settings.setValue("redactFinal", on)
        for w in (getattr(self, "act_redact_final", None), getattr(self, "chk_redact_final", None)):
            if w is not None and w.isChecked() != on:
                w.blockSignals(True)
                w.setChecked(on)
                w.blockSignals(False)
        self.view.scene().update()
        for v in (self.view, self.pane_left, self.pane_right):
            vp = getattr(v, "viewport", None)
            if vp:
                vp().update()

    def _redact_first_use_hint(self):
        """Sansür aracı ilk seçildiğinde bir kez uyarır."""
        if str(self.settings.value("redactHintShown", "false")).lower() == "true":
            return
        self.settings.setValue("redactHintShown", True)
        self.toasts.show("Kaydedince altındaki metin ve resim PDF'ten KALICI silinir.", "warning", timeout_ms=6000)

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
                                                 workspace.last_dir(), OPEN_FILTER)
        if paths:
            workspace.remember(paths[0])
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
        self.status.reset()
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
            self._drop_draft(s)
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
        self._drop_draft(closing)
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
    # Küçük resimler / İçindekiler / sayfa gösterimi / yakınlaştırma
    # =====================================================================
    _THUMB_LOADED = Qt.ItemDataRole.UserRole + 1


    # =====================================================================
    # Kapatma
    # =====================================================================
    def closeEvent(self, event):
        for s in list(self.sessions):
            if not self._confirm_discard(s):
                event.ignore()
                return
        for s in self.sessions:
            self._drop_draft(s)                  # normal kapanış: kurtarma taslağı gerekmez
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
    QTimer.singleShot(600, win.startup_checks)        # taşıma önerisi, kapanmayan belgeler, otomatik kurtarma
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
