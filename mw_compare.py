"""
mw_compare.py
=============
Metin farkı / karşılaştırma modu yöntemleri.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations

import os



import textdiff
from ui.ocrdialog import _OcrTask


class CompareMixin:
    # =====================================================================
    # Karşılaştırma modu
    # =====================================================================
    def toggle_compare_mode(self, checked):
        self.canvas_stack.setCurrentIndex(1 if checked else 0)
        for key, b in self._tool_buttons:
            if checked:
                b.setEnabled(key == "number")
            else:
                b.setEnabled(self.active_session is not None)
        if checked:
            if self.state.tool != "number":
                self._select_tool("number", dict(self._tool_buttons)["number"])
            self.pane_left.refresh_sessions()
            self.pane_right.refresh_sessions()
            if len(self.sessions) > 1 and self.pane_right.combo.count() > 1:
                self.pane_right.combo.setCurrentIndex(1)
            self._schedule_diff()
        else:
            self._select_tool("select", self.btn_select)
            self._cancel_diff()
        self._update_prop_bar()
        self._place_floating()

    # -- metin farkı (iki sürüm) ---------------------------------------------
    def compare_documents(self):
        """Karşılaştırma modunu açar ve sol/sağ belgelerin metin farkını çıkarır."""
        if not self.act_compare.isChecked():
            self.act_compare.setChecked(True)
            self.toggle_compare_mode(True)
        self._run_diff()

    def _schedule_diff(self):
        if not self.act_compare.isChecked():
            return
        self._cancel_diff()
        self._diff_timer.start()

    def _cancel_diff(self):
        self._diff_timer.stop()
        self._diff_token += 1
        if self._diff_task is not None:
            self._diff_task.cancel()
            self._diff_task = None
        self._diff = None
        self.pane_left.set_marks({})
        self.pane_right.set_marks({})

    def _run_diff(self):
        self._cancel_diff()
        sa, sb = self.pane_left.session, self.pane_right.session
        if sa is None or sb is None or sa is sb:
            self.diff_panel.set_message("Metin farkı için sol ve sağ panelde iki FARKLI belge seçin "
                                        "(örn. eski ve yeni sürüm).")
            return
        token = self._diff_token
        ignore_case = self.diff_panel.ignore_case
        self.diff_panel.set_busy()

        def job(progress, cancelled):
            return textdiff.compare(sa.pdf, sb.pdf, ignore_case=ignore_case, check=cancelled,
                                    progress=progress)

        task = _OcrTask(job)
        task.signals.progress.connect(lambda d, t: token == self._diff_token
                                      and self.diff_panel.set_busy(d, t))
        task.signals.done.connect(lambda res: self._on_diff_done(token, res))
        task.signals.failed.connect(lambda msg: token == self._diff_token and
                                    self.diff_panel.set_message(f"Karşılaştırma yapılamadı: {msg}"))
        self._diff_task = task
        self.threadpool.start(task)

    def _on_diff_done(self, token: int, res):
        if token != self._diff_token or res.cancelled:
            return
        self._diff_task = None
        self._diff = res
        sa, sb = self.pane_left.session, self.pane_right.session
        self.diff_panel.set_names(*(os.path.basename(x.path) if x is not None and x.path else "" for x in (sa, sb)))
        self.diff_panel.show_result(res)
        self._apply_diff_marks()

    def _apply_diff_marks(self):
        if self._diff is None or self._diff.error:
            return
        left: dict = {}
        right: dict = {}
        for c in self.diff_panel.visible_changes():
            for page, r in c.a_rects:
                left.setdefault(page, []).append((*r, "del"))
            for page, r in c.b_rects:
                right.setdefault(page, []).append((*r, "add"))
        self.pane_left.set_marks(left)
        self.pane_right.set_marks(right)

    def _goto_change(self, c):
        fa, fb = c.focus_a(), c.focus_b()
        if fa:
            self.pane_left.goto(fa[0], fa[1])
        if fb:
            self.pane_right.goto(fb[0], fb[1])
