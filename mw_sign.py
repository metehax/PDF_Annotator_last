"""
mw_sign.py
==========
Elektronik/dijital imza, imza kütüphanesi ve damga yöntemleri.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations

import os


from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QColor, QImage
from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QMessageBox

from models import AddAnnotationCommand, ImageAnnotation
from ui.signatures import DigitalSignDialog, ReportDialog, SignatureDialog, SignatureLibrary, report_html
from ui.stamps import (
    SCALE as STAMP_SCALE, StampLibraryDialog, image_png_bytes, preview_icon, render_stamp, today,
)


class SignMixin:
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
