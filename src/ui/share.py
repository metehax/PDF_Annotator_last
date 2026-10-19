"""
ui/share.py
===========
"Telefonla aktar (QR)" penceresi: yerel ağda geçici, anahtarlı küçük bir web
sunucusu (qrshare.ShareServer) açar, QR'ı gösterir. Telefondan gelen dosyalar
kaydedilip uygulamada açılır; açık belge telefona indirilmek üzere sunulabilir.
Pencere kapanınca (ya da boşta kalınca) sunucu durur.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from typing import List, Optional
from urllib.parse import urlparse

from PySide6.QtCore import QSize, QStandardPaths, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QLineEdit, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

import qrshare
import scan
import sharing
import workspace
from pdf_engine import IMAGE_EXTS
from ui.icons import icon

IDLE_LIMIT_S = 15 * 60
WIFI_SETTINGS_URL = "ms-settings:network-wifi"
HOTSPOT_HELP = (
    "<b>Aynı ağda değil misiniz? Mobil sıcak nokta kullanın (internet gerekmez):</b><br>"
    "1. Telefonda <i>Mobil sıcak nokta / Kişisel erişim noktası</i>nı açın.<br>"
    "2. Bu bilgisayarı telefonun Wi‑Fi ağına bağlayın.<br>"
    "3. Yukarıdaki <i>Ağ adresi</i> listesinden yeni adresi seçin; QR'ı telefonla yeniden okutun.<br>"
    "Aktarım doğrudan telefon ile bilgisayar arasında kalır, hiçbir dış servis kullanılmaz.")
TUNNEL_WARN = (
    "<b>Deneysel:</b> Kendi kurduğunuz bir tünel (cloudflared, ngrok vb.) adresini girin; tüneli bu bilgisayarda "
    "<i>yerel bağlantı noktası</i>na yönlendirin. Uygulama üçüncü taraf bir servisle <u>kendisi bağlanmaz</u>; ancak "
    "dosyalar o servisten geçer. Bu kipte telefon önce 6 haneli PIN'i girmelidir; 5 yanlış denemede kilitlenir.")
QR_PX = 240


def _bool(v) -> bool:
    return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")


def default_receive_dir() -> str:
    docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return os.path.join(docs or os.path.expanduser("~"), "PDF Annotator Gelen")


class ShareDialog(QDialog):
    received = Signal(str)                    # sunucu iş parçacığından ana iş parçacığına

    def __init__(self, main, host: Optional[str] = None, receive_dir: Optional[str] = None):
        super().__init__(main)
        self.setWindowTitle("Telefonla aktar (QR)")
        self.resize(580, 760)
        self._main = main
        self._server: Optional[qrshare.ShareServer] = None
        self._tmp: Optional[str] = None
        self._receive_dir = receive_dir or str(main.settings.value("qrReceiveDir", "") or workspace.out_dir("inbox") or default_receive_dir())
        self._forced_host = host
        st = main.settings
        self.idle_limit = max(1, int(st.value("share/idle_min", IDLE_LIMIT_S // 60) or 15)) * 60
        self.max_bytes = max(1, int(st.value("share/max_mb", 200) or 200)) * 1024 * 1024
        self._pin_default = _bool(st.value("share/pin_default", False))

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)
        title = QLabel("Telefonla dosya aktar")
        title.setObjectName("propTitle")
        v.addWidget(title)
        self.hint = QLabel("Telefonun kamerasıyla QR'ı okutun; açılan sayfadan dosya ya da fotoğraf seçin, "
                           "kamerayla çekin veya bilgisayardan belge indirin.")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)

        self.qr = QLabel()
        self.qr.setFixedSize(QR_PX + 24, QR_PX + 24)
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setStyleSheet("background:#ffffff; border-radius:12px;")
        v.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignHCenter)

        self.url_lbl = QLabel()
        self.url_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.url_lbl.setWordWrap(True)
        self.url_lbl.setContentsMargins(0, 8, 0, 4)
        v.addWidget(self.url_lbl)
        row = QHBoxLayout()
        self.ip_combo = QComboBox()
        self.ip_combo.setToolTip("Birden fazla ağ varsa telefonun bağlı olduğu ağın adresini seçin")
        self.ip_combo.currentIndexChanged.connect(self._ip_changed)
        self.btn_copy = QPushButton(icon("copy"), "Bağlantıyı kopyala")
        self.btn_copy.setObjectName("secondary")
        self.btn_copy.clicked.connect(self._copy_url)
        row.addWidget(QLabel("Ağ adresi:"))
        row.addWidget(self.ip_combo, 1)
        row.addWidget(self.btn_copy)
        v.addLayout(row)

        # -- aynı ağda değil misiniz? ----------------------------------------------
        self.btn_help = QPushButton("Aynı ağda değil misiniz?")
        self.btn_help.setObjectName("secondary")
        self.btn_help.setCheckable(True)
        self.btn_help.toggled.connect(lambda on: self.help_box.setVisible(on))
        v.addWidget(self.btn_help)
        self.help_box = QWidget()
        hb = QVBoxLayout(self.help_box)
        hb.setContentsMargins(0, 0, 0, 0)
        self.help_lbl = QLabel(HOTSPOT_HELP)
        self.help_lbl.setObjectName("hint")
        self.help_lbl.setWordWrap(True)
        hb.addWidget(self.help_lbl)
        self.btn_wifi = QPushButton("Wi‑Fi ayarlarını aç")
        self.btn_wifi.setObjectName("secondary")
        self.btn_wifi.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(WIFI_SETTINGS_URL)))
        hb.addWidget(self.btn_wifi)
        self.help_box.hide()
        v.addWidget(self.help_box)

        # -- gelişmiş: kendi internet tüneli + PIN ----------------------------------
        self.chk_tunnel = QCheckBox("Gelişmiş: kendi internet tünelimi kullanacağım (PIN'li)")
        self.chk_tunnel.toggled.connect(lambda on: self.set_tunnel(on))
        v.addWidget(self.chk_tunnel)
        self.tunnel_box = QWidget()
        tb = QVBoxLayout(self.tunnel_box)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(6)
        self.tunnel_warn = QLabel(TUNNEL_WARN)
        self.tunnel_warn.setObjectName("hintWarn")
        self.tunnel_warn.setWordWrap(True)
        tb.addWidget(self.tunnel_warn)
        self.port_lbl = QLabel("")
        self.port_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        tb.addWidget(self.port_lbl)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Tünel adresi:"))
        self.tunnel_edit = QLineEdit()
        self.tunnel_edit.setPlaceholderText("https://ornek.trycloudflare.com")
        self.tunnel_edit.editingFinished.connect(lambda: self.set_tunnel_address(self.tunnel_edit.text()))
        trow.addWidget(self.tunnel_edit, 1)
        tb.addLayout(trow)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("PIN:"))
        self.pin_lbl = QLabel("")
        self.pin_lbl.setStyleSheet("font-size:24px; font-weight:700; letter-spacing:5px;")
        self.pin_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        prow.addWidget(self.pin_lbl)
        prow.addStretch(1)
        self.btn_newpin = QPushButton("Yeni PIN")
        self.btn_newpin.setObjectName("secondary")
        self.btn_newpin.clicked.connect(self.new_pin)
        self.btn_unlock = QPushButton("Kilidi aç")
        self.btn_unlock.setObjectName("secondary")
        self.btn_unlock.clicked.connect(self.unlock)
        prow.addWidget(self.btn_newpin)
        prow.addWidget(self.btn_unlock)
        tb.addLayout(prow)
        self.pin_state = QLabel("")
        self.pin_state.setObjectName("hint")
        self.pin_state.setWordWrap(True)
        tb.addWidget(self.pin_state)
        self.tunnel_box.hide()
        v.addWidget(self.tunnel_box)
        self._tunnel_on = False
        self._public_base = ""
        self._pin: Optional[str] = qrshare.generate_pin() if self._pin_default else None

        self.lan_pin = QLabel("")
        self.lan_pin.setObjectName("hint")
        self.lan_pin.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lan_pin.hide()
        v.addWidget(self.lan_pin)

        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)

        # -- sekme 1: telefondan al ---------------------------------------------------
        tab_in = QWidget()
        ti = QVBoxLayout(tab_in)
        ti.setContentsMargins(0, 8, 0, 0)
        ti.setSpacing(6)
        self.log = QListWidget()
        self.log.setMinimumHeight(110)
        self.log.setIconSize(QSize(44, 44))
        self.log.itemDoubleClicked.connect(self._open_item)
        self.log.itemSelectionChanged.connect(self._sync_row_buttons)
        ti.addWidget(self.log, 1)
        rb = QHBoxLayout()
        self.btn_row_scan = QPushButton(icon("scan"), "Tara")
        self.btn_row_open = QPushButton("Aç")
        self.btn_row_pdf = QPushButton(icon("image_pdf"), "PDF'e çevir")
        self.btn_row_show = QPushButton(icon("folder_open"), "Klasörde göster")
        self.btn_row_scan.clicked.connect(self.row_scan)
        self.btn_row_open.clicked.connect(self.row_open)
        self.btn_row_pdf.clicked.connect(self.row_pdf)
        self.btn_row_show.clicked.connect(self.row_show)
        for b_ in (self.btn_row_scan, self.btn_row_open, self.btn_row_pdf, self.btn_row_show):
            b_.setObjectName("secondary")
            rb.addWidget(b_)
        ti.addLayout(rb)
        r2 = QHBoxLayout()
        self.chk_open = QCheckBox("Gelen dosyaları otomatik aç")
        self.chk_open.setChecked(True)
        self.dir_lbl = QLabel()
        self.dir_lbl.setObjectName("hint")
        self.btn_dir = QPushButton("Klasör…")
        self.btn_dir.setObjectName("secondary")
        self.btn_dir.clicked.connect(self._change_dir)
        self.btn_folder = QPushButton(icon("folder"), "Aç")
        self.btn_folder.setObjectName("secondary")
        self.btn_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self._receive_dir)))
        r2.addWidget(self.chk_open, 1)
        r2.addWidget(self.btn_dir)
        r2.addWidget(self.btn_folder)
        ti.addLayout(r2)
        ti.addWidget(self.dir_lbl)
        r2b = QHBoxLayout()
        self.chk_scan = QCheckBox("İşlemi belirtilmeyen fotoğrafları tarayıcıya al")
        self.chk_scan.setToolTip("Telefon sayfasında “Belge tara” seçilen fotoğraflar her zaman tarayıcıya gider.")
        self.btn_scan = QPushButton(icon("scan"), "Taramayı bitir")
        self.btn_scan.setObjectName("secondary")
        self.btn_scan.clicked.connect(self.finish_scan)
        r2b.addWidget(self.chk_scan, 1)
        r2b.addWidget(self.btn_scan)
        ti.addLayout(r2b)
        self.chk_autoscan = QCheckBox("Gelen fotoğraflar gelince tarayıcıyı otomatik aç")
        self.chk_autoscan.setChecked(_bool(main.settings.value("share/auto_scan", True)))
        self.chk_autoscan.toggled.connect(lambda on: main.settings.setValue("share/auto_scan", bool(on)))
        ti.addWidget(self.chk_autoscan)
        self._scan_queue: List[str] = []
        self._scan_dlg = None
        self._sync_scan()
        self.tabs.addTab(tab_in, icon("phone"), "Telefondan al")

        # -- sekme 2: telefona gönder -------------------------------------------------
        tab_out = QWidget()
        to = QVBoxLayout(tab_out)
        to.setContentsMargins(0, 8, 0, 0)
        to.setSpacing(6)
        self.out_list = QListWidget()
        self.out_list.setMinimumHeight(90)
        to.addWidget(self.out_list, 1)
        r3 = QHBoxLayout()
        self.btn_offer = QPushButton(icon("phone"), "Açık belgeyi telefona sun")
        self.btn_offer.setObjectName("secondary")
        self.btn_offer.clicked.connect(self.offer_active)
        self.btn_offer_files = QPushButton(icon("plus"), "Dosya ekle…")
        self.btn_offer_files.setObjectName("secondary")
        self.btn_offer_files.clicked.connect(self._offer_dialog)
        self.btn_unoffer = QPushButton("Sunulanları kaldır")
        self.btn_unoffer.setObjectName("secondary")
        self.btn_unoffer.clicked.connect(self._unoffer)
        r3.addWidget(self.btn_offer, 1)
        r3.addWidget(self.btn_offer_files)
        r3.addWidget(self.btn_unoffer)
        to.addLayout(r3)
        self.offer_lbl = QLabel("")
        self.offer_lbl.setObjectName("hint")
        self.offer_lbl.setWordWrap(True)
        to.addWidget(self.offer_lbl)
        self.tabs.addTab(tab_out, icon("share"), "Telefona gönder")

        self.warn = QLabel("Telefon ve bilgisayar aynı Wi‑Fi ağında olmalı. Bağlanamazsa Windows Güvenlik Duvarı'nda "
                           "“özel ağlar”a izin verin. Bağlantı şifrelenmez (HTTP): yalnızca güvendiğiniz ağda kullanın. "
                           f"Pencere kapanınca ya da {self.idle_limit // 60} dk boşta kalınca sunucu durur.")
        self.warn.setObjectName("hintWarn")
        self.warn.setWordWrap(True)
        v.addWidget(self.warn)
        r4 = QHBoxLayout()
        r4.addStretch(1)
        self.btn_stop = QPushButton("Durdur ve kapat")
        self.btn_stop.clicked.connect(self.close)
        r4.addWidget(self.btn_stop)
        v.addLayout(r4)

        self.received.connect(self._on_received)
        self._idle = QTimer(self)
        self._idle.setInterval(5000)
        self._idle.timeout.connect(self._check_idle)

        ips = [host] if host else qrshare.lan_addresses()
        self.ip_combo.blockSignals(True)
        for ip in ips or ["127.0.0.1"]:
            self.ip_combo.addItem(ip)
        self.ip_combo.blockSignals(False)
        if not ips:
            self.hint.setText("Ağ bağlantısı bulunamadı; telefon bağlanamaz. Wi‑Fi'ye bağlanıp pencereyi yeniden açın.")
        self.dir_lbl.setText(f"Kaydedilen yer: {self._receive_dir}")
        self._start(self.ip_combo.currentText())
        self._sync_buttons()

    # -- sunucu --------------------------------------------------------------
    @property
    def server(self) -> Optional[qrshare.ShareServer]:
        return self._server

    def _start(self, host: str):
        old = self._server
        offers = old.listing() if old else []
        if old:
            old.stop()
        try:
            self._server = qrshare.ShareServer(self._receive_dir, on_received=self.received.emit, host=host,
                                               pin=self._pin, max_bytes=self.max_bytes).start()
        except OSError as ex:
            self._server = None
            QMessageBox.critical(self, "Sunucu açılamadı", f"{host} adresinde dinlenemedi:\n{ex}")
            self.url_lbl.setText("")
            self.qr.clear()
            return
        if offers and old and self._tmp:                       # adres değişince sunulanları yeni sunucuya taşı
            for it in old._offers:
                self._server.offer(it["path"], it["name"])
        self._show_url()
        self.refresh_pin_state()
        self._refresh_out()
        self._idle.start()

    def share_url(self) -> str:
        """Telefona verilecek adres: tünel kipinde tünel adresi + anahtar (adres girilmediyse boş), değilse yerel adres."""
        if self._server is None:
            return ""
        if self._tunnel_on:
            return f"{self._public_base}/{self._server.token}/" if self._public_base else ""
        return self._server.url

    def _show_url(self):
        url = self.share_url()
        if self._tunnel_on:
            self.port_lbl.setText(f"Yerel bağlantı noktası (tüneli buraya yönlendirin): http://127.0.0.1:{self._server.port}"
                                  if self._server else "")
        if not url:
            self.url_lbl.setText("Tünel adresini girin" if self._tunnel_on else "")
            self.qr.clear()
            return
        self.url_lbl.setText(url)
        pm = QPixmap()
        pm.loadFromData(qrshare.qr_png(url, scale=max(QR_PX // 41, 4)))
        self.qr.setPixmap(pm.scaled(QR_PX, QR_PX, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.FastTransformation))

    # -- internet tüneli + PIN ---------------------------------------------------
    @staticmethod
    def normalize_public_url(text: str) -> str:
        """Geçerli http(s) tünel adresini (sondaki / ve boşluk atılmış) döndürür; geçersizse boş."""
        t = (text or "").strip()
        u = urlparse(t)
        if u.scheme not in ("http", "https") or not u.netloc or any(c.isspace() for c in t) or u.query or u.fragment:
            return ""
        return t.rstrip("/")

    def set_tunnel(self, on: bool, address: Optional[str] = None):
        """Tünel kipini açar/kapatır. Açılınca sunucu yalnız 127.0.0.1'de PIN'li yeniden başlar; kapanınca yerel ağa döner.
        Uygulama tünel adresine kendisi bağlanmaz: adres yalnızca QR/bağlantı metninde kullanılır."""
        on = bool(on)
        self._tunnel_on = on
        self._pin = qrshare.generate_pin() if (on or self._pin_default) else None
        for w, state in ((self.chk_tunnel, on),):
            w.blockSignals(True)
            w.setChecked(state)
            w.blockSignals(False)
        self.tunnel_box.setVisible(on)
        self.ip_combo.setEnabled(not on)
        if on:
            saved = address if address is not None else str(self._main.settings.value("share/tunnelUrl", "") or "")
            self._public_base = self.normalize_public_url(saved)
            self.tunnel_edit.setText(self._public_base)
            self._start("127.0.0.1")
        else:
            self._public_base = ""
            self._start(self.ip_combo.currentText())
        self.refresh_pin_state()
        self._sync_buttons()

    def set_tunnel_address(self, text: str) -> bool:
        base = self.normalize_public_url(text)
        if not base:
            self.pin_state.setText("Geçerli bir adres girin (https://…).")
            return False
        self._public_base = base
        self._main.settings.setValue("share/tunnelUrl", base)
        self._show_url()
        self.refresh_pin_state()
        return True

    def refresh_pin_state(self):
        sv = self._server
        lan = bool(sv and sv.pin_required and not self._tunnel_on)
        self.lan_pin.setVisible(lan)
        if lan:
            self.lan_pin.setText(f"PIN: {sv.pin} (telefon ilk açılışta soracak)")
        self.pin_lbl.setText(sv.pin if sv and sv.pin_required else "")
        locked = bool(sv and sv.locked)
        self.btn_unlock.setVisible(self._tunnel_on and locked)
        self.btn_newpin.setEnabled(bool(sv and sv.pin_required))
        if not self._tunnel_on or sv is None:
            self.pin_state.setText("")
        elif locked:
            self.pin_state.setText("Çok fazla yanlış PIN denendi: kilitlendi. Tanıdığınız birine aitse “Kilidi aç”, değilse “Yeni PIN”.")
        else:
            self.pin_state.setText(f"{sv.attempts_left} yanlış deneme hakkı kaldı." if sv.failed_attempts else "PIN'i yalnızca telefondaki kişiye söyleyin.")

    def new_pin(self):
        if self._server is not None and self._server.pin_required:
            self._pin = self._server.new_pin()
            self.refresh_pin_state()

    def unlock(self):
        if self._server is not None:
            self._server.unlock()
            self.refresh_pin_state()

    def _copy_url(self):
        url = self.share_url()
        if url:
            QApplication.clipboard().setText(url)
            self._main.toasts.show("Bağlantı panoya kopyalandı", "success")

    def _ip_changed(self, _i):
        if self._server is not None:
            self._start(self.ip_combo.currentText())

    def _check_idle(self):
        if self._tunnel_on:
            self.refresh_pin_state()
        if self._server and self._server.idle_seconds() > self.idle_limit:
            self.stop()                       # önce zamanlayıcı + sunucu durur: bildirim bir kez çıkar
            if self.isVisible():              # pencere zaten kapalıysa (×/Esc) bildirim gösterilmez
                self._main.toasts.show("Telefon aktarımı boşta kaldığı için durduruldu.", "info")
                self.close()

    def stop(self):
        self._idle.stop()
        if self._server is not None:
            self._server.stop()
            self._server = None
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None

    def closeEvent(self, e):
        self.stop()
        super().closeEvent(e)

    def done(self, r):                        # Esc/reject/accept closeEvent çağırmaz: sunucu ve zamanlayıcı burada durur
        self.stop()
        super().done(r)

    # -- telefondan gelen ----------------------------------------------------
    def _is_image(self, path: str) -> bool:
        return os.path.splitext(path)[1].lower() in IMAGE_EXTS

    def _on_received(self, path: str):
        name = os.path.basename(path)
        action = self._server.actions.get(path, "") if self._server else ""
        it = QListWidgetItem(f"{time.strftime('%H:%M')}   ✓ {name}")
        it.setData(Qt.ItemDataRole.UserRole, path)
        if self._is_image(path):
            pm = QPixmap(path)
            if not pm.isNull():
                it.setIcon(QIcon(pm.scaled(88, 88, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.FastTransformation)))
        self.log.insertItem(0, it)
        self._main.toasts.show(f"Telefondan alındı: {name}", "success")
        if self._is_image(path) and (action == "scan" or (not action and self.chk_scan.isChecked())):
            self._scan_queue.append(path)                    # taramaya gider; belge olarak açılmaz
            self._sync_scan()
            if self.chk_autoscan.isChecked():
                self.finish_scan()
        elif self._is_image(path) and action == "pdf":
            self._to_pdf([path], open_result=self.chk_open.isChecked())
        elif self.chk_open.isChecked():
            self._main.open_paths([path])

    def _sync_scan(self):
        n = len(self._scan_queue)
        self.btn_scan.setText(f"Taramayı bitir ({n})" if n else "Taramayı bitir")
        self.btn_scan.setEnabled(n > 0)

    def finish_scan(self):
        """Biriken fotoğrafları belge tarama penceresinde açar (pencere zaten açıksa oraya ekler) ve kuyruğu boşaltır."""
        paths = [p for p in self._scan_queue if os.path.exists(p)]
        self._scan_queue = []
        self._sync_scan()
        if not paths:
            return None
        sd = self._scan_dlg
        if sd is not None and sd.isVisible():
            sd.add_sources(paths)
            return sd
        self._scan_dlg = self._main.scan_images(paths)
        return self._scan_dlg

    # -- listedeki satır eylemleri ------------------------------------------------
    def _row_path(self) -> Optional[str]:
        it = self.log.currentItem()
        p = it.data(Qt.ItemDataRole.UserRole) if it else None
        return p if p and os.path.exists(p) else None

    def _sync_row_buttons(self):
        p = self._row_path()
        img = bool(p) and self._is_image(p)
        self.btn_row_scan.setEnabled(img or (bool(p) and p.lower().endswith(".pdf")))
        self.btn_row_open.setEnabled(bool(p))
        self.btn_row_pdf.setEnabled(img)
        self.btn_row_show.setEnabled(bool(p))

    def row_scan(self):
        p = self._row_path()
        if p:
            self._scan_queue.append(p)
            self._sync_scan()
            return self.finish_scan()

    def row_open(self):
        p = self._row_path()
        if p:
            self._main.open_paths([p])

    def row_pdf(self):
        p = self._row_path()
        if p and self._is_image(p):
            return self._to_pdf([p], open_result=True)

    def row_show(self):
        p = self._row_path()
        if p:
            sharing.reveal(p)

    def _to_pdf(self, paths, open_result: bool = False):
        """Görselleri (yanlarına) PDF yapar; var olan dosyanın üstüne yazmaz."""
        outs = []
        for p in paths:
            base = os.path.splitext(p)[0]
            out = base + ".pdf"
            n = 2
            while os.path.exists(out):
                out = f"{base} ({n}).pdf"
                n += 1
            try:
                scan.images_to_pdfs([p], out, False)
            except Exception as ex:
                QMessageBox.critical(self, "Hata", f"PDF'e çevrilemedi:\n{ex}")
                continue
            outs.append(out)
        if outs:
            self._main.toasts.show(f"PDF oluşturuldu: {os.path.basename(outs[0])}", "success")
            if open_result:
                self._main.open_paths(outs)
        return outs

    def _open_item(self, item):
        p = item.data(Qt.ItemDataRole.UserRole)
        if p and os.path.exists(p):
            self._main.open_paths([p])

    def _change_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Gelen dosyaların kaydedileceği klasör", self._receive_dir)
        if d:
            self._receive_dir = d
            self._main.settings.setValue("qrReceiveDir", d)
            if self._server:
                self._server.receive_dir = d
            self.dir_lbl.setText(f"Kaydedilen yer: {d}")

    # -- telefona gönder -----------------------------------------------------
    def _sync_buttons(self):
        self.btn_offer.setEnabled(self._main.active_session is not None and self._server is not None)
        self.btn_offer_files.setEnabled(self._server is not None)
        self.btn_unoffer.setEnabled(bool(self._server and self._server.listing()))

    def _refresh_out(self):
        self.out_list.clear()
        if self._server:
            for f in self._server.listing():
                self.out_list.addItem(f"⬇ {f['name']}")

    def _offer_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Telefona sunulacak dosyalar", "", "Tüm dosyalar (*.*)")
        self.offer_files(files)

    def offer_files(self, files):
        """Seçilen dosyaları telefonda indirme listesine koyar (belge kopyalanmaz, yol sunulur)."""
        if self._server is None:
            return 0
        n = 0
        for f in files:
            if os.path.isfile(f):
                self._server.offer(f, os.path.basename(f))
                n += 1
        if n:
            self.offer_lbl.setText(f"{n} dosya sunuldu. Telefondaki sayfada “Bilgisayardan indir” bölümünde görünür.")
        self._refresh_out()
        self._sync_buttons()
        return n

    def offer_active(self):
        s = self._main.active_session
        if s is None or self._server is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self._tmp is None:
                self._tmp = tempfile.mkdtemp(prefix="pdfannot_qr_")
            base = os.path.splitext(os.path.basename(s.path or s.title or "belge"))[0] or "belge"
            path = os.path.join(self._tmp, base + ".pdf")
            snap = s.pdf._annotated_copy(s.annotations, self._main.font_ctx)
            try:
                snap.save(path, garbage=3, deflate=True)
            finally:
                snap.close()
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Hata", f"Belge hazırlanamadı:\n{ex}")
            return
        QApplication.restoreOverrideCursor()
        self._server.offer(path, base + ".pdf")
        self.offer_lbl.setText(f"Sunuluyor: {base}.pdf (işaretlerinizle). Telefondaki sayfada “Bilgisayardan indir” "
                               "bölümünde birkaç saniye içinde görünür. Belgeyi değiştirdiyseniz yeniden sunun.")
        self._refresh_out()
        self._sync_buttons()

    def _unoffer(self):
        if self._server:
            self._server.clear_offers()
        self.offer_lbl.setText("")
        self.out_list.clear()
        self._sync_buttons()
