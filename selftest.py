"""`--selftest`: pencere açmadan modülleri, kaynak dosyaları ve çekirdekleri sınar (derleme denetimi).

Sonuç `selftest.txt`a yazılır (pencereli exe'de konsol yoktur); hata varsa çıkış kodu 1."""
import importlib
import os
import sys
import tempfile
import time

import appinfo

MODULES = [
    "a11y", "convert", "crashguard", "digisign", "docsec", "fonts", "forms", "gizmo", "headfoot", "main_window",
    "models", "mw_annot", "mw_build", "mw_common", "mw_compare", "mw_doctools", "mw_export", "mw_forms",
    "mw_nav", "mw_notes", "mw_ocr", "mw_pages", "mw_share", "mw_sign", "mw_workspace", "ocr", "pdf_engine",
    "pii", "qrshare", "scan", "sharing", "textdiff", "views", "workflow", "workspace",
    "ui.a11y", "ui.comments", "ui.compare", "ui.convert", "ui.docdialogs", "ui.flatten", "ui.formui",
    "ui.icons", "ui.imgpdf", "ui.kvkk", "ui.ocrdialog", "ui.overlays", "ui.pagetools", "ui.palette",
    "ui.preferences", "ui.redactopts", "ui.scanner", "ui.share", "ui.sidepanel", "ui.signatures",
    "ui.stamps", "ui.textdialog", "ui.theme", "ui.toast", "ui.watermark", "ui.welcome", "ui.widgets",
    "ui.workflow",
    # üçüncü taraf: dinamik içe aktarılanlar PyInstaller'da kolay eksik kalır
    "pymupdf", "pdf2docx", "pyhanko.sign", "pyhanko.pdf_utils.reader", "segno", "openpyxl", "cv2", "numpy", "PIL",
    "PySide6.QtSvg", "PySide6.QtPrintSupport", "PySide6.QtNetwork",
]


def _make_pdf(text="Merhaba dunya. Bu bir deneme belgesidir."):
    import pymupdf as fitz
    d = fitz.open()
    pg = d.new_page()
    pg.insert_text((72, 100), text, fontsize=18)
    pg.insert_text((72, 140), "Ad    Tutar", fontsize=12)
    out = d.tobytes()
    d.close()
    return out


def run(argv):
    args = [a for a in argv[1:] if a != "--selftest"]
    if args:
        out_file = args[0]
    else:
        base = os.path.dirname(sys.executable) if appinfo.frozen() else os.path.dirname(os.path.abspath(__file__))
        out_file = os.path.join(base, "selftest.txt")
    lines, bad = [], []
    t0 = time.time()

    def step(name, fn):
        try:
            extra = fn()
            lines.append(f"OK    {name}" + (f"  [{extra}]" if extra else ""))
        except BaseException as ex:                       # noqa: BLE001 — her hata rapora girer
            bad.append(name)
            lines.append(f"FAIL  {name}: {type(ex).__name__}: {ex}")

    lines.append(f"{appinfo.APP_NAME} {appinfo.VERSION}  frozen={appinfo.frozen()}  python={sys.version.split()[0]}")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    tmp = tempfile.mkdtemp(prefix="pdfa_selftest_")
    os.environ["PDF_ANNOTATOR_WORKSPACE"] = os.path.join(tmp, "ws")

    def imports():
        for m in MODULES:
            try:
                importlib.import_module(m)
            except BaseException as ex:                   # noqa: BLE001
                bad.append("içe aktarma " + m)
                lines.append(f"FAIL  import {m}: {type(ex).__name__}: {ex}")
        return f"{len(MODULES)} modül"
    step("modüller", imports)

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    def resources():
        import ocr
        import fonts
        td = ocr.find_tessdata()
        if not td:
            raise RuntimeError("tessdata bulunamadı")
        have = ocr.installed_languages(td)
        for need in ("tur", "eng"):
            if need not in have:
                raise RuntimeError(f"{need}.traineddata yok ({td})")
        if not any(n.lower().endswith(".ttf") for n in os.listdir(fonts._BUNDLED_DIR)):
            raise RuntimeError("fonts/ boş")
        return "tessdata=" + ",".join(have)
    step("tessdata + fontlar", resources)

    def icons():
        from ui import icons as ic
        from PySide6.QtCore import QSize
        n = 0
        for name in ic.names():
            if ic.icon(name).pixmap(QSize(24, 24)).isNull():
                raise RuntimeError("ikon boş: " + name)
            n += 1
        return f"{n} ikon"
    step("ikonlar (SVG)", icons)

    def render():
        import pymupdf as fitz
        d = fitz.open("pdf", _make_pdf())
        pix = d[0].get_pixmap(dpi=72)
        if pix.width < 100:
            raise RuntimeError("render boş")
        return f"{pix.width}x{pix.height}"
    step("PDF render", render)

    def ocr_run():
        import pymupdf as fitz
        import ocr
        d = fitz.open("pdf", _make_pdf("Merhaba dunya deneme"))
        pix = d[0].get_pixmap(dpi=200)
        data = pix.pdfocr_tobytes(language="eng", tessdata=ocr.find_tessdata())
        txt = fitz.open("pdf", data)[0].get_text().lower()
        if "merhaba" not in txt and "deneme" not in txt:
            raise RuntimeError("OCR metni bulunamadı: " + txt[:40])
        return txt.strip()[:30]
    step("OCR", ocr_run)

    def word():
        import convert
        out = os.path.join(tmp, "a.docx")
        convert.to_docx(_make_pdf(), out)
        if not os.path.getsize(out):
            raise RuntimeError("docx boş")
    step("Word (pdf2docx)", word)

    def excel():
        import convert
        out = os.path.join(tmp, "a.xlsx")
        try:
            convert.to_xlsx(_make_pdf(), out)
        except convert.ConvertError:                      # örnekte tablo yok: motor çalıştı, yeter
            pass
    step("Excel (openpyxl)", excel)

    def qr():
        import qrshare
        if qrshare.qr_png("http://127.0.0.1:1/x/")[:4] != b"\x89PNG":
            raise RuntimeError("QR PNG değil")
    step("QR (segno)", qr)

    def scan():
        import numpy as np
        import scan as sc
        img = np.full((300, 400, 3), 255, np.uint8)
        img[60:240, 80:320] = 30
        c = sc.detect_corners(img, fallback=True)
        out = sc.apply_filter(sc.warp(img, c), "belge", 0, 0)
        p = os.path.join(tmp, "s.pdf")
        sc.to_pdf([out], p)
        if not os.path.getsize(p):
            raise RuntimeError("tarama PDF boş")
    step("Tarama (OpenCV)", scan)

    def window():
        import main_window
        import workspace
        from PySide6.QtCore import QSettings
        w = main_window.MainWindow()
        w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
        workspace.configure(w.settings)
        w.close()
    step("ana pencere kurulumu", window)

    lines.append(("HATA: " + ", ".join(bad)) if bad else "TAMAM")
    lines[-1] += f"  ({time.time() - t0:.1f} sn)"
    text = "\n".join(lines) + "\n"
    for target in (out_file, os.path.join(tempfile.gettempdir(), "pdfannotator_selftest.txt")):
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(text)
            break
        except OSError:
            continue
    try:
        sys.stdout.write(text)
    except Exception:                                      # noqa: BLE001 — pencereli exe'de stdout yok
        pass
    del app
    return 1 if bad else 0
