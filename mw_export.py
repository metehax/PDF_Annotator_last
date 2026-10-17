"""
mw_export.py
============
Kaydetme, dışa aktarma, birleştirme/bölme ve proje (JSON) yöntemleri.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations

import os

import pymupdf as fitz

from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox

from pdf_engine import (
    IMAGE_EXTS, image_to_pdf_document, is_image_path, save_project_json, load_project_json,
)
from ui.watermark import WatermarkDialog
from mw_common import OPEN_FILTER


class ExportMixin:
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
