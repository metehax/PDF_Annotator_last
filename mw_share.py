"""
mw_share.py
===========
Dosya → Paylaş: e-postayla gönder, bulut klasörüne kaydet (OneDrive / Google Drive / Dropbox yerel klasörü),
dosya konumunu aç. Çekirdek `sharing.py`'dadır; uygulama hiçbir üçüncü taraf servisle kendisi konuşmaz.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Callable, List, Optional

from PySide6.QtWidgets import QInputDialog, QMessageBox

import qrshare
import sharing

SHARE_TMP = "PDF Annotator paylasim"


class ShareMixin:
    # -- hazırlık -----------------------------------------------------------------
    def _stem(self, s) -> str:
        return os.path.splitext(os.path.basename(s.path))[0] if s.path else "belge"

    def _is_original_current(self, s) -> bool:
        """Diskteki özgün PDF güncel mi (kaydedilmemiş değişiklik yok)? O zaman olduğu gibi paylaşılabilir."""
        return bool(s.path) and s.path.lower().endswith(".pdf") and os.path.isfile(s.path) and not self._is_dirty(s)

    def _export_copy(self, s, out: str) -> str:
        """Belgenin işaretli kopyasını yazar (parola ayarı korunur)."""
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        s.pdf.export_pdf(out, s.annotations, self.font_ctx, security=getattr(s, "security", None))
        return out

    def _share_file(self, s) -> str:
        """Paylaşılacak dosya: özgün güncelse kendisi, değilse geçici klasöre yazılmış işaretli kopya."""
        if self._is_original_current(s):
            return s.path
        out = os.path.join(tempfile.gettempdir(), SHARE_TMP, self._stem(s) + "_isaretli.pdf")
        return self._export_copy(s, out)

    # -- e-posta ----------------------------------------------------------------------
    def share_email(self) -> Optional[str]:
        """Outlook varsa dosya ekli yeni ileti; yoksa dosyanın klasörü + boş e-posta (dosyayı sürükleyin). Modu döndürür."""
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return None
        try:
            path = self._share_file(s)
            mode = sharing.compose_email(path, subject=os.path.basename(path))
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"E-posta hazırlanamadı:\n{ex}")
            return None
        if mode == "outlook":
            self.toasts.show("Outlook'ta ek olarak açıldı.", "success")
        else:
            self.toasts.show("Dosyanın klasörü açıldı; dosyayı e-posta iletisine sürükleyip bırakın.", "info", timeout_ms=7000)
        return mode

    # -- bulut klasörü ----------------------------------------------------------------
    def share_cloud(self, choose: Optional[Callable[[List[sharing.CloudFolder]], Optional[sharing.CloudFolder]]] = None
                    ) -> Optional[str]:
        """Belgenin (işaretli) kopyasını yerel bulut klasörüne yazar; senkronu o uygulama yapar. Yazılan yolu döndürür."""
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return None
        folders = sharing.cloud_folders()
        if not folders:
            self.toasts.show("OneDrive, Google Drive ya da Dropbox klasörü bulunamadı. Bu uygulamalardan biri kuruluysa "
                             "oturum açtığınızdan emin olun.", "warning", timeout_ms=7000)
            return None
        folder = (choose or self._choose_cloud)(folders) if len(folders) > 1 or choose else folders[0]
        if folder is None:
            return None
        try:
            if self._is_original_current(s):
                dest = qrshare.unique_path(folder.path, self._stem(s) + ".pdf")
                shutil.copy2(s.path, dest)
            else:
                dest = self._export_copy(s, qrshare.unique_path(folder.path, self._stem(s) + "_isaretli.pdf"))
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Bulut klasörüne kaydedilemedi:\n{ex}")
            return None
        self.toasts.show(f"{folder.name} klasörüne kaydedildi: {os.path.basename(dest)}. "
                         "Eşitlemeyi ilgili uygulama yapar.", "success", timeout_ms=6000)
        return dest

    def _choose_cloud(self, folders: List[sharing.CloudFolder]) -> Optional[sharing.CloudFolder]:
        labels = [f"{f.name} — {f.path}" for f in folders]
        item, ok = QInputDialog.getItem(self, "Bulut klasörü", "Hangi klasöre kaydedilsin?", labels, 0, False)
        return folders[labels.index(item)] if ok and item in labels else None

    # -- konum --------------------------------------------------------------------------
    def share_reveal(self) -> Optional[str]:
        """Dosya konumunu Gezgin'de açar (kaydedilmemiş belgede önce işaretli kopya yazılır)."""
        s = self.active_session
        if not s:
            self.toasts.show("Önce bir belge açın.", "info")
            return None
        try:
            return sharing.reveal(s.path if s.path and os.path.exists(s.path) else self._share_file(s))
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Konum açılamadı:\n{ex}")
            return None
