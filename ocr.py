"""OCR (optik karakter tanıma) katmanı.

PyMuPDF'in yerleşik Tesseract desteğini kullanır. Çalışması için yalnızca
dil dosyalarının (``tur.traineddata``, ``eng.traineddata``) bulunduğu bir
``tessdata`` klasörü gerekir. Aranan yerler (sırayla):

1. Uygulama klasöründeki ``tessdata/``
2. ``TESSDATA_PREFIX`` ortam değişkeni
3. Windows: ``C:\\Program Files\\Tesseract-OCR\\tessdata`` (UB Mannheim
   kurulumu) ve kullanıcı ``Programs`` klasörü
4. Linux/macOS: ``/usr/share/tesseract-ocr/*/tessdata`` vb.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import pymupdf as fitz

from appinfo import app_dir

APP_TESSDATA = os.path.join(app_dir(), "tessdata")
PREFERRED_LANGS = ["tur", "eng"]
DEFAULT_DPI = 300


class OcrUnavailable(RuntimeError):
    """Tesseract dil verisi bulunamadığında fırlatılır (kullanıcıya gösterilir)."""


def _candidate_dirs() -> List[str]:
    dirs = [APP_TESSDATA, os.environ.get("TESSDATA_PREFIX", "")]
    dirs += [
        r"C:\Program Files\Tesseract-OCR\tessdata",
        r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Tesseract-OCR\tessdata"),
        "/usr/local/share/tessdata",
        "/opt/homebrew/share/tessdata",
    ]
    dirs += glob.glob("/usr/share/tesseract-ocr/*/tessdata")
    dirs += ["/usr/share/tessdata"]
    return [d for d in dirs if d]


def installed_languages(tessdata: str) -> List[str]:
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(tessdata, "*.traineddata"))
                  if os.path.basename(p) != "osd.traineddata")


def find_tessdata() -> Optional[str]:
    """İçinde en az bir dil dosyası olan ilk tessdata klasörünü döner."""
    for d in _candidate_dirs():
        if os.path.isdir(d) and installed_languages(d):
            return d
    return None


def setup_message() -> str:
    return (
        "OCR için Tesseract dil verisi bulunamadı.\n\n"
        "Kurulum (biri yeterli):\n"
        "1) Tesseract'ı kurun (Windows: UB Mannheim yükleyicisi; kurulumda "
        "'Turkish' dilini işaretleyin), ya da\n"
        "2) tur.traineddata ve eng.traineddata dosyalarını (tessdata_fast deposundan) "
        f"şu klasöre koyun:\n{APP_TESSDATA}"
    )


def pick_language(tessdata: str, wanted: Optional[str] = None) -> str:
    """'tur+eng' gibi bir dil dizgesi üretir; yüklü olmayan dilleri eler."""
    have = set(installed_languages(tessdata))
    if wanted:
        req = [x for x in wanted.split("+") if x]
    else:
        req = PREFERRED_LANGS
    use = [x for x in req if x in have]
    if not use:
        use = [sorted(have)[0]]
    return "+".join(use)


def open_snapshot(pdf_doc: "fitz.Document", lock) -> "fitz.Document":
    """Ana belgenin bağımsız bir kopyasını açar; OCR arka plan iş parçacığında
    ana belgeye dokunmadan çalışır (MuPDF thread-safe değildir)."""
    with lock:
        return fitz.open("pdf", pdf_doc.write())


def ocr_pages(doc: "fitz.Document", pages: List[int], language: str, tessdata: str,
              dpi: int = DEFAULT_DPI,
              progress: Optional[Callable[[int, int], None]] = None,
              cancelled: Optional[Callable[[], bool]] = None) -> List[str]:
    """Verilen sayfaların metnini OCR ile okur. Her sayfa için bir metin döner."""
    results: List[str] = []
    total = len(pages)
    for n, idx in enumerate(pages):
        if cancelled is not None and cancelled():
            break
        page = doc[idx]
        tp = page.get_textpage_ocr(flags=fitz.TEXT_PRESERVE_WHITESPACE, language=language,
                                   dpi=dpi, full=True, tessdata=tessdata)
        results.append(page.get_text("text", textpage=tp).strip())
        if progress is not None:
            progress(n + 1, total)
    return results


def make_searchable_pdf(doc: "fitz.Document", out_path: str, language: str, tessdata: str,
                        dpi: int = DEFAULT_DPI,
                        progress: Optional[Callable[[int, int], None]] = None,
                        cancelled: Optional[Callable[[], bool]] = None) -> bool:
    """Her sayfayı görüntüleyip OCR metin katmanı ekleyerek aranabilir/seçilebilir
    yeni bir PDF üretir. İptal edilirse False döner ve dosya yazılmaz."""
    out = fitz.open()
    total = doc.page_count
    try:
        for i in range(total):
            if cancelled is not None and cancelled():
                return False
            pix = doc[i].get_pixmap(dpi=dpi, alpha=False)
            data = pix.pdfocr_tobytes(language=language, tessdata=tessdata)
            with fitz.open("pdf", data) as one:
                out.insert_pdf(one)
            if progress is not None:
                progress(i + 1, total)
        out.save(out_path, garbage=3, deflate=True)
    finally:
        out.close()
    return True


def missing_languages(tessdata: str, wanted: Optional[List[str]] = None) -> List[str]:
    """İstenen (varsayılan: tur, eng) ama yüklü olmayan dilleri döner."""
    have = set(installed_languages(tessdata))
    return [x for x in (wanted or PREFERRED_LANGS) if x not in have]


# ---------------------------------------------------------------------------
# Düzenlenebilir metin satırları / blokları (metin düzenleme aracı için)
# ---------------------------------------------------------------------------
@dataclass
class TextItem:
    rect: Tuple[float, float, float, float]   # x0, y0, x1, y1 (PDF punto)
    text: str
    size: float
    color: Optional[Tuple[int, int, int]]     # None: bilinmiyor (örnekle)
    font: str = ""


def _span_color(c: int) -> Tuple[int, int, int]:
    return ((c >> 16) & 255, (c >> 8) & 255, c & 255)


def _parse_dict(data: dict, from_ocr: bool):
    lines: List[TextItem] = []
    blocks: List[TextItem] = []
    for b in data.get("blocks", []):
        if b.get("type", 0) != 0:
            continue
        block_lines: List[TextItem] = []
        for ln in b.get("lines", []):
            spans = [sp for sp in ln.get("spans", []) if sp.get("text", "").strip() or sp.get("text")]
            text = "".join(sp.get("text", "") for sp in spans).strip()
            if not text:
                continue
            x0, y0, x1, y1 = ln["bbox"]
            if from_ocr:
                size = max(4.0, (y1 - y0) / 1.0)
                color, font = None, ""
            else:
                big = max(spans, key=lambda sp: len(sp.get("text", "")))
                size = float(big.get("size", 11.0))
                color, font = _span_color(int(big.get("color", 0))), big.get("font", "")
            block_lines.append(TextItem((x0, y0, x1, y1), text, size, color, font))
        if not block_lines:
            continue
        lines.extend(block_lines)
        bx0 = min(l.rect[0] for l in block_lines); by0 = min(l.rect[1] for l in block_lines)
        bx1 = max(l.rect[2] for l in block_lines); by1 = max(l.rect[3] for l in block_lines)
        first = block_lines[0]
        blocks.append(TextItem((bx0, by0, bx1, by1), "\n".join(l.text for l in block_lines),
                               first.size, first.color, first.font))
    return lines, blocks


def extract_items(page: "fitz.Page", tessdata: Optional[str], language: str,
                  force_ocr: bool = False, dpi: int = DEFAULT_DPI) -> Dict:
    """Sayfadaki metni satır ve paragraf olarak döner. Sayfada gerçek metin
    katmanı varsa onu kullanır (font/punto/renk dahil); yoksa ya da
    ``force_ocr`` ise OCR uygular. Sonuç: {"source", "lines", "blocks"}."""
    if not force_ocr and page.get_text("text").strip():
        lines, blocks = _parse_dict(page.get_text("dict"), from_ocr=False)
        return {"source": "native", "lines": lines, "blocks": blocks}
    if tessdata is None:
        raise OcrUnavailable(setup_message())
    tp = page.get_textpage_ocr(flags=fitz.TEXT_PRESERVE_WHITESPACE, language=language,
                               dpi=dpi, full=True, tessdata=tessdata)
    lines, blocks = _parse_dict(page.get_text("dict", textpage=tp), from_ocr=True)
    return {"source": "ocr", "lines": lines, "blocks": blocks}


def sample_colors(page: "fitz.Page", rect: Tuple[float, float, float, float],
                  zoom: float = 3.0) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """Bir metin kutusunun arka plan rengini (kenar halkasının medyanı) ve yazı
    rengini (arka plandan en uzak piksellerin ortalaması) örnekler."""
    from PIL import Image
    clip = fitz.Rect(*rect) + (-3, -3, 3, 3)
    clip = clip & page.rect
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    w, h = img.size
    px = img.load()
    ring = []
    band = 2
    for y in range(h):
        for x in range(w):
            if x < band or y < band or x >= w - band or y >= h - band:
                ring.append(px[x, y])
    if not ring:
        return (255, 255, 255), (0, 0, 0)
    bg = tuple(sorted(c[i] for c in ring)[len(ring) // 2] for i in range(3))
    far = []
    for y in range(band, h - band):
        for x in range(band, w - band):
            c = px[x, y]
            d = abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2])
            far.append((d, c))
    if not far:
        return bg, (0, 0, 0)
    far.sort(key=lambda t: t[0], reverse=True)
    top = [c for _, c in far[:max(1, len(far) // 25)]]
    fg = tuple(sum(c[i] for c in top) // len(top) for i in range(3))
    return bg, fg
