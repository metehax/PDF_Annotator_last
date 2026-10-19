"""
mw_nav.py
=========
Gezinme: küçük resimler, içindekiler, sayfa/yakınlaştırma, arama.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations

from typing import Dict, List, Tuple


from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QListWidgetItem, QTreeWidgetItem

from ui.widgets import THUMB_ASPECT_ROLE, THUMB_ROLE


class NavMixin:
    def _build_thumbnails(self):
        """Küçük resim listesini anında kurar (boş kâğıt simgeleriyle);
        gerçek görüntüler göründükçe arka planda üretilir."""
        self._close_form_editor()
        self._refresh_forms()
        s = self.active_session
        self._thumb_gen += 1
        self.thumb_list.blockSignals(True)
        self.thumb_list.clear()
        if s:
            for i in range(s.pdf.page_count):
                item = QListWidgetItem(f"{i + 1}")
                pw, ph = s.pdf.page_size(i)
                item.setData(THUMB_ASPECT_ROLE, (ph / pw) if pw else 1.414)
                self.thumb_list.addItem(item)
            self.thumb_list.setCurrentRow(s.current_page)
        self.thumb_list.blockSignals(False)
        self._thumb_timer.start(0)

    def _load_visible_thumbs(self):
        s = self.active_session
        lw = self.thumb_list
        if not s or lw.count() == 0:
            return
        vr = lw.viewport().rect()
        first = lw.indexAt(vr.topLeft() + QPoint(8, 8)).row()
        last = lw.indexAt(vr.bottomLeft() + QPoint(8, -8)).row()
        first = max(0, first)
        last = min(lw.count() - 1, (last if last >= 0 else first + 8) + 4)
        gen = self._thumb_gen
        for i in range(first, last + 1):
            item = lw.item(i)
            if item is None or item.data(self._THUMB_LOADED):
                continue
            item.setData(self._THUMB_LOADED, True)
            task = s.pdf.make_render_task(i, False, 0.25 * self.devicePixelRatioF() * 1.2)
            self._thumb_tasks.append(task)

            def on_done(idx, qimg, _task=task, _gen=gen, _s=s):
                if _task in self._thumb_tasks:
                    self._thumb_tasks.remove(_task)
                if _gen != self._thumb_gen or _s is not self.active_session:
                    return
                it = self.thumb_list.item(idx)
                if it is not None:
                    it.setData(THUMB_ROLE, QPixmap.fromImage(qimg))

            def on_fail(_idx, _msg, _task=task):
                if _task in self._thumb_tasks:
                    self._thumb_tasks.remove(_task)

            task.signals.finished.connect(on_done)
            task.signals.failed.connect(on_fail)
            self.threadpool.start(task)

    def _build_toc(self):
        self.toc_tree.clear()
        s = self.active_session
        if not s:
            return
        toc = s.pdf.toc()
        if not toc:
            item = QTreeWidgetItem(["(İçindekiler yok)"])
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.toc_tree.addTopLevelItem(item)
            return
        stack: List[Tuple[int, QTreeWidgetItem]] = []
        for level, title, page in toc:
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, page)
            while stack and stack[-1][0] >= level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(item)
            else:
                self.toc_tree.addTopLevelItem(item)
            stack.append((level, item))
        self.toc_tree.expandAll()

    def _on_toc_item_clicked(self, item, _col):
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page:
            self.goto_page(int(page) - 1)

    def _on_thumb_selected(self, row):
        if row >= 0 and self.active_session and row != self.active_session.current_page:
            self.goto_page(row)

    def goto_page(self, index):
        s = self.active_session
        if not s:
            return
        index = max(0, min(index, s.pdf.page_count - 1))
        s.current_page = index
        self.view.show_page(s, index, invert=self.night_mode)
        self._after_page_change(index)

    def _on_view_page_changed(self, index):
        """Kullanıcı kaydırınca ya da başka bir sayfaya tıklayınca."""
        s = self.active_session
        if not s or not (0 <= index < s.pdf.page_count) or index == s.current_page:
            return
        s.current_page = index
        self._after_page_change(index)

    def _after_page_change(self, index):
        s = self.active_session
        self._update_page_label(index, s.pdf.page_count)
        if self.thumb_list.currentRow() != index:
            self.thumb_list.blockSignals(True)
            self.thumb_list.setCurrentRow(index)
            self.thumb_list.blockSignals(False)
            item = self.thumb_list.item(index)
            if item is not None:
                self.thumb_list.scrollToItem(item)
        self.refresh_layers_panel()
        self._update_search_highlight_for_page()
        if self.state.tool == "edit":
            self._scan_current_page_for_edit()

    def fit_width(self):
        if self.active_session:
            self.view.fit_width()

    def fit_page(self):
        if self.active_session:
            self.view.fit_page()

    def _sync_zoom_slider(self, zoom=None):
        self._zoom = self.view.zoom() if zoom is None else zoom
        pct = int(round(self._zoom * 100))
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(max(self.zoom_slider.minimum(), min(self.zoom_slider.maximum(), pct)))
        self.zoom_slider.blockSignals(False)
        self.lbl_zoom.setText(f"{pct}%")

    def _on_zoom_slider_changed(self, value):
        self._apply_zoom_percent(value)

    def _apply_zoom_percent(self, pct):
        self.view.set_zoom(pct / 100.0)

    # =====================================================================
    # Arama (Ctrl+F)
    # =====================================================================
    def _focus_search(self):
        if not self.active_session:
            return
        self.side.show_page("search")
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def run_search(self):
        s = self.active_session
        query = self.search_edit.text().strip()
        if not s or not query:
            return
        self.lbl_search_status.setText("Aranıyor…")
        self.search_results_list.clear()
        task = s.pdf.make_search_task(query)
        self._pending_search_tasks.append(task)

        def cleanup():
            if task in self._pending_search_tasks:
                self._pending_search_tasks.remove(task)

        def on_finished(result, _s=s):
            cleanup()
            if _s is not self.active_session:
                return
            self._apply_search_results(result)

        def on_failed(_msg):
            cleanup()
            self.lbl_search_status.setText("Arama başarısız oldu.")

        task.signals.finished.connect(on_finished)
        task.signals.failed.connect(on_failed)
        self.threadpool.start(task)

    def _apply_search_results(self, result: Dict[int, list]):
        self._search_results = result
        self._search_flat = []
        self.search_results_list.clear()
        for page in sorted(result.keys()):
            hits = result[page]
            for local_idx in range(len(hits)):
                self._search_flat.append((page, local_idx))
            item = QListWidgetItem(f"Sayfa {page + 1} — {len(hits)} eşleşme")
            item.setData(Qt.ItemDataRole.UserRole, page)
            self.search_results_list.addItem(item)
        total = len(self._search_flat)
        self.lbl_search_status.setText(f"{total} eşleşme bulundu." if total else "Eşleşme bulunamadı.")
        self._search_pos = -1
        self.view.set_all_search_highlights(result)
        if total:
            self.goto_next_search_hit()

    def _on_search_result_clicked(self, item):
        page = item.data(Qt.ItemDataRole.UserRole)
        if page is not None:
            page = int(page)
            if (page, 0) in self._search_flat:
                self._search_pos = self._search_flat.index((page, 0))
                self._show_search_hit()
            else:
                self.goto_page(page)

    def goto_next_search_hit(self):
        if not self._search_flat:
            return
        self._search_pos = (self._search_pos + 1) % len(self._search_flat)
        self._show_search_hit()

    def goto_prev_search_hit(self):
        if not self._search_flat:
            return
        self._search_pos = (self._search_pos - 1) % len(self._search_flat)
        self._show_search_hit()

    def _show_search_hit(self):
        page, local_idx = self._search_flat[self._search_pos]
        self.view.set_all_search_highlights(self._search_results, (page, local_idx), center=True)
        s = self.active_session
        if s and s.current_page != page:
            s.current_page = page
            self._after_page_change(page)
        self.lbl_search_status.setText(f"{self._search_pos + 1} / {len(self._search_flat)}")

    def _update_search_highlight_for_page(self):
        """Görünüm tüm sayfaların vurgularını kendisi tutar; belge yeniden
        kurulduğunda (sekme değişimi vb.) güncel sonuçları yeniden verir."""
        if not self.active_session:
            return
        active = None
        if self._search_flat and 0 <= self._search_pos < len(self._search_flat):
            active = self._search_flat[self._search_pos]
        self.view.set_all_search_highlights(self._search_results or {}, active)

    # =====================================================================
    # Annotation ekle / sil / taşı / boyutlandır (QUndoStack üzerinden)
    # =====================================================================
    def _on_session_change(self, session, page):
        """Tüm QUndoCommand'ların ortak geri çağrısı: ilgili görünümleri
        tazeler (ana sayfa + karşılaştırma panelleri + katmanlar)."""
        for pane in (self.pane_left, self.pane_right):
            if pane.session is session and pane.page == page:
                pane._render()
        if self.active_session is session:
            self.view.refresh_page(page)
            if page == session.current_page:
                self.refresh_layers_panel()
            else:
                self.refresh_comments_panel()
