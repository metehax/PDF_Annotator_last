"""İki belge sürümünün metin karşılaştırması (arayüzsüz çekirdek).

Önce satır düzeyinde, değişen satır öbeklerinin içinde kelime düzeyinde fark
alınır. Konumlar sayfa pt cinsindendir ve sayfanın GÖRÜNEN (döndürülmüş)
yönüne çevrilmiştir; böylece ComparePane sahnesine doğrudan çizilir.
"""
from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import fitz

Rect4 = Tuple[float, float, float, float]
KIND_LABEL = {"add": "Eklendi", "del": "Silindi", "mod": "Değişti"}


@dataclass
class Word:
    page: int
    rect: Rect4
    text: str
    line: int                       # belge genelinde benzersiz satır kimliği


def _union(rects) -> Rect4:
    xs0, ys0, xs1, ys1 = zip(*rects)
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def _spans(words: List[Word]) -> List[Tuple[int, Rect4]]:
    """Ardışık, aynı satırdaki kelimeleri tek dikdörtgende birleştirir."""
    out: List[Tuple[int, Rect4]] = []
    group: List[Word] = []
    for w in words + [None]:
        if group and (w is None or w.line != group[0].line or w.page != group[0].page):
            out.append((group[0].page, _union([g.rect for g in group])))
            group = []
        if w is not None:
            group.append(w)
    return out


@dataclass
class Change:
    kind: str                                   # 'add' | 'del' | 'mod'
    a_words: List[Word] = field(default_factory=list)
    b_words: List[Word] = field(default_factory=list)
    a_anchor: Optional[Word] = None             # eklemede eski belgedeki karşılık noktası
    b_anchor: Optional[Word] = None             # silmede yeni belgedeki karşılık noktası

    def __post_init__(self):
        self.a_rects = _spans(self.a_words)
        self.b_rects = _spans(self.b_words)

    @property
    def text_a(self) -> str:
        return " ".join(w.text for w in self.a_words)

    @property
    def text_b(self) -> str:
        return " ".join(w.text for w in self.b_words)

    def focus_a(self) -> Optional[Tuple[int, Rect4]]:
        if self.a_rects:
            return self.a_rects[0]
        return (self.a_anchor.page, self.a_anchor.rect) if self.a_anchor else None

    def focus_b(self) -> Optional[Tuple[int, Rect4]]:
        if self.b_rects:
            return self.b_rects[0]
        return (self.b_anchor.page, self.b_anchor.rect) if self.b_anchor else None

    @property
    def page(self) -> int:
        """Listede gruplanacağı sayfa: yeni belgedeki yer, yoksa eskideki."""
        f = self.focus_b() or self.focus_a()
        return f[0] if f else 0


@dataclass
class DiffResult:
    changes: List[Change] = field(default_factory=list)
    words_a: int = 0
    words_b: int = 0
    error: str = ""                             # '' | 'no_text_a' | 'no_text_b'
    cancelled: bool = False

    def count(self, kind: str) -> int:
        return sum(1 for c in self.changes if c.kind == kind)

    def by_page(self) -> Dict[int, List[Change]]:
        out: Dict[int, List[Change]] = {}
        for c in self.changes:
            out.setdefault(c.page, []).append(c)
        return dict(sorted(out.items()))

    def summary(self) -> str:
        if not self.changes:
            return "Metinler aynı"
        return (f"{self.count('add')} eklenen · {self.count('del')} silinen · "
                f"{self.count('mod')} değişen")


def extract_lines(pdf, check: Optional[Callable[[], bool]] = None,
                  tick: Optional[Callable[[int], None]] = None) -> List[List[Word]]:
    """PDFDocument'in metnini satır satır (okuma sırasıyla) çıkarır."""
    lines: List[List[Word]] = []
    counter = 0
    for p in range(pdf.page_count):
        if check and check():
            break
        with pdf.lock:
            page = pdf.doc[p]
            mat = page.rotation_matrix
            raw = page.get_text("words")
        cur_key, cur = None, []
        for x0, y0, x1, y1, txt, blk, ln, _wn in raw:
            txt = txt.strip()
            if not txt:
                continue
            key = (blk, ln)
            if key != cur_key:
                if cur:
                    lines.append(cur)
                cur_key, cur = key, []
                counter += 1
            r = fitz.Rect(x0, y0, x1, y1) * mat
            cur.append(Word(p, (r.x0, r.y0, r.x1, r.y1), txt, counter))
        if cur:
            lines.append(cur)
        if tick:
            tick(p)
    return lines


def _norm(text: str, ignore_case: bool) -> str:
    text = unicodedata.normalize("NFKC", text)
    return text.casefold() if ignore_case else text


def _anchor(words: List[Word], idx: int) -> Optional[Word]:
    if not words:
        return None
    return words[idx - 1] if idx > 0 else words[0]


def _same_line(words: List[Optional[Word]]) -> bool:
    return len({(w.page, w.line) for w in words if w is not None}) <= 1


def _merge_close(ops, aw: List[Word], bw: List[Word], max_gap: int = 1):
    """Aralarında en çok `max_gap` ortak kelime olan ardışık farkları birleştirir
    (tek kelimelik ortak boşluklar listeyi gereksiz bölmesin). Yalnızca aynı
    satırdaki kelimeler birleşir; araya eklenen/silinen satır komşusuna yapışmaz."""
    out: List[list] = []

    def mergeable(prev, eq, nxt) -> bool:
        a = [aw[prev[2] - 1] if prev[2] > prev[1] else None, *aw[eq[1]:eq[2]],
             aw[nxt[0]] if nxt[1] > nxt[0] else None]
        b = [bw[prev[4] - 1] if prev[4] > prev[3] else None, *bw[eq[3]:eq[4]],
             bw[nxt[2]] if nxt[3] > nxt[2] else None]
        return _same_line(a) and _same_line(b)

    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            out.append([tag, i1, i2, j1, j2])
            continue
        if (len(out) >= 2 and out[-1][0] == "equal" and out[-1][2] - out[-1][1] <= max_gap
                and out[-2][0] != "equal" and mergeable(out[-2], out[-1], (i1, i2, j1, j2))):
            out.pop()
            prev = out[-1]
            prev[0], prev[2], prev[4] = "replace", i2, j2
        else:
            out.append([tag, i1, i2, j1, j2])
    return out


def compare(pdf_a, pdf_b, *, ignore_case: bool = False,
            check: Optional[Callable[[], bool]] = None,
            progress: Optional[Callable[[int, int], None]] = None) -> DiffResult:
    """pdf_a = eski sürüm, pdf_b = yeni sürüm (PDFDocument)."""
    res = DiffResult()
    total = pdf_a.page_count + pdf_b.page_count
    la = extract_lines(pdf_a, check, (lambda p: progress(p + 1, total)) if progress else None)
    lb = extract_lines(pdf_b, check, (lambda p: progress(pdf_a.page_count + p + 1, total))
                       if progress else None)
    if check and check():
        res.cancelled = True
        return res
    res.words_a = sum(len(ln) for ln in la)
    res.words_b = sum(len(ln) for ln in lb)
    if not res.words_a:
        res.error = "no_text_a"
        return res
    if not res.words_b:
        res.error = "no_text_b"
        return res

    ka = [_norm(" ".join(w.text for w in ln), ignore_case) for ln in la]
    kb = [_norm(" ".join(w.text for w in ln), ignore_case) for ln in lb]
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes():
        if check and check():
            res.cancelled = True
            return res
        if tag == "equal":
            continue
        aw = [w for ln in la[i1:i2] for w in ln]
        bw = [w for ln in lb[j1:j2] for w in ln]
        if tag == "delete":
            anchor = lb[j1][0] if j1 < len(lb) else (lb[-1][-1] if lb else None)
            res.changes.append(Change("del", aw, [], b_anchor=anchor))
        elif tag == "insert":
            anchor = la[i1 - 1][-1] if i1 > 0 else (la[0][0] if la else None)
            res.changes.append(Change("add", [], bw, a_anchor=anchor))
        else:
            _word_changes(res, aw, bw, ignore_case)
    return res


def _word_changes(res: DiffResult, aw: List[Word], bw: List[Word], ignore_case: bool):
    ta = [_norm(w.text, ignore_case) for w in aw]
    tb = [_norm(w.text, ignore_case) for w in bw]
    ops = difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in _merge_close(ops, aw, bw):
        if tag == "equal":
            continue
        if i1 == i2:
            res.changes.append(Change("add", [], bw[j1:j2], a_anchor=_anchor(aw, i1)))
        elif j1 == j2:
            res.changes.append(Change("del", aw[i1:i2], [], b_anchor=_anchor(bw, j1)))
        else:
            res.changes.append(Change("mod", aw[i1:i2], bw[j1:j2]))


def snippet(text: str, limit: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"
