"""
mw_workspace.py
===============
Tercihler, çalışma klasörü taşıması ve otomatik kurtarma (taslak yazma/geri yükleme) yöntemleri.

MainWindow bu mixin'i miras alır; yöntemler `self` üzerinden ana pencerenin durumuna erişir.
Çekirdek `workspace.py`'dadır (arayüzsüz).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from typing import Callable, List, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

import workspace
from models import DocumentSession
from pdf_engine import PDFDocument
from ui import theme as ui_theme
from ui.preferences import PreferencesDialog


class WorkspaceMixin:
    # -- Tercihler ---------------------------------------------------------------
    def open_preferences(self):
        dlg = getattr(self, "_prefs_dialog", None)
        if dlg is None or not dlg.isVisible():
            dlg = self._prefs_dialog = PreferencesDialog(self)
            dlg.show()
        else:
            dlg.reload()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def apply_theme_pref(self, pref: str):
        """pref: "light" | "dark" | "" (sistem)."""
        pref = pref if pref in ("light", "dark") else ""
        self.settings.setValue("theme", pref)
        self.dark_mode = (pref == "dark") if pref else ui_theme.system_prefers_dark()
        self._apply_style()

    # -- açılış denetimleri ------------------------------------------------------
    def startup_checks(self):
        """Açılışta bir kez: eski gelen klasörü taşıma önerisi, kapanmayan belgeler, otomatik kurtarma zamanlayıcısı."""
        self.check_migration()
        self.check_recovery()
        self.start_recovery()

    def check_migration(self, decide: Optional[Callable[[str, int], str]] = None) -> Optional[str]:
        """Eski 'PDF Annotator Gelen' klasörü varsa taşımayı önerir. decide(yol, dosya_sayısı) → "move"|"later"|"never".
        Yapılan seçimi döndürür (öneri yoksa None). Hiçbir dosya silinmez."""
        if not workspace.migration_pending():
            return None
        old = workspace.old_inbox()
        n = len(workspace._files_in(old))
        choice = (decide or self._ask_migration)(old, n)
        if choice == "move":
            moved, errors = workspace.migrate_old_inbox(old)
            msg = f"{moved} dosya {workspace.sub('Gelen')} klasörüne taşındı."
            if errors:
                msg += f" {len(errors)} dosya taşınamadı."
            self.toasts.show(msg, "warning" if errors else "success")
        elif choice == "never":
            workspace.decline_migration()
        return choice

    def _ask_migration(self, old: str, n: int) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Eski gelen klasörü bulundu")
        box.setText(f"<b>{n} dosya</b> eski gelen klasöründe duruyor:<br>{old}")
        box.setInformativeText(f"Yeni çalışma klasörüne ({os.path.join(workspace.root(), 'Gelen')}) taşınsın mı? "
                               "Dosyalar silinmez, yalnızca taşınır.")
        b_move = box.addButton("Taşı", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Şimdilik değil", QMessageBox.ButtonRole.RejectRole)
        b_never = box.addButton("Bir daha sorma", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(b_move)
        box.exec()
        c = box.clickedButton()
        return "move" if c is b_move else "never" if c is b_never else "later"

    # -- otomatik kurtarma: yazma ------------------------------------------------
    def start_recovery(self):
        """Zamanlayıcıyı (ayardaki dakikada bir) başlatır; kapalıysa durdurur."""
        t = getattr(self, "_recovery_timer", None)
        if t is None:
            t = self._recovery_timer = QTimer(self)
            t.timeout.connect(self._autosave_drafts)
        t.stop()
        if workspace.recovery_enabled():
            t.start(workspace.recovery_minutes() * 60 * 1000)
        return t

    def restart_recovery(self):
        """Tercihler değişince: zamanlayıcıyı yeniden kur; kapatıldıysa açık oturumların taslaklarını sil."""
        self.start_recovery()
        if not workspace.recovery_enabled():
            for s in self.sessions:
                self._drop_draft(s)

    @staticmethod
    def _draft_id(s) -> str:
        if not getattr(s, "draft_id", None):
            s.draft_id = uuid.uuid4().hex[:12]
        return s.draft_id

    def _write_session_draft(self, s) -> None:
        with s.pdf.lock:
            data = s.pdf.doc.write()
        workspace.write_draft(self._draft_id(s), data, s.to_project_dict(), s.title, s.pdf.page_count)
        s._draft_sig = (s.undo_stack.index(), s.pdf.page_count)

    def _autosave_drafts(self) -> int:
        """Değişmiş oturumlar için taslak yazar (değişmemiş olanın taslağını siler). Yazılan taslak sayısını döndürür.
        Parolalı belgeler düz metin yedeklenmesin diye atlanır."""
        if not workspace.recovery_enabled():
            return 0
        n = 0
        for s in list(self.sessions):
            try:
                if not self._is_dirty(s):
                    self._drop_draft(s)
                    continue
                if getattr(s, "security", None) is not None:
                    continue
                sig = (s.undo_stack.index(), s.pdf.page_count)
                if getattr(s, "_draft_sig", None) == sig and getattr(s, "draft_id", None):
                    continue
                self._write_session_draft(s)
                n += 1
            except Exception as ex:          # yedekleme asla işi bozmasın
                self.status.setText(f"Otomatik kurtarma yazılamadı: {ex}")
        return n

    def _drop_draft(self, s) -> None:
        did = getattr(s, "draft_id", None)
        if did:
            workspace.delete_draft(did)
            s._draft_sig = None

    # -- otomatik kurtarma: geri yükleme -----------------------------------------
    def check_recovery(self, decide: Optional[Callable[[List[workspace.Draft]], str]] = None) -> Optional[str]:
        """Kapanmayan belgelerin taslakları varsa sorar. decide(taslaklar) → "restore"|"keep"|"delete"."""
        live = {getattr(s, "draft_id", None) for s in self.sessions}
        drafts = [d for d in workspace.list_drafts() if d.id not in live]
        if not drafts:
            return None
        choice = (decide or self._ask_recovery)(drafts)
        if choice == "restore":
            ok = [d for d in drafts if self._restore_one(d)]
            if ok:
                self.toasts.show(f"{len(ok)} belge kurtarıldı; değişiklikler henüz kaydedilmedi.", "success",
                                 timeout_ms=6000)
        elif choice == "delete":
            for d in drafts:
                workspace.delete_draft(d.id)
        return choice

    def _ask_recovery(self, drafts: List[workspace.Draft]) -> str:
        lines = "".join(f"<li>{d.title or d.id} — {d.when()}</li>" for d in drafts[:8])
        more = f"<li>… ve {len(drafts) - 8} belge daha</li>" if len(drafts) > 8 else ""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Kapanmayan belgeler bulundu")
        box.setText("Uygulama kapanmadan önceki kaydedilmemiş çalışmalar bulundu:")
        box.setInformativeText(f"<ul>{lines}{more}</ul>Kurtarılsın mı?")
        b_restore = box.addButton("Kurtar", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Şimdilik değil", QMessageBox.ButtonRole.RejectRole)
        b_delete = box.addButton("Sil", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(b_restore)
        box.exec()
        c = box.clickedButton()
        return "restore" if c is b_restore else "delete" if c is b_delete else "keep"

    def _restore_one(self, d: workspace.Draft) -> Optional[DocumentSession]:
        """Taslağı yeni bir sekmede açar (belge baytları + işaretler); değişmiş olarak işaretlenir."""
        try:
            data, proj = workspace.read_draft(d.id)
            fd, tmp = tempfile.mkstemp(suffix=".pdf", prefix="kurtarilan_")
            os.close(fd)
            with open(tmp, "wb") as f:                    # taslak dosyası açık tutulmasın (silinebilsin)
                f.write(data)
            pdf = PDFDocument(tmp)
            source = str(proj.get("source_pdf", "") or "")
            s = DocumentSession(pdf, source if source else tmp)
            s.title = str(proj.get("title", "") or os.path.basename(s.path))
            s.security = None
            s.load_project_dict(proj)
            for page, rot in s.rotations.items():
                if 0 <= page < pdf.page_count:
                    pdf.set_absolute_rotation(page, rot)
            s.draft_id = d.id
            s.dirty = True
            s.undo_stack.cleanChanged.connect(lambda _c: self.refresh_doc_tabs())
            self.undo_group.addStack(s.undo_stack)
            self.sessions.append(s)
            self._set_ui_enabled(True)
            self.refresh_doc_tabs()
            self.switch_session(len(self.sessions) - 1)
            return s
        except Exception as ex:
            QMessageBox.critical(self, "Hata", f"'{d.title or d.id}' kurtarılamadı:\n{ex}")
            return None
