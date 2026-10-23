"""
mw_textcopy.py
==============
Metin Seç aracı ve otomatik OCR: sayfadaki metni (gerçek metin katmanı ya da OCR) kelime kelime
önbelleğe alır; sürüklenen alandaki metni panoya kopyalar.

MainWindow bu mixin'i miras alır.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

import pymupdf as fitz

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication, QMessageBox

import ocr
import workspace
from ui.ocrdialog import _OcrTask


def words_to_text(words: List[tuple], rect: Optional[QRectF] = None) -> str:
    """words: (x0, y0, x1, y1, metin, blok, satır, sıra). rect verilirse yalnızca merkezi içinde olanlar.
    Okuma sırası korunur; satır sonu "\\n", blok sonu boş satır."""
    out: List[str] = []
    last = None
    for x0, y0, x1, y1, w, b, ln, _n in words:
        if rect is not None and not rect.contains((x0 + x1) / 2, (y0 + y1) / 2):
            continue
        if last is not None:
            out.append("\n\n" if b != last[0] else "\n" if ln != last[1] else " ")
        out.append(w)
        last = (b, ln)
    return "".join(out)


class TextCopyMixin:
    # -- sayfa kelimeleri: önbellek + arka plan işi ------------------------------------------
    def _words_cache(self, s) -> Dict:
        c = getattr(s.pdf, "words_cache", None)
        if c is None:
            c = s.pdf.words_cache = {}
        return c

    def _words_pending(self) -> Dict:
        if not hasattr(self, "_wp"):
            self._wp = {}               # (id(s), sayfa) -> [geri çağrılar]
            self._wqueue = []           # [(s, sayfa)]
            self._wbusy = False
            self._wwarned = False
        return self._wp

    def ensure_words(self, s, page: int, then: Optional[Callable] = None, user: bool = False) -> None:
        """Sayfa kelimelerini hazırlar; then(entry) hazır olunca çağrılır. entry: {"source","words"} ya da None."""
        cache = self._words_cache(s)
        if page in cache:
            if then:
                then(cache[page])
            return
        pend = self._words_pending()
        key = (id(s), page)
        if key in pend:
            if then:
                pend[key].append(then)
            if user and (s, page) in self._wqueue:          # kullanıcı bekliyor: öne al
                self._wqueue.remove((s, page))
                self._wqueue.insert(0, (s, page))
            return
        pend[key] = [then] if then else []
        if user:
            self._wqueue.insert(0, (s, page))
        else:
            self._wqueue.append((s, page))
        self._words_next()

    def _words_next(self) -> None:
        if self._wbusy:
            return
        while self._wqueue:
            s, page = self._wqueue.pop(0)
            if s not in self.sessions or page >= s.pdf.page_count:
                self._wp.pop((id(s), page), None)
                continue
            self._words_run(s, page)
            return

    def _words_run(self, s, page: int) -> None:
        try:
            self._words_run_inner(s, page)
        except Exception:                          # arka plan hazırlığı asla uygulamayı bozmasın
            self._wbusy = False
            self._wp.pop((id(s), page), None)
            self._words_next()

    def _words_run_inner(self, s, page: int) -> None:
        key = (id(s), page)
        rev = s.pdf.page_rev(page)
        with s.pdf.lock:
            pg = s.pdf.doc[page]
            has_native = bool(pg.get_text("text").strip())
            rot = fitz.Matrix(pg.rotation_matrix)
            snap = fitz.open()
            try:
                snap.insert_pdf(s.pdf.doc, from_page=page, to_page=page)
            except Exception:                    # PDF olmayan kaynak (ör. uzantısı yanıltıcı resim): görüntüden kur
                snap.close()
                snap = fitz.open()
                sp = snap.new_page(width=pg.rect.width, height=pg.rect.height)
                sp.insert_image(sp.rect, pixmap=pg.get_pixmap(dpi=ocr.DEFAULT_DPI))
        tessdata = None if has_native else ocr.find_tessdata()
        if not has_native and tessdata is None:
            snap.close()
            if not self._wwarned:
                self._wwarned = True
                self.status.setText("Taranmış sayfa: OCR kurulu değil, metin okunamıyor.")
            self._words_done(s, page, key, rev, None)
            return
        lang = ocr.pick_language(tessdata) if tessdata else "eng"

        def job(_progress, _cancelled):
            try:
                p0 = snap[0]
                if has_native:
                    words, src = p0.get_text("words"), "native"
                else:
                    tp = p0.get_textpage_ocr(flags=fitz.TEXT_PRESERVE_WHITESPACE, language=lang,
                                             dpi=ocr.DEFAULT_DPI, full=True, tessdata=tessdata)
                    words, src = p0.get_text("words", textpage=tp), "ocr"
                out = []
                for x0, y0, x1, y1, w, b, ln, n in words:
                    r = fitz.Rect(x0, y0, x1, y1) * rot       # sayfanın görünen yönüne
                    out.append((r.x0, r.y0, r.x1, r.y1, w, b, ln, n))
                return {"source": src, "words": out}
            finally:
                snap.close()

        task = _OcrTask(job)
        self._wbusy = True
        if not has_native:
            self.status.setText(f"OCR: sayfa {page + 1} okunuyor…")
        task.signals.done.connect(lambda entry: self._words_done(s, page, key, rev, entry))
        task.signals.failed.connect(lambda _m: self._words_done(s, page, key, rev, None))
        self.threadpool.start(task)

    def _words_done(self, s, page, key, rev, entry) -> None:
        self._wbusy = False
        cbs = self._wp.pop(key, [])
        if entry is not None and s in self.sessions and s.pdf.page_rev(page) == rev:
            self._words_cache(s)[page] = entry
            if entry["source"] == "ocr":
                self.status.setText(f"OCR tamam: sayfa {page + 1} ({len(entry['words'])} kelime). "
                                    "Metin Seç aracıyla (K) kopyalayabilirsiniz.")
        for cb in cbs:
            cb(entry)
        self._words_next()

    # -- otomatik OCR -------------------------------------------------------------------------
    def auto_ocr_kick(self) -> None:
        """Etkinse geçerli sayfayı, ardından belgenin kalan sayfalarını arka planda okur."""
        s = self.active_session
        if not s or not workspace.auto_ocr_enabled():
            return
        if ocr.find_tessdata() is None:
            return
        cur = s.current_page
        order = [cur] + [p for p in range(cur + 1, s.pdf.page_count)] + [p for p in range(cur)]
        for p in order:
            self.ensure_words(s, p, user=(p == cur))

    # -- Metin Seç aracı ----------------------------------------------------------------------
    def on_text_rect_requested(self, rect: QRectF) -> None:
        s = self.active_session
        if not s:
            return
        page = s.current_page
        self.status.setText("Metin okunuyor…")

        def done(entry):
            if entry is None:
                QMessageBox.warning(self, "Metin okunamadı",
                                    ocr.setup_message() if ocr.find_tessdata() is None
                                    else "Bu sayfadan metin okunamadı.")
                return
            text = words_to_text(entry["words"], rect)
            if not text.strip():
                self.toasts.show("Seçilen alanda metin bulunamadı.", "info")
                return
            QApplication.clipboard().setText(text)
            n = len(text.split())
            prev = " ".join(text.split())[:60]
            src = " (OCR)" if entry["source"] == "ocr" else ""
            self.toasts.show(f"{n} kelime kopyalandı{src}<br><span style='color:gray'>{prev}</span>", "success")

        self.ensure_words(s, page, then=done, user=True)

    def copy_page_text(self) -> None:
        """Geçerli sayfanın tüm metnini panoya kopyalar (Düzenle menüsü)."""
        s = self.active_session
        if not s:
            return
        page = s.current_page

        def done(entry):
            if entry is None or not entry["words"]:
                self.toasts.show("Bu sayfada okunabilir metin bulunamadı.", "info")
                return
            QApplication.clipboard().setText(words_to_text(entry["words"]))
            self.toasts.show(f"Sayfa {page + 1} metni kopyalandı ({len(entry['words'])} kelime).", "success")

        self.ensure_words(s, page, then=done, user=True)
