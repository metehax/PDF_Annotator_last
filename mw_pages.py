"""
mw_pages.py
===========
Sayfa işlemleri: ekle/sil/çoğalt/taşı/döndür, küçük resim bağlam menüleri.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations

import copy


from PySide6.QtWidgets import QMenu, QMessageBox

from ui.icons import icon


class PagesMixin:
    # =====================================================================
    # Sayfa yönetimi (ekle / sil / kopyala / taşı / döndür)
    # =====================================================================
    def _reindex_annotations(self, session, old_count, transform):
        order = [session.annotations.get(i, []) for i in range(old_count)]
        order = transform(order)
        session.annotations = {i: lst for i, lst in enumerate(order)}
        # Sayfa yapısı değişti; eski geri-al kayıtları artık geçersiz sayfa
        # indekslerine işaret edebilir.
        session.undo_stack.clear()

    def _delete_page(self, idx):
        s = self.active_session
        if not s:
            return
        if s.pdf.page_count <= 1:
            QMessageBox.warning(self, "Uyarı", "Belgede tek sayfa var, silinemez.")
            return
        old_count = s.pdf.page_count
        s.pdf.delete_page(idx)
        self._reindex_annotations(s, old_count, lambda order: (order.pop(idx), order)[1])
        s.current_page = min(s.current_page, s.pdf.page_count - 1)
        self._mark_dirty()
        self._build_thumbnails()
        self.goto_page(s.current_page)
        self.status.setText(f"{idx + 1}. sayfa silindi.")

    def _insert_blank_page(self, idx):
        s = self.active_session
        if not s:
            return
        old_count = s.pdf.page_count
        w, h = s.pdf.page_size(0) if old_count else (595, 842)
        idx = max(0, min(idx, old_count))
        s.pdf.insert_blank_page(idx, w, h)
        self._reindex_annotations(s, old_count, lambda order: (order.insert(idx, []), order)[1])
        self._mark_dirty()
        self._build_thumbnails()
        self.goto_page(idx)
        self.status.setText("Boş sayfa eklendi.")

    def _duplicate_page(self, idx):
        s = self.active_session
        if not s:
            return
        old_count = s.pdf.page_count
        s.pdf.duplicate_page(idx)

        def _t(order):
            order.insert(idx + 1, copy.deepcopy(order[idx]))
            return order

        self._reindex_annotations(s, old_count, _t)
        self._mark_dirty()
        self._build_thumbnails()
        self.goto_page(idx + 1)
        self.status.setText("Sayfa kopyalandı.")

    def _move_page(self, frm, to):
        s = self.active_session
        if not s:
            return
        old_count = s.pdf.page_count
        s.pdf.move_page(frm, to)

        def _t(order):
            item = order.pop(frm)
            order.insert(to, item)
            return order

        self._reindex_annotations(s, old_count, _t)
        self._mark_dirty()
        self._build_thumbnails()
        self.goto_page(to)
        self.status.setText("Sayfa taşındı.")

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
        s.pdf.rotate_page(idx, delta)
        s.rotations[idx] = s.pdf.page_rotation(idx)
        self._mark_dirty()
        self._build_thumbnails()
        self.goto_page(idx)
        self.status.setText("Sayfa döndürüldü.")

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
