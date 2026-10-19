"""
ui/scansource.py
================
"Tara" komutunun kaynak seçici penceresi: Dosyalar · Telefondan · Açık belge. Açık belgede kapsam
(bu sayfa / sayfa aralığı / tüm belge) ve sonucun yeri (aynı PDF'te yerine / yeni PDF) seçilir.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

import pdfops

SOURCES = ("files", "phone", "doc")


class ScanSourceDialog(QDialog):
    def __init__(self, main, page_count: int = 0, current_page: int = 0):
        super().__init__(main)
        self.setWindowTitle("Tara")
        self.setMinimumWidth(440)
        self._n = page_count
        self._cur = current_page
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)
        t = QLabel("Neyi taramak istiyorsunuz?")
        t.setObjectName("propTitle")
        v.addWidget(t)
        self.r_files = QRadioButton("Dosyalar — fotoğraf ya da PDF seç")
        self.r_phone = QRadioButton("Telefondan — QR ile fotoğraf çek / gönder")
        self.r_doc = QRadioButton("Açık belge — sayfalarını temizle ve düzelt")
        self.r_files.setChecked(True)
        for r in (self.r_files, self.r_phone, self.r_doc):
            v.addWidget(r)
        self.r_doc.setEnabled(page_count > 0)
        if page_count <= 0:
            self.r_doc.setToolTip("Önce bir belge açın.")

        self.doc_box = QWidget()
        d = QVBoxLayout(self.doc_box)
        d.setContentsMargins(24, 0, 0, 0)
        self.r_page = QRadioButton(f"Yalnız bu sayfa ({current_page + 1})")
        self.r_range = QRadioButton("Sayfa aralığı")
        self.r_all = QRadioButton(f"Tüm belge ({page_count} sayfa)")
        self.r_all.setChecked(True)
        self.ed_range = QLineEdit()
        self.ed_range.setPlaceholderText("örn. 1-3, 5")
        self.ed_range.textChanged.connect(self._check)
        d.addWidget(self.r_page)
        rr = QHBoxLayout()
        rr.addWidget(self.r_range)
        rr.addWidget(self.ed_range, 1)
        d.addLayout(rr)
        d.addWidget(self.r_all)
        d.addWidget(QLabel("Sonuç:"))
        self.r_replace = QRadioButton("Aynı PDF'te sayfaların yerine koy (geri alınabilir)")
        self.r_new = QRadioButton("Yeni PDF olarak kaydet")
        self.r_replace.setChecked(True)
        d.addWidget(self.r_replace)
        d.addWidget(self.r_new)
        v.addWidget(self.doc_box)
        self._g_src, self._g_scope, self._g_out = QButtonGroup(self), QButtonGroup(self), QButtonGroup(self)
        for g, rs in ((self._g_src, (self.r_files, self.r_phone, self.r_doc)), (self._g_scope, (self.r_page, self.r_range, self.r_all)),
                      (self._g_out, (self.r_replace, self.r_new))):
            for r in rs:
                g.addButton(r)
        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet("color:#d14")
        v.addWidget(self.lbl_err)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = QPushButton("Vazgeç")
        self.btn_ok = QPushButton("Devam")
        self.btn_ok.setObjectName("primary")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self.accept)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        v.addLayout(row)
        for r in (self.r_files, self.r_phone, self.r_doc, self.r_page, self.r_range, self.r_all):
            r.toggled.connect(self._check)
        self._check()

    def source(self) -> str:
        return "doc" if self.r_doc.isChecked() else "phone" if self.r_phone.isChecked() else "files"

    def pages(self) -> Optional[List[int]]:
        """Seçilen 0 tabanlı sayfa dizinleri; geçersiz aralıkta None."""
        if self.r_page.isChecked():
            return [self._cur]
        if self.r_range.isChecked():
            try:
                return sorted(set(pdfops.parse_ranges(self.ed_range.text(), self._n)))
            except ValueError:
                return None
        return list(range(self._n))

    def replace(self) -> bool:
        return self.r_replace.isChecked()

    def _check(self, *_):
        doc = self.r_doc.isChecked()
        self.doc_box.setVisible(doc)
        self.ed_range.setEnabled(self.r_range.isChecked())
        msg = ""
        if doc and self.r_range.isChecked():
            try:
                pdfops.parse_ranges(self.ed_range.text(), self._n)
                if not self.ed_range.text().strip():
                    msg = "Bir sayfa aralığı yazın."
            except ValueError as ex:
                msg = str(ex)
        self.lbl_err.setText(msg)
        self.btn_ok.setEnabled(not msg)
