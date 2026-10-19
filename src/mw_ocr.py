"""
mw_ocr.py
=========
OCR ve taranmış sayfada metin düzenleme yöntemleri.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations


import pymupdf as fitz

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from models import AddAnnotationCommand, RedactionAnnotation, TextAnnotation
import ocr
from ui.textdialog import TextDialog, ocr_text_width
from ui.ocrdialog import OcrDialog, _OcrTask


class OcrMixin:
    def open_ocr_dialog(self):
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return
        OcrDialog(self, s, self).exec()

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
