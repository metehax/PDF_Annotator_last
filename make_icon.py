"""app.ico üretir: ui/icons.py içindeki "app" SVG simgesini vurgu renkli yuvarlak kare üstüne çizer."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from ui import icons


def render(size):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#2f6fed")))
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    r = QSvgRenderer(icons.svg_bytes("app", "#ffffff", 1.75))
    m = size * 0.2
    r.render(p, QRectF(m, m, size - 2 * m, size - 2 * m))
    p.end()
    return img


def main():
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    from PIL import Image
    import io
    ims = []
    for s in sizes:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        render(s).save(buf, "PNG")
        ims.append(Image.open(io.BytesIO(bytes(ba))).convert("RGBA"))
    ims[-1].save(os.path.join(ROOT, "app.ico"), format="ICO", sizes=[(s, s) for s in sizes], append_images=ims[:-1])
    print("app.ico yazildi")


if __name__ == "__main__":
    main()
