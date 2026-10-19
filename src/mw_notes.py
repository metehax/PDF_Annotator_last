"""
mw_notes.py
===========
Yapışkan notlar ve Yorumlar paneli.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations

import os


from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog, QMessageBox

from models import AddAnnotationCommand, NoteAnnotation, NoteStateCommand
from ui.comments import ask_note_text


class NotesMixin:
    # =====================================================================
    # Yapışkan notlar ve Yorumlar paneli
    # =====================================================================
    def _show_comments_panel(self):
        self.side.show_page("comments")

    def refresh_comments_panel(self):
        if not hasattr(self, "comments"):
            return
        s = self.active_session
        notes = []
        if s:
            for pidx in sorted(s.annotations):
                notes += [(pidx, a) for a in s.annotations[pidx] if isinstance(a, NoteAnnotation)]
        self.comments.set_notes(notes)

    def _note_page(self, ann):
        s = self.active_session
        if s:
            for pidx, lst in s.annotations.items():
                if ann in lst:
                    return pidx
        return None

    def on_note_requested(self, pt: QPointF):
        s = self.active_session
        if not s:
            return
        text = ask_note_text(self, "Yeni not", "")
        if text is None or not text.strip():
            return
        pw, ph = s.pdf.page_size(s.current_page)
        x = min(max(0.0, pt.x()), max(0.0, pw - NoteAnnotation.SIZE))
        y = min(max(0.0, pt.y()), max(0.0, ph - NoteAnnotation.SIZE))
        ann = NoteAnnotation(x, y, text.strip(), QColor(self.state.note_color))
        s.undo_stack.push(AddAnnotationCommand(s, s.current_page, ann,
                                               on_change=self._on_session_change, label="Not Ekle"))
        self.status.setText("Not eklendi. Çift tıklayarak düzenleyebilir, Yorumlar panelinden yanıtlayabilirsiniz.")

    def _push_note_state(self, ann, new_state, label):
        s = self.active_session
        page = self._note_page(ann)
        if not s or page is None:
            return
        s.undo_stack.push(NoteStateCommand(s, page, ann, new_state,
                                           on_change=self._on_session_change, label=label))

    def edit_note(self, ann):
        text = ask_note_text(self, "Notu düzenle", ann.text)
        if text is None or not text.strip() or text.strip() == ann.text:
            return
        st = ann.snapshot()
        st["text"] = text.strip()
        self._push_note_state(ann, st, "Notu Düzenle")

    def reply_note(self, ann):
        text = ask_note_text(self, "Yanıtla", "", prompt=f"{ann.author} notuna yanıt")
        if text is None or not text.strip():
            return
        from models import default_author, _now_iso
        st = ann.snapshot()
        st["replies"].append(dict(author=default_author(), created=_now_iso(), text=text.strip()))
        self._push_note_state(ann, st, "Yanıt Ekle")

    def toggle_note_done(self, ann):
        st = ann.snapshot()
        st["done"] = not ann.done
        self._push_note_state(ann, st, "Çözüldü" if st["done"] else "Yeniden Aç")

    def _on_comment_goto(self, page, ann):
        self.goto_page(page)
        for gitem, a in self.view.item_ann_map.items():
            gitem.setSelected(a is ann)
            if a is ann:
                self.view.centerOn(gitem)

    def export_comments(self):
        s = self.active_session
        if not s:
            return
        notes = []
        for pidx in sorted(s.annotations):
            notes += [(pidx, a) for a in s.annotations[pidx] if isinstance(a, NoteAnnotation)]
        if not notes:
            return
        default = os.path.splitext(s.path)[0] + "_yorumlar.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Yorumları Kaydet", default, "Metin (*.txt)")
        if not path:
            return
        lines = [f"Yorumlar — {s.title}", ""]
        for pidx, n in notes:
            lines.append(f"[Sayfa {pidx + 1}] {n.author} · {n.created}{' · ÇÖZÜLDÜ' if n.done else ''}")
            lines.append(n.text)
            for r in n.replies:
                lines.append(f"    > {r.get('author', '')} · {r.get('created', '')}: {r.get('text', '')}")
            lines.append("")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self._toast_saved("Yorumlar kaydedildi", path)
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kaydedilemedi:\n{ex}")
