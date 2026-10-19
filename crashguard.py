"""
crashguard.py
=============
Güvenlik ağı: yakalanmamış Python hataları (ana + arka plan iş parçacıkları), Qt iletileri ve yerel
(MuPDF/Qt) çökmeler çalışma klasörünün `Gunlukler` alt klasöründeki günlüğe yazılır.

* `pdfannotator.log`  — dönen günlük (en çok ~1 MB x 3 dosya)
* `yerel_cokme.log`   — `faulthandler` (C seviyesi çökme izi); açılışta büyükse sıfırlanır

Yakalanmamış hata uygulamayı kapatmaz; kullanıcıya bir kez sade bir uyarı gösterilir (`notifier`).
Aynı hata art arda tekrar uyarı açmaz (anahtar = hata türü + son çerçeve; `COOLDOWN_S` içinde bastırılır).
"""
from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import os
import sys
import threading
import time
import traceback
from typing import Callable, Optional

import workspace

LOG_NAME = "pdfannotator.log"
NATIVE_NAME = "yerel_cokme.log"
MAX_BYTES = 1_000_000
BACKUPS = 3
COOLDOWN_S = 60.0
MAX_ACTIVE_KEYS = 200

_logger: Optional[logging.Logger] = None
_native_file = None
_notifier: Optional[Callable[[str, str], None]] = None     # (özet, günlük_yolu) — ana iş parçacığında çağrılır
_seen: dict = {}
_lock = threading.Lock()
_prev_excepthook = None
_prev_thread_hook = None


def log_dir() -> str:
    """`<çalışma klasörü>\\Gunlukler` (yoksa oluşturur; oluşturulamazsa geçici klasör)."""
    d = os.path.join(workspace.root(), "Gunlukler")
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        import tempfile
        d = os.path.join(tempfile.gettempdir(), "PDFAnnotator_Gunlukler")
        os.makedirs(d, exist_ok=True)
        return d


def log_path() -> str:
    return os.path.join(log_dir(), LOG_NAME)


def get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        lg = logging.getLogger("pdfannotator")
        lg.setLevel(logging.INFO)
        lg.propagate = False
        try:
            h = logging.handlers.RotatingFileHandler(log_path(), maxBytes=MAX_BYTES, backupCount=BACKUPS,
                                                     encoding="utf-8", delay=True)
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
            lg.addHandler(h)
        except OSError:
            lg.addHandler(logging.NullHandler())
        _logger = lg
    return _logger


def _error_key(exc_type, exc, tb) -> str:
    where = ""
    try:
        fr = traceback.extract_tb(tb)
        if fr:
            where = f"{os.path.basename(fr[-1].filename)}:{fr[-1].lineno}"
    except Exception:
        pass
    return f"{getattr(exc_type, '__name__', exc_type)}@{where}"


def should_notify(key: str, now: Optional[float] = None) -> bool:
    """Aynı anahtar `COOLDOWN_S` içinde yeniden uyarı üretmez."""
    now = time.monotonic() if now is None else now
    with _lock:
        last = _seen.get(key)
        if last is not None and now - last < COOLDOWN_S:
            return False
        if len(_seen) >= MAX_ACTIVE_KEYS:
            _seen.clear()
        _seen[key] = now
        return True


def report(exc_type, exc, tb, origin: str = "ana") -> None:
    """Hatayı günlüğe yazar ve (bastırılmadıysa) kullanıcıya bildirir. Asla istisna fırlatmaz."""
    try:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        get_logger().error("Yakalanmamış hata (%s iş parçacığı):\n%s", origin, text)
        try:
            sys.stderr.write(text)
        except Exception:
            pass
        if _notifier is not None and should_notify(_error_key(exc_type, exc, tb)):
            _notifier(f"{getattr(exc_type, '__name__', 'Hata')}: {exc}", log_path())
    except Exception:
        pass


def _excepthook(exc_type, exc, tb):
    report(exc_type, exc, tb, "ana")


def _thread_hook(args):
    if args.exc_type is SystemExit:
        return
    report(args.exc_type, args.exc_value, args.exc_traceback, getattr(args.thread, "name", "arka plan"))


def _qt_handler(mode, context, message):
    try:
        from PySide6.QtCore import QtMsgType
        lvl = {QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
               QtMsgType.QtFatalMsg: logging.CRITICAL}.get(mode)
        if lvl is None:
            return                                   # debug/info: gürültü
        if "propagateSizeHints" in message or "QFont::setPointSize" in message:
            return                                   # zararsız, çok sık
        get_logger().log(lvl, "Qt: %s", message)
    except Exception:
        pass


def install(notifier: Optional[Callable[[str, str], None]] = None) -> str:
    """Kancaları kurar; günlük dosyasının yolunu döndürür. `notifier` ana iş parçacığında çalıştırılmalıdır
    (başka iş parçacığından gelen hata için çağıran taraf sinyalle ana iş parçacığına yönlendirir)."""
    global _notifier, _prev_excepthook, _prev_thread_hook, _native_file
    _notifier = notifier
    get_logger().info("--- oturum başladı ---")
    _prev_excepthook, sys.excepthook = sys.excepthook, _excepthook
    _prev_thread_hook, threading.excepthook = threading.excepthook, _thread_hook
    try:
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(_qt_handler)
    except Exception:
        pass
    try:
        p = os.path.join(log_dir(), NATIVE_NAME)
        if os.path.exists(p) and os.path.getsize(p) > MAX_BYTES:
            os.remove(p)
        _native_file = open(p, "a", encoding="utf-8")
        _native_file.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} oturum ===\n")
        _native_file.flush()
        faulthandler.enable(file=_native_file, all_threads=True)
    except Exception:
        _native_file = None
    return log_path()


def uninstall() -> None:
    """Testler için: kancaları geri alır."""
    global _notifier, _native_file
    _notifier = None
    if _prev_excepthook is not None:
        sys.excepthook = _prev_excepthook
    if _prev_thread_hook is not None:
        threading.excepthook = _prev_thread_hook
    try:
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(None)
    except Exception:
        pass
    try:
        faulthandler.disable()
        if _native_file is not None:
            _native_file.close()
    except Exception:
        pass
    _native_file = None
    _seen.clear()
