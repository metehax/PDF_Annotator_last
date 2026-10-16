"""
ui/icons.py
===========
Uygulamanın kendi ikon seti: 24x24 görünüm kutusunda, ince çizgili
(stroke) SVG'ler. Renk SVG'ye gömülmez; çizim anında aktif temadan
(ui.theme) ve düğmenin durumundan (normal / üzerinde / devre dışı /
seçili) seçilir. Böylece tema değişince ikonlar da kendiliğinden uyar.

Kullanım:
    from ui.icons import icon
    btn.setIcon(icon("open"))
    btn.setIcon(icon("trash", role="danger"))
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import QByteArray, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ui import theme

# Her değer, <svg> içine konacak öğelerdir. "currentColor" çizim anında
# gerçek renkle değiştirilir (dolgu gereken yerlerde fill="currentColor").
_PATHS: Dict[str, str] = {
    # -- dosya -------------------------------------------------------------
    "open": '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.3l2 2.5h8.7A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    "file_plus": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M12 11.5v6M9 14.5h6"/>',
    "file_copy": '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h2"/>',
    "merge": '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/><path d="M15 3h4a2 2 0 0 1 2 2v4"/><path d="M9 21H5a2 2 0 0 1-2-2v-4"/>',
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9"/><path d="M14.5 14.5 20 20"/><path d="M8.1 8.1 12 12"/>',
    "download": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
    "save": '<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v5h8V3"/><rect x="7" y="13" width="10" height="8" rx="1"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>',
    "images": '<rect x="7" y="7" width="14" height="14" rx="2"/><circle cx="12" cy="12" r="1.5"/><path d="m21 17-3.5-3.5L11 20"/><path d="M17 3H5a2 2 0 0 0-2 2v12"/>',
    "folder": '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.3l2 2.5h8.7A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"/>',
    "project": '<path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5a2 2 0 0 0 2 2h1"/><path d="M16 21h1a2 2 0 0 0 2-2v-5a2 2 0 0 1 2-2 2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1"/>',
    "watermark": '<path d="M12 3s-6 6.6-6 11a6 6 0 0 0 12 0c0-4.4-6-11-6-11z"/><path d="M9.5 14.5a2.5 2.5 0 0 0 2.5 2.5"/>',
    "ocr": '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7.5 8h9M7.5 12h9M7.5 16h5.5"/>',
    # -- düzen ---------------------------------------------------------------
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "trash": '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M9 7V4h6v3"/>',
    "copy": '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>',
    "clipboard": '<rect x="8" y="2.5" width="8" height="4" rx="1"/><path d="M16 4.5h2a2 2 0 0 1 2 2V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6.5a2 2 0 0 1 2-2h2"/>',
    "rename": '<path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17z"/><path d="M13.5 6.5l3 3"/>',
    "close": '<path d="M18 6 6 18M6 6l12 12"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "reset": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    "bring_front": '<path d="M5 3h14"/><path d="m18 13-6-6-6 6"/><path d="M12 7v14"/>',
    "send_back": '<path d="M5 21h14"/><path d="m6 11 6 6 6-6"/><path d="M12 17V3"/>',
    "arrow_up": '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
    "arrow_down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    # -- görünüm --------------------------------------------------------------
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>',
    "moon": '<path d="M20.5 14.5A8.5 8.5 0 1 1 9.5 3.5a7 7 0 0 0 11 11z"/>',
    "contrast": '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/>',
    "compare": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>',
    "chevron_left": '<path d="m15 18-6-6 6-6"/>',
    "chevron_right": '<path d="m9 18 6-6-6-6"/>',
    "chevron_up": '<path d="m18 15-6-6-6 6"/>',
    "chevron_down": '<path d="m6 9 6 6 6-6"/>',
    "rotate_ccw": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    "rotate_cw": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    "fit_width": '<path d="M3 5v14M21 5v14"/><path d="M7 12h10"/><path d="m10 9-3 3 3 3M14 9l3 3-3 3"/>',
    "fit_page": '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    "zoom_in": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/><path d="M11 8v6M8 11h6"/>',
    "zoom_out": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/><path d="M8 11h6"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "sliders": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    # -- araçlar ---------------------------------------------------------------
    "select": '<path d="M5 3.5 11 20l2.3-6.7L20 11z"/><path d="m13.5 13.5 5 5"/>',
    "text": '<path d="M5 7V4.5h14V7"/><path d="M12 4.5v15"/><path d="M9 19.5h6"/>',
    "edit_text": '<path d="M4 7V5h11v2"/><path d="M9.5 5v12"/><path d="M7.5 17h4"/><path d="M14 21l.6-3L19.4 13.2a1.6 1.6 0 0 1 2.3 2.3L17 20.4z"/>',
    "ink": '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z"/><path d="M14.5 5.5l3 3"/>',
    "line": '<path d="M5 19 19 5"/><path d="M10 5h9v9"/>',
    "rect": '<rect x="4" y="5" width="16" height="14" rx="2"/>',
    "oval": '<ellipse cx="12" cy="12" rx="9" ry="7"/>',
    "highlight": '<path d="m14 4 6 6-8.5 8.5H8.5v-3z"/><path d="M8.5 18.5 6 21H3"/><path d="m11 7 6 6"/>',
    "redact": '<rect x="3" y="5" width="18" height="14" rx="2"/><rect x="6.5" y="9.5" width="11" height="5" rx="1" fill="currentColor"/>',
    "number": '<circle cx="12" cy="12" r="9"/><path d="M10.5 9 12.5 7.5v9"/>',
    "stamp": '<path d="M5 21h14"/><path d="M4 17.5v-2A2.5 2.5 0 0 1 6.5 13h11a2.5 2.5 0 0 1 2.5 2.5v2a.5.5 0 0 1-.5.5h-15a.5.5 0 0 1-.5-.5z"/><path d="M14 13V9.5c0-1.5 1.5-2 1.5-4a3.5 3.5 0 0 0-7 0c0 2 1.5 2.5 1.5 4V13"/>',
    "privacy": '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6z"/><path d="M9.5 11.5h5v4h-5z"/><path d="M10.5 11.5V10a1.5 1.5 0 0 1 3 0v1.5"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "shield": '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6z"/><path d="m9 12 2 2 4-4"/>',
    "compress": '<path d="M4 14h6v6"/><path d="M20 10h-6V4"/><path d="m14 10 7-7"/><path d="m3 21 7-7"/>',
    "blur": '<circle cx="12" cy="12" r="2.5"/><circle cx="12" cy="12" r="6.5" stroke-dasharray="2.2 2.6"/><circle cx="12" cy="12" r="10" stroke-dasharray="1.2 3.4"/>',
    "note": '<path d="M5 4h14v11l-5 5H5z"/><path d="M14 20v-5h5"/><path d="M8 9h8M8 12.5h5"/>',
    "comment": '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12h5"/>',
    "headfoot": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M5 7.5h14M5 16.5h14"/><path d="M9 19h6"/>',
    "crop": '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
    # -- bilgi ---------------------------------------------------------------
    "warning": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 16v-5M12 8h.01"/>',
    "app": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 15.5l2-2 4 4"/><path d="M9 12h3"/>',
}


def names():
    return sorted(_PATHS)


def svg_bytes(name: str, color: str, stroke: float = 1.75) -> bytes:
    body = _PATHS[name].replace("currentColor", color)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    ).encode("utf-8")


# Aynı (ad, renk) için QSvgRenderer'ı tekrar kurmamak adına küçük önbellek
_renderers: Dict[tuple, QSvgRenderer] = {}


def _renderer(name: str, color: str) -> QSvgRenderer:
    key = (name, color)
    r = _renderers.get(key)
    if r is None:
        r = QSvgRenderer(QByteArray(svg_bytes(name, color)))
        _renderers[key] = r
    return r


class _SvgIconEngine(QIconEngine):
    """Rengini çizim anında temadan ve duruma göre seçen ikon motoru."""

    def __init__(self, name: str, role: str = "default"):
        super().__init__()
        self._name = name
        self._role = role

    def _color(self, mode: QIcon.Mode, state: QIcon.State) -> str:
        t = theme.current()
        if mode == QIcon.Mode.Disabled:
            return t["icon_disabled"]
        if self._role == "accent":
            return t["accent"]
        if self._role == "danger":
            return t["danger"]
        if self._role == "on_accent":
            return "#ffffff"
        if self._role == "toggle" and state == QIcon.State.On:
            return t["accent_text"]
        if state == QIcon.State.On:
            return t["icon_on"]
        if mode in (QIcon.Mode.Active, QIcon.Mode.Selected):
            return t["icon_hover"]
        return t["icon"]

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State):
        _renderer(self._name, self._color(mode, state)).render(painter, QRectF(rect))

    def _render(self, size: QSize, mode, state, scale: float) -> QPixmap:
        w = max(1, int(round(size.width() * scale)))
        h = max(1, int(round(size.height() * scale)))
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint(p, QRect(QPoint(0, 0), QSize(w, h)), mode, state)
        p.end()
        pm.setDevicePixelRatio(scale)
        return pm

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return self._render(size, mode, state, 1.0)

    def scaledPixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float) -> QPixmap:
        return self._render(size, mode, state, max(1.0, scale))

    def clone(self) -> QIconEngine:
        return _SvgIconEngine(self._name, self._role)

    def key(self) -> str:
        return "pdfannotator-svg"


def icon(name: str, role: str = "default") -> QIcon:
    """role: default | accent | danger | on_accent | toggle (seçiliyken vurgu rengi)"""
    if name not in _PATHS:
        raise KeyError(f"Bilinmeyen ikon: {name}")
    return QIcon(_SvgIconEngine(name, role))


def pixmap(name: str, size: int, color: Optional[str] = None, scale: float = 1.0) -> QPixmap:
    """Etiket vb. için düz renkli ikon görüntüsü."""
    color = color or theme.current()["icon"]
    w = max(1, int(round(size * scale)))
    pm = QPixmap(w, w)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _renderer(name, color).render(p, QRectF(0, 0, w, w))
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm
