"""
headfoot.py
===========
Sayfa numarası, üstbilgi / altbilgi ve Bates numaralandırma motoru.

Metinlerde şu yer tutucular kullanılır:
    {sayfa}  numara (başlangıç değerinden itibaren)      {toplam}  son numara
    {tarih}  bugünün tarihi (gg.aa.yyyy)                 {dosya}   dosya adı
    {bates}  Bates numarası (önek + sıfır dolgulu sayı + sonek)
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import List, Tuple

import pymupdf as fitz

from pdf_engine import text_width

POSITIONS = ("sol", "orta", "sağ")


@dataclass
class HeadFootConfig:
    header: List[str] = field(default_factory=lambda: ["", "", ""])    # sol, orta, sağ
    footer: List[str] = field(default_factory=lambda: ["", "{sayfa} / {toplam}", ""])
    font_size: float = 10.0
    color: Tuple[float, float, float] = (0.2, 0.2, 0.2)
    margin: float = 28.0              # kenara uzaklık (pt)
    start_number: int = 1
    skip_first: bool = False          # ilk seçili sayfaya yazma (kapak)
    scope: str = "all"                # "all" | "range"
    page_start: int = 1
    page_end: int = 1
    bates_prefix: str = ""
    bates_suffix: str = ""
    bates_digits: int = 6
    bates_start: int = 1

    def pages(self, page_count: int) -> List[int]:
        if self.scope == "range":
            lo = max(1, min(self.page_start, page_count))
            hi = max(1, min(self.page_end, page_count))
            if lo > hi:
                lo, hi = hi, lo
            pages = list(range(lo - 1, hi))
        else:
            pages = list(range(page_count))
        return pages[1:] if self.skip_first and pages else pages

    def is_empty(self) -> bool:
        return not any(t.strip() for t in self.header + self.footer)


def bates_text(cfg: HeadFootConfig, order: int) -> str:
    n = cfg.bates_start + order
    return f"{cfg.bates_prefix}{str(n).zfill(max(1, cfg.bates_digits))}{cfg.bates_suffix}"


def resolve(text: str, cfg: HeadFootConfig, order: int, count: int, filename: str) -> str:
    """`order`: seçili sayfalar içindeki 0 tabanlı sıra, `count`: seçili sayfa sayısı."""
    if not text:
        return ""
    last = cfg.start_number + max(0, count - 1)
    return (text.replace("{sayfa}", str(cfg.start_number + order))
                .replace("{toplam}", str(last))
                .replace("{tarih}", datetime.date.today().strftime("%d.%m.%Y"))
                .replace("{dosya}", filename)
                .replace("{bates}", bates_text(cfg, order)))


def apply_header_footer(doc: "fitz.Document", cfg: HeadFootConfig, font_ctx, filename: str = "") -> None:
    pages = cfg.pages(doc.page_count)
    count = len(pages)
    for order, idx in enumerate(pages):
        page = doc[idx]
        vis = page.rect                       # görünen (döndürülmüş) alan
        rot = page.rotation
        for row, y_kind in ((cfg.header, "top"), (cfg.footer, "bottom")):
            for col, raw in enumerate(row):
                text = resolve(raw, cfg, order, count, filename)
                if not text.strip():
                    continue
                tw = text_width(text, font_ctx, cfg.font_size)
                if col == 0:
                    x = cfg.margin
                elif col == 1:
                    x = (vis.width - tw) / 2
                else:
                    x = vis.width - cfg.margin - tw
                y = cfg.margin + cfg.font_size * 0.8 if y_kind == "top" else vis.height - cfg.margin
                pt = fitz.Point(x, y) * page.derotation_matrix + page.cropbox_position
                kw = dict(fontsize=cfg.font_size, color=cfg.color, rotate=rot)
                try:
                    if font_ctx is not None:
                        page.insert_text(pt, text, fontname=font_ctx[0], fontfile=font_ctx[1], **kw)
                    else:
                        page.insert_text(pt, text, fontname="helv", **kw)
                except Exception:
                    pass
