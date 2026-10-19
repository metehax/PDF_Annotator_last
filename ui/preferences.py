"""
ui/preferences.py
=================
Tercihler penceresi: çalışma klasörü ve "çıktıları buraya kaydet" kutuları, otomatik kurtarma, tema,
son klasörü hatırlama. Değişiklikler anında ayara yazılır (Tamam/İptal yok; "Kapat" yeterli).
"""

from __future__ import annotations

import os
import sys
from typing import Dict

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout,
)

import appinfo
import workspace
from ui.icons import icon

THEMES = (("", "Sistem"), ("light", "Açık"), ("dark", "Koyu"))


def _section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("sectionTitle")
    return lbl


class PreferencesDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.setWindowTitle("Tercihler")
        self.resize(560, 660)
        self._main = main
        self._loading = True
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)
        title = QLabel("Tercihler")
        title.setObjectName("propTitle")
        v.addWidget(title)

        # -- çalışma klasörü -------------------------------------------------
        v.addWidget(_section("Çalışma klasörü"))
        row = QHBoxLayout()
        self.root_edit = QLineEdit()
        self.root_edit.setReadOnly(True)
        self.btn_choose = QPushButton(icon("folder"), "Seç…")
        self.btn_open = QPushButton("Aç")
        self.btn_reset = QPushButton(icon("reset"), "Sıfırla")
        for b in (self.btn_choose, self.btn_open, self.btn_reset):
            b.setObjectName("secondary")
        self.btn_choose.clicked.connect(self._choose_root)
        self.btn_open.clicked.connect(self._open_root)
        self.btn_reset.clicked.connect(self._reset_root)
        row.addWidget(self.root_edit, 1)
        row.addWidget(self.btn_choose)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_reset)
        v.addLayout(row)
        self.root_hint = QLabel()
        self.root_hint.setObjectName("hint")
        self.root_hint.setWordWrap(True)
        v.addWidget(self.root_hint)

        v.addWidget(QLabel("Çıktıları çalışma klasörüne kaydet:"))
        self.chk_kind: Dict[str, QCheckBox] = {}
        for kind, (subdir, label) in workspace.KINDS.items():
            c = QCheckBox(f"{label}  ·  {subdir}")
            c.toggled.connect(lambda on, k=kind: self._kind_toggled(k, on))
            self.chk_kind[kind] = c
            v.addWidget(c)
        note = QLabel("Kapalı olan türlerde pencereler eski varsayılanına (belgenin yanı, son klasör) döner. "
                      "Pencerelerde elle seçtiğiniz yol her zaman önceliklidir.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        v.addWidget(note)

        # -- otomatik kurtarma ---------------------------------------------
        v.addSpacing(6)
        v.addWidget(_section("Otomatik kurtarma"))
        row = QHBoxLayout()
        self.chk_rec = QCheckBox("Değişmiş belgeleri düzenli olarak yedekle")
        self.chk_rec.toggled.connect(self._rec_changed)
        self.sp_min = QSpinBox()
        self.sp_min.setRange(workspace.MIN_MINUTES, workspace.MAX_MINUTES)
        self.sp_min.setSuffix(" dk")
        self.sp_min.valueChanged.connect(self._rec_changed)
        row.addWidget(self.chk_rec, 1)
        row.addWidget(QLabel("Süre"))
        row.addWidget(self.sp_min)
        v.addLayout(row)
        rec_note = QLabel("Uygulama beklenmedik biçimde kapanırsa, bir sonraki açılışta kurtarma önerilir. Parolalı belgeler "
                          "güvenlik için yedeklenmez. Normal kaydetme/kapatma yedeği siler.")
        rec_note.setObjectName("hint")
        rec_note.setWordWrap(True)
        v.addWidget(rec_note)

        # -- genel ------------------------------------------------------------
        v.addSpacing(6)
        v.addWidget(_section("Genel"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Tema"))
        self.cb_theme = QComboBox()
        for key, label in THEMES:
            self.cb_theme.addItem(label, key)
        self.cb_theme.currentIndexChanged.connect(self._theme_changed)
        row.addWidget(self.cb_theme)
        row.addStretch(1)
        v.addLayout(row)
        self.chk_last = QCheckBox("Son kullanılan klasörü hatırla")
        self.chk_last.toggled.connect(self._last_changed)
        v.addWidget(self.chk_last)
        v.addSpacing(6)
        v.addWidget(_section("Güncelleme"))
        self.chk_upd = QCheckBox("Açılışta güncellemeleri denetle")
        self.chk_upd.toggled.connect(self._upd_changed)
        v.addWidget(self.chk_upd)
        row = QHBoxLayout()
        self.lbl_upd = QLabel()
        self.lbl_upd.setObjectName("hint")
        row.addWidget(self.lbl_upd, 1)
        self.btn_upd = QPushButton("Şimdi denetle")
        self.btn_notes = QPushButton("Sürüm notları")
        for b in (self.btn_upd, self.btn_notes):
            b.setObjectName("secondary")
            row.addWidget(b)
        self.btn_upd.clicked.connect(lambda: self._main.check_updates(manual=True))
        self.btn_notes.clicked.connect(lambda: self._main.show_release_notes())
        v.addLayout(row)
        v.addSpacing(6)
        v.addWidget(_section("Windows"))
        row = QHBoxLayout()
        row.addWidget(QLabel("\"Birlikte aç\" listesi"))
        row.addStretch(1)
        self.btn_openwith_add = QPushButton("Ekle…")
        self.btn_openwith_del = QPushButton("Kaldır")
        for b in (self.btn_openwith_add, self.btn_openwith_del):
            b.setObjectName("secondary")
            b.setEnabled(sys.platform == "win32")
            row.addWidget(b)
        self.btn_openwith_add.clicked.connect(lambda: self._main._register_open_with())
        self.btn_openwith_del.clicked.connect(lambda: self._main._unregister_open_with())
        v.addLayout(row)
        note = QLabel("PDF ve resimlere sağ tıklayıp Birlikte aç dediğinizde bu uygulamanın görünmesini sağlar (yalnız sizin hesabınız için).")
        note.setObjectName("hint")
        note.setWordWrap(True)
        v.addWidget(note)
        v.addStretch(1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        btn_close = QPushButton("Kapat")
        btn_close.setObjectName("primary")
        btn_close.clicked.connect(self.accept)
        foot.addWidget(btn_close)
        v.addLayout(foot)

        self.reload()

    # -- ayar <-> pencere -------------------------------------------------------
    def reload(self):
        """Pencere öğelerini geçerli ayarlardan doldurur (değişiklik sinyali göndermeden)."""
        self._loading = True
        self.root_edit.setText(workspace.root())
        self._sync_root_hint()
        for kind, c in self.chk_kind.items():
            c.setChecked(workspace.use(kind))
        self.chk_rec.setChecked(workspace.recovery_enabled())
        self.sp_min.setValue(workspace.recovery_minutes())
        self.sp_min.setEnabled(self.chk_rec.isChecked())
        cur = str(self._main.settings.value("theme", "") or "")
        self.cb_theme.setCurrentIndex(max(0, self.cb_theme.findData(cur if cur in ("light", "dark") else "")))
        self.chk_last.setChecked(workspace.remember_last())
        from mw_update import auto_enabled
        self.chk_upd.setChecked(auto_enabled(self._main.settings))
        has_url = bool(self._main.update_url())
        self.chk_upd.setEnabled(has_url)
        self.btn_upd.setEnabled(has_url)
        self.lbl_upd.setText(f"Sürüm {appinfo.VERSION}" if has_url
                             else f"Sürüm {appinfo.VERSION} — güncelleme adresi tanımlı değil")
        self._loading = False

    def _sync_root_hint(self):
        env = bool(os.environ.get(workspace.ENV_ROOT, "").strip())
        self.btn_choose.setEnabled(not env)
        self.btn_reset.setEnabled(not env and workspace.is_custom_root())
        self.root_hint.setText("Klasör ortam değişkeniyle belirlendi; buradan değiştirilemez." if env else
                               ("Varsayılan: " + workspace.default_root() if workspace.is_custom_root()
                                else "Varsayılan konum kullanılıyor (Belgeler\\PDF Annotator)."))

    # -- çalışma klasörü ---------------------------------------------------------
    def _choose_root(self):
        d = QFileDialog.getExistingDirectory(self, "Çalışma klasörünü seçin", workspace.root())
        if d:
            self.set_root(d)

    def set_root(self, d: str):
        try:
            workspace.set_root(d)
            workspace.ensure_all()
        except OSError as ex:
            QMessageBox.critical(self, "Hata", f"Klasör oluşturulamadı:\n{ex}")
            return
        self.reload()

    def _reset_root(self):
        workspace.reset_root()
        self.reload()

    def _open_root(self):
        workspace.ensure_all()
        QDesktopServices.openUrl(QUrl.fromLocalFile(workspace.root()))

    def _kind_toggled(self, kind: str, on: bool):
        if self._loading:
            return
        workspace.set_use(kind, on)
        if kind == "inbox" and on:                      # elle seçilmiş QR klasörü varsa artık çalışma klasörü kullanılsın
            self._main.settings.setValue("qrReceiveDir", "")

    # -- kurtarma / genel -------------------------------------------------------
    def _rec_changed(self, *_):
        if self._loading:
            return
        workspace.set_recovery_enabled(self.chk_rec.isChecked())
        workspace.set_recovery_minutes(self.sp_min.value())
        self.sp_min.setEnabled(self.chk_rec.isChecked())
        hook = getattr(self._main, "restart_recovery", None)
        if hook:
            hook()

    def _upd_changed(self, on: bool):
        if not self._loading:
            self._main.settings.setValue("update/auto", bool(on))

    def _theme_changed(self, *_):
        if self._loading:
            return
        hook = getattr(self._main, "apply_theme_pref", None)
        if hook:
            hook(self.cb_theme.currentData())

    def _last_changed(self, on: bool):
        if not self._loading:
            workspace.set_remember_last(on)
