"""
ui/toolhelp.py
==============
Özellik çubuğundaki (i) düğmesi: üzerine gelince/tıklayınca aracın nasıl kullanıldığını gösteren küçük,
kendini tekrarlayan animasyon + kısa açıklama. Animasyonlar dosya içermez, QPainter ile çizilir; yalnızca
açıkken zamanlayıcı çalışır (düşük maliyet). "Animasyonları azalt" açıksa son kare durağan gösterilir.
"""

from __future__ import annotations

import math
from typing import Callable, Dict

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QToolButton, QVBoxLayout, QWidget

import workspace

W, H = 240, 140           # animasyon tuvali
LOOP = 4.0                # saniye
ACCENT = QColor("#3a86ff")
INK = QColor("#e63946")


def _p(t: float, a: float, b: float) -> float:
    """t'nin [a, b] aralığındaki ilerlemesi (0..1, yumuşatılmış)."""
    if b <= a:
        return 1.0 if t >= b else 0.0
    x = max(0.0, min(1.0, (t - a) / (b - a)))
    return x * x * (3 - 2 * x)


def _lerp(a: QPointF, b: QPointF, k: float) -> QPointF:
    return QPointF(a.x() + (b.x() - a.x()) * k, a.y() + (b.y() - a.y()) * k)


def _page(p: QPainter, lines: bool = True) -> None:
    p.setPen(QPen(QColor("#d5d8de"), 1))
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(14, 10, W - 28, H - 20), 6, 6)
    if lines:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e3e6ec"))
        for i, w in enumerate((150, 170, 120, 160, 90)):
            p.drawRoundedRect(QRectF(30, 26 + i * 18, w, 6), 3, 3)


def _cursor(p: QPainter, pos: QPointF, press: float = 0.0) -> None:
    if press > 0.01:                                     # tıklama dalgası
        c = QColor(ACCENT); c.setAlphaF(0.35 * (1 - press))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(c)
        p.drawEllipse(pos, 4 + 12 * press, 4 + 12 * press)
    poly = QPolygonF([QPointF(0, 0), QPointF(0, 15), QPointF(4, 11), QPointF(7, 17), QPointF(10, 15),
                      QPointF(7, 10), QPointF(12, 10)])
    p.save()
    p.translate(pos)
    p.setPen(QPen(QColor("#ffffff"), 1.2))
    p.setBrush(QColor("#1b1f27"))
    p.drawPolygon(poly)
    p.restore()


def _drag(t: float, a: QPointF, b: QPointF, t0=0.5, t1=2.0, rel=3.2):
    """Sürükleme: (imleç konumu, ilerleme, bırakma dalgası)."""
    k = _p(t, t0, t1)
    pos = _lerp(a, b, k) if t < rel else b
    return pos, k, _p(t, rel, rel + 0.5)


def _label(p: QPainter, text: str, x: float, y: float, size: int = 8, color=QColor("#334")) -> None:
    f = QFont(); f.setPixelSize(size); p.setFont(f); p.setPen(color)
    p.drawText(QPointF(x, y), text)


# --- sahneler: her biri (painter, t) -------------------------------------------------------------------
def s_select(p, t):
    _page(p)
    k = _p(t, 0.6, 2.0)
    r = QRectF(40 + 90 * k, 70, 60, 30)
    p.setPen(QPen(ACCENT, 1.5)); p.setBrush(QColor(58, 134, 255, 40)); p.drawRect(r)
    p.setBrush(QColor("#fff"))
    for c in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
        p.drawRect(QRectF(c.x() - 3, c.y() - 3, 6, 6))
    _cursor(p, QPointF(r.center().x(), r.center().y() + 4), _p(t, 3.0, 3.5) if t > 3 else 0)


def s_text(p, t):
    _page(p, False)
    pos = QPointF(60, 60)
    _cursor(p, pos + QPointF(0, 4), _p(t, 0.3, 0.8))
    n = int(_p(t, 1.0, 2.4) * 9)
    if t > 0.9:
        p.setPen(QPen(ACCENT, 1, Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(56, 44, 120, 28))
        _label(p, "Merhaba!!"[:n], 62, 63, 15, QColor("#1d3557"))


def s_edit(p, t):
    _page(p)
    p.setPen(QPen(ACCENT, 1.2)); p.setBrush(QColor(58, 134, 255, 35)); p.drawRect(QRectF(26, 61, 120, 12))
    _label(p, "Eski metin" if t < 1.6 else "Yeni metin", 30, 71, 10, QColor("#1d3557"))
    _cursor(p, QPointF(120, 76), _p(t, 0.5, 1.0) if t < 1.2 else 0)


def s_ink(p, t):
    _page(p, False)
    k = _p(t, 0.5, 3.0)
    path = QPainterPath(QPointF(40, 90))
    n = max(2, int(60 * k))
    for i in range(1, n):
        x = 40 + 160 * i / 60
        path.lineTo(x, 85 - 22 * math.sin(i / 60 * 3 * math.pi) * (1 - i / 90))
    p.setPen(QPen(INK, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
    _cursor(p, path.currentPosition(), 0)


def s_highlight(p, t):
    _page(p)
    k = _p(t, 0.7, 2.2)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255, 235, 59, 150))
    p.drawRect(QRectF(28, 44, 150 * k, 14))
    _cursor(p, QPointF(28 + 150 * k, 56), _p(t, 2.4, 2.9) if t > 2.2 else 0)


def s_line(p, t):
    _page(p, False)
    a, b = QPointF(45, 100), QPointF(195, 45)
    k = _p(t, 0.6, 2.0)
    e = _lerp(a, b, k)
    p.setPen(QPen(INK, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)); p.drawLine(a, e)
    if k > 0.99:
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        for d in (2.6, -2.6):
            p.drawLine(b, b - QPointF(math.cos(ang + d * 0.1 + (0.5 if d > 0 else -0.5)) * 14,
                                      math.sin(ang + d * 0.1 + (0.5 if d > 0 else -0.5)) * 14))
    _cursor(p, e, 0)


def _shape(p, t, oval: bool):
    _page(p, False)
    pos, k, rel = _drag(t, QPointF(55, 40), QPointF(185, 105), 0.6, 2.0, 2.4)
    r = QRectF(QPointF(55, 40), pos).normalized()
    p.setPen(QPen(INK, 2.4)); p.setBrush(QColor(255, 209, 102, 100))
    (p.drawEllipse if oval else p.drawRect)(r)
    _cursor(p, pos, rel)


def s_rect(p, t): _shape(p, t, False)
def s_oval(p, t): _shape(p, t, True)


def s_redact(p, t):
    _page(p)
    _label(p, "TC: 123 456 789 01", 32, 55, 11, QColor("#222"))
    pos, k, rel = _drag(t, QPointF(28, 42), QPointF(160, 62), 0.6, 1.8, 2.2)
    r = QRectF(QPointF(28, 42), pos).normalized()
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(0, 0, 0, 255 if t > 2.2 else 120)); p.drawRect(r)
    _cursor(p, pos, rel)
    if t > 2.4:
        _label(p, "kalıcı silindi", 34, 110, 9, QColor("#c62828"))


def s_blur(p, t):
    _page(p)
    _label(p, "Gizli bilgi 12345", 32, 55, 11, QColor("#222"))
    pos, k, rel = _drag(t, QPointF(28, 42), QPointF(160, 62), 0.6, 1.8, 2.2)
    r = QRectF(QPointF(28, 42), pos).normalized()
    if t > 2.2:                                           # mozaik
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(int(r.width() // 7) + 1):
            for j in range(int(r.height() // 7) + 1):
                g = 140 + ((i * 7 + j * 13) % 5) * 22
                p.setBrush(QColor(g, g, g)); p.drawRect(QRectF(r.x() + i * 7, r.y() + j * 7, 7, 7).intersected(r))
    else:
        p.setPen(QPen(ACCENT, 1.4, Qt.PenStyle.DashLine)); p.setBrush(QColor(58, 134, 255, 40)); p.drawRect(r)
    _cursor(p, pos, rel)


def s_image(p, t):
    _page(p, False)
    k = _p(t, 0.8, 1.6)
    r = QRectF(70, 35, 100 * k, 70 * k)
    r.moveCenter(QPointF(120, 70))
    p.setPen(QPen(QColor("#6c757d"), 1.5)); p.setBrush(QColor("#cfe8ff")); p.drawRect(r)
    if k > 0.9:
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#4caf50"))
        p.drawPolygon(QPolygonF([QPointF(80, 100), QPointF(110, 62), QPointF(135, 92), QPointF(150, 78), QPointF(165, 100)]))
        p.setBrush(QColor("#ffeb3b")); p.drawEllipse(QPointF(145, 52), 7, 7)
    _cursor(p, QPointF(120, 70), _p(t, 0.3, 0.8) if t < 1 else 0)


def s_number(p, t):
    _page(p, False)
    for i, (x, y) in enumerate(((60, 50), (130, 80), (190, 50))):
        k = _p(t, 0.5 + i * 1.0, 0.9 + i * 1.0)
        if k <= 0:
            continue
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(INK); p.drawEllipse(QPointF(x, y), 11 * k, 11 * k)
        if k > 0.8:
            _label(p, str(i + 1), x - 3, y + 4, 11, QColor("#fff"))
    _cursor(p, QPointF(60 + 70 * min(2, int(t)), 60 + 15 * (int(t) % 2)), 0)


def s_stamp(p, t):
    _page(p)
    k = _p(t, 0.7, 1.4)
    s = 1.6 - 0.6 * k
    p.save(); p.translate(120, 75); p.rotate(-8); p.scale(s, s)
    c = QColor("#2e7d32"); c.setAlphaF(min(1.0, k + 0.1))
    p.setPen(QPen(c, 2.4)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRoundedRect(QRectF(-45, -14, 90, 28), 4, 4)
    _label(p, "ONAYLANDI", -34, 5, 12, c)
    p.restore()


def s_sign(p, t):
    _page(p, False)
    k = _p(t, 0.6, 2.8)
    path = QPainterPath(QPointF(50, 95))
    pts = [(62, 55), (74, 100), (86, 60), (98, 98), (118, 70), (134, 95), (150, 78), (172, 90)]
    n = k * (len(pts) - 1)
    for i, (x, y) in enumerate(pts):
        if i <= n:
            path.lineTo(x, y)
        elif i - 1 < n:
            a, b = pts[i - 1], (x, y); f = n - (i - 1)
            path.lineTo(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
    p.setPen(QPen(QColor("#14288a"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
    p.setPen(QPen(QColor("#9aa"), 1)); p.drawLine(40, 108, 200, 108)
    _cursor(p, path.currentPosition(), 0)


def s_note(p, t):
    _page(p)
    k = _p(t, 0.8, 1.4)
    p.save(); p.translate(150, 60 - 10 * (1 - k)); p.scale(k, k)
    p.setPen(QPen(QColor("#d4a017"), 1)); p.setBrush(QColor("#ffd23f")); p.drawRect(QRectF(-24, -22, 48, 44))
    p.setPen(QPen(QColor("#7a5c00"), 1.2))
    for i in range(3):
        p.drawLine(QPointF(-17, -10 + i * 10), QPointF(17 - i * 6, -10 + i * 10))
    p.restore()
    _cursor(p, QPointF(150, 65), _p(t, 0.4, 0.9) if t < 1.2 else 0)


def s_copytext(p, t):
    _page(p)
    words = ((32, 40, 40), (76, 40, 34), (114, 40, 46), (32, 58, 52), (88, 58, 40), (132, 58, 30))
    pos, k, rel = _drag(t, QPointF(26, 34), QPointF(170, 66), 0.6, 2.0, 2.4)
    r = QRectF(QPointF(26, 34), pos).normalized()
    p.setPen(QPen(ACCENT, 1.2, Qt.PenStyle.DashLine)); p.setBrush(QColor(58, 134, 255, 30)); p.drawRect(r)
    p.setPen(Qt.PenStyle.NoPen)
    for x, y, w in words:
        sel = r.contains(QPointF(x + w / 2, y + 3))
        p.setBrush(QColor(58, 134, 255, 140) if sel else QColor("#c4c9d2"))
        p.drawRoundedRect(QRectF(x, y, w, 8), 3, 3)
    _cursor(p, pos, rel)
    if t > 2.5:
        p.setBrush(QColor("#1b1f27")); p.drawRoundedRect(QRectF(60, 106, 120, 20), 8, 8)
        _label(p, "Metin kopyalandı ✓", 72, 120, 10, QColor("#fff"))


def s_crop(p, t):
    _page(p)
    pos, k, rel = _drag(t, QPointF(45, 38), QPointF(170, 98), 0.6, 1.8, 2.2)
    r = QRectF(QPointF(45, 38), pos).normalized()
    p.setPen(QPen(ACCENT, 1.5, Qt.PenStyle.DashLine)); p.setBrush(QColor(58, 134, 255, 30)); p.drawRect(r)
    if 2.3 < t < 2.7:
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255, 255, 255, int(200 * (1 - (t - 2.3) / 0.4)))); p.drawRect(r)
    _cursor(p, pos, rel)


def s_form(p, t):
    _page(p, False)
    pos, k, rel = _drag(t, QPointF(55, 55), QPointF(185, 80), 0.6, 1.8, 2.2)
    r = QRectF(QPointF(55, 55), pos).normalized()
    p.setPen(QPen(QColor("#8c96ad"), 1.2)); p.setBrush(QColor("#f0f4ff")); p.drawRect(r)
    if t > 2.4 and int(t * 3) % 2 == 0:
        p.setPen(QPen(QColor("#222"), 1.2)); p.drawLine(QPointF(60, 61), QPointF(60, 74))
    _cursor(p, pos, rel)


SCENES: Dict[str, Callable] = {
    "select": s_select, "text": s_text, "edit": s_edit, "ink": s_ink, "highlight": s_highlight, "line": s_line,
    "rect": s_rect, "oval": s_oval, "redact": s_redact, "blur": s_blur, "image": s_image, "number": s_number,
    "stamp": s_stamp, "sign": s_sign, "note": s_note, "copytext": s_copytext, "crop": s_crop, "form": s_form,
}


class _Canvas(QWidget):
    def __init__(self, tool: str):
        super().__init__()
        self.tool = tool
        self.setFixedSize(W, H)
        self.t = LOOP * 0.92                              # durağan (animasyonlar azaltılmışsa) kare
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(40)                       # ~25 kare/sn
        self._timer.timeout.connect(self._tick)

    def start(self, animate: bool) -> None:
        if animate:
            self._clock.start()
            self._timer.start()
        else:
            self.update()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self.t = (self._clock.elapsed() / 1000.0) % LOOP
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#eef1f6"))
        scene = SCENES.get(self.tool)
        try:
            if scene:
                scene(p, self.t)
        except Exception:                                  # çizim hatası arayüzü bozmasın
            pass
        p.end()


class ToolHelpPopup(QFrame):
    """Animasyon + açıklama; dışarı tıklayınca/Esc ile kapanır, kapanınca zamanlayıcı durur."""

    def __init__(self, tool: str, title: str, text: str, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("toolHelp")
        self.setStyleSheet("QFrame#toolHelp{background:palette(window);border:1px solid palette(mid);"
                           "border-radius:10px;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)
        t = QLabel(f"<b>{title}</b>")
        v.addWidget(t)
        self.canvas = _Canvas(tool)
        v.addWidget(self.canvas, 0, Qt.AlignmentFlag.AlignHCenter)
        self.body = QLabel(text.replace("\n", "<br>"))
        self.body.setWordWrap(True)
        self.body.setFixedWidth(W)
        v.addWidget(self.body)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.canvas.start(not workspace.reduce_motion())

    def hideEvent(self, e) -> None:
        self.canvas.stop()
        super().hideEvent(e)


class InfoButton(QToolButton):
    """(i) düğmesi: tıklayınca ya da bir an üzerinde durunca animasyonlu yardımı açar."""

    def __init__(self, text: str):
        super().__init__()
        self.tool = ""
        self.title = ""
        self.help_text = text
        self.popup: ToolHelpPopup | None = None
        self.setMouseTracking(True)
        self._hover = QTimer(self)
        self._hover.setSingleShot(True)
        self._hover.setInterval(350)
        self._hover.timeout.connect(self.show_help)
        self.clicked.connect(self.show_help)

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.ToolTip:                # yazı ipucu yerine animasyonlu yardım açılır
            return True
        return super().event(e)

    def enterEvent(self, e) -> None:
        self._hover.start()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover.stop()
        super().leaveEvent(e)

    def show_help(self) -> None:
        if self.popup is not None and self.popup.isVisible():
            return
        self.popup = ToolHelpPopup(self.tool, self.title or "Nasıl kullanılır?", self.help_text, self)
        self.popup.adjustSize()
        g = self.mapToGlobal(self.rect().bottomRight())
        scr = QApplication.screenAt(g) or QApplication.primaryScreen()
        x = max(scr.availableGeometry().left(), g.x() - self.popup.width() + 6)
        self.popup.move(x, g.y() + 4)
        self.popup.show()
