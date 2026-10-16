"""Elektronik imza: çizerek, el yazısı yazı tipiyle yazarak ya da görselden
oluşturma; kayıtlı imza kütüphanesi (QSettings, PNG base64)."""
import base64
import json
import uuid
from typing import List, Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRect, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPainterPath,
                           QPen, QPixmap)
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider,
                               QTabWidget, QVBoxLayout, QWidget)

# Windows'ta yaygın el yazısı yazı tipleri (yalnızca kurulu olanlar listelenir)
HAND_FONTS = ["Segoe Script", "Lucida Handwriting", "Ink Free", "Brush Script MT", "Freestyle Script",
              "Kristen ITC", "Mistral", "Vladimir Script", "Edwardian Script ITC", "Monotype Corsiva",
              "Segoe Print"]
INK = QColor(20, 40, 120)


def handwriting_fonts() -> List[str]:
    have = set(QFontDatabase.families())
    return [f for f in HAND_FONTS if f in have] or ["Segoe Print" if "Segoe Print" in have else "Arial"]


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def trim(img: QImage, pad: int = 6) -> Optional[QImage]:
    """Saydam kenarları kırpar; boş görüntüde None."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    xs, ys = [], []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if img.pixelColor(x, y).alpha() > 20:
                xs.append(x); ys.append(y)
    if not xs:
        return None
    r = QRect(min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)
    return img.copy(r.intersected(img.rect()))


def remove_white(img: QImage, threshold: int = 215) -> QImage:
    """Taranmış imzanın açık renkli arka planını saydam yapar."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    if img.width() > 1200:
        img = img.scaledToWidth(1200, Qt.TransformationMode.SmoothTransformation)
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if min(c.red(), c.green(), c.blue()) >= threshold:
                img.setPixelColor(x, y, QColor(0, 0, 0, 0))
    return img


def render_text(text: str, family: str, color: QColor = INK) -> Optional[QImage]:
    font = QFont(family, 64)
    img = QImage(1400, 220, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(font)
    p.setPen(color)
    p.drawText(img.rect().adjusted(20, 0, -20, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
    p.end()
    return trim(img)


class SignatureLibrary:
    KEY = "signatures"

    def __init__(self, settings):
        self.settings = settings
        self.items: List[dict] = []
        self.load()

    def load(self):
        try:
            self.items = json.loads(self.settings.value(self.KEY, "") or "[]")
        except Exception:
            self.items = []

    def save(self):
        self.settings.setValue(self.KEY, json.dumps(self.items))

    def add(self, png: bytes, label: str = "") -> dict:
        it = {"id": uuid.uuid4().hex[:8], "label": label, "png": base64.b64encode(png).decode()}
        self.items.append(it)
        self.save()
        return it

    def remove(self, sid: str):
        self.items = [i for i in self.items if i["id"] != sid]
        self.save()

    @staticmethod
    def png(item: dict) -> bytes:
        return base64.b64decode(item["png"])

    @staticmethod
    def icon(item: dict, w: int = 110, h: int = 32) -> QIcon:
        img = QImage.fromData(SignatureLibrary.png(item))
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.white)
        p = QPainter(pm)
        sc = img.scaled(QSize(w - 4, h - 4), Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
        p.drawImage((w - sc.width()) // 2, (h - sc.height()) // 2, sc)
        p.end()
        return QIcon(pm)


class DrawPad(QWidget):
    """Fareyle/kalemle imza çizme alanı (görüntü 2x çözünürlükte tutulur)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(460, 170)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.paths: List[QPainterPath] = []
        self.color = QColor(INK)
        self.width_ = 2.6

    def clear(self):
        self.paths = []
        self.update()

    def mousePressEvent(self, e):
        path = QPainterPath(e.position())
        path.lineTo(e.position() + QPointF(0.1, 0.1))
        self.paths.append(path)
        self.update()

    def mouseMoveEvent(self, e):
        if self.paths and e.buttons() & Qt.MouseButton.LeftButton:
            self.paths[-1].lineTo(e.position())
            self.update()

    def _draw(self, p: QPainter):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.color, self.width_, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        for path in self.paths:
            p.drawPath(path)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.white)
        p.setPen(QPen(QColor(200, 200, 210), 1, Qt.PenStyle.DashLine))
        y = int(self.height() * 0.72)
        p.drawLine(20, y, self.width() - 20, y)
        self._draw(p)
        p.end()

    def image(self) -> Optional[QImage]:
        if not self.paths:
            return None
        img = QImage(self.width() * 2, self.height() * 2, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.scale(2, 2)
        self._draw(p)
        p.end()
        return trim(img)


class SignatureDialog(QDialog):
    """Yeni imza oluşturma: Çiz / Yaz / Görsel sekmeleri. Sonuç: self.result_png"""

    def __init__(self, parent=None, default_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Yeni imza")
        self.result_png: Optional[bytes] = None
        self.result_label = ""
        self.color = QColor(INK)
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs)

        # Çiz
        w = QWidget(); lv = QVBoxLayout(w)
        self.pad = DrawPad()
        lv.addWidget(QLabel("Fare ya da kalemle imzanızı çizin:"))
        lv.addWidget(self.pad)
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(10, 60); self.slider.setValue(26); self.slider.setFixedWidth(120)
        self.slider.valueChanged.connect(lambda val: (setattr(self.pad, "width_", val / 10), self.pad.update()))
        btn_clear = QPushButton("Temizle"); btn_clear.clicked.connect(self.pad.clear)
        row.addWidget(QLabel("Kalınlık")); row.addWidget(self.slider)
        row.addStretch(); row.addWidget(btn_clear)
        lv.addLayout(row)
        self.tabs.addTab(w, "Çiz")

        # Yaz
        w = QWidget(); lv = QVBoxLayout(w)
        self.name_edit = QLineEdit(default_name)
        self.name_edit.setPlaceholderText("Ad Soyad")
        self.font_combo = QComboBox()
        for f in handwriting_fonts():
            self.font_combo.addItem(f)
            self.font_combo.setItemData(self.font_combo.count() - 1, QFont(f, 13), Qt.ItemDataRole.FontRole)
        self.preview = QLabel(); self.preview.setMinimumHeight(110)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background:white;border:1px solid #ccd;")
        self.name_edit.textChanged.connect(self._update_preview)
        self.font_combo.currentIndexChanged.connect(self._update_preview)
        lv.addWidget(QLabel("Adınız:")); lv.addWidget(self.name_edit)
        lv.addWidget(QLabel("El yazısı yazı tipi:")); lv.addWidget(self.font_combo)
        lv.addWidget(self.preview)
        self.tabs.addTab(w, "Yaz")

        # Görsel
        w = QWidget(); lv = QVBoxLayout(w)
        self.img_label = QLabel("Taranmış ya da fotoğrafı çekilmiş imza görseli seçin.")
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.img_label.setMinimumHeight(130)
        self.img_label.setStyleSheet("background:white;border:1px solid #ccd;")
        self.chk_white = QCheckBox("Beyaz arka planı kaldır"); self.chk_white.setChecked(True)
        self.chk_white.toggled.connect(self._update_image)
        btn = QPushButton("Görsel seç…"); btn.clicked.connect(self._pick_image)
        lv.addWidget(self.img_label); lv.addWidget(self.chk_white); lv.addWidget(btn)
        self.tabs.addTab(w, "Görsel")
        self._src_image: Optional[QImage] = None
        self._img_result: Optional[QImage] = None

        row = QHBoxLayout()
        btn_col = QPushButton("Mürekkep rengi…"); btn_col.clicked.connect(self._pick_color)
        row.addWidget(btn_col); row.addStretch()
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._update_preview()

    def _pick_color(self):
        c = QColorDialog.getColor(self.color, self, "Mürekkep rengi")
        if c.isValid():
            self.color = c
            self.pad.color = c
            self.pad.update()
            self._update_preview()

    def _update_preview(self, *_):
        img = render_text(self.name_edit.text().strip(), self.font_combo.currentText(), self.color)
        self.preview.setPixmap(QPixmap.fromImage(img).scaled(
            QSize(440, 100), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            if img else QPixmap())

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "İmza görseli", "",
                                              "Resimler (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)")
        if path:
            self.load_image(QImage(path))

    def load_image(self, img: QImage):
        self._src_image = img if not img.isNull() else None
        self._update_image()

    def _update_image(self, *_):
        if self._src_image is None:
            return
        img = remove_white(self._src_image) if self.chk_white.isChecked() else self._src_image
        self._img_result = trim(img, 2) or img
        self.img_label.setPixmap(QPixmap.fromImage(self._img_result).scaled(
            QSize(440, 120), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def build(self) -> Optional[QImage]:
        i = self.tabs.currentIndex()
        if i == 0:
            return self.pad.image()
        if i == 1:
            self.result_label = self.name_edit.text().strip()
            return render_text(self.result_label, self.font_combo.currentText(), self.color)
        return self._img_result

    def _accept(self):
        img = self.build()
        if img is None:
            self.tabs.currentWidget().setFocus()
            return
        self.result_png = png_bytes(img)
        self.accept()


class DigitalSignDialog(QDialog):
    """Sertifika (.pfx/.p12), parola, imza alanı, neden ve yer seçimi. values() → dict"""

    def __init__(self, parent=None, sig_fields: List[str] = (), settings=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QFormLayout
        self.settings = settings
        self.setWindowTitle("Dijital olarak imzala")
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        form = QFormLayout(); v.addLayout(form)
        self.pfx = QLineEdit(str(settings.value("signPfx", "") if settings else ""))
        b1 = QPushButton("Gözat…"); b1.clicked.connect(self._browse)
        b2 = QPushButton("Oluştur…"); b2.setToolTip("Deneme için kendinden imzalı sertifika üret")
        b2.clicked.connect(self._create)
        r = QHBoxLayout(); r.addWidget(self.pfx, 1); r.addWidget(b1); r.addWidget(b2)
        form.addRow("Sertifika", r)
        self.pw = QLineEdit(); self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Parola", self.pw)
        self.field = QComboBox()
        self.field.addItem("Görünür imza (bu sayfa, sağ alt)", ("box", None))
        self.field.addItem("Görünmez imza", ("invisible", None))
        for n in sig_fields:
            self.field.addItem(f"İmza alanı: {n}", ("field", n))
        if sig_fields:
            self.field.setCurrentIndex(2)
        form.addRow("Yer", self.field)
        self.reason = QLineEdit(str(settings.value("signReason", "Onaylıyorum") if settings else ""))
        self.location = QLineEdit(str(settings.value("signLocation", "") if settings else ""))
        form.addRow("Neden", self.reason)
        form.addRow("Konum", self.location)
        note = QLabel("İmzalı kopya ayrı bir dosyaya kaydedilir. İmzadan sonra belgeyi değiştirip "
                      "yeniden kaydetmek imzayı geçersiz kılar.")
        note.setWordWrap(True); note.setStyleSheet("color:gray;")
        v.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("İmzala…")
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Sertifika", self.pfx.text(), "Sertifika (*.pfx *.p12)")
        if p:
            self.pfx.setText(p)

    def _create(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        import digisign
        name, ok = QInputDialog.getText(self, "Kendinden imzalı sertifika", "Ad Soyad:")
        if not ok or not name.strip():
            return
        p, _ = QFileDialog.getSaveFileName(self, "Sertifikayı kaydet", f"{name.strip()}.pfx", "Sertifika (*.pfx)")
        if not p:
            return
        if not self.pw.text():
            QMessageBox.warning(self, "Parola", "Önce sertifika için bir parola yazın.")
            return
        digisign.create_self_signed(p, name.strip(), self.pw.text())
        self.pfx.setText(p)

    def _ok(self):
        if not self.pfx.text().strip():
            self.pfx.setFocus()
            return
        self.accept()

    def values(self) -> dict:
        mode, name = self.field.currentData()
        if self.settings:
            self.settings.setValue("signPfx", self.pfx.text().strip())
            self.settings.setValue("signReason", self.reason.text().strip())
            self.settings.setValue("signLocation", self.location.text().strip())
        return {"pfx": self.pfx.text().strip(), "password": self.pw.text(), "mode": mode, "field": name,
                "reason": self.reason.text().strip(), "location": self.location.text().strip()}


def report_html(reports) -> str:
    from digisign import MOD_TEXT
    if not reports:
        return "<p>Bu belgede dijital imza yok.</p>"
    rows = []
    for r in reports:
        mark = ("<b style='color:#1a7f37'>✔ Geçerli</b>" if r.ok else "<b style='color:#c62828'>✖ Sorunlu</b>")
        rows.append(
            f"<h3>{r.field} — {mark}</h3><table cellspacing=4>"
            f"<tr><td>İmzalayan</td><td><b>{r.signer}</b></td></tr>"
            f"<tr><td>Zaman</td><td>{r.when or '-'}</td></tr>"
            + (f"<tr><td>Neden</td><td>{r.reason}</td></tr>" if r.reason else "")
            + f"<tr><td>Bütünlük</td><td>{'Bozulmamış' if r.intact else 'BOZULMUŞ'}</td></tr>"
            f"<tr><td>Kriptografi</td><td>{'Geçerli' if r.valid else 'GEÇERSİZ'}</td></tr>"
            f"<tr><td>Sertifika</td><td>{'Güvenilir köke bağlı' if r.trusted else 'Güven zinciri doğrulanamadı (kendinden imzalı ya da tanınmayan sağlayıcı)'}</td></tr>"
            f"<tr><td>Sonraki değişiklik</td><td>{'Yok (imza tüm dosyayı kapsıyor)' if r.covers_all else MOD_TEXT.get(r.modification, r.modification)}</td></tr>"
            + (f"<tr><td>Hata</td><td>{r.error}</td></tr>" if r.error else "") + "</table>")
    return "".join(rows)


class ReportDialog(QDialog):
    def __init__(self, parent, title: str, html: str):
        super().__init__(parent)
        from PySide6.QtWidgets import QTextBrowser
        self.setWindowTitle(title)
        self.resize(560, 440)
        v = QVBoxLayout(self)
        tb = QTextBrowser(); tb.setHtml(html); v.addWidget(tb)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); bb.rejected.connect(self.reject)
        v.addWidget(bb)
