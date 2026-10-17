"""
mw_forms.py
===========
AcroForm alanları: doldurma, düzenleme, oluşturma, sıfırlama, hesaplama.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations



from PySide6.QtCore import QPointF, QRectF, QTimer
from PySide6.QtWidgets import QDialog

from models import FormFieldCommand, FormValuesCommand
import forms
from ui.formui import FormFieldDialog, FormFieldEditor


class FormsMixin:
    # -- PDF formları ---------------------------------------------------------
    def _refresh_forms(self):
        """Alan listesini belgeden yeniden okur; paneli ve vurguları tazeler."""
        s = self.active_session
        fields = []
        if s is not None:
            with s.pdf.lock:
                fields = forms.list_fields(s.pdf.doc)
        self._form_fields = fields
        if hasattr(self, "forms_panel"):
            self.forms_panel.set_fields(fields)
        self._refresh_form_overlay()

    def _refresh_form_overlay(self):
        on = not hasattr(self, "forms_panel") or self.forms_panel.chk_highlight.isChecked()
        by_page = {}
        if on:
            for f in getattr(self, "_form_fields", []):
                r = f.rect
                by_page.setdefault(f.page, []).append(QRectF(r.x0, r.y0, r.width, r.height))
        self.view.set_form_overlay(by_page)

    def _form_hit(self, page, x, y):
        return forms.field_at(getattr(self, "_form_fields", []), page, x, y) is not None

    def _forms_changed(self, pages):
        s = self.active_session
        if not s:
            return
        for p in pages:
            if 0 <= p < s.pdf.page_count:
                s.pdf._invalidate_page(p)
        self._refresh_forms()
        for p in pages:
            if 0 <= p < s.pdf.page_count:
                self.view.refresh_page(p)

    def _push_form_values(self, values, label="Form Doldur"):
        s = self.active_session
        if not s:
            return
        s.undo_stack.push(FormValuesCommand(s, values, on_done=self._forms_changed, label=label))

    def on_form_field_clicked(self, page, pt):
        f = forms.field_at(self._form_fields, page, pt.x(), pt.y())
        if f is None:
            return
        if f.kind == "checkbox":
            self._push_form_values({f.name: "Off" if f.checked else f.on_state})
        elif f.kind == "radio":
            if not f.checked:
                self._push_form_values({f.name: f.on_state})
        elif f.kind == "calc":
            self.toasts.show(f"'{f.name}' hesaplanan bir alan: {f.value or 'boş'} "
                             f"({dict(forms.CALC_OPS).get(f.calc_op, '')}: {', '.join(f.calc_sources)})")
        elif f.kind == "signature":
            self.toasts.show(f"'{f.name}' bir imza alanı: Araçlar › Dijital imza ile imzalayın.")
        elif f.kind == "other" or f.readonly:
            self.toasts.show(f"'{f.name}' alanı bu uygulamada düzenlenemez.")
        else:
            self._open_form_editor(f)

    def _open_form_editor(self, f):
        self._finish_form_editor()
        prect = self.view.page_rect_in_scene(f.page)
        scene_r = QRectF(prect.x() + f.rect.x0, prect.y() + f.rect.y0, f.rect.width, f.rect.height)
        vr = self.view.mapFromScene(scene_r).boundingRect()
        ed = FormFieldEditor(f, self.view.viewport())
        ed.place(vr)
        ed.committed.connect(self._on_form_editor_commit)
        ed.cancelled.connect(self._close_form_editor)
        self._form_editor = ed
        ed.start()

    def _close_form_editor(self):
        ed = getattr(self, "_form_editor", None)
        self._form_editor = None
        if ed is not None:
            ed.hide()
            ed.deleteLater()

    def _finish_form_editor(self):
        ed = getattr(self, "_form_editor", None)
        if ed is not None:
            ed.finish()

    def _center_on_field(self, f):
        self.view.centerOn(self.view.page_rect_in_scene(f.page).topLeft()
                           + QPointF(f.rect.x0 + f.rect.width / 2, f.rect.y0))

    def _on_form_editor_commit(self, f, value, nav):
        self._close_form_editor()
        if value != f.value:
            self._push_form_values({f.name: value})
        if not nav:
            return
        order = [x for x in self._form_fields if x.kind in ("text", "date", "combo") and not x.readonly]
        if not order:
            return
        keys = [(x.page, x.nm) for x in order]
        i = keys.index((f.page, f.nm)) if (f.page, f.nm) in keys else -1
        nxt = order[(i + nav) % len(order)]
        self._goto_form_field(nxt)

    def _goto_form_field(self, f):
        if f.page != self.active_session.current_page:
            self.goto_page(f.page)
        self._center_on_field(f)
        if f.kind in ("text", "date", "combo") and not f.readonly:
            QTimer.singleShot(0, lambda: self._open_form_editor(f))

    def _on_form_goto(self, f):
        if self.state.tool != "select":
            self._tool_shortcut("select")
        self._goto_form_field(f)

    def ask_form_field(self, spec, creating=True):
        """Özellik penceresi; test betikleri bu yöntemi değiştirebilir. spec | None döner."""
        others = [f for f in self._form_fields if f.nm != spec.get("nm")]
        names = []
        for f in others:
            if f.name not in names:
                names.append(f.name)
        groups = sorted({f.name for f in others if f.kind == "radio"})
        dlg = FormFieldDialog(spec, names, groups, self, creating=creating)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return dlg.result_spec()

    def on_form_field_requested(self, page, rect):
        s = self.active_session
        if not s:
            return
        kind = self.state.form_kind
        if rect.width() < 6 or rect.height() < 6:
            w, h = forms.DEFAULT_SIZE[kind]
            rect = QRectF(rect.x(), rect.y(), w, h)
        with s.pdf.lock:
            doc = s.pdf.doc
            if kind == "radio":
                group = getattr(self, "_last_radio_group", None)
                groups = {f.name for f in self._form_fields if f.kind == "radio"}
                name = group if group in groups else forms.unique_name(doc, forms.KIND_BASE[kind])
                n = sum(1 for f in self._form_fields if f.name == name) + 1
                spec = {"name": name, "on_state": f"Secenek{n}"}
            else:
                spec = {"name": forms.unique_name(doc, forms.KIND_BASE[kind])}
        spec.update(kind=kind, rect=(rect.left(), rect.top(), rect.right(), rect.bottom()),
                    value="", font_size=10)
        if kind == "combo":
            spec["options"] = ["Seçenek 1", "Seçenek 2"]
        if kind == "date":
            spec["date_fmt"] = forms.DATE_FORMATS[0]
        if kind == "calc":
            spec.update(calc_op="SUM", calc_sources=[])
        if self.state.form_ask or kind == "calc":
            spec = self.ask_form_field(spec, creating=True)
            if spec is None:
                return
        if kind == "radio":
            self._last_radio_group = spec["name"]
        s.undo_stack.push(FormFieldCommand(s, page, None, spec, on_done=self._forms_changed,
                                           label=f"{forms.KIND_NAMES[kind]} ekle"))
        self.toasts.show(f"'{spec['name']}' alanı eklendi. Doldurmak için Seç aracıyla tıklayın.")

    def edit_form_field(self, f):
        s = self.active_session
        if not s or f is None:
            return
        if f.kind == "other":
            self.toasts.show("Bu alan türünün özellikleri düzenlenemez.")
            return
        with s.pdf.lock:
            old = forms.field_spec(s.pdf.doc, f.page, f.nm)
        if old is None:
            return
        if old["kind"] == "radio":
            old["value"] = old["on_state"] if f.checked else "Off"
        new = self.ask_form_field(dict(old), creating=False)
        if new is None or new == old:
            return
        if f.kind == "radio" and new["on_state"] != old["on_state"]:
            new["value"] = "Off"
        if new["name"] != old["name"]:
            users = [c.name for c in self._form_fields if c.kind == "calc" and old["name"] in c.calc_sources]
            if users:
                self.toasts.show(f"Not: {', '.join(users)} formülü eski adı ({old['name']}) kullanıyor; "
                                 "özelliklerinden kaynakları güncelleyin.")
        s.undo_stack.push(FormFieldCommand(s, f.page, old, new, on_done=self._forms_changed,
                                           label="Form alanını değiştir"))

    def delete_form_field(self, f):
        s = self.active_session
        if not s or f is None:
            return
        with s.pdf.lock:
            old = forms.field_spec(s.pdf.doc, f.page, f.nm)
        if old is None:
            return
        if old["kind"] == "radio":
            old["value"] = old["on_state"] if f.checked else "Off"
        s.undo_stack.push(FormFieldCommand(s, f.page, old, None, on_done=self._forms_changed,
                                           label="Form alanını sil"))
        self.toasts.show(f"'{f.name}' alanı silindi (Ctrl+Z ile geri alınır).")

    def reset_form(self):
        s = self.active_session
        if not s:
            return
        if not self._form_fields:
            self.toasts.show("Bu belgede form alanı yok.")
            return
        s.undo_stack.push(FormValuesCommand(s, reset=True, on_done=self._forms_changed,
                                            label="Formu Sıfırla"))
        self.toasts.show("Form sıfırlandı (Ctrl+Z ile geri alınır).")

    def recalculate_form(self):
        s = self.active_session
        if not s:
            return
        with s.pdf.lock:
            pages = forms.recalculate(s.pdf.doc)
        if pages:
            self._mark_dirty()
            self._forms_changed(pages)
        self.toasts.show("Hesaplanan alanlar güncel.")
