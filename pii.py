"""
pii.py
======
Kişisel veri (KVKK) bulucu: sayfadaki TC kimlik numarası, IBAN, telefon,
e-posta, araç plakası ve kart numaralarını bulur ve her eşleşmenin sayfa
üzerindeki kutusunu döndürür.

* Metin, kelimeler konumlarıyla birlikte okunur (PyMuPDF "words"). Sayfada
  gerçek metin yoksa (taranmış sayfa/resim) isteğe bağlı olarak OCR yapılır.
* Her satır tek bir metin olarak birleştirilip düzenli ifadelerle aranır;
  eşleşmenin karakter aralığı kelime kutularına geri çevrilir (kelimenin
  yalnızca bir kısmı eşleştiyse kutu karakter oranına göre daraltılır).
* Yanlış alarmı azaltmak için TC kimlik no, IBAN ve kart numaraları kontrol
  haneleriyle doğrulanır.

Arayüzden bağımsızdır (Qt kullanmaz); doğrudan test edilebilir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import pymupdf as fitz

CATEGORIES: Dict[str, str] = {
    "tc": "TC Kimlik No",
    "iban": "IBAN",
    "phone": "Telefon",
    "email": "E-posta",
    "plate": "Plaka",
    "card": "Kart No",
}


@dataclass
class Hit:
    kind: str                      # CATEGORIES anahtarı
    text: str                      # bulunan değer (olduğu gibi)
    rect: Tuple[float, float, float, float]   # sayfa koordinatı (döndürülmüş görünüm)
    page: int = 0

    @property
    def label(self) -> str:
        return CATEGORIES.get(self.kind, self.kind)

    def masked(self) -> str:
        """Listede gösterim için ortası gizlenmiş değer."""
        t = self.text.strip()
        if self.kind == "email" and "@" in t:
            user, dom = t.split("@", 1)
            return (user[:2] + "•" * max(1, len(user) - 2)) + "@" + dom
        compact = re.sub(r"\s", "", t)
        if len(compact) <= 4:
            return "•" * len(compact)
        keep = 2 if len(compact) < 10 else 3
        return compact[:keep] + "•" * (len(compact) - keep - 2) + compact[-2:]


# ---------------------------------------------------------------------------
# Doğrulayıcılar
# ---------------------------------------------------------------------------
def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def valid_tc(s: str) -> bool:
    d = [int(c) for c in _digits(s)]
    if len(d) != 11 or d[0] == 0:
        return False
    if (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10 != d[9]:
        return False
    return sum(d[:10]) % 10 == d[10]


def valid_iban(s: str) -> bool:
    t = re.sub(r"\s", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", t):
        return False
    if t.startswith("TR") and len(t) != 26:
        return False
    moved = t[4:] + t[:4]
    num = "".join(str(int(ch, 36)) for ch in moved)
    return int(num) % 97 == 1


def valid_luhn(s: str) -> bool:
    d = _digits(s)
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# ---------------------------------------------------------------------------
# Desenler (sıra önemlidir: önce uzun/özgül olanlar)
# ---------------------------------------------------------------------------
_SEP = r"[ \t.\-]?"
PATTERNS: List[Tuple[str, "re.Pattern", Optional[Callable[[str], bool]]]] = [
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), None),
    ("iban", re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}(?![A-Za-z0-9])"), valid_iban),
    ("card", re.compile(r"(?<![\d])[3-6]\d{3}(?:[ \-]?\d{4}){2}[ \-]?\d{1,7}(?![\d])"), valid_luhn),
    ("tc", re.compile(r"(?<![\d])[1-9](?: ?\d){10}(?![\d])"), valid_tc),
    ("phone", re.compile(
        r"(?<![\d+(])(?:(?:\+ ?90|0090)" + _SEP + r")?(?:\(0?[2-5]\d{2}\)|(?:0" + _SEP + r")?[2-5]\d{2})"
        + _SEP + r"\d{3}" + _SEP + r"\d{2}" + _SEP + r"\d{2}(?![\d])"), None),
    ("plate", re.compile(
        r"(?<![A-Za-z0-9])(?:0[1-9]|[1-7]\d|8[01]) ?"
        r"(?:[A-PR-VYZ] ?\d{4,5}|[A-PR-VYZ]{2} ?\d{3,4}|[A-PR-VYZ]{3} ?\d{2,3})(?![A-Za-z0-9])"), None),
]


def _phone_ok(text: str) -> bool:
    d = _digits(text)
    if d.startswith("0090"):
        d = d[4:]
    elif d.startswith("90") and text.strip().startswith("+"):
        d = d[2:]
    elif d.startswith("0"):
        d = d[1:]
    if len(d) != 10:
        return False
    # öneksiz yazımda yalnızca cep numaraları (5xx) kabul edilir
    has_prefix = len(_digits(text)) > 10
    return d[0] == "5" or has_prefix


def find_in_text(text: str, kinds: Iterable[str]) -> List[Tuple[str, int, int]]:
    """(tür, başlangıç, bitiş) listesi. Çakışan eşleşmelerde önce gelen kazanır."""
    kinds = set(kinds)
    taken: List[Tuple[int, int]] = []
    out: List[Tuple[str, int, int]] = []
    for kind, rx, check in PATTERNS:
        if kind not in kinds:
            continue
        for m in rx.finditer(text):
            a, b = m.span()
            val = m.group(0)
            if check is not None and not check(val):
                continue
            if kind == "phone" and not _phone_ok(val):
                continue
            if any(a < tb and ta < b for ta, tb in taken):
                continue
            taken.append((a, b))
            out.append((kind, a, b))
    out.sort(key=lambda x: x[1])
    return out


# ---------------------------------------------------------------------------
# Sayfa tarama
# ---------------------------------------------------------------------------
Word = Tuple[float, float, float, float, str, int, int, int]


def _line_groups(words: Sequence[Word]):
    groups: Dict[Tuple[int, int], List[Word]] = {}
    for w in words:
        groups.setdefault((w[5], w[6]), []).append(w)
    for key in sorted(groups):
        yield sorted(groups[key], key=lambda w: w[7])


def find_in_words(words: Sequence[Word], kinds: Iterable[str]) -> List[Hit]:
    hits: List[Hit] = []
    for line in _line_groups(words):
        spans = []
        parts = []
        pos = 0
        for w in line:
            text = w[4]
            spans.append((pos, pos + len(text), w))
            parts.append(text)
            pos += len(text) + 1
        joined = " ".join(parts)
        for kind, a, b in find_in_text(joined, kinds):
            x0 = y0 = float("inf")
            x1 = y1 = float("-inf")
            for wa, wb, w in spans:
                if wb <= a or wa >= b:
                    continue
                n = max(1, wb - wa)
                fa = (max(a, wa) - wa) / n
                fb = (min(b, wb) - wa) / n
                ww = w[2] - w[0]
                x0 = min(x0, w[0] + ww * fa)
                x1 = max(x1, w[0] + ww * fb)
                y0 = min(y0, w[1])
                y1 = max(y1, w[3])
            if x1 > x0 and y1 > y0:
                hits.append(Hit(kind, joined[a:b], (x0, y0, x1, y1)))
    return hits


def page_words(page: "fitz.Page", ocr: Optional[Tuple[str, str]] = None, dpi: int = 300) -> List[Word]:
    """Sayfanın kelimeleri (döndürülmüş görünüm koordinatlarıyla). Sayfada
    gerçek metin yoksa ve ocr=(tessdata, dil) verildiyse OCR yapılır."""
    words = page.get_text("words")
    if not words and ocr is not None:
        tessdata, lang = ocr
        tp = page.get_textpage_ocr(language=lang, tessdata=tessdata, dpi=dpi, full=True)
        words = page.get_text("words", textpage=tp)
    if page.rotation:
        m = page.rotation_matrix
        out = []
        for w in words:
            r = fitz.Rect(w[:4]) * m
            out.append((r.x0, r.y0, r.x1, r.y1) + tuple(w[4:]))
        words = out
    return list(words)


def scan_page(page: "fitz.Page", kinds: Iterable[str], ocr: Optional[Tuple[str, str]] = None) -> List[Hit]:
    hits = find_in_words(page_words(page, ocr), kinds)
    for h in hits:
        h.page = page.number
    return hits
