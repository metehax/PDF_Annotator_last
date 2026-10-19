"""
ui/preferences.py
=================
Ayarlar penceresi: soldan kategori listesi (Genel · Görünüm · Çalışma klasörü · Tarama · Telefon aktarımı ·
Güncelleme · Kısayollar). Değişiklikler anında ayara yazılır (Tamam/İptal yok; "Kapat" yeterli).
"""

from __future__ import annotations

import os
import sys
from typing import Dict

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPushButton, QSpinBox, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

import appinfo
import workspace
from ui.icons import icon

THEMES = (("", "Sistem"), ("light", "Açık"), ("dark", "Koyu"))
TAB_WIDTHS = (("compact", "Dar"), ("normal", "Orta"), ("wide", "Geniş"))
TAB_CHARS = {"compact": 18, "normal": 30, "wide": 46}      # sekme başlığında en çok görünen harf sayısı

CATEGORIES = ("Genel", "Görünüm", "Çalışma klasörü", "Tarama", "Telefon aktarımı", "Güncelleme", "Kısayollar")
# komut paletinde aranabilen ayarlar: (başlık, kategori)
SEARCH_ENTRIES = (
    ("Tema (açık / koyu)", "Görünüm"), ("Düğmelerde yazı göster", "Görünüm"), ("Sekme genişliği", "Görünüm"),
    ("Çalışma klasörü", "Çalışma klasörü"), ("Otomatik kurtarma", "Çalışma klasörü"),
    ("Çıktıları çalışma klasörüne kaydet", "Çalışma klasörü"),
    ("Son kullanılan klasörü hatırla", "Genel"), ("Birlikte aç listesi", "Genel"),
    ("Taranan belgelerin klasörü", "Tarama"), ("Telefondan gelen dosyaların klasörü", "Telefon aktarımı"),
    ("Güncellemeleri denetle", "Güncelleme"), ("Klavye kısayolları", "Kısayollar"),
)


def _section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("sectionTitle")
    return lbl


def _note(text: str) -> QLabel:
    n = QLabel(text)
    n.setObjectName("hint")
    n.setWordWrap(True)
    return n


class PreferencesDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.setWindowTitle("Ayarlar")
        self.resize(780, 580)
        self._main = main
        self._loading = True
        self.chk_kind: Dict[str, QCheckBox] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(8)
        title = QLabel("Ayarlar")
        title.setObjectName("propTitle")
        outer.addWidget(title)
        mid = QHBoxLayout()
        mid.setSpacing(14)
        self.nav = QListWidget()
        self.nav.setObjectName("prefNav")
        self.nav.setFixedWidth(170)
        self.stack = QStackedWidget()
        mid.addWidget(self.nav)
        mid.addWidget(self.stack, 1)
        outer.addLayout(mid, 1)
        builders = (self._page_general, self._page_look, self._page_workspace, self._page_scan,
                    self._page_phone, self._page_update, self._page_keys)
        for name, build in zip(CATEGORIES, builders):
            page = QWidget()
            v = QVBoxLayout(page)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(8)
            build(v)
            v.addStretch(1)
            self.nav.addItem(name)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        foot = QHBoxLayout()
        foot.addStretch(1)
        btn_close = QPushButton("Kapat")
        btn_close.setObjectName("primary")
        btn_close.clicked.connect(self.accept)
        foot.addWidget(btn_close)
        outer.addLayout(foot)
        self.reload()

    def show_category(self, name: str) -> bool:
        """Soldaki listeden kategoriyi seçer (komut paleti ayar aramasından)."""
        if name in CATEGORIES:
            self.nav.setCurrentRow(CATEGORIES.index(name))
            return True
        return False

    def current_category(self) -> str:
        return CATEGORIES[self.nav.currentRow()]

    def _kind_box(self, kind: str) -> QCheckBox:
        subdir, label = workspace.KINDS[kind]
        c = QCheckBox(f"{label}  ·  {subdir}")
        c.toggled.connect(lambda on, k=kind: self._kind_toggled(k, on))
        self.chk_kind[kind] = c
        return c

    # -- sayfalar ---------------------------------------------------------------
    def _page_general(self, v):
        v.addWidget(_section("Genel"))
        self.chk_last = QCheckBox("Son kullanılan klasörü hatırla")
        self.chk_last.toggled.connect(self._last_changed)
        v.addWidget(self.chk_last)
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
        v.addWidget(_note("PDF ve resimlere sağ tıklayıp Birlikte aç dediğinizde bu uygulamanın görünmesini sağlar "
                          "(yalnız sizin hesabınız için)."))

    def _page_look(self, v):
        v.addWidget(_section("Görünüm"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Tema"))
        self.cb_theme = QComboBox()
        for key, label in THEMES:
            self.cb_theme.addItem(label, key)
        self.cb_theme.currentIndexChanged.connect(self._theme_changed)
        row.addWidget(self.cb_theme)
        row.addStretch(1)
        v.addLayout(row)
        self.chk_labels = QCheckBox("Düğmelerde yazı göster")
        self.chk_labels.toggled.connect(self._look_changed)
        v.addWidget(self.chk_labels)
        row = QHBoxLayout()
        row.addWidget(QLabel("Sekme genişliği"))
        self.cb_tabw = QComboBox()
        for key, label in TAB_WIDTHS:
            self.cb_tabw.addItem(label, key)
        self.cb_tabw.currentIndexChanged.connect(self._look_changed)
        row.addWidget(self.cb_tabw)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(_note("Uzun dosya adlarında başı ve uzantısı görünür; tam ad sekmenin üstüne gelince çıkar."))

    def _page_workspace(self, v):
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
        self.root_hint = _note("")
        v.addWidget(self.root_hint)
        v.addWidget(QLabel("Çıktıları çalışma klasörüne kaydet:"))
        for kind in workspace.KINDS:
            if kind not in ("scans", "inbox"):
                v.addWidget(self._kind_box(kind))
        v.addWidget(_note("Kapalı olan türlerde pencereler eski varsayılanına (belgenin yanı, son klasör) döner. "
                          "Pencerelerde elle seçtiğiniz yol her zaman önceliklidir."))
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
        v.addWidget(_note("Uygulama beklenmedik biçimde kapanırsa, bir sonraki açılışta kurtarma önerilir. Parolalı belgeler "
                          "güvenlik için yedeklenmez. Normal kaydetme/kapatma yedeği siler."))

    def _page_scan(self, v):
        v.addWidget(_section("Tarama"))
        v.addWidget(self._kind_box("scans"))
        v.addWidget(_note("Belge tarama penceresinden çıkan PDF'ler için varsayılan klasör. "
                          "Pencerede elle seçtiğiniz yol her zaman önceliklidir."))

    def _page_phone(self, v):
        v.addWidget(_section("Telefon aktarımı"))
        v.addWidget(self._kind_box("inbox"))
        v.addWidget(_note("Telefondan gelen dosyalar bu klasöre kaydedilir. Pencere kapanınca ya da 15 dk boşta kalınca "
                          "sunucu kendiliğinden durur."))

    def _page_update(self, v):
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

    def _page_keys(self, v):
        v.addWidget(_section("Kısayollar"))
        self.keys = QTreeWidget()
        self.keys.setHeaderLabels(["Komut", "Kısayol"])
        self.keys.setRootIsDecorated(False)
        self.keys.setColumnWidth(0, 340)
        v.addWidget(self.keys, 1)

    def _fill_keys(self):
        from mw_common import TOOL_KEYS, TOOL_NAMES
        self.keys.clear()
        rows = set()
        for a in self._main.findChildren(QAction):
            sc = a.shortcut().toString()
            if sc and a.text():
                rows.add((a.text().replace("&", "").rstrip("…").strip(), sc))
        for key, letter in TOOL_KEYS.items():
            rows.add((f"{TOOL_NAMES.get(key, key)} aracı", letter))
        for name, sc in sorted(rows):
            QTreeWidgetItem(self.keys, [name, sc])

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
        st = self._main.settings
        cur = str(st.value("theme", "") or "")
        self.cb_theme.setCurrentIndex(max(0, self.cb_theme.findData(cur if cur in ("light", "dark") else "")))
        self.chk_labels.setChecked(str(st.value("ui/button_labels", "false")).lower() == "true")
        self.cb_tabw.setCurrentIndex(max(0, self.cb_tabw.findData(str(st.value("ui/tab_width", "normal") or "normal"))))
        self.chk_last.setChecked(workspace.remember_last())
        from mw_update import auto_enabled
        self.chk_upd.setChecked(auto_enabled(st))
        has_url = bool(self._main.update_url())
        self.chk_upd.setEnabled(has_url)
        self.btn_upd.setEnabled(has_url)
        self.lbl_upd.setText(f"Sürüm {appinfo.VERSION}" if has_url
                             else f"Sürüm {appinfo.VERSION} — güncelleme adresi tanımlı değil")
        self._fill_keys()
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

    def _look_changed(self, *_):
        if self._loading:
            return
        st = self._main.settings
        st.setValue("ui/button_labels", self.chk_labels.isChecked())
        st.setValue("ui/tab_width", self.cb_tabw.currentData())
        hook = getattr(self._main, "apply_view_prefs", None)
        if hook:
            hook()
