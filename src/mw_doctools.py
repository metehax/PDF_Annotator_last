"""
mw_doctools.py
==============
Belge araçları: sıkıştırma, parola, güvenlik, tarama, dönüştürme, erişilebilirlik, KVKK, iş akışı, üstbilgi/kırpma, yazdırma.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations

import os

import pymupdf as fitz

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QProgressDialog

from models import CropPagesCommand
from pdf_engine import IMAGE_EXTS
import docsec
from headfoot import HeadFootConfig
from ui.docdialogs import CompressDialog, DocInfoDialog, PasswordDialog, SecurityCheckDialog
from ui.a11y import A11yDialog
from ui.convert import ConvertDialog
from ui.flatten import FlattenDialog
from ui.share import ShareDialog
from ui.imgpdf import ImagesPdfDialog
from ui.scanner import ScanDialog, pdf_sources
from ui.kvkk import KvkkDialog
from ui.workflow import WorkflowDialog
from ui.pagetools import CropPagesDialog, HeadFootDialog


class DocToolsMixin:
    # -- yazdırma ---------------------------------------------------------------
    def print_document(self):
        s = self.active_session
        if not s:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        self._finish_form_editor()
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(s.title)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Yazdır")
        dlg.setOption(QPrintDialog.PrintDialogOption.PrintPageRange, True)
        dlg.setOption(QPrintDialog.PrintDialogOption.PrintCurrentPage, True)
        dlg.setMinMax(1, s.pdf.page_count)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        n = self.print_to(printer)
        if n:
            self.toasts.show(f"{n} sayfa yazıcıya gönderildi.")

    def print_to(self, printer, pages=None) -> int:
        """Belgeyi (işaretler ve form değerleriyle) yazıcıya basar; basılan sayfa sayısını döner."""
        from PySide6.QtGui import QPageLayout, QPainter
        from PySide6.QtPrintSupport import QPrinter
        s = self.active_session
        n = s.pdf.page_count
        if pages is None:
            rng = printer.printRange()
            if rng == QPrinter.PrintRange.PageRange and printer.fromPage() > 0:
                pages = list(range(printer.fromPage() - 1, min(printer.toPage(), n)))
            elif rng == QPrinter.PrintRange.CurrentPage:
                pages = [s.current_page]
            else:
                pages = list(range(n))
        if not pages:
            return 0
        tmp = s.pdf._annotated_copy(s.annotations, self.font_ctx)
        dpi = max(96, min(printer.resolution(), 300))
        prog = QProgressDialog("Yazdırılıyor…", "İptal", 0, len(pages), self)
        prog.setWindowTitle("Yazdır")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(400)
        painter = QPainter()
        done = 0
        try:
            for i, pidx in enumerate(pages):
                if prog.wasCanceled():
                    break
                page = tmp[pidx]
                landscape = page.rect.width > page.rect.height
                printer.setPageOrientation(QPageLayout.Orientation.Landscape if landscape
                                           else QPageLayout.Orientation.Portrait)
                if i == 0:
                    if not painter.begin(printer):
                        raise RuntimeError("Yazıcı başlatılamadı.")
                else:
                    printer.newPage()
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format.Format_RGB888)
                area = painter.viewport()
                sc = min(area.width() / img.width(), area.height() / img.height())
                w, h = img.width() * sc, img.height() * sc
                painter.drawImage(QRectF((area.width() - w) / 2, (area.height() - h) / 2, w, h), img)
                done += 1
                prog.setValue(i + 1)
                QApplication.processEvents()
        except Exception as e:
            QMessageBox.critical(self, "Yazdır", f"Yazdırma başarısız:\n{e}")
        finally:
            if painter.isActive():
                painter.end()
            tmp.close()
            prog.close()
        return done

    # -- belge güvenliği ve bilgileri ------------------------------------------
    def save_compressed(self):
        s = self.active_session
        if not s:
            return
        if not self._confirm_redactions(s):
            return
        size = os.path.getsize(s.path) if os.path.exists(s.path) else 0
        dlg = CompressDialog(self, size)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        default = os.path.splitext(s.path)[0] + "_kucuk.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Sıkıştırılmış PDF'i Kaydet", default, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            s.pdf.export_pdf(path, s.annotations, self.font_ctx, security=getattr(s, "security", None),
                             compress=dlg.level())
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        new = os.path.getsize(path)
        self._mark_saved(s)
        if size:
            pct = round(100 * (1 - new / size))
            change = f"%{pct} küçüldü" if pct > 0 else "zaten sıkıştırılmıştı"
            text = f"Sıkıştırıldı: {docsec.human_size(size)} → {docsec.human_size(new)} ({change})"
        else:
            text = f"Kaydedildi: {docsec.human_size(new)}"
        self.status.setText(text)
        self._toast_saved(text, path, note="Özgün dosya değişmedi.")

    def open_password(self):
        s = self.active_session
        if not s:
            return
        dlg = PasswordDialog(self, getattr(s, "security", None))
        code = dlg.exec()
        if code == QDialog.DialogCode.Rejected:
            return
        s.security = dlg.result_options if code != 2 else None
        self._mark_dirty(s)
        if s.security is not None and s.security.active:
            self.toasts.show(f"Parola koruması ayarlandı ({s.security.describe()}). "
                             "Belgeyi kaydettiğinizde uygulanır.", "success", timeout_ms=5000)
        else:
            s.security = None
            self.toasts.show("Parola koruması kaldırıldı. Kaydettiğinizde belge parolasız olur.", "info")

    def open_doc_info(self):
        s = self.active_session
        if not s:
            return
        DocInfoDialog(self, s, lambda: self._mark_dirty(s)).exec()

    def open_security_check(self):
        s = self.active_session
        if not s:
            return

        def cleaned():
            s.pdf._invalidate()                  # sayfa içeriği değişmiş olabilir
            self._mark_dirty(s)
            self._build_thumbnails()
            self.goto_page(s.current_page)
            self.toasts.show("Seçilen içerik temizlendi. Kaydettiğinizde PDF'e yansır.", "success")

        SecurityCheckDialog(self, s, cleaned).exec()

    # -- Telefonla aktar (QR) ---------------------------------------------------
    def open_share(self):
        """Yerel ağda geçici sunucu + QR penceresi (tek örnek); pencere kapanınca sunucu durur."""
        dlg = getattr(self, "_share_dialog", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return dlg
        dlg = self._share_dialog = ShareDialog(self)
        dlg.show()
        return dlg

    def open_share_send(self):
        """Paylaş → Telefona gönder: pencerenin "Telefona gönder" sekmesini açar."""
        dlg = self.open_share()
        dlg.tabs.setCurrentIndex(1)
        return dlg

    # -- Belge tarama -----------------------------------------------------------
    def scan_images(self, paths=None):
        """Görsellerden (ya da PDF'lerden) tarama penceresi; yol verilmezse dosya seçtirir."""
        if not paths:
            flt = "Görsel ve PDF (" + " ".join("*" + e for e in IMAGE_EXTS) + " *.pdf)"
            paths, _ = QFileDialog.getOpenFileNames(self, "Taranacak dosyalar", "", flt)
        if not paths:
            return None
        dlg = self._scan_dialog = ScanDialog(self, list(paths))
        dlg.show()
        return dlg

    def images_to_pdf(self, paths=None):
        """Çoklu görseli tek PDF'e ya da her biri ayrı PDF'e çevirir (ayarlı, toplu yol)."""
        dlg = self._imgpdf_dialog = ImagesPdfDialog(self, list(paths or []))
        dlg.show()
        return dlg

    def scan_command(self):
        """Doğrudan "Tara": kaynak seç (Dosyalar · Telefondan · Açık belge) ve ilgili pencereyi aç."""
        from ui.scansource import ScanSourceDialog
        s = self.active_session
        dlg = ScanSourceDialog(self, s.pdf.page_count if s else 0, s.current_page if s else 0)
        if not dlg.exec():
            return None
        src = dlg.source()
        if src == "phone":
            d = self.open_share()
            d.tabs.setCurrentIndex(0)
            return d
        if src == "doc":
            pages = dlg.pages()
            return self.scan_document(pages, dlg.replace()) if pages else None
        return self.scan_images()

    def scan_document(self, pages=None, replace: bool = False):
        """Açık belgenin sayfalarını (200 dpi) tarama penceresinde aç: kırp, temizle, yeniden PDF yap.
        `pages`: 0 tabanlı dizinler (None = tümü). `replace`: sonuç aynı PDF'te o sayfaların yerine konur (geri alınabilir)."""
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return None
        try:
            snap = s.pdf._annotated_copy(s.annotations, self.font_ctx)
            data = snap.write()
            snap.close()
            srcs = pdf_sources(data, os.path.basename(s.path) if s.path else "belge")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Belge hazırlanamadı:\n{ex}")
            return None
        chosen = sorted(set(pages)) if pages else list(range(len(srcs)))
        srcs = [srcs[i] for i in chosen]
        start = chosen.index(s.current_page) if s.current_page in chosen else 0
        dlg = self._scan_dialog = ScanDialog(self, srcs, start=start)
        if replace:
            dlg.replace_cb = lambda out: self._replace_scanned(s, chosen, out)
        dlg.show()
        return dlg

    def _replace_scanned(self, s, pages, out):
        """Taranan sayfaları (PDF `out`) belgede `pages` yerine koyar; sayı tutmazsa yeni PDF olarak açar."""
        from models import PagesReplaceCommand
        with fitz.open(out) as scanned:
            if scanned.page_count != len(pages):
                self.toasts.show("Sayfa sayısı değiştiği için sonuç yeni PDF olarak açıldı.", "warning")
                self.open_paths([out])
                return False
            before = s.pdf.snapshot_bytes()
            doc = fitz.open("pdf", before)
            try:
                for k in range(len(pages) - 1, -1, -1):          # sondan başa: önceki dizinler kaymaz
                    doc.delete_page(pages[k])
                    doc.insert_pdf(scanned, from_page=k, to_page=k, start_at=pages[k])
                after = doc.write()
            finally:
                doc.close()
        s.pdf.replace_content(after)
        s.undo_stack.push(PagesReplaceCommand(s, "Taranan sayfaları yerine koy", before, after, pages,
                                              on_change=lambda: self._scan_replaced_changed(s)))
        self._scan_replaced_changed(s)
        self.toasts.show(f"{len(pages)} sayfa taranan sürümle değiştirildi (Ctrl+Z geri alır).", "success")
        return True

    def _scan_replaced_changed(self, s):
        s.pdf._invalidate()
        self._mark_dirty(s)
        self._build_thumbnails()
        self._build_toc()
        self.goto_page(min(s.current_page, s.pdf.page_count - 1))

    # -- Word / Excel dönüştürme ve erişilebilirlik ---------------------------
    def open_flatten(self):
        """İşaret/yorum/form alanlarını sayfa içeriğine gömen düzleştirilmiş kopya (isteğe bağlı resme çevirme)."""
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return None
        dlg = self._flatten_dialog = FlattenDialog(self, s)
        dlg.show()
        return dlg

    def open_convert(self, fmt: str = "docx"):
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return None
        dlg = self._convert_dialog = ConvertDialog(self, s, fmt)
        dlg.exec()
        return dlg

    def open_a11y(self):
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return None

        def changed():
            s.pdf._invalidate()                  # OCR sayfaları değiştirmiş olabilir
            self._mark_dirty(s)
            self._build_thumbnails()
            self._build_toc()                    # yer imleri eklenmiş olabilir
            self.goto_page(s.current_page)

        dlg = self._a11y_dialog = A11yDialog(self, s, changed)
        dlg.exec()
        return dlg

    # -- KVKK ----------------------------------------------------------------
    def open_kvkk(self):
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return
        if self._kvkk_dialog is not None and self._kvkk_dialog.isVisible() \
                and self._kvkk_dialog._session is s:
            self._kvkk_dialog.raise_()
            self._kvkk_dialog.activateWindow()
            return
        self._kvkk_dialog = KvkkDialog(self, s)
        self._kvkk_dialog.show()

    # -- Görsel iş akışı ---------------------------------------------------------
    def open_workflow(self):
        """Adım zinciri penceresi (tek örnek); belge açık olmasa da dosya/klasör için kullanılabilir."""
        dlg = getattr(self, "_workflow_dialog", None)
        if dlg is None:
            dlg = self._workflow_dialog = WorkflowDialog(self)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    # =====================================================================
    # Sayfa numarası / üstbilgi / Bates ve sayfa kırpma
    # =====================================================================
    def save_pdf_with_headfoot(self, bates: bool):
        s = self.active_session
        if not s:
            return
        initial = getattr(self, "_headfoot_cfg", None) or HeadFootConfig()
        dlg = HeadFootDialog(initial, s.pdf.page_count, os.path.basename(s.path), bates, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cfg = dlg.get_config()
        self._headfoot_cfg = cfg
        suffix = "_bates" if bates else "_numarali"
        default = os.path.splitext(s.path)[0] + suffix + ".pdf"
        path, _ = QFileDialog.getSaveFileName(self, "PDF Olarak Kaydet", default, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            s.pdf.export_pdf(path, s.annotations, self.font_ctx, headfoot=cfg,
                             security=getattr(s, "security", None),
                             source_name=os.path.basename(s.path))
            self.status.setText(f"Kaydedildi: {path}")
            self._toast_saved("Kopya kaydedildi", path, note="Özgün dosya değişmedi.")
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")

    def open_crop_pages(self):
        s = self.active_session
        if not s:
            return

        def auto(idx):
            r = s.pdf.content_bbox(idx)
            if r is None:
                return None
            w, h = s.pdf.page_size(idx)
            return (r.y0, h - r.y1, r.x0, w - r.x1)

        dlg = CropPagesDialog(s.pdf.page_count, s.current_page, s.pdf.page_size(s.current_page),
                              auto, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        top, bottom, left, right = dlg.margins_pt()
        crops = {}
        for idx in dlg.pages():
            w, h = s.pdf.page_size(idx)
            if w - left - right < 20 or h - top - bottom < 20:
                continue
            crops[idx] = fitz.Rect(left, top, w - right, h - bottom)
        if not crops:
            QMessageBox.warning(self, "Kırp", "Kırpma değerleri sayfa boyutuna göre çok büyük.")
            return
        self._apply_crops(crops)

    def _apply_crops(self, crops):
        s = self.active_session
        if not s:
            return

        def done():
            self._mark_dirty()
            self._build_thumbnails()
            self.view.show_page(s, s.current_page, invert=self.night_mode)
            self.refresh_layers_panel()

        s.undo_stack.push(CropPagesCommand(s, crops, on_done=done))
        self.toasts.show(f"{len(crops)} sayfa kırpıldı (Ctrl+Z ile geri alınır)")
