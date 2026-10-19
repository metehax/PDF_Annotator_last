"""PDF formları (AcroForm): alanları listeleme, doldurma, sıfırlama, hesaplama
ve yeni alan oluşturma / silme.

Alanlar doğrudan belgenin (fitz.Document) içinde yaşar; işaretler gibi ayrı
tutulmaz. Bir alan, sayfası + kendi /NM kimliği ile bulunur (xref, silinip
yeniden oluşturulunca değişir; /NM korunur). Değerler alan adıyla tutulur:
aynı adlı tüm parçacıklar (ör. radyo grubu) aynı değeri paylaşır.

Tarih alanı = Acrobat uyumlu AFDate biçim betiği taşıyan metin alanı;
hesaplanan alan = AFSimple_Calculate betiği taşıyan salt okunur metin alanı.
Böylece Acrobat vb. okuyucular da aynı davranışı gösterir; uygulama içinde
hesaplamayı `recalculate()` yapar.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import fitz

FIELD_KINDS = [
    ("text", "Metin alanı"),
    ("checkbox", "Onay kutusu"),
    ("radio", "Radyo düğmesi"),
    ("combo", "Açılır liste"),
    ("date", "Tarih"),
    ("calc", "Hesaplanan alan"),
    ("signature", "İmza alanı"),
]
KIND_NAMES = dict(FIELD_KINDS)
KIND_BASE = {"text": "Metin", "checkbox": "Onay", "radio": "Secim", "combo": "Liste",
             "date": "Tarih", "calc": "Toplam", "signature": "Imza"}

CALC_OPS = [("SUM", "Toplam (+)"), ("PRD", "Çarpım (×)"), ("AVG", "Ortalama"),
            ("MIN", "En küçük"), ("MAX", "En büyük")]
DATE_FORMATS = ["dd.mm.yyyy", "dd/mm/yyyy", "yyyy-mm-dd", "dd.mm.yy"]

# çizim sırasında tıklanıp bırakılan küçük alanlar için varsayılan boyutlar (pt)
DEFAULT_SIZE = {"text": (160, 22), "checkbox": (14, 14), "radio": (14, 14), "combo": (140, 22),
                "date": (100, 22), "calc": (100, 22), "signature": (180, 50)}

_CALC_RE = re.compile(r'AFSimple_Calculate\(\s*"(\w+)"\s*,\s*new\s+Array\s*\((.*?)\)\s*\)', re.S)
_DATE_RE = re.compile(r'AFDate_(?:Format|Keystroke)Ex\(\s*"([^"]+)"')
_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")

FF_READONLY = 1
FF_NO_TOGGLE_OFF = 1 << 14
FF_RADIO = 1 << 15


@dataclass
class FieldInfo:
    page: int
    nm: str                       # parçacık kimliği (/NM)
    name: str                     # alan adı (radyoda grup adı)
    kind: str
    value: str
    rect: "fitz.Rect"             # görünen (döndürülmüş) sayfa koordinatı, pt
    options: List[str] = field(default_factory=list)
    on_state: str = ""            # onay/radyo: "seçili" durumunun adı
    readonly: bool = False
    calc_op: str = ""
    calc_sources: List[str] = field(default_factory=list)
    date_fmt: str = ""

    @property
    def checked(self) -> bool:
        return self.kind in ("checkbox", "radio") and self.value not in ("", "Off") and \
            self.value == self.on_state


# ---------------------------------------------------------------------------
# okuma
# ---------------------------------------------------------------------------
def has_form(doc: "fitz.Document") -> bool:
    try:
        return bool(doc.is_form_pdf)
    except Exception:
        return False


def _ensure_nm(doc, w) -> str:
    t, v = doc.xref_get_key(w.xref, "NM")
    if t == "string" and v:
        return v
    nm = "pa-" + uuid.uuid4().hex[:10]
    doc.xref_set_key(w.xref, "NM", fitz.get_pdf_str(nm))
    return nm


def _on_state(w) -> str:
    try:
        st = w.on_state()
        if st and st is not True:
            return str(st)
    except Exception:
        pass
    try:
        names = (w.button_states() or {}).get("normal") or []
        for n in names:
            if n != "Off":
                return n
    except Exception:
        pass
    return "Yes"


def _kind_of(w) -> str:
    ft = w.field_type
    if ft == fitz.PDF_WIDGET_TYPE_CHECKBOX:
        return "checkbox"
    if ft == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
        return "radio"
    if ft in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
        return "combo"
    if ft == fitz.PDF_WIDGET_TYPE_SIGNATURE:
        return "signature"
    if ft == fitz.PDF_WIDGET_TYPE_TEXT:
        if w.script_calc and _CALC_RE.search(w.script_calc):
            return "calc"
        if (w.script_format and "AFDate" in w.script_format) or \
                (w.script_stroke and "AFDate" in w.script_stroke):
            return "date"
        return "text"
    return "other"          # imza, buton vb. — listelenir ama düzenlenmez


def _display_rect(page, r) -> "fitz.Rect":
    return fitz.Rect(r) * page.rotation_matrix if page.rotation else fitz.Rect(r)


def _info(doc, pidx, page, w) -> FieldInfo:
    kind = _kind_of(w)
    info = FieldInfo(page=pidx, nm=_ensure_nm(doc, w), name=w.field_name or "", kind=kind,
                     value="" if w.field_value is None else str(w.field_value),
                     rect=_display_rect(page, w.rect),
                     readonly=bool(w.field_flags & FF_READONLY))
    if kind in ("checkbox", "radio"):
        info.on_state = _on_state(w)
        if info.value in ("True", "true"):
            info.value = info.on_state
        elif info.value in ("False", "false", ""):
            info.value = "Off"
    elif kind == "combo":
        info.options = [c[1] if isinstance(c, (list, tuple)) else str(c)
                        for c in (w.choice_values or [])]
    elif kind == "calc":
        m = _CALC_RE.search(w.script_calc)
        info.calc_op = m.group(1).upper()
        info.calc_sources = re.findall(r'"([^"]*)"', m.group(2))
    elif kind == "date":
        m = _DATE_RE.search((w.script_format or "") + (w.script_stroke or ""))
        info.date_fmt = m.group(1) if m else DATE_FORMATS[0]
    return info


def list_fields(doc: "fitz.Document") -> List[FieldInfo]:
    out: List[FieldInfo] = []
    if not has_form(doc):
        return out
    for pidx in range(doc.page_count):
        page = doc[pidx]
        for w in page.widgets():
            out.append(_info(doc, pidx, page, w))
    return out


def _widget(doc, pidx: int, nm: str):
    page = doc[pidx]
    for w in page.widgets():
        t, v = doc.xref_get_key(w.xref, "NM")
        if v == nm:
            return page, w
    return page, None


def field_names(doc) -> List[str]:
    seen, out = set(), []
    for f in list_fields(doc):
        if f.name not in seen:
            seen.add(f.name)
            out.append(f.name)
    return out


def unique_name(doc, base: str) -> str:
    names = set(field_names(doc))
    base = base or "Alan"
    i = 1
    while f"{base}{i}" in names:
        i += 1
    return f"{base}{i}"


# ---------------------------------------------------------------------------
# değer yazma
# ---------------------------------------------------------------------------
def _set_button(doc, w, on: bool, state: str) -> None:
    doc.xref_set_key(w.xref, "AS", "/" + (state if on else "Off"))


_TR_FONT = ("<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding<</Type/Encoding"
            "/BaseEncoding/WinAnsiEncoding/Differences[208/Gbreve 221/Idotaccent 222/Scedilla"
            " 240/gbreve 253/dotlessi 254/scedilla]>>>>")
_HELV = fitz.Font("helv")


def _tr_font(doc) -> int:
    """AcroForm/DR'de Türkçe karakterli (cp1254) Helvetica: /PaTr."""
    t, v = doc.xref_get_key(doc.pdf_catalog(), "AcroForm/DR/Font/PaTr")
    if t == "xref":
        return int(v.split()[0])
    fx = doc.get_new_xref()
    doc.update_object(fx, _TR_FONT)
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm/DR/Font/PaTr", f"{fx} 0 R")
    return fx


def _needs_own_ap(text: str) -> bool:
    if not text:
        return True
    try:
        text.encode("cp1252")
        return False
    except UnicodeEncodeError:
        return True


def _rgb(c) -> str:
    return " ".join(f"{v:g}" for v in (c or ())[:3])


def _write_text_ap(doc, page, w, text: str) -> None:
    """MuPDF Türkçe harflerde (ş, ğ, ı, İ…) Helv görünümünü bozuk üretir; bu
    durumda ve boş değerde görünüm akışını biz yazarız."""
    fx = _tr_font(doc)
    r = fitz.Rect(w.rect)
    rot = page.rotation % 360
    W, H = (r.height, r.width) if rot in (90, 270) else (r.width, r.height)
    fs = float(w.text_fontsize or 0) or max(6.0, min(12.0, H * 0.62))
    multiline = bool(w.field_flags & (1 << 12))
    lines = [text]
    if multiline:
        lines = []
        for para in text.split("\n"):
            cur = ""
            for word in para.split(" "):
                cand = (cur + " " + word).strip()
                if cur and _HELV.text_length(cand, fs) > W - 4:
                    lines.append(cur)
                    cur = word
                else:
                    cur = cand
            lines.append(cur)
    elif text and not w.text_fontsize:
        tl = _HELV.text_length(text, fs)
        if tl > W - 4:
            fs = max(5.0, fs * (W - 4) / tl)
    parts = []
    if w.fill_color:
        parts.append(f"{_rgb(w.fill_color)} rg 0 0 {W:g} {H:g} re f")
    if w.border_color and (w.border_width or 0) > 0:
        bw = w.border_width
        parts.append(f"{_rgb(w.border_color)} RG {bw:g} w {bw / 2:g} {bw / 2:g} "
                     f"{W - bw:g} {H - bw:g} re S")
    parts.append(f"/Tx BMC q 1 1 {W - 2:g} {H - 2:g} re W n BT /PaTr {fs:g} Tf "
                 f"{_rgb(w.text_color) or '0 0 0'} rg")
    lead = fs * 1.15
    y = (H - fs * 0.72) / 2 if not multiline else H - 2 - fs
    for i, ln in enumerate(lines):
        if not ln:
            continue
        hexs = ln.encode("cp1254", "replace").hex()
        parts.append(f"1 0 0 1 2 {y - i * lead:.2f} Tm <{hexs}> Tj")
    parts.append("ET Q EMC")
    m = fitz.Matrix(rot) if rot else fitz.Identity
    ap = doc.get_new_xref()
    doc.update_object(ap, "<</Type/XObject/Subtype/Form/BBox[0 0 %g %g]/Matrix[%g %g %g %g 0 0]"
                      "/Resources<</Font<</PaTr %d 0 R>>>>>>" % (W, H, m.a, m.b, m.c, m.d, fx))
    doc.update_stream(ap, "\n".join(parts).encode("latin-1"))
    doc.xref_set_key(w.xref, "AP", f"<</N {ap} 0 R>>")
    doc.xref_set_key(w.xref, "DA", fitz.get_pdf_str(f"/PaTr {w.text_fontsize or 0:g} Tf 0 g"))
    if rot:
        doc.xref_set_key(w.xref, "MK/R", str(rot))


def _set_text(doc, page, w, value: str) -> None:
    if _needs_own_ap(value):
        doc.xref_set_key(w.xref, "V", fitz.get_pdf_str(value))
        _write_text_ap(doc, page, w, value)
    else:
        w.field_value = value
        w.update()


def set_value(doc: "fitz.Document", name: str, value: str) -> List[int]:
    """`name` adlı alanın tüm parçacıklarına değeri yazar. Onay/radyoda değer,
    seçilecek parçacığın durum adıdır ("Off" = hiçbiri). Değişen sayfaları döner."""
    pages = []
    value = "" if value is None else str(value)
    for pidx in range(doc.page_count):
        page = doc[pidx]
        hit = False
        for w in page.widgets():
            if w.field_name != name:
                continue
            hit = True
            kind = _kind_of(w)
            if kind in ("checkbox", "radio"):
                st = _on_state(w)
                _set_button(doc, w, value == st, st)
                tgt = w.xref
                pt, pv = doc.xref_get_key(w.xref, "Parent")
                if kind == "radio" and pt == "xref":
                    tgt = int(pv.split()[0])
                doc.xref_set_key(tgt, "V", "/" + (value if value and value != "Off" else "Off"))
            elif kind == "other":
                continue
            else:
                _set_text(doc, page, w, value)
        if hit:
            pages.append(pidx)
    return pages


def get_value(doc, name: str) -> str:
    vals = [f for f in list_fields(doc) if f.name == name]
    for f in vals:
        if f.kind in ("checkbox", "radio"):
            if f.checked:
                return f.on_state
        else:
            return f.value
    return "Off" if vals else ""


def snapshot_values(doc) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for f in list_fields(doc):
        if f.kind in ("checkbox", "radio"):
            if f.checked or f.name not in out:
                out[f.name] = f.on_state if f.checked else out.get(f.name, "Off")
        elif f.kind != "other":
            out.setdefault(f.name, f.value)
    return out


def apply_values(doc, values: Dict[str, str]) -> List[int]:
    pages = set()
    for name, v in values.items():
        pages.update(set_value(doc, name, v))
    return sorted(pages)


def reset_values(doc) -> List[int]:
    """Tüm alanları boşaltır (onay/radyo: işaretsiz); hesaplananlar yeniden hesaplanır."""
    vals = {}
    for f in list_fields(doc):
        if f.kind in ("checkbox", "radio"):
            vals[f.name] = "Off"
        elif f.kind in ("text", "date", "combo", "calc"):
            vals[f.name] = ""
    pages = set(apply_values(doc, vals))
    pages.update(recalculate(doc))
    return sorted(pages)


# ---------------------------------------------------------------------------
# hesaplama
# ---------------------------------------------------------------------------
def parse_number(s) -> Optional[float]:
    s = str(s or "").strip().replace(" ", "").replace("₺", "").replace("TL", "")
    if not s:
        return None
    if "," in s and "." in s:            # 1.234,5 (TR) ya da 1,234.5 (EN)
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def format_number(x: float) -> str:
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def compute(op: str, nums: List[float]) -> float:
    if not nums:
        return 0.0
    if op == "PRD":
        r = 1.0
        for n in nums:
            r *= n
        return r
    if op == "AVG":
        return sum(nums) / len(nums)
    if op == "MIN":
        return min(nums)
    if op == "MAX":
        return max(nums)
    return sum(nums)


def recalculate(doc) -> List[int]:
    """Hesaplanan alanları (birbirine bağlı olabilir) birkaç turda günceller."""
    fields = list_fields(doc)
    calcs = [f for f in fields if f.kind == "calc"]
    if not calcs:
        return []
    values = snapshot_values(doc)
    pages = set()
    for _ in range(len(calcs) + 1):
        changed = False
        for f in calcs:
            nums = []
            for src in f.calc_sources:
                n = parse_number(values.get(src, ""))
                if n is not None:
                    nums.append(n)
            res = format_number(compute(f.calc_op, nums)) if nums else ""
            if values.get(f.name) != res:
                values[f.name] = res
                pages.update(set_value(doc, f.name, res))
                changed = True
        if not changed:
            break
    return sorted(pages)


# ---------------------------------------------------------------------------
# oluşturma / silme
# ---------------------------------------------------------------------------
def export_name(label: str) -> str:
    """Radyo seçeneği için PDF ad nesnesine uygun durum adı."""
    s = re.sub(r"[^A-Za-z0-9_-]", "", (label or "").translate(_TR))
    return s or "Secenek"


def _acroform_fields(doc):
    t, v = doc.xref_get_key(doc.pdf_catalog(), "AcroForm/Fields")
    if t != "array":
        return []
    return [int(x) for x in re.findall(r"(\d+)\s+0\s+R", v)]


def _set_acroform_fields(doc, xrefs) -> None:
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm/Fields",
                     "[" + " ".join(f"{x} 0 R" for x in xrefs) + "]")


def _radio_parent(doc, name: str) -> Optional[int]:
    for x in _acroform_fields(doc):
        t, v = doc.xref_get_key(x, "T")
        k, _ = doc.xref_get_key(x, "Kids")
        if k == "array" and t == "string" and v == name:
            return x
    return None


def _join_radio_group(doc, kid: int, name: str, state: str) -> None:
    """PyMuPDF her radyoyu ayrı alan yapar; burada ortak bir üst alana
    (/Kids) bağlanır ve 'Yes' durumu seçeneğin adıyla değiştirilir."""
    t, apn = doc.xref_get_key(kid, "AP/N")
    if t == "dict" and "/Yes" in apn:
        doc.xref_set_key(kid, "AP/N", apn.replace("/Yes", "/" + state))
    t, apd = doc.xref_get_key(kid, "AP/D")
    if t == "dict" and "/Yes" in apd:
        doc.xref_set_key(kid, "AP/D", apd.replace("/Yes", "/" + state))
    doc.xref_set_key(kid, "AS", "/Off")
    parent = _radio_parent(doc, name)
    fields = [x for x in _acroform_fields(doc) if x != kid]
    if parent is None:
        parent = doc.get_new_xref()
        doc.update_object(parent, "<</FT/Btn/Ff %d/T%s/V/Off/Kids[]>>"
                          % (FF_RADIO | FF_NO_TOGGLE_OFF, fitz.get_pdf_str(name)))
        fields.append(parent)
    _, kids = doc.xref_get_key(parent, "Kids")
    kid_list = [int(x) for x in re.findall(r"(\d+)\s+0\s+R", kids)] + [kid]
    doc.xref_set_key(parent, "Kids", "[" + " ".join(f"{x} 0 R" for x in kid_list) + "]")
    doc.xref_set_key(kid, "Parent", f"{parent} 0 R")
    for key in ("T", "V", "FT", "Ff"):
        doc.xref_set_key(kid, key, "null")
    _set_acroform_fields(doc, fields)


def add_field(doc: "fitz.Document", pidx: int, spec: dict) -> str:
    """spec: kind, name, rect (görünen koordinat), value, options, on_state,
    calc_op, calc_sources, date_fmt, font_size, nm (isteğe bağlı). /NM döner."""
    page = doc[pidx]
    kind = spec["kind"]
    rect = fitz.Rect(spec["rect"])
    if page.rotation:
        rect = rect * page.derotation_matrix
    w = fitz.Widget()
    w.rect = rect
    w.field_name = spec["name"] if kind != "radio" else "__pa_tmp_" + uuid.uuid4().hex[:6]
    w.border_color = (0.55, 0.6, 0.72)
    w.border_width = 0.8
    w.fill_color = (0.94, 0.96, 1.0)
    w.text_fontsize = float(spec.get("font_size") if spec.get("font_size") is not None else 10)
    w.text_font = "Helv"
    if kind == "checkbox":
        w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        w.field_value = False
    elif kind == "radio":
        w.field_type = fitz.PDF_WIDGET_TYPE_RADIOBUTTON
        w.field_value = False
    elif kind == "combo":
        w.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
        opts = [o for o in spec.get("options") or [] if o] or ["Seçenek 1"]
        w.choice_values = opts
        w.field_value = ""
    elif kind == "signature":            # boş imza alanı; dijital imzayla doldurulur
        w.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE
        w.fill_color = (1.0, 0.98, 0.9)
    else:
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.field_value = ""
        if kind == "date":
            fmt = spec.get("date_fmt") or DATE_FORMATS[0]
            w.script_format = f'AFDate_FormatEx("{fmt}");'
            w.script_stroke = f'AFDate_KeystrokeEx("{fmt}");'
        elif kind == "calc":
            srcs = ", ".join(f'"{s}"' for s in spec.get("calc_sources") or [])
            w.script_calc = f'AFSimple_Calculate("{spec.get("calc_op") or "SUM"}", new Array({srcs}));'
            w.field_flags |= FF_READONLY
            w.fill_color = (0.95, 0.95, 0.95)
    page.add_widget(w)
    # PyMuPDF yeni parçacığın xref'ini nesneye yazmıyor: sayfadan geri bul
    created = None
    for cw in page.widgets():
        if cw.field_name == w.field_name and fitz.Rect(cw.rect) == fitz.Rect(w.rect):
            created = cw
    xref = created.xref
    nm = spec.get("nm") or "pa-" + uuid.uuid4().hex[:10]
    doc.xref_set_key(xref, "NM", fitz.get_pdf_str(nm))
    if kind == "radio":
        _join_radio_group(doc, xref, spec["name"], export_name(spec.get("on_state") or spec["name"]))
    if kind in ("text", "date", "calc", "combo") and spec.get("value"):
        if kind != "combo" or spec["value"] in (spec.get("options") or []):
            set_value(doc, spec["name"], spec["value"])
    if kind in ("checkbox", "radio") and spec.get("value") not in (None, "", "Off", False):
        _p, cw = _widget(doc, pidx, nm)
        st = _on_state(cw)
        if spec["value"] in (True, st):
            set_value(doc, cw.field_name, st)
    return nm


def field_spec(doc, pidx: int, nm: str) -> Optional[dict]:
    page, w = _widget(doc, pidx, nm)
    if w is None:
        return None
    f = _info(doc, pidx, page, w)
    return {"kind": f.kind, "name": f.name, "rect": tuple(f.rect), "value": f.value,
            "options": list(f.options), "on_state": f.on_state, "calc_op": f.calc_op,
            "calc_sources": list(f.calc_sources), "date_fmt": f.date_fmt,
            "font_size": w.text_fontsize, "nm": nm}


def delete_field(doc: "fitz.Document", pidx: int, nm: str) -> Optional[dict]:
    """Parçacığı siler; geri almak için `add_field(doc, pidx, spec)` ile aynı
    /NM'yle yeniden oluşturulabilecek tanımı döner."""
    spec = field_spec(doc, pidx, nm)
    page, w = _widget(doc, pidx, nm)
    if w is None:
        return None
    if spec["kind"] == "radio":
        spec["value"] = spec["on_state"] if spec["value"] == spec["on_state"] else "Off"
    xref = w.xref
    pt, pv = doc.xref_get_key(xref, "Parent")
    page.delete_widget(w)
    if pt == "xref":
        parent = int(pv.split()[0])
        _, kids = doc.xref_get_key(parent, "Kids")
        rest = [int(x) for x in re.findall(r"(\d+)\s+0\s+R", kids) if int(x) != xref]
        doc.xref_set_key(parent, "Kids", "[" + " ".join(f"{x} 0 R" for x in rest) + "]")
        if not rest:
            _set_acroform_fields(doc, [x for x in _acroform_fields(doc) if x != parent])
    _set_acroform_fields(doc, [x for x in _acroform_fields(doc) if x != xref])
    return spec


def field_at(fields: List[FieldInfo], pidx: int, x: float, y: float) -> Optional[FieldInfo]:
    for f in reversed(fields):
        if f.page == pidx and f.rect.contains(fitz.Point(x, y)):
            return f
    return None
