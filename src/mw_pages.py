"""
mw_pages.py
===========
Sayfa işlemleri: ekle/sil/çoğalt/taşı/döndür, küçük resim bağlam menüleri.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations

import copy


from PySide6.QtWidgets import QMenu, QMessageBox

from models import PageStructureCommand
from ui.icons import icon


class PagesMixin:
    # =====================================================================
    # Sayfa yönetimi (ekle / sil / kopyala / taşı / döndür)
    # =====================================================================
    def _reindexed(self, session, old_count, transform):
        """İşaret sözlüğünün sayfa yapısı değişimine göre yeni hâli (oturumu değiştirmez)."""
        order = [session.annotations.get(i, []) for i in range(old_count)]
        order = transform(order)
        return {i: lst for i, lst in enumerate(order)}

    def _page_op(self, label, do_doc, undo_doc, order_transform, target_after, target_before=None, after_rot=None,
                 status=""):
        """Sayfa yapısı işlemini geri alınabilir komut olarak uygular (Ctrl+Z ile geri alınır)."""
        s = self.active_session
        old_count = s.pdf.page_count
        after = self._reindexed(s, old_count, order_transform)
        cmd = PageStructureCommand(s, label, do_doc, undo_doc, after, on_change=self._after_page_structure,
                                   target_after=target_after,
                                   target_before=s.current_page if target_before is None else target_before,
                                   after_rot=after_rot)
        s.undo_stack.push(cmd)
        if status:
            self.status.setText(status)

    def _after_page_structure(self, session, target):
        """Sayfa işlemi uygulanınca / geri alınınca: küçük resimler, içindekiler ve görünüm tazelenir."""
        if session is not self.active_session:
            return
        session.current_page = max(0, min(target, session.pdf.page_count - 1))
        self.refresh_doc_tabs()
        self._build_thumbnails()
        self._build_toc()
        self._refresh_forms()
        self.goto_page(session.current_page)

    def _delete_page(self, idx):
        s = self.active_session
        if not s:
            return
        if s.pdf.page_count <= 1:
            QMessageBox.warning(self, "Uyarı", "Belgede tek sayfa var, silinemez.")
            return
        data = s.pdf.page_bytes(idx)
        self._page_op(f"{idx + 1}. Sayfayı Sil", lambda: s.pdf.delete_page(idx), lambda: s.pdf.insert_page_bytes(idx, data),
                      lambda order: (order.pop(idx), order)[1], target_after=min(idx, s.pdf.page_count - 2),
                      target_before=idx, status=f"{idx + 1}. sayfa silindi (Ctrl+Z ile geri alınabilir).")

    def _insert_blank_page(self, idx):
        s = self.active_session
        if not s:
            return
        old_count = s.pdf.page_count
        w, h = s.pdf.page_size(0) if old_count else (595, 842)
        idx = max(0, min(idx, old_count))
        self._page_op("Boş Sayfa Ekle", lambda: s.pdf.insert_blank_page(idx, w, h), lambda: s.pdf.delete_page(idx),
                      lambda order: (order.insert(idx, []), order)[1], target_after=idx,
                      status="Boş sayfa eklendi.")

    def _duplicate_page(self, idx):
        s = self.active_session
        if not s:
            return

        def _t(order):
            order.insert(idx + 1, copy.deepcopy(order[idx]))
            return order

        self._page_op("Sayfayı Kopyala", lambda: s.pdf.duplicate_page(idx), lambda: s.pdf.delete_page(idx + 1), _t,
                      target_after=idx + 1, status="Sayfa kopyalandı.")

    def _move_page(self, frm, to):
        s = self.active_session
        if not s:
            return

        def _t(order):
            item = order.pop(frm)
            order.insert(to, item)
            return order

        # `to`: sayfanın taşıma sonrası konumu. PyMuPDF `move_page(pno, hedef)` sayfayı hedefin ÖNÜNE koyar:
        # ileri taşımada hedef bir fazla verilir (aksi hâlde 1 adım ilerleme hiçbir şey yapmazdı).
        fwd = lambda a, b: b if b < a else b + 1
        self._page_op("Sayfayı Taşı", lambda: s.pdf.move_page(frm, fwd(frm, to)), lambda: s.pdf.move_page(to, fwd(to, frm)),
                      _t, target_after=to, target_before=frm, status="Sayfa taşındı.")

    def _rotate_current_page(self, delta):
        s = self.active_session
        if not s:
            return
        self._rotate_page(s.current_page, delta)

    def _rotate_page(self, idx, delta):
        s = self.active_session
        if not s:
            return
        if s.annotations.get(idx):
            reply = QMessageBox.question(
                self, "Sayfa Döndür",
                "Bu sayfada işaretler var. Döndürme sonrası konumları kayabilir.\n"
                "Devam edilsin mi?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        after_rot = dict(s.rotations)
        after_rot[idx] = (s.pdf.page_rotation(idx) + delta) % 360
        self._page_op("Sayfayı Döndür", lambda: s.pdf.rotate_page(idx, delta), lambda: s.pdf.rotate_page(idx, -delta),
                      lambda order: order, target_after=idx, target_before=idx, after_rot=after_rot,
                      status="Sayfa döndürüldü.")

    def _on_thumb_context_menu(self, pos):
        s = self.active_session
        if not s:
            return
        row = self.thumb_list.indexAt(pos).row()
        if row < 0:
            return
        self._page_menu(row, self.thumb_list.viewport().mapToGlobal(pos))

    def _page_menu(self, row, global_pos):
        s = self.active_session
        if not s:
            return
        menu = QMenu(self)
        act_before = menu.addAction(icon("file_plus"), "Öncesine Boş Sayfa Ekle")
        act_after = menu.addAction(icon("file_plus"), "Sonrasına Boş Sayfa Ekle")
        act_dup = menu.addAction(icon("file_copy"), "Sayfayı Kopyala")
        menu.addSeparator()
        act_up = menu.addAction(icon("arrow_up"), "Yukarı Taşı")
        act_down = menu.addAction(icon("arrow_down"), "Aşağı Taşı")
        menu.addSeparator()
        act_rot_cw = menu.addAction(icon("rotate_cw"), "Saat Yönünde Döndür")
        act_rot_ccw = menu.addAction(icon("rotate_ccw"), "Tersine Döndür")
        menu.addSeparator()
        act_del = menu.addAction(icon("trash", "danger"), "Sayfayı Sil")
        chosen = menu.exec(global_pos)
        if chosen == act_before:
            self._insert_blank_page(row)
        elif chosen == act_after:
            self._insert_blank_page(row + 1)
        elif chosen == act_dup:
            self._duplicate_page(row)
        elif chosen == act_up and row > 0:
            self._move_page(row, row - 1)
        elif chosen == act_down and row < s.pdf.page_count - 1:
            self._move_page(row, row + 1)
        elif chosen == act_rot_cw:
            self._rotate_page(row, 90)
        elif chosen == act_rot_ccw:
            self._rotate_page(row, -90)
        elif chosen == act_del:
            self._delete_page(row)
