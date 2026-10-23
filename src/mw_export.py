"""
mw_export.py
============
Kaydetme, dışa aktarma, birleştirme/bölme ve proje (JSON) yöntemleri.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations

import os

import pymupdf as fitz

from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QFileDialog, QInputDialog, QMessageBox

from models import RedactionAnnotation

from pdf_engine import (
    IMAGE_EXTS, is_image_path, save_project_json, load_project_json,
)
from ui.watermark import WatermarkDialog
from mw_common import OPEN_FILTER
import workspace


class ExportMixin:
    # =====================================================================
    # Dosya: kaydet / dışa aktar / birleştir / ayır / proje
    # =====================================================================
    def save_document(self):
        """Ctrl+S: PDF bulunduğu dosyanın üzerine yazılır; resim açıldıysa resim olarak kaydedilir."""
        s = self.active_session
        if s:
            self.save_in_place(s)

    @staticmethod
    def _file_signed(path) -> bool:
        try:
            with open(path, "rb") as f:
                return b"/ByteRange" in f.read()
        except OSError:
            return False

    def save_in_place(self, s, auto=False) -> bool:
        """Belgeyi bulunduğu dosyanın üzerine yazar (işaretler ve geri alma geçmişi bellekte kalır)."""
        if s.pdf.is_image:
            if auto:
                return False
            if s is not self.active_session:
                self.switch_session(self.sessions.index(s))
            self.save_as_image()
            return not self._is_dirty(s)
        if not auto and not self._confirm_redactions(s, overwrite=True):
            return False
        if self._file_signed(s.path):
            if auto:
                return False
            r = QMessageBox.question(
                self, "Dijital imzalı dosya",
                f"'{s.title}' dijital imzalı. Üzerine yazmak mevcut imzaları GEÇERSİZ kılar.\n\n"
                "Yine de üzerine yazılsın mı? (Hayır: Farklı kaydet)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if r != QMessageBox.StandardButton.Yes:
                if r == QMessageBox.StandardButton.No:
                    self.save_pdf_as()
                return not self._is_dirty(s)
        tmp = s.path + ".kaydediliyor"
        try:
            s.pdf.export_pdf(tmp, s.annotations, self.font_ctx, security=getattr(s, "security", None))
            os.replace(tmp, s.path)
        except Exception as ex:
            try:
                os.remove(tmp)
            except OSError:
                pass
            if auto:
                self.status.setText(f"Otomatik kayıt başarısız: {ex}")
            else:
                QMessageBox.critical(self, "Hata", f"Kaydedilemedi (dosya başka yerde açık olabilir; "
                                                   f"'Farklı kaydet' deneyin):\n{ex}")
            return False
        self._mark_saved(s)
        self._drop_draft(s)
        if auto:
            self.status.setText(f"Otomatik kaydedildi: {s.title}")
        else:
            self.toasts.show(f"Kaydedildi: {s.title}", "success")
        return True

    def set_autosave(self, on: bool):
        workspace.set_autosave_overwrite(bool(on))
        if on:
            self._autosave_timer.start()
            self.toasts.show("Otomatik kaydetme açık: değişiklikler her 30 sn'de özgün dosyaya yazılır. "
                             "Sansür/bulanıklaştırma dosyaya kalıcı işlenir.", "info", timeout_ms=7000)
        else:
            self._autosave_timer.stop()

    def _autosave_tick(self):
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return
        for s in list(self.sessions):
            if self._is_dirty(s) and not s.pdf.is_image:
                self.save_in_place(s, auto=True)

    def ask_save_all(self, dirty):
        """(mod, oturumlar, klasör) ya da None. Testte sahtelenir."""
        from ui.savedlg import SaveAllDialog
        dlg = SaveAllDialog(dirty, self, str(self.settings.value("saveAllDir", "") or ""))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        if dlg.mode == "dir":
            self.settings.setValue("saveAllDir", dlg.target_dir())
        return dlg.mode, dlg.chosen(), dlg.target_dir()

    def save_all(self) -> bool:
        """Kaydedilmemiş tüm sekmeleri kaydeder (üzerine yaz / kopya / klasöre); hepsi kaydedildiyse True."""
        dirty = [s for s in self.sessions if self._is_dirty(s)]
        if not dirty:
            self.toasts.show("Kaydedilmemiş belge yok.", "info")
            return True
        res = self.ask_save_all(dirty)
        if not res:
            return False
        mode, chosen, folder = res
        done, skipped = 0, []
        for s in chosen:
            if s.pdf.is_image:
                skipped.append(s.title)
                continue
            if mode == "over":
                if self.save_in_place(s):
                    done += 1
                continue
            base = os.path.splitext(s.title)[0]
            out_dir = folder if mode == "dir" else os.path.dirname(s.path)
            out = os.path.join(out_dir, base + "_isaretli.pdf")
            k = 2
            while os.path.exists(out):
                out = os.path.join(out_dir, f"{base}_isaretli{k}.pdf")
                k += 1
            try:
                s.pdf.export_pdf(out, s.annotations, self.font_ctx, security=getattr(s, "security", None))
                self._mark_saved(s)
                done += 1
            except Exception as ex:
                QMessageBox.critical(self, "Hata", f"{s.title} kaydedilemedi:\n{ex}")
        msg = f"{done} belge kaydedildi."
        if skipped:
            msg += f" Resim sekmeleri atlandı (ayrı kaydedin): {', '.join(skipped)}"
        self.toasts.show(msg, "success")
        return not any(self._is_dirty(s) for s in chosen if not s.pdf.is_image)

    def save_pdf_as(self):
        """Farklı kaydet: yeni dosyaya yazar ve belge artık o dosya olur (sekme adı/yolu değişir)."""
        s = self.active_session
        if not s:
            return
        if not self._confirm_redactions(s):
            return
        default = os.path.splitext(s.path)[0] + ("_kopya.pdf" if not s.pdf.is_image else ".pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Farklı Kaydet", default, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            s.pdf.export_pdf(path, s.annotations, self.font_ctx, security=getattr(s, "security", None))
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")
            return
        self._mark_saved(s)
        self._drop_draft(s)
        s.path = path
        s.title = os.path.basename(path)
        s.pdf.path = path
        self.refresh_doc_tabs()
        self._toast_saved("Kaydedildi", path)

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

    def _ask_redaction_summary(self, n: int, pages: int) -> str:
        """"save" | "final" | "cancel" (testlerde bu yöntem örnek üzerinde değiştirilir)."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Sansür uygulanacak")
        over = getattr(self, "_redact_overwrite", False)
        box.setText(f"<b>{n} sansür kutusu ({pages} sayfada)</b> " +
                    ("dosyaya uygulanacak." if over else "kopyaya uygulanacak."))
        box.setInformativeText(("Altındaki metin ve resim ÖZGÜN DOSYADAN KALICI olarak silinir. " if over else
                                "Altındaki metin ve resim kopyadan KALICI olarak silinir (özgün dosya değişmez). ") +
                               "Ekranda yarı saydam görünen kutular çıktıda tam dolgu olur.")
        again = QCheckBox("Bir daha sorma")
        box.setCheckBox(again)
        b_save = box.addButton("Kaydet", QMessageBox.ButtonRole.AcceptRole)
        b_final = box.addButton("Nihai görünüme bak", QMessageBox.ButtonRole.ActionRole)
        box.addButton("İptal", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(b_save)
        box.exec()
        c = box.clickedButton()
        if c is b_save:
            if again.isChecked():
                self.settings.setValue("redactConfirmOff", True)
            return "save"
        return "final" if c is b_final else "cancel"

    def _confirm_redactions(self, s, overwrite=False) -> bool:
        """Kaydetmeden önce sansür özeti: kaç kutu, kaç sayfa; "Nihai görünüme bak" ekranı çıktıdaki gibi gösterir."""
        boxes = [(p, a) for p, lst in s.annotations.items() for a in lst
                 if isinstance(a, RedactionAnnotation) and not a.quiet]
        if not boxes or str(self.settings.value("redactConfirmOff", "false")).lower() == "true":
            return True
        self._redact_overwrite = overwrite
        choice = self._ask_redaction_summary(len(boxes), len({p for p, _ in boxes}))
        if choice == "final":
            self.set_redact_final_view(True)
            self.toasts.show("Nihai görünüm açıldı: kutuları kontrol edip tekrar kaydedin.", "info")
        return choice == "save"

    def save_pdf(self):
        s = self.active_session
        if not s:
            return
        if not self._confirm_redactions(s):
            return
        default = os.path.splitext(s.path)[0] + "_isaretli.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Kopya Olarak Kaydet (özgün dosya değişmez)", default, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            s.pdf.export_pdf(path, s.annotations, self.font_ctx, security=getattr(s, "security", None))
            self.status.setText(f"Kaydedildi: {path}")
            self._mark_saved(s)
            self._toast_saved("Kopya kaydedildi", path, note="Özgün dosya değişmedi.")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")

    def save_pdf_with_watermark(self):
        s = self.active_session
        if not s:
            return
        if not self._confirm_redactions(s):
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
            self._toast_saved("Filigranlı kopya kaydedildi", path, note="Özgün dosya değişmedi.")
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

    def merge_pdfs(self, paths=None):
        """Birleştir penceresi: sıralı liste, dosya başına sayfa aralığı, önizleme."""
        from ui.mergesplit import MergeDialog
        dlg = MergeDialog(self, paths or ())
        dlg.show()
        return dlg

    def split_pdfs(self, paths=None):
        """Böl penceresi: aralık / her N sayfa / yer imi / her sayfa; birden çok PDF."""
        from ui.mergesplit import SplitDialog
        if paths is None:
            s = self.active_session
            paths = [s.path] if s and s.path and os.path.isfile(s.path) else ()
        dlg = SplitDialog(self, paths)
        dlg.show()
        return dlg

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
        stem = os.path.splitext(os.path.basename(s.path))[0] + ".pdfproj.json"
        default = workspace.join_out("projects", stem, os.path.dirname(s.path))
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
        start = workspace.out_dir("projects") or workspace.last_dir()
        path, _ = QFileDialog.getOpenFileName(self, "Proje Aç", start, "PDF Proje (*.json)")
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
