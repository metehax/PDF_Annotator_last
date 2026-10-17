"""
mw_annot.py
===========
İşaret oluşturma/silme/yerleştirme, numaralandırma, kırpma kutusu, katmanlar paneli.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
"""

from __future__ import annotations


import uuid

import pymupdf as fitz

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidgetItem, QMenu, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from models import (
    Annotation, AddAnnotationCommand, BlurAnnotation, HighlightAnnotation, ImageAnnotation, InkAnnotation,
    LineAnnotation, MoveAnnotationCommand, NoteAnnotation, NumberAnnotation, RedactionAnnotation,
    RemoveAnnotationCommand, ResizeAnnotationCommand, ShapeAnnotation, TextAnnotation,
    ZOrderCommand, number_to_color,
)
from pdf_engine import load_image_bytes_from_path, qimage_to_png_bytes
from ui.icons import icon, pixmap as icon_pixmap
from ui.textdialog import TextDialog


class AnnotMixin:
    def add_annotation(self, ann):
        s = self.active_session
        if not s:
            return
        cmd = AddAnnotationCommand(s, s.current_page, ann, on_change=self._on_session_change,
                                    label="İşaret Ekle")
        s.undo_stack.push(cmd)
        self.status.setText("İşaret eklendi.")

    def on_text_requested(self, rect: QRectF):
        dlg = TextDialog(self.state.font_family, self.state.font_size,
                         self.state.text_color, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text, family, size, color = dlg.result_values()
        if not text.strip():
            return
        # Son seçimler bir sonraki metin için hatırlanır.
        self.state.font_family = family
        self.state.font_size = size
        self.state.text_color = color
        if hasattr(self, "font_combo_panel"):
            self.font_combo_panel.setCurrentText(family)
        for btn in self._color_buttons_by_attr.get("text_color", []):
            btn.setStyleSheet(f"background:{color.name()};")
        # Kutu yüksekliği seçilen puntoya göre ayarlanır (satır sayısı kadar).
        lines = max(1, text.count("\n") + 1)
        rect = QRectF(rect.x(), rect.y(), rect.width(), max(rect.height(), size * 1.4 * lines))
        self.add_annotation(TextAnnotation(rect, text, color, size, family))

    def on_number_requested(self, scene_pt: QPointF):
        s = self.active_session
        if not s:
            return
        if s.number_counter is None:
            s.number_counter = int(self.state.number_start)
        n = s.number_counter
        color = number_to_color(n) if self.state.number_multicolor else self.state.number_color
        ann = NumberAnnotation(scene_pt.x(), scene_pt.y(), n, color, self.state.number_size)

        def setter(v, _s=s):
            _s.number_counter = v
            self._refresh_number_label()

        cmd = AddAnnotationCommand(s, s.current_page, ann, on_change=self._on_session_change,
                                    counter_before=n, counter_after=n + 1, counter_setter=setter,
                                    label=f"Numara {n}")
        s.undo_stack.push(cmd)
        self.status.setText(f"Numara {n} yerleştirildi.")

    def on_number_requested_in_pane(self, pane, scene_pt: QPointF):
        session = pane.session
        if session is None:
            return
        page = pane.page
        self.undo_group.setActiveStack(session.undo_stack)

        if not self.state.number_pair_mode:
            if session.number_counter is None:
                session.number_counter = int(self.state.number_start)
            n = session.number_counter
            color = number_to_color(n) if self.state.number_multicolor else self.state.number_color
            ann = NumberAnnotation(scene_pt.x(), scene_pt.y(), n, color, self.state.number_size)

            def setter(v, _s=session):
                _s.number_counter = v
                self._refresh_number_label()

            cmd = AddAnnotationCommand(session, page, ann, on_change=self._on_session_change,
                                        counter_before=n, counter_after=n + 1, counter_setter=setter,
                                        label=f"Numara {n}")
            session.undo_stack.push(cmd)
            self.status.setText(f"Numara {n} yerleştirildi.")
            return

        # --- Eşleştir modu ---
        pend = self._pair_pending
        if pend is None:
            n = self._pair_counter
            color = number_to_color(n) if self.state.number_multicolor else self.state.number_color
            ann = NumberAnnotation(scene_pt.x(), scene_pt.y(), n, color, self.state.number_size)

            def setter(v):
                self._pair_pending = v
                self._refresh_number_label()

            cmd = AddAnnotationCommand(session, page, ann, on_change=self._on_session_change,
                                        counter_before=None, counter_after=(pane, n, color),
                                        counter_setter=setter, label=f"Eşleştirme {n} (1/2)")
            session.undo_stack.push(cmd)
            self.status.setText(f"Eşleştirme: {n} numarası kondu, aynısını diğer panele koyun.")
        else:
            first_pane, n, color = pend
            if pane is first_pane:
                self.status.setText("Önce DİĞER panele aynı numarayı koyun (ya da Eşleştir'i kapatın).")
                return
            ann = NumberAnnotation(scene_pt.x(), scene_pt.y(), n, color, self.state.number_size)

            def setter(v, _fp=first_pane, _n=n, _c=color):
                if v[0] == "redo2":
                    self._pair_counter = _n + 1
                    self._pair_pending = None
                else:
                    self._pair_counter = _n
                    self._pair_pending = (_fp, _n, _c)
                self._refresh_number_label()

            cmd = AddAnnotationCommand(session, page, ann, on_change=self._on_session_change,
                                        counter_before=("undo2",), counter_after=("redo2",),
                                        counter_setter=setter, label=f"Eşleştirme {n} (2/2)")
            session.undo_stack.push(cmd)
            self.status.setText(f"{n} numaralı çift tamamlandı. Sıradaki: {self._pair_counter}")

    def reset_pair_counter(self):
        self._pair_counter = int(self.state.number_start)
        self._pair_pending = None
        self._refresh_number_label()
        self.status.setText(f"Eşleştirme sayacı sıfırlandı. Sıradaki: {self._pair_counter}")

    def _on_number_start_changed(self, v):
        self.state.number_start = v
        self._refresh_number_label()

    def _on_pair_toggled(self, checked):
        self.state.number_pair_mode = checked
        self._pair_pending = None
        if checked:
            self._pair_counter = int(self.state.number_start)
        self._refresh_number_label()

    def reset_number_counter(self):
        if self.active_session:
            self.active_session.number_counter = int(self.state.number_start)
            self._refresh_number_label()

    def _refresh_number_label(self):
        if not hasattr(self, "lbl_next_number"):
            return
        if self.state.number_pair_mode:
            self.lbl_next_number.setText(f"Sıradaki (eşleştirme): {self._pair_counter}")
            return
        s = self.active_session
        if s is None:
            self.lbl_next_number.setText("Sıradaki: —")
            return
        n = s.number_counter if s.number_counter is not None else int(self.state.number_start)
        self.lbl_next_number.setText(f"Sıradaki: {n}")

    # -- kırpma ------------------------------------------------------------
    def on_crop_requested(self, rect: QRectF):
        s = self.active_session
        if not s:
            return
        try:
            clip = fitz.Rect(rect.left(), rect.top(), rect.right(), rect.bottom())
            with s.pdf.lock:
                page = s.pdf.doc[s.current_page]
                pix = page.get_pixmap(matrix=fitz.Matrix(4.0, 4.0), clip=clip, alpha=False)
                qimg = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format.Format_RGB888).copy()
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"Kırpılamadı:\n{ex}")
            return
        self._show_crop_dialog(qimg, rect)

    def _show_crop_dialog(self, qimage: QImage, rect: QRectF = None):
        dlg = QDialog(self)
        dlg.setWindowTitle("Kırpılan Alan")
        v = QVBoxLayout(dlg)
        pm = QPixmap.fromImage(qimage)
        preview = QLabel()
        max_w = 480
        preview.setPixmap(pm.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
                          if pm.width() > max_w else pm)
        v.addWidget(preview)
        info = QLabel(f"{pm.width()} × {pm.height()} piksel")
        info.setObjectName("hint")
        v.addWidget(info)
        row = QHBoxLayout()
        btn_copy = QPushButton(icon("clipboard"), "Panoya Kopyala")
        btn_copy.setObjectName("secondary")
        btn_save = QPushButton(icon("save", "on_accent"), "PNG Olarak Kaydet")
        btn_save.setObjectName("primary")
        btn_close = QPushButton("Kapat")
        row.addWidget(btn_copy); row.addWidget(btn_save); row.addWidget(btn_close)
        v.addLayout(row)
        if rect is not None:
            btn_page = QPushButton(icon("crop"), "Sayfayı bu alana kırp")
            btn_page.setObjectName("secondary")
            btn_page.setToolTip("Sayfanın görünen alanını bu bölgeyle sınırlar (Ctrl+Z ile geri alınır)")

            def do_page_crop():
                dlg.accept()
                self._apply_crops({self.active_session.current_page:
                                   fitz.Rect(rect.left(), rect.top(), rect.right(), rect.bottom())})

            btn_page.clicked.connect(do_page_crop)
            v.addWidget(btn_page)

        def do_copy():
            QApplication.clipboard().setImage(qimage)
            self.status.setText("Kırpılan alan panoya kopyalandı.")

        def do_save():
            path, _ = QFileDialog.getSaveFileName(self, "Kırpılan Alanı Kaydet", "kirpma.png", "PNG (*.png)")
            if path:
                if not path.lower().endswith(".png"):
                    path += ".png"
                qimage.save(path)
                self.status.setText(f"Kaydedildi: {path}")

        btn_copy.clicked.connect(do_copy)
        btn_save.clicked.connect(do_save)
        btn_close.clicked.connect(dlg.accept)
        dlg.exec()

    # -- resim ekleme --------------------------------------------------------
    def on_image_place_requested(self, rect: QRectF):
        s = self.active_session
        if not s:
            return
        menu = QMenu(self)
        act_file = menu.addAction(icon("folder"), "Dosyadan Seç…")
        act_clip = menu.addAction(icon("clipboard"), "Panodan Yapıştır")
        chosen = menu.exec(self.view.mapToGlobal(self.view.rect().center()))
        image_bytes = None
        if chosen == act_file:
            path, _ = QFileDialog.getOpenFileName(self, "Resim Seç", "",
                                                  "Görseller (*.png *.jpg *.jpeg *.bmp *.svg)")
            if not path:
                return
            try:
                image_bytes = load_image_bytes_from_path(path)
            except Exception as ex:
                QMessageBox.critical(self, "Hata", f"Görsel yüklenemedi:\n{ex}")
                return
        elif chosen == act_clip:
            img = QApplication.clipboard().image()
            if img.isNull():
                self.toasts.show("Panoda bir görsel bulunamadı.", "warning")
                return
            image_bytes = qimage_to_png_bytes(img)
        else:
            return

        qimg = QImage()
        qimg.loadFromData(image_bytes)
        if self.state.image_keep_aspect and qimg.width() and qimg.height():
            ar = qimg.height() / qimg.width()
            rect = QRectF(rect.left(), rect.top(), rect.width(), rect.width() * ar)

        ann = ImageAnnotation(rect, image_bytes, opacity=self.state.image_opacity,
                              keep_aspect=self.state.image_keep_aspect)
        self.add_annotation(ann)

    # -- yeniden boyutlandırma -----------------------------------------------
    def on_resize_requested(self, ann, old_rect: QRectF, new_rect: QRectF):
        s = self.active_session
        if not s:
            return
        page = self.view.page_of_annotation(ann)
        cmd = ResizeAnnotationCommand(s, s.current_page if page is None else page, ann, old_rect, new_rect,
                                      on_change=self._on_session_change)
        s.undo_stack.push(cmd)

    # -- taşıma ------------------------------------------------------------
    def sync_moved_items(self):
        s = self.active_session
        if not s:
            return
        moved_any = False
        for gitem, ann in list(self.view.item_ann_map.items()):
            pos = gitem.pos()
            if pos.x() != 0 or pos.y() != 0:
                dx, dy = pos.x(), pos.y()
                page = self.view.page_of_item(gitem)
                cmd = MoveAnnotationCommand(s, s.current_page if page is None else page, ann, dx, dy,
                                            on_change=self._on_session_change)
                s.undo_stack.push(cmd)
                moved_any = True
        if moved_any:
            self.status.setText("Öge taşındı.")

    # -- silme / katman sırası ------------------------------------------------
    def _delete_item(self, gitem):
        s = self.active_session
        ann = self.view.item_ann_map.get(gitem)
        if not s or ann is None:
            return
        page = self.view.page_of_item(gitem)
        cmd = RemoveAnnotationCommand(s, s.current_page if page is None else page, ann,
                                      on_change=self._on_session_change)
        s.undo_stack.push(cmd)
        self.status.setText("Öge silindi.")

    # -- kopyala / kes / yapıştır / tümünü seç ----------------------------------------
    def _selected_pairs(self):
        """Seçili işaretler: [(sayfa, işaret)] (yönlendirme tutamacı hariç)."""
        out = []
        for gitem in self.view.scene_obj.selectedItems():
            if gitem is self.view.gizmo:
                continue
            ann = self.view.item_ann_map.get(gitem)
            if ann is not None:
                page = self.view.page_of_item(gitem)
                out.append((self.active_session.current_page if page is None else page, ann))
        return out

    def copy_selected(self) -> int:
        """Seçili işaretleri iç panoya kopyalar (Ctrl+C); kopyalanan sayıyı döndürür."""
        if not self.active_session:
            return 0
        pairs = self._selected_pairs()
        self._ann_clipboard = [ann.to_dict() for _, ann in pairs]
        self._paste_count = 0
        if pairs:
            self.status.setText(f"{len(pairs)} işaret kopyalandı (Ctrl+V ile yapıştırın).")
        return len(pairs)

    def cut_selected(self) -> int:
        n = self.copy_selected()
        if n:
            self.delete_selected()
        return n

    def paste_annotations(self) -> int:
        """Panodaki işaretleri geçerli sayfaya yapıştırır (her yapıştırmada biraz kayık); tek adımda geri alınır."""
        s = self.active_session
        clip = getattr(self, "_ann_clipboard", None)
        if not s or not clip:
            return 0
        self._paste_count = getattr(self, "_paste_count", 0) + 1
        off = 14.0 * self._paste_count
        s.undo_stack.beginMacro(f"{len(clip)} işareti yapıştır")
        for d in clip:
            new = Annotation.from_dict(dict(d))
            new.uid = uuid.uuid4().hex
            new.translate(off, off)
            s.undo_stack.push(AddAnnotationCommand(s, s.current_page, new, on_change=self._on_session_change,
                                                   label="İşaret Yapıştır"))
        s.undo_stack.endMacro()
        self.status.setText(f"{len(clip)} işaret yapıştırıldı.")
        return len(clip)

    def select_all_annotations(self) -> int:
        """Geçerli sayfadaki tüm işaretleri seçer (Ctrl+A)."""
        s = self.active_session
        if not s:
            return 0
        n = 0
        for gitem, ann in list(self.view.item_ann_map.items()):
            if self.view.page_of_item(gitem) == s.current_page:
                gitem.setSelected(True)
                n += 1
        return n

    def delete_selected(self):
        """Seçili işaretleri siler. Önce işaretler toplanır: ilk silme sayfayı yeniden çizip sahne öğelerini yenilediği için
        öğe öğe silmek yalnız ilkini silerdi. Tek geri alma adımıdır."""
        s = self.active_session
        pairs = self._selected_pairs() if s else []
        if not pairs:
            return
        s.undo_stack.beginMacro(f"{len(pairs)} işareti sil")
        for page, ann in pairs:
            s.undo_stack.push(RemoveAnnotationCommand(s, page, ann, on_change=self._on_session_change))
        s.undo_stack.endMacro()
        self.status.setText("Öge silindi." if len(pairs) == 1 else f"{len(pairs)} öge silindi.")

    def show_item_context_menu(self, gitem, global_pos):
        if gitem is None or gitem not in self.view.item_ann_map:
            # işaret değil: sayfanın kendisine sağ tıklandı
            if self.active_session and self.canvas_stack.currentIndex() == 0:
                self._page_menu(self.active_session.current_page, global_pos)
            return
        menu = QMenu(self)
        act_front = menu.addAction(icon("bring_front"), "En Öne Getir")
        act_back = menu.addAction(icon("send_back"), "En Arkaya Gönder")
        menu.addSeparator()
        act_del = menu.addAction(icon("trash", "danger"), "Sil")
        chosen = menu.exec(global_pos)
        s = self.active_session
        ann = self.view.item_ann_map.get(gitem)
        if chosen == act_del:
            self._delete_item(gitem)
        page = self.view.page_of_item(gitem)
        if page is None and s:
            page = s.current_page
        if chosen == act_front and s and ann:
            s.undo_stack.push(ZOrderCommand(s, page, ann, True, on_change=self._on_session_change))
        elif chosen == act_back and s and ann:
            s.undo_stack.push(ZOrderCommand(s, page, ann, False, on_change=self._on_session_change))

    # =====================================================================
    # Katmanlar paneli
    # =====================================================================
    def _ann_label(self, ann):
        """(ikon adı, etiket)"""
        if isinstance(ann, TextAnnotation):
            return "text", ann.text.replace(chr(10), " ")[:24] or "Metin"
        if isinstance(ann, InkAnnotation):
            return "ink", "Kalem çizimi"
        if isinstance(ann, LineAnnotation):
            return "line", "Çizgi / Ok"
        if isinstance(ann, ShapeAnnotation):
            return ("rect", "Dörtgen") if ann.kind == "rect" else ("oval", "Oval")
        if isinstance(ann, HighlightAnnotation):
            return "highlight", "Fosforlu"
        if isinstance(ann, RedactionAnnotation):
            return ("edit_text", "Silinen orijinal metin") if getattr(ann, "quiet", False) \
                else ("redact", "Sansür (kalıcı)")
        if isinstance(ann, BlurAnnotation):
            return "blur", "Bulanıklaştırma" if ann.mode == "blur" else "Mozaik"
        if isinstance(ann, NoteAnnotation):
            return "note", "Not: " + (ann.text.replace(chr(10), " ")[:20] or "(boş)")
        if isinstance(ann, NumberAnnotation):
            return "number", f"Numara {ann.number}"
        if isinstance(ann, ImageAnnotation):
            src = ann.source_path or ""
            if src.startswith("stamp:"):
                return "stamp", f"Damga: {src[6:]}"
            if src.startswith("sign:"):
                return "sign", "İmza"
            return "image", "Resim"
        return "layers", "Öge"

    def refresh_layers_panel(self):
        self.refresh_comments_panel()
        if not hasattr(self, "layers_list"):
            return
        self.layers_list.clear()
        s = self.active_session
        anns = s.annotations.get(s.current_page, []) if s else []
        for ann in anns:
            list_item = QListWidgetItem()
            row = QWidget()
            row.setObjectName("layerRow")
            h = QHBoxLayout(row)
            h.setContentsMargins(8, 2, 2, 2)
            h.setSpacing(8)
            icon_name, text = self._ann_label(ann)
            ico = QLabel()
            ico.setPixmap(icon_pixmap(icon_name, 16, scale=self.devicePixelRatioF()))
            h.addWidget(ico)
            lbl = QLabel(text)
            lbl.setObjectName("layerLabel")
            h.addWidget(lbl, 1)
            btn = self._icon_button("trash", "Sil", lambda _=False, a=ann: self._delete_annotation_by_ref(a))
            btn.setIcon(icon("trash", "danger"))
            btn.setIconSize(QSize(16, 16))
            h.addWidget(btn)
            list_item.setData(Qt.ItemDataRole.UserRole, ann)
            list_item.setSizeHint(row.sizeHint())
            self.layers_list.addItem(list_item)
            self.layers_list.setItemWidget(list_item, row)
        if not anns:
            empty = QListWidgetItem("Bu sayfada henüz işaret yok.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.layers_list.addItem(empty)

    def _on_layer_clicked(self, list_item):
        ann = list_item.data(Qt.ItemDataRole.UserRole)
        if ann is None:
            return
        for gitem, a in self.view.item_ann_map.items():
            gitem.setSelected(a is ann)
            if a is ann:
                self.view.centerOn(gitem)

    def _delete_annotation_by_ref(self, ann, page=None):
        gitem = None
        for k, v in self.view.item_ann_map.items():
            if v is ann:
                gitem = k
                break
        if gitem is not None:
            self._delete_item(gitem)
        elif page is not None and self.active_session:       # öğesi henüz çizilmemiş sayfa
            s = self.active_session
            s.undo_stack.push(RemoveAnnotationCommand(s, page, ann, on_change=self._on_session_change))
