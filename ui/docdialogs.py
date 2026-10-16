"""
ui/docdialogs.py
================
Belge güvenliği ve bilgileri pencereleri:

* PasswordDialog      — açma parolası + izinler
* CompressDialog      — sıkıştırma seviyesi seçimi
* DocInfoDialog       — başlık/yazar vb. + gömülü dosyalar
* SecurityCheckDialog — riskli içerik denetimi ve temizlik
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QRadioButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

import docsec
from ui import theme
from ui.icons import icon, pixmap as icon_pixmap


def _title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("propTitle")
    return lbl


def _hint(text: str, warn: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("hintWarn" if warn else "hint")
    lbl.setWordWrap(True)
    return lbl


def _password_field(placeholder: str) -> QLineEdit:
    e = QLineEdit()
    e.setEchoMode(QLineEdit.EchoMode.Password)
    e.setPlaceholderText(placeholder)
    act = e.addAction(icon("eye"), QLineEdit.ActionPosition.TrailingPosition)
    act.setToolTip("Parolayı göster / gizle")

    def toggle():
        e.setEchoMode(QLineEdit.EchoMode.Normal if e.echoMode() == QLineEdit.EchoMode.Password
                      else QLineEdit.EchoMode.Password)

    act.triggered.connect(toggle)
    return e


# ---------------------------------------------------------------------------
class PasswordDialog(QDialog):
    def __init__(self, parent, current: Optional[docsec.SecurityOptions]):
        super().__init__(parent)
        self.setWindowTitle("Parola koruması")
        self.result_options: Optional[docsec.SecurityOptions] = None
        cur = current or docsec.SecurityOptions()
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)
        v.addWidget(_title("Parola koruması"))
        v.addWidget(_hint("Ayarlar bu belgeyi PDF olarak her kaydettiğinizde uygulanır "
                          "(256-bit AES şifreleme)."))

        self.chk_open = QCheckBox("Belgeyi açmak için parola iste")
        self.chk_open.setChecked(bool(cur.user_password))
        v.addWidget(self.chk_open)
        form = QFormLayout()
        self.pw1 = _password_field("Açma parolası")
        self.pw2 = _password_field("Parolayı tekrar yazın")
        self.pw1.setText(cur.user_password)
        self.pw2.setText(cur.user_password)
        form.addRow("Parola:", self.pw1)
        form.addRow("Tekrar:", self.pw2)
        v.addLayout(form)

        line = QFrame()
        line.setObjectName("barSep")
        line.setFixedHeight(1)
        v.addWidget(line)
        v.addWidget(QLabel("<b>Belgeyi açan kişi şunları yapabilsin:</b>"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        self.perm_checks: Dict[str, QCheckBox] = {}
        for i, (key, label, _flag) in enumerate(docsec.PERMISSIONS):
            c = QCheckBox(label)
            c.setChecked(key in cur.allowed)
            self.perm_checks[key] = c
            grid.addWidget(c, i // 2, i % 2)
        v.addLayout(grid)
        form2 = QFormLayout()
        self.owner = _password_field("Boş bırakılırsa rastgele üretilir")
        self.owner.setText(cur.owner_password)
        form2.addRow("İzin parolası:", self.owner)
        v.addLayout(form2)
        v.addWidget(_hint("İzin parolası, kısıtlamaları kaldırmak için gerekir. Boş bırakırsanız "
                          "kimsenin bilmediği rastgele bir parola kullanılır; kısıtlamalar "
                          "sonradan kaldırılamaz (asıl dosyanız bu uygulamada açık kalır)."))
        v.addWidget(_hint("Not: İzinleri her PDF programı aynı sıkılıkta uygulamaz; gerçek "
                          "güvenlik için açma parolası kullanın.", warn=True))

        self.err = QLabel("")
        self.err.setStyleSheet(f"color:{theme.current()['danger']};")
        v.addWidget(self.err)
        row = QHBoxLayout()
        self.btn_remove = QPushButton(icon("close"), "Korumayı kaldır")
        self.btn_remove.setEnabled(cur.active)
        self.btn_remove.clicked.connect(self._remove)
        row.addWidget(self.btn_remove)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        v.addLayout(row)
        self.chk_open.toggled.connect(self._sync)
        self._sync()
        self.resize(520, 0)

    def _sync(self):
        on = self.chk_open.isChecked()
        self.pw1.setEnabled(on)
        self.pw2.setEnabled(on)

    def _remove(self):
        self.result_options = None
        self.done(2)

    def _accept(self):
        pw = self.pw1.text() if self.chk_open.isChecked() else ""
        if self.chk_open.isChecked():
            if len(pw) < 4:
                self.err.setText("Parola en az 4 karakter olmalı.")
                return
            if pw != self.pw2.text():
                self.err.setText("Parolalar aynı değil.")
                return
        allowed = {k for k, c in self.perm_checks.items() if c.isChecked()}
        owner = self.owner.text()
        if owner and owner == pw:
            self.err.setText("İzin parolası açma parolasından farklı olmalı.")
            return
        self.result_options = docsec.SecurityOptions(pw, owner, allowed)
        self.accept()


# ---------------------------------------------------------------------------
class CompressDialog(QDialog):
    def __init__(self, parent, current_size: int):
        super().__init__(parent)
        self.setWindowTitle("Sıkıştırarak kaydet")
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(10)
        v.addWidget(_title("Sıkıştırarak kaydet"))
        v.addWidget(_hint(f"Şu anki dosya boyutu: {docsec.human_size(current_size)}. "
                          "İşaretleriniz ve parola ayarlarınız korunur."))
        self.group = QButtonGroup(self)
        for key, cfg in docsec.COMPRESS_LEVELS.items():
            rb = QRadioButton(cfg["title"])
            rb.setProperty("level", key)
            f = rb.font()
            f.setBold(True)
            rb.setFont(f)
            self.group.addButton(rb)
            v.addWidget(rb)
            d = _hint(cfg["desc"])
            d.setContentsMargins(26, 0, 0, 6)
            v.addWidget(d)
            if key == "balanced":
                rb.setChecked(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Kaydet…")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(480, 0)

    def level(self) -> str:
        return self.group.checkedButton().property("level")


# ---------------------------------------------------------------------------
class DocInfoDialog(QDialog):
    """Belge bilgileri (düzenlenebilir) + gömülü dosyalar. Değişiklikler canlı
    belgeye yazılır; dışa aktarırken PDF'e geçer."""

    def __init__(self, parent, session, on_changed):
        super().__init__(parent)
        self.setWindowTitle("Belge bilgileri")
        self.s = session
        self.doc = session.pdf.doc
        self.on_changed = on_changed
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        v.addWidget(_title(session.title))
        tabs = QTabWidget()
        v.addWidget(tabs, 1)

        # -- özellikler
        props = QWidget()
        pv = QVBoxLayout(props)
        pv.setContentsMargins(4, 10, 4, 4)
        form = QFormLayout()
        form.setVerticalSpacing(8)
        meta = self.doc.metadata or {}
        self.fields: Dict[str, QLineEdit] = {}
        for key, label in docsec.META_FIELDS:
            e = QLineEdit(meta.get(key) or "")
            self.fields[key] = e
            form.addRow(label + ":", e)
        pv.addLayout(form)
        info = QFormLayout()
        info.setVerticalSpacing(4)
        for k, val in docsec.info_summary(self.doc, session.path):
            lbl = QLabel(val)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setWordWrap(True)
            info.addRow(k + ":", lbl)
        box = QFrame()
        box.setObjectName("sectionFrame")
        box.setLayout(info)
        info.setContentsMargins(12, 10, 12, 10)
        pv.addSpacing(6)
        pv.addWidget(box)
        pv.addStretch(1)
        tabs.addTab(props, "Özellikler")

        # -- gömülü dosyalar
        emb = QWidget()
        ev = QVBoxLayout(emb)
        ev.setContentsMargins(4, 10, 4, 4)
        ev.addWidget(_hint("PDF'in içine eklenmiş dosyalar. Ekledikleriniz kaydettiğiniz PDF'e gömülür."))
        self.emb_list = QListWidget()
        self.emb_list.setIconSize(QSize(18, 18))
        ev.addWidget(self.emb_list, 1)
        er = QHBoxLayout()
        b_add = QPushButton(icon("plus"), "Dosya ekle…")
        b_add.setObjectName("secondary")
        b_add.clicked.connect(self._add_file)
        self.b_save = QPushButton(icon("download"), "Dışarı kaydet…")
        self.b_save.clicked.connect(self._extract)
        self.b_del = QPushButton(icon("trash", "danger"), "Sil")
        self.b_del.clicked.connect(self._delete)
        for b in (b_add, self.b_save, self.b_del):
            er.addWidget(b)
        er.addStretch(1)
        ev.addLayout(er)
        tabs.addTab(emb, f"Gömülü dosyalar ({self.doc.embfile_count()})")
        self._emb_tab = (tabs, 1)
        self.emb_list.currentRowChanged.connect(self._sync_emb)
        self._fill_emb()

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(560, 600)

    def _fill_emb(self):
        self.emb_list.clear()
        for name in self.doc.embfile_names():
            try:
                inf = self.doc.embfile_info(name)
                size = docsec.human_size(int(inf.get("size") or inf.get("length") or 0))
            except Exception:
                size = ""
            item = QListWidgetItem(icon("file"), f"{name}    {size}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.emb_list.addItem(item)
        tabs, i = self._emb_tab
        tabs.setTabText(i, f"Gömülü dosyalar ({self.doc.embfile_count()})")
        self._sync_emb()

    def _sync_emb(self, *_):
        has = self.emb_list.currentItem() is not None
        self.b_save.setEnabled(has)
        self.b_del.setEnabled(has)

    def _add_file(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Gömülecek dosyaları seçin")
        for p in paths:
            name = os.path.basename(p)
            base, ext = os.path.splitext(name)
            n = 2
            while name in self.doc.embfile_names():
                name = f"{base} ({n}){ext}"
                n += 1
            with open(p, "rb") as f:
                self.doc.embfile_add(name, f.read(), filename=os.path.basename(p))
        if paths:
            self._fill_emb()
            self.on_changed()

    def _extract(self):
        item = self.emb_list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        path, _ = QFileDialog.getSaveFileName(self, "Dosyayı kaydet", name)
        if path:
            with open(path, "wb") as f:
                f.write(self.doc.embfile_get(name))

    def _delete(self):
        item = self.emb_list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self, "Gömülü dosyayı sil", f"'{name}' belgeden silinsin mi?") \
                == QMessageBox.StandardButton.Yes:
            self.doc.embfile_del(name)
            self._fill_emb()
            self.on_changed()

    def _accept(self):
        meta = dict(self.doc.metadata or {})
        changed = False
        for key, e in self.fields.items():
            if (meta.get(key) or "") != e.text():
                meta[key] = e.text()
                changed = True
        if changed:
            meta = {k: v for k, v in meta.items() if k in (
                "title", "author", "subject", "keywords", "creator", "producer",
                "creationDate", "modDate", "trapped")}
            self.doc.set_metadata(meta)
            self.on_changed()
        self.accept()


# ---------------------------------------------------------------------------
_SEV = {"high": ("Yüksek risk", "danger"), "medium": ("Orta risk", "warning"), "low": ("Bilgi", "accent_text")}


class SecurityCheckDialog(QDialog):
    def __init__(self, parent, session, on_cleaned):
        super().__init__(parent)
        self.setWindowTitle("Güvenlik denetimi")
        self.s = session
        self.on_cleaned = on_cleaned
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        v.addWidget(_title("Güvenlik denetimi"))
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(18, 18))
        v.addWidget(self.tree, 1)

        v.addWidget(QLabel("<b>Temizlenecekler</b>"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        self.clean_checks: Dict[str, QCheckBox] = {}
        for i, (key, (label, default, tip)) in enumerate(docsec.CLEAN_OPTIONS.items()):
            c = QCheckBox(label)
            c.setChecked(default)
            if tip:
                c.setToolTip(tip)
            self.clean_checks[key] = c
            grid.addWidget(c, i // 2, i % 2)
        v.addLayout(grid)
        self.warn = _hint(docsec.CLEAN_OPTIONS["hidden_text"][2], warn=True)
        self.warn.setVisible(False)
        self.clean_checks["hidden_text"].toggled.connect(self.warn.setVisible)
        v.addWidget(self.warn)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_clean = QPushButton(icon("check", "on_accent"), "Seçilenleri temizle")
        self.btn_clean.setObjectName("primary")
        self.btn_clean.clicked.connect(self._clean)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        row.addWidget(self.btn_clean)
        row.addWidget(close)
        v.addLayout(row)
        self.resize(600, 640)
        self._scan()

    def _scan(self):
        with self.s.pdf.lock:
            findings = docsec.scan(self.s.pdf.doc)
        self.tree.clear()
        t = theme.current()
        dpr = self.devicePixelRatioF()
        high = sum(1 for f in findings if f.severity == "high")
        med = sum(1 for f in findings if f.severity == "medium")
        if not findings:
            self.summary.setText("<b>Riskli içerik bulunamadı.</b> Belgede betik, otomatik eylem, "
                                 "gömülü dosya ya da dış bağlantı yok.")
        elif high:
            self.summary.setText(f"<b style='color:{t['danger']}'>{high} yüksek riskli</b> bulgu var. "
                                 "Güvenmediğiniz bir kaynaktan geldiyse temizleyip öyle paylaşın.")
        else:
            self.summary.setText(f"{len(findings)} bulgu ({med} orta risk). Aşağıdan inceleyebilirsiniz.")
        for f in findings:
            label, color_key = _SEV[f.severity]
            top = QTreeWidgetItem([f"{f.title}  ·  {f.count}"])
            top.setIcon(0, QIcon(icon_pixmap("warning" if f.severity != "low" else "info", 18,
                                             t[color_key], dpr)))
            top.setToolTip(0, f"{label}: {f.explain}")
            fnt = top.font(0)
            fnt.setBold(True)
            top.setFont(0, fnt)
            self.tree.addTopLevelItem(top)
            exp = QTreeWidgetItem([f.explain])
            exp.setForeground(0, theme.qcolor("text_faint"))
            top.addChild(exp)
            for it in f.items:
                top.addChild(QTreeWidgetItem([it]))
            top.setExpanded(f.severity == "high")
        self.btn_clean.setEnabled(bool(findings))

    def _clean(self):
        opts = [k for k, c in self.clean_checks.items() if c.isChecked()]
        if not opts:
            return
        with self.s.pdf.lock:
            docsec.clean(self.s.pdf.doc, opts)
        self.on_cleaned()
        self._scan()
