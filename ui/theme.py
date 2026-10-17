"""
ui/theme.py
===========
Renk sistemi ve uygulama stili.

* `TOKENS` — açık ve koyu tema için tek kaynak renk tablosu. Arayüzün
  her yeri renkleri buradan alır (stil dosyası, ikonlar, çizim alanı).
* `apply(app, name)` — QPalette + yazı tipi + stil dosyasını uygular.
  Temel renkler QPalette ile verilir; stil kuralları yalnızca gereken
  bileşenlere yazılır (genel `QWidget {...}` kuralı çizim alanını da
  stil motorundan geçirip yavaşlattığı için bilerek yok).
* `system_prefers_dark()` — Windows'un açık/koyu tercihi.
* QSS'nin resim isteyen yerleri (açılır ok, onay işareti, sekme kapatma)
  için SVG'ler geçici klasöre tema rengiyle yazılır.
"""

from __future__ import annotations

import os
import tempfile
from typing import Dict

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QMenu

TOKENS: Dict[str, Dict[str, str]] = {
    "dark": dict(
        bg="#141518",            # pencere zemini
        surface="#1b1c20",       # çubuklar, paneller
        surface2="#24262b",      # giriş alanları, düğme zemini
        hover="#2c2e34",
        pressed="#33363d",
        border="#2a2c31",
        border_strong="#3a3d44",
        text="#e9eaed",
        text_muted="#a3a7b0",
        text_faint="#6e737c",
        accent="#5b7cfa",
        accent_hover="#6d8bff",
        accent_pressed="#4a69e6",
        accent_soft="rgba(91, 124, 250, 0.16)",
        accent_text="#9fb3ff",
        danger="#f05252",
        good="#3fb97a",
        warning="#f2b544",
        warning_soft="rgba(242, 181, 68, 0.10)",
        canvas="#26282d",
        icon="#c3c6cd",
        icon_hover="#ffffff",
        icon_on="#ffffff",
        icon_disabled="#4f535b",
        tooltip_bg="#f0f1f3",
        tooltip_fg="#141518",
        scroll="#3b3e45",
        scroll_hover="#50545c",
        shadow="rgba(0, 0, 0, 0.45)",
    ),
    "light": dict(
        bg="#eef0f3",
        surface="#ffffff",
        surface2="#f3f4f6",
        hover="#e9ebef",
        pressed="#dfe2e7",
        border="#e2e4e8",
        border_strong="#cfd3d9",
        text="#16181d",
        text_muted="#5a606a",
        text_faint="#8b919b",
        accent="#3e63f2",
        accent_hover="#3456dc",
        accent_pressed="#2c4bc4",
        accent_soft="rgba(62, 99, 242, 0.12)",
        accent_text="#2f51d6",
        danger="#dc3a3a",
        good="#1f9d57",
        warning="#b7791f",
        warning_soft="rgba(214, 158, 46, 0.12)",
        canvas="#e3e6ea",
        icon="#454a53",
        icon_hover="#16181d",
        icon_on="#ffffff",
        icon_disabled="#b8bcc3",
        tooltip_bg="#1f2126",
        tooltip_fg="#f4f5f7",
        scroll="#c4c8ce",
        scroll_hover="#a9aeb6",
        shadow="rgba(16, 24, 40, 0.18)",
    ),
}

_current = "dark"


def current() -> Dict[str, str]:
    return TOKENS[_current]


def qcolor(key: str) -> QColor:
    """Tema rengini QColor olarak verir ("rgba(r, g, b, a)" biçimi dahil)."""
    v = current()[key]
    if v.startswith("rgba("):
        r, g, b, a = [x.strip() for x in v[5:-1].split(",")]
        c = QColor(int(r), int(g), int(b))
        c.setAlphaF(float(a))
        return c
    return QColor(v)


def name() -> str:
    return _current


def system_prefers_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return True


# ---------------------------------------------------------------------------
# QSS'nin ihtiyaç duyduğu küçük SVG'ler (tema rengiyle diske yazılır)
# ---------------------------------------------------------------------------
_ASSET_DIR = os.path.join(tempfile.gettempdir(), "pdf_annotator_ui")


def _asset(icon_name: str, color: str, stroke: float = 2.0) -> str:
    from ui.icons import svg_bytes
    os.makedirs(_ASSET_DIR, exist_ok=True)
    fname = f"{icon_name}_{color.strip('#')}_{str(stroke).replace('.', '_')}.svg"
    path = os.path.join(_ASSET_DIR, fname)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(svg_bytes(icon_name, color, stroke))
    return path.replace("\\", "/")


def stylesheet(t: Dict[str, str]) -> str:
    chevron = _asset("chevron_down", t["text_muted"])
    chevron_up = _asset("chevron_up", t["text_muted"])
    check = _asset("check", "#ffffff", 3.0)
    close = _asset("close", t["text_faint"])
    close_hover = _asset("close", t["text"])
    return f"""
/* ---- temel ---------------------------------------------------------- */
QMainWindow, QDialog {{ background:{t['bg']}; color:{t['text']}; }}
QToolTip {{ background:{t['tooltip_bg']}; color:{t['tooltip_fg']}; border:none;
    border-radius:6px; padding:5px 8px; font-size:12px; }}
QLabel {{ color:{t['text_muted']}; background:transparent; }}
QLabel:disabled {{ color:{t['text_faint']}; }}

/* ---- çubuklar -------------------------------------------------------- */
#toolbar {{ background:{t['surface']}; border-bottom:1px solid {t['border']}; }}
#bottombar {{ background:{t['surface']}; border-top:1px solid {t['border']}; }}
#tbGroup {{ background:transparent; border-right:1px solid {t['border']}; }}
#tbGroupTitle {{ color:{t['text_faint']}; font-size:10px; font-weight:600; letter-spacing:0.6px; }}
#status {{ background:{t['surface']}; color:{t['text_faint']}; font-size:12px; }}
#pagelbl {{ min-width:64px; qproperty-alignment:AlignCenter; color:{t['text']};
    font-weight:600; }}
#zoomlbl {{ color:{t['text_muted']}; min-width:44px; qproperty-alignment:AlignCenter; }}
QFrame#sep {{ background:{t['border']}; border:none; min-width:1px; max-width:1px; margin:6px 4px; }}

/* ---- araç rayı ------------------------------------------------------- */
#toolRail {{ background:{t['surface']}; border:1px solid {t['border']}; border-radius:14px; }}
QToolButton#toolbtn {{ background:transparent; border:none; border-radius:10px;
    padding:0; margin:0; }}
QToolButton#toolbtn:hover {{ background:{t['hover']}; }}
QToolButton#toolbtn:pressed {{ background:{t['pressed']}; }}
QToolButton#toolbtn:checked {{ background:{t['accent']}; }}
QToolButton#toolbtn:disabled {{ background:transparent; }}
#railSep {{ background:{t['border']}; min-height:1px; max-height:1px; margin:4px 8px; }}

/* ---- düğmeler -------------------------------------------------------- */
QPushButton, QToolButton {{ background:transparent; color:{t['text']};
    border:1px solid transparent; border-radius:8px; padding:6px 10px; }}
QPushButton:hover, QToolButton:hover {{ background:{t['hover']}; }}
QPushButton:pressed, QToolButton:pressed {{ background:{t['pressed']}; }}
QPushButton:disabled, QToolButton:disabled {{ color:{t['text_faint']}; }}
QPushButton:checked, QToolButton:checked {{ background:{t['accent_soft']}; color:{t['accent_text']}; }}
QToolButton::menu-indicator {{ image:none; width:0; }}
QPushButton#iconbtn, QToolButton#iconbtn {{ padding:6px; min-width:20px; }}
QPushButton#secondary {{ background:{t['surface2']}; border:1px solid {t['border_strong']}; }}
QPushButton#secondary:hover {{ background:{t['hover']}; }}
QPushButton#primary, QToolButton#primary {{ background:{t['accent']}; color:#ffffff;
    border:1px solid {t['accent']}; font-weight:600; }}
QPushButton#primary:hover, QToolButton#primary:hover {{ background:{t['accent_hover']};
    border-color:{t['accent_hover']}; }}
QPushButton#primary:pressed, QToolButton#primary:pressed {{ background:{t['accent_pressed']}; }}
QPushButton#primary:disabled, QToolButton#primary:disabled {{ background:{t['surface2']};
    border-color:{t['border']}; color:{t['text_faint']}; }}
QPushButton#danger {{ color:{t['danger']}; }}
QPushButton#colorbtn {{ border:1px solid {t['border_strong']}; border-radius:8px; padding:0; }}
QDialogButtonBox QPushButton {{ background:{t['surface2']}; border:1px solid {t['border_strong']};
    min-width:72px; }}
QDialogButtonBox QPushButton:default {{ background:{t['accent']}; border-color:{t['accent']};
    color:#ffffff; font-weight:600; }}

/* ---- giriş alanları -------------------------------------------------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background:{t['surface2']}; color:{t['text']}; border:1px solid {t['border']};
    border-radius:8px; padding:5px 8px;
    selection-background-color:{t['accent']}; selection-color:#ffffff; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color:{t['border_strong']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border-color:{t['accent']}; }}
QComboBox {{ padding-right:24px; }}
QComboBox::drop-down {{ border:none; width:22px; }}
QComboBox::down-arrow {{ image:url("{chevron}"); width:14px; height:14px; }}
QComboBox QAbstractItemView {{ background:{t['surface']}; color:{t['text']};
    border:1px solid {t['border_strong']}; border-radius:8px; padding:4px; outline:none;
    selection-background-color:{t['accent_soft']}; selection-color:{t['text']}; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ border:none; width:18px; background:transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image:url("{chevron_up}"); width:12px; height:12px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image:url("{chevron}"); width:12px; height:12px; }}

QCheckBox, QRadioButton {{ color:{t['text']}; spacing:8px; background:transparent; }}
QCheckBox::indicator {{ width:16px; height:16px; border-radius:5px;
    border:1px solid {t['border_strong']}; background:{t['surface2']}; }}
QCheckBox::indicator:hover {{ border-color:{t['accent']}; }}
QCheckBox::indicator:checked {{ background:{t['accent']}; border-color:{t['accent']};
    image:url("{check}"); }}
QRadioButton::indicator {{ width:16px; height:16px; border-radius:9px;
    border:1px solid {t['border_strong']}; background:{t['surface2']}; }}
QRadioButton::indicator:hover {{ border-color:{t['accent']}; }}
QRadioButton::indicator:checked {{ border-color:{t['accent']};
    background:qradialgradient(cx:.5, cy:.5, radius:.5, fx:.5, fy:.5, stop:0 {t['accent']}, stop:.42 {t['accent']},
    stop:.47 {t['surface2']}, stop:1 {t['surface2']}); }}

QSlider {{ background:transparent; }}
QSlider::groove:horizontal {{ height:4px; background:{t['border_strong']}; border-radius:2px; }}
QSlider::sub-page:horizontal {{ background:{t['accent']}; border-radius:2px; }}
QSlider::handle:horizontal {{ width:14px; height:14px; margin:-6px 0; border-radius:8px;
    background:#ffffff; border:2px solid {t['accent']}; }}
QSlider::handle:horizontal:hover {{ border-color:{t['accent_hover']}; }}

QProgressBar {{ background:{t['surface2']}; border:none; border-radius:4px; height:8px;
    text-align:center; color:{t['text_muted']}; }}
QProgressBar::chunk {{ background:{t['accent']}; border-radius:4px; }}

/* ---- listeler / ağaçlar ---------------------------------------------- */
QListWidget, QTreeWidget, QListView, QTreeView {{ background:{t['surface']}; color:{t['text']};
    border:none; outline:none; }}
QListWidget::item, QTreeWidget::item {{ border-radius:6px; padding:5px 6px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background:{t['hover']}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background:{t['accent_soft']}; color:{t['text']}; }}
QListWidget#thumbs {{ background:{t['surface']}; }}
QListWidget#thumbs::item {{ background:transparent; border:2px solid transparent;
    border-radius:8px; padding:6px; color:{t['text_muted']}; }}
QListWidget#thumbs::item:hover {{ background:{t['hover']}; }}
QListWidget#thumbs::item:selected {{ background:{t['accent_soft']}; border-color:{t['accent']};
    color:{t['accent_text']}; }}
QListWidget#layers::item {{ padding:0; }}

/* ---- sekmeler -------------------------------------------------------- */
QTabWidget::pane {{ border:none; background:{t['surface']}; top:-1px; }}
QTabWidget::tab-bar {{ left:8px; }}
QTabBar {{ background:transparent; }}
QTabBar::tab {{ background:transparent; color:{t['text_muted']}; padding:7px 12px;
    margin:6px 2px 6px 0; border-radius:8px; }}
QTabBar::tab:hover {{ background:{t['hover']}; color:{t['text']}; }}
QTabBar::tab:selected {{ background:{t['surface2']}; color:{t['text']}; font-weight:600; }}
QTabBar#doctabs {{ background:transparent; }}
QTabBar#doctabs::tab {{ background:transparent; color:{t['text_muted']}; padding:6px 8px 6px 12px;
    margin:0 2px; border:1px solid transparent; border-radius:8px; min-width:80px; max-width:220px; }}
QTabBar#doctabs::tab:hover {{ background:{t['hover']}; color:{t['text']}; }}
QTabBar#doctabs::tab:selected {{ background:{t['surface2']}; color:{t['text']}; border-color:{t['border']};
    font-weight:600; }}
QTabBar::close-button {{ image:url("{close}"); subcontrol-position:right; margin-left:6px;
    width:14px; height:14px; border-radius:4px; }}
QTabBar::close-button:hover {{ image:url("{close_hover}"); background:{t['hover']}; }}

/* ---- kenar panelleri ------------------------------------------------- */
QDockWidget {{ color:{t['text_muted']}; font-size:11px; font-weight:600; }}
QDockWidget::title {{ background:{t['surface']}; padding:8px 12px 4px 12px; text-align:left; }}
QDockWidget > QWidget {{ background:{t['surface']}; }}
QMainWindow::separator {{ background:{t['border']}; width:1px; height:1px; }}
QMainWindow::separator:hover {{ background:{t['accent']}; }}
QSplitter::handle {{ background:{t['border']}; }}

#sectionFrame {{ background:{t['surface']}; border:1px solid {t['border']}; border-radius:12px; }}
#sectionTitle {{ color:{t['text_faint']}; font-size:10px; font-weight:600; letter-spacing:0.6px;
    padding:2px 2px 4px 2px; }}
#propPage {{ background:{t['surface']}; }}
#propTitle {{ color:{t['text']}; font-size:14px; font-weight:600; }}
#hint {{ color:{t['text_faint']}; font-size:12px; }}
#hintWarn {{ color:{t['text_muted']}; font-size:12px; background:{t['warning_soft']};
    border-left:3px solid {t['warning']}; border-radius:6px; padding:8px 10px; }}
#nextNumber {{ font-weight:700; color:{t['accent_text']}; }}
#layerRow {{ background:transparent; }}
#layerLabel {{ color:{t['text']}; }}

/* ---- menüler ---------------------------------------------------------- */
QMenu {{ background:{t['surface']}; color:{t['text']}; border:1px solid {t['border_strong']};
    border-radius:10px; padding:6px; }}
QMenu::item {{ padding:7px 22px 7px 10px; border-radius:6px; background:transparent; }}
QMenu::item:selected {{ background:{t['accent_soft']}; color:{t['text']}; }}
QMenu::item:disabled {{ color:{t['text_faint']}; }}
QMenu::icon {{ padding-left:8px; }}
QMenu::separator {{ height:1px; background:{t['border']}; margin:5px 6px; }}

/* ---- yeni yerleşim ------------------------------------------------------ */
#topbar {{ background:{t['surface']}; border-bottom:1px solid {t['border']}; }}
QToolButton#menuBtn {{ color:{t['text_muted']}; padding:6px 9px; border-radius:7px; }}
QToolButton#menuBtn:hover, QToolButton#menuBtn:pressed {{ color:{t['text']}; background:{t['hover']}; }}
QToolButton#secondaryTb {{ background:{t['surface2']}; border:1px solid {t['border_strong']};
    padding:6px 12px; }}
QToolButton#secondaryTb:hover {{ background:{t['hover']}; }}
QToolButton#secondaryTb:disabled {{ border-color:{t['border']}; }}
#statusbar {{ background:{t['surface']}; border-top:1px solid {t['border']}; }}
#status {{ background:transparent; }}
QLineEdit#pageEdit {{ padding:3px 4px; border-radius:6px; }}
#pageTotal {{ color:{t['text_muted']}; padding:0 6px 0 6px; }}
QToolButton#zoomBtn {{ color:{t['text_muted']}; min-width:46px; padding:5px 6px; }}
QToolButton#iconbtn {{ padding:6px; }}
QToolButton#iconbtn:checked {{ background:{t['accent_soft']}; }}

#sideRail {{ background:{t['surface']}; border-right:1px solid {t['border']}; }}
QToolButton#railBtn {{ background:transparent; border:none; border-radius:10px; padding:0; }}
QToolButton#railBtn:hover {{ background:{t['hover']}; }}
QToolButton#railBtn:checked {{ background:{t['accent_soft']}; }}
#sidePanel {{ background:{t['surface']}; border-right:1px solid {t['border']}; }}
#panelTitle {{ color:{t['text']}; font-size:13px; font-weight:600; padding:14px 14px 8px 14px; }}
#panelBody {{ background:{t['surface']}; }}
#workspace, #compareWrap {{ background:{t['canvas']}; }}

#capsule {{ background:{t['surface']}; border:1px solid {t['border']}; border-radius:14px; }}
#propBar {{ background:{t['surface']}; border:1px solid {t['border']}; border-radius:12px; }}
#miniBar {{ background:{t['surface']}; border:1px solid {t['border']}; border-radius:10px; }}
#barSep {{ background:{t['border_strong']}; }}
QToolButton#barBtn {{ background:transparent; border:none; border-radius:8px; padding:0; }}
QToolButton#barBtn:hover {{ background:{t['hover']}; }}
QToolButton#barBtn:pressed {{ background:{t['pressed']}; }}
QPushButton#segBtn {{ background:{t['surface2']}; border:1px solid {t['border']}; border-radius:7px;
    padding:4px 10px; }}
QPushButton#segBtn:checked {{ background:{t['accent_soft']}; border-color:{t['accent']}; color:{t['accent_text']}; }}
#valueLbl {{ color:{t['text_muted']}; }}
#propPage QLabel {{ color:{t['text_muted']}; }}
#propPage QLabel#propTitle {{ color:{t['text']}; font-size:13px; font-weight:600; }}

#welcome {{ background:{t['bg']}; }}
#welcomeTitle {{ color:{t['text']}; font-size:24px; font-weight:600; }}
#welcomeSub {{ color:{t['text_muted']}; font-size:14px; }}
#dropZone {{ background:{t['surface']}; border:2px dashed {t['border_strong']}; border-radius:16px; }}
#dropHint {{ color:{t['text']}; font-size:15px; font-weight:600; }}
#dropFormats {{ color:{t['text_faint']}; font-size:12px; }}
QPushButton#recentItem {{ background:{t['surface']}; border:1px solid {t['border']}; border-radius:10px;
    padding:0; text-align:left; }}
QPushButton#recentItem:hover {{ background:{t['hover']}; border-color:{t['accent']}; }}
#recentName {{ color:{t['text']}; font-weight:600; }}
#recentFolder {{ color:{t['text_faint']}; font-size:11px; }}
#dropOverlay {{ background:{t['accent_soft']}; border:3px dashed {t['accent']}; border-radius:18px;
    color:{t['accent_text']}; font-size:22px; font-weight:600; }}

/* ---- bildirimler, komut paleti -------------------------------------------- */
#toast {{ background:{t['surface']}; border:1px solid {t['border_strong']}; border-radius:12px; }}
#toast[kind="success"] {{ border-left:3px solid {t['accent']}; }}
#toast[kind="warning"] {{ border-left:3px solid {t['warning']}; }}
#toast[kind="error"] {{ border-left:3px solid {t['danger']}; }}
#toastText {{ color:{t['text']}; }}
QPushButton#toastAction {{ color:{t['accent_text']}; font-weight:600; padding:4px 8px; }}
#palette {{ background:{t['surface']}; border:1px solid {t['border_strong']}; border-radius:14px; }}
QLineEdit#paletteEdit {{ font-size:15px; padding:9px 10px; border-radius:10px; }}
QListWidget#paletteList {{ background:transparent; }}
QListWidget#paletteList::item {{ padding:0; border-radius:8px; }}
QListWidget#paletteList::item:selected {{ background:{t['accent_soft']}; }}
#paletteTitle {{ color:{t['text']}; }}
#paletteCat {{ color:{t['text_faint']}; font-size:12px; }}
#kbd {{ color:{t['text_muted']}; background:{t['surface2']}; border:1px solid {t['border']};
    border-radius:5px; padding:1px 6px; font-size:11px; }}

/* ---- kaydırma çubukları (ince, modern) -------------------------------- */
QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
QScrollBar:horizontal {{ background:transparent; height:10px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{t['scroll']}; border-radius:3px; min-height:32px; margin:0 1px; }}
QScrollBar::handle:horizontal {{ background:{t['scroll']}; border-radius:3px; min-width:32px; margin:1px 0; }}
QScrollBar::handle:hover {{ background:{t['scroll_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; border:none; background:none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background:none; }}
QAbstractScrollArea::corner {{ background:transparent; }}
QScrollArea {{ background:transparent; border:none; }}
"""


class _MenuPolisher(QObject):
    """Menüleri yuvarlak köşeli gösterebilmek için çerçevesiz ve saydam
    zeminli yapar (aksi halde köşelerde kare arka plan görünür)."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Polish and isinstance(obj, QMenu):
            obj.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            obj.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
            obj.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        return False


_polisher = None


def apply(app: QApplication, theme_name: str) -> str:
    """Temayı uygular ve ana pencereye verilecek stil dosyasını döner."""
    global _current, _polisher
    _current = theme_name if theme_name in TOKENS else "dark"
    t = current()
    pal = QPalette()
    for role, key in (
        (QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Base, "surface2"), (QPalette.ColorRole.AlternateBase, "surface"),
        (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "surface2"),
        (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.ToolTipBase, "tooltip_bg"),
        (QPalette.ColorRole.ToolTipText, "tooltip_fg"), (QPalette.ColorRole.Highlight, "accent"),
        (QPalette.ColorRole.PlaceholderText, "text_faint"), (QPalette.ColorRole.Mid, "border_strong"),
        (QPalette.ColorRole.Light, "hover"), (QPalette.ColorRole.Dark, "border"),
    ):
        pal.setColor(role, QColor(t[key]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    for role, key in ((QPalette.ColorRole.Text, "text_faint"), (QPalette.ColorRole.WindowText, "text_faint"),
                      (QPalette.ColorRole.ButtonText, "text_faint")):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(t[key]))
    app.setPalette(pal)
    font = QFont("Segoe UI")
    font.setPixelSize(13)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    if _polisher is None:
        _polisher = _MenuPolisher(app)
        app.installEventFilter(_polisher)
    return stylesheet(t)
