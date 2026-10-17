import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
import pymupdf as fitz
from PySide6.QtCore import QRectF, QSettings
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsScene

tmp = tempfile.mkdtemp(prefix="i2_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


app = QApplication.instance() or QApplication(sys.argv)
from models import Annotation, DocumentSession, RedactionAnnotation, RedactItem, TextAnnotation
from pdf_engine import PDFDocument, resolve_font_ctx

FC = resolve_font_ctx()
SECRET = "GIZLIKELIME12345"
OTHER = "Herkese acik metin kalir"

# --- kaynak PDF: gizli metin + açık metin + dolgulu "resim" benzeri şekil
SRC = os.path.join(tmp, "kaynak.pdf")
d = fitz.open()
pg = d.new_page()
pg.insert_text((72, 100), SECRET, fontsize=18)
pg.insert_text((72, 160), OTHER, fontsize=14)
pg.draw_rect(fitz.Rect(72, 220, 200, 300), color=None, fill=(1, 0, 0))
pg2 = d.new_page()
pg2.insert_text((72, 100), SECRET, fontsize=18)
pg2.set_rotation(90)
d.save(SRC)
d.close()
BOX = QRectF(66, 80, 220, 28)                     # SECRET'in üstü (sayfa pt)


def export(anns_by_page, name="out.pdf"):
    out = os.path.join(tmp, name)
    PDFDocument(SRC).export_pdf(out, anns_by_page, FC)
    return out


def pix_at(doc, page, x, y, zoom=2):
    pm = doc[page].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    px = pm.pixel(int(x * zoom), int(y * zoom))
    return tuple(px)


# ---------------- gerçek silme (davranış değişmemeli) ----------------
RedactionAnnotation.final_view = False
o = export({0: [RedactionAnnotation(BOX, QColor("#000000"))]})
r = fitz.open(o)
t = r[0].get_text()
check("sansürlenen metin PDF'ten silindi", SECRET not in t and "GIZLI" not in t.replace(" ", ""), t[:60])
check("diğer metin yerinde", OTHER in t)
check("kutu tam siyah dolu (yumuşak görünüm çıktıya sızmaz)", pix_at(r, 0, 120, 94) == (0, 0, 0) and pix_at(r, 0, 70, 82) == (0, 0, 0), str(pix_at(r, 0, 120, 94)))
check("kutu dışı değişmedi (kırmızı dolgu)", pix_at(r, 0, 100, 260)[0] > 200 and pix_at(r, 0, 100, 260)[1] < 40)
r.close()
RedactionAnnotation.final_view = True
o2 = export({0: [RedactionAnnotation(BOX, QColor("#000000"))]}, "out_final.pdf")
a, b = fitz.open(o), fitz.open(o2)
check("nihai görünüm bayrağı çıktıyı değiştirmez", a[0].get_pixmap().samples == b[0].get_pixmap().samples
      and a[0].get_text() == b[0].get_text())
a.close(); b.close()
RedactionAnnotation.final_view = False

# --- dolgu renkleri
for hexcol, rgb in (("#404040", (64, 64, 64)), ("#ffffff", (255, 255, 255)), ("#336699", (51, 102, 153))):
    o = export({0: [RedactionAnnotation(BOX, QColor(hexcol))]}, "renk.pdf")
    r = fitz.open(o)
    px = pix_at(r, 0, 120, 94)
    check(f"dolgu {hexcol}", max(abs(px[i] - rgb[i]) for i in range(3)) <= 2 and SECRET not in r[0].get_text(), str(px))
    r.close()

# --- etiket
LABEL = "GİZLİ"
o = export({0: [RedactionAnnotation(BOX, QColor("#000000"), label=LABEL)]}, "etiket.pdf")
r = fitz.open(o)
t = r[0].get_text()
check("etiketli: gizli metin yok, etiket var (Türkçe harfli)", SECRET not in t and LABEL in t, repr(t[:60]))
spans = [s for b in r[0].get_text("dict")["blocks"] if b["type"] == 0 for ln in b["lines"] for s in ln["spans"] if "GİZLİ" in s["text"]]
check("koyu dolguda etiket beyaz", spans and spans[0]["color"] == 0xFFFFFF, str(spans and spans[0]["color"]))
bb = fitz.Rect(spans[0]["bbox"]) if spans else None
check("etiket kutunun içinde ve ortada", bb is not None and bb.x0 >= BOX.left() - 1 and bb.x1 <= BOX.right() + 1
      and bb.y0 >= BOX.top() - 1 and bb.y1 <= BOX.bottom() + 1 and abs((bb.x0 + bb.x1) / 2 - (BOX.left() + BOX.right()) / 2) < 6, str(bb))
check("etiket: diğer metin yerinde", OTHER in t)
r.close()
o = export({0: [RedactionAnnotation(BOX, QColor("#ffffff"), label="[KARARTILDI]")]}, "etiket2.pdf")
r = fitz.open(o)
spans = [s for b in r[0].get_text("dict")["blocks"] if b["type"] == 0 for ln in b["lines"] for s in ln["spans"] if "KARARTILDI" in s["text"]]
check("açık dolguda etiket siyah", spans and spans[0]["color"] == 0 and SECRET not in r[0].get_text(), str(spans and spans[0]["color"]))
r.close()
o = export({0: [RedactionAnnotation(QRectF(66, 80, 14, 28), QColor("#000000"), label="ÇOK UZUN BİR ETİKET")]}, "dar.pdf")
r = fitz.open(o)
check("kutuya sığmayan etiket yazılmaz, silme yine de olur", "ETİKET" not in r[0].get_text() and SECRET not in r[0].get_text())
r.close()
o = export({0: [RedactionAnnotation(QRectF(66, 80, 220, 4), QColor("#000000"), label="GİZLİ")]}, "alcak.pdf")
r = fitz.open(o)
check("çok alçak kutuda etiket atlanır, hata yok", "GİZLİ" not in r[0].get_text())
r.close()
o = export({0: [RedactionAnnotation(BOX, QColor("#000000"), quiet=True, label="GİZLİ")]}, "quiet.pdf")
r = fitz.open(o)
check("quiet (metin düzenleme) kutusuna etiket yazılmaz", "GİZLİ" not in r[0].get_text() and SECRET not in r[0].get_text())
r.close()
o = export({0: [RedactionAnnotation(BOX, QColor("#000000"), label="  ")]}, "bos.pdf")
r = fitz.open(o)
check("boşluktan ibaret etiket = etiket yok", "GİZLİ" not in r[0].get_text() and r[0].get_text().strip() == OTHER)
r.close()
# iki kutu, biri etiketli
o = export({0: [RedactionAnnotation(BOX, QColor("#000000"), label="GİZLİ"), RedactionAnnotation(QRectF(66, 145, 220, 22), QColor("#000000"))]}, "iki.pdf")
r = fitz.open(o)
check("çok kutu: ikisi de silindi, yalnız birinde etiket", SECRET not in r[0].get_text() and OTHER not in r[0].get_text() and r[0].get_text().count("GİZLİ") == 1)
r.close()

# --- döndürülmüş sayfa: kutu GÖRÜNEN (ekran) koordinatındadır; silme doğru yeri bulmalı, etiket dik durmalı
src_doc = fitz.open(SRC)
un = src_doc[1].search_for(SECRET)[0]                    # döndürülmemiş sayfa koordinatı
vis = fitz.Rect(un) * src_doc[1].rotation_matrix          # ekranda görünen yer
vis.normalize()
src_doc.close()
RB = QRectF(vis.x0 - 2, vis.y0 - 2, vis.width + 4, vis.height + 4)
check("döndürülmüş sayfa: görünen kutu döndürülmemiş konumdan farklı", abs(vis.x0 - un.x0) > 50)
o = export({1: [RedactionAnnotation(RB, QColor("#000000"))]}, "dondu0.pdf")
r = fitz.open(o)
check("döndürülmüş sayfada da altındaki metin silinir", SECRET not in r[1].get_text(), repr(r[1].get_text()[:40]))
check("döndürülmüş sayfa: dolgu görünen kutunun üstünde", pix_at(r, 1, (vis.x0 + vis.x1) / 2, (vis.y0 + vis.y1) / 2) == (0, 0, 0))
r.close()
o = export({1: [RedactionAnnotation(RB, QColor("#000000"), label="GIZLI")]}, "dondu.pdf")
r = fitz.open(o)
t1 = r[1].get_text()
check("döndürülmüş sayfa: etiket tek parça, gizli metin yok", "GIZLI" in t1 and SECRET not in t1, repr(t1[:50]))
import ocr
tess = ocr.find_tessdata()
if tess:
    pg1 = r[1]                                           # sayfa nesnesi tutulmalı (textpage ona bağlı)
    tp = pg1.get_textpage_ocr(language="eng", dpi=216, full=True, tessdata=tess)
    txt = pg1.get_text("text", textpage=tp).upper().replace(" ", "")
    check("döndürülmüş sayfada etiket görünen yönde okunabilir (OCR)", "GIZLI" in txt, txt[:40])
else:
    check("OCR kurulu değil: dönük sayfa okunabilirliği atlandı", True)
r.close()

# ---------------- geriye uyumluluk ----------------
new = RedactionAnnotation(BOX, QColor("#404040"), label="GİZLİ")
dct = new.to_dict()
check("to_dict etiketi taşır", dct["label"] == "GİZLİ" and dct["fill_color"])
back = Annotation.from_dict(dct)
check("gidiş-dönüş: etiket + renk + kutu", isinstance(back, RedactionAnnotation) and back.label == "GİZLİ" and back.fill_color.name() == "#404040"
      and back.rect == BOX and back.uid == new.uid)
old = {k: v for k, v in dct.items() if k != "label"}
oldann = Annotation.from_dict(old)
check("eski kayıt (label yok) yüklenir", isinstance(oldann, RedactionAnnotation) and oldann.label == "" and oldann.quiet is False)
legacy = {"type": "redaction", "uid": "abc", "rect": [10, 20, 30, 40], "fill_color": "#000000ff"}
try:
    la = Annotation.from_dict(legacy)
    lok = isinstance(la, RedactionAnnotation) and la.label == "" and la.quiet is False
except Exception:
    lok = False
check("en eski biçim (quiet de yok) yüklenir", lok)
sess = DocumentSession(PDFDocument(SRC), SRC)
proj = {"version": 1, "source_pdf": SRC, "title": "kaynak.pdf", "rotations": {},
        "annotations": {"0": [old, TextAnnotation(QRectF(10, 10, 100, 20), "x", QColor("#000"), 12).to_dict()], "1": [dct]}}
sess.load_project_dict(proj)
check("eski proje JSON'u oturuma yüklenir", len(sess.annotations[0]) == 2 and isinstance(sess.annotations[0][0], RedactionAnnotation)
      and sess.annotations[1][0].label == "GİZLİ")
proj2 = sess.to_project_dict()
check("proje yeniden yazılınca etiket korunur", proj2["annotations"]["1"][0]["label"] == "GİZLİ" and "label" in proj2["annotations"]["0"][0])

# ---------------- ekran öğesi: yumuşak / nihai ----------------
def render_item(item, w=120, h=60):
    sc = QGraphicsScene(0, 0, w, h)
    sc.setBackgroundBrush(QColor("white"))
    sc.addItem(item)
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    sc.render(p)
    p.end()
    return img


rect = QRectF(20, 10, 80, 40)
ann = RedactionAnnotation(rect, QColor("#000000"))
item = ann.create_item()
RedactionAnnotation.final_view = False
check("create_item: RedactItem", isinstance(item, RedactItem))
a, border, rad = item.appearance()
check("yumuşak: ~%55 alfa, kenar var, yuvarlak köşe", 120 <= a <= 160 and border and rad > 0, str((a, border, rad)))
img = render_item(item)
c = QColor(img.pixel(60, 30)).red()
check("yumuşak: dolgu yarı saydam (siyah değil, beyaz değil)", 80 < c < 160, str(c))
corner = QColor(img.pixel(20, 10)).red()
check("yumuşak: köşe yuvarlak (köşe pikseli dolu değil)", corner > c + 30, f"{corner} vs {c}")
edge = QColor(img.pixel(60, 10)).red()
check("yumuşak: kenar çizgisi dolgudan farklı (açık/vurgu)", edge != c, str(edge))
RedactionAnnotation.final_view = True
a2, border2, rad2 = item.appearance()
img2 = render_item(ann.create_item())
check("nihai görünüm: tam dolgu, kenarsız, dik köşe", (a2, border2, rad2) == (255, False, 0.0))
check("nihai: dolgu tam siyah, köşe de dolu", QColor(img2.pixel(60, 30)).red() == 0 and QColor(img2.pixel(21, 11)).red() == 0)
check("anahtar aynı öğeyi canlı değiştirir (yeniden oluşturma gerekmez)", item.appearance() != (RedactItem.SOFT_ALPHA, True, RedactItem.RADIUS))
RedactionAnnotation.final_view = False
check("anahtar kapanınca yumuşağa döner", item.appearance() == (RedactItem.SOFT_ALPHA, True, RedactItem.RADIUS))
q = RedactionAnnotation(rect, QColor("#ffffff"), quiet=True).create_item()
check("quiet: her zaman düz tam dolgu (altındaki yazı sızmasın)", q.appearance() == (255, False, 0.0))
RedactionAnnotation.final_view = True
check("quiet nihai bayraktan bağımsız", q.appearance() == (255, False, 0.0))
RedactionAnnotation.final_view = False

# ====================== pencere ======================
import main_window as mw
import workspace
from ui.redactopts import RedactOptions
from ui.kvkk import KvkkDialog
from mw_common import TOOLS

w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
w.stamp_lib.settings = w.settings
w.sig_lib.settings = w.settings
workspace.configure(w.settings)
w.resize(1400, 900)
w.show()


def pump(ms=150, until=None, limit=15000):
    t0 = time.time()
    while (time.time() - t0) * 1000 < (limit if until else ms):
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.01)
    return False


red_tool = next(t for t in TOOLS if t and t[0] == "redact")
check("araç ipucu: KALICI silinir", "KALICI" in red_tool[3] and "metin ve resim" in red_tool[3], red_tool[3])
check("özellik çubuğunda sansür seçenekleri", isinstance(w.redact_opts, RedactOptions) and len(w.redact_opts.preset_btns) == 3)
check("hazır dolgu: siyah işaretli başlar", w.redact_opts.preset_btns[0][1].isChecked() and w.state.redact_color.name() == "#000000")
w.redact_opts.preset_btns[1][1].click()
check("Koyu gri hazırı: durum + özel renk düğmesi", w.state.redact_color.name() == "#404040"
      and "#404040" in w._color_buttons_by_attr["redact_color"][0].styleSheet() and w.redact_opts.preset_btns[1][1].isChecked()
      and not w.redact_opts.preset_btns[0][1].isChecked())
w.redact_opts.preset_btns[2][1].click()
check("Beyaz hazırı", w.state.redact_color.name() == "#ffffff")
w._set_redact_color(QColor("#123456"))
w.redact_opts.refresh()
check("özel renk: hazırların hiçbiri işaretli değil", not any(b.isChecked() for _, b in w.redact_opts.preset_btns))
w.redact_opts.preset_btns[0][1].click()
w.redact_opts.label_combo.setCurrentText("[KARARTILDI]")
check("etiket kutusu -> durum", w.state.redact_label == "[KARARTILDI]")
w.redact_opts.label_combo.setCurrentText("  GİZLİ  ")
check("etiket kırpılır", w.state.redact_label == "GİZLİ")
check("etiket ön ayarları", [w.redact_opts.label_combo.itemText(i) for i in range(w.redact_opts.label_combo.count())][:3] == ["", "GİZLİ", "[KARARTILDI]"])

# ilk kullanım uyarısı
shown = []
w.toasts.show = lambda *a, **k: shown.append(a[0])
btn = next(b for k, b in w._tool_buttons if k == "redact") if isinstance(w._tool_buttons[0], tuple) else None
w._select_tool("redact", btn or w.btn_select)
check("ilk seçimde KALICI uyarısı", any("KALICI" in m for m in shown) and str(w.settings.value("redactHintShown")).lower() == "true", str(shown))
n = len(shown)
w._select_tool("select", w.btn_select)
w._select_tool("redact", btn or w.btn_select)
check("uyarı yalnız bir kez", len(shown) == n)
w._select_tool("select", w.btn_select)

# belge + sansür + nihai görünüm anahtarı
w.open_paths([SRC])
pump(400)
s = w.sessions[0]
ra = RedactionAnnotation(BOX, QColor("#000000"), label="GİZLİ")
w.add_annotation(ra)
pump(300)
items = [i for i in w.view.scene().items() if isinstance(i, RedactItem)]
check("sahnede RedactItem var", len(items) >= 1)
check("başlangıç: yumuşak", all(i.appearance()[1] for i in items) and RedactionAnnotation.final_view is False)
w.chk_redact_final.setChecked(True)
pump(100)
check("anahtar (özellik çubuğu): bayrak + ayar + menü senkron", RedactionAnnotation.final_view and w.act_redact_final.isChecked()
      and str(w.settings.value("redactFinal")).lower() == "true")
check("anahtar: sahne öğesi nihai görünüme geçti", all(i.appearance() == (255, False, 0.0) for i in items))
w.act_redact_final.setChecked(False)
pump(100)
check("menüden kapatınca: onay kutusu senkron, öğe yumuşak", not w.chk_redact_final.isChecked() and not RedactionAnnotation.final_view
      and all(i.appearance()[1] for i in items))
w.set_redact_final_view(True)
check("ayar yeniden başlatmada okunur (bayrak kalıcı)", str(QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat).value("redactFinal")).lower() == "true")
w.set_redact_final_view(False)
# pencereden dışa aktarma: gerçek silme + etiket
outw = os.path.join(tmp, "pencere.pdf")
s.pdf.export_pdf(outw, s.annotations, w.font_ctx)
rw = fitz.open(outw)
check("pencere dışa aktarımı: silindi + etiket", SECRET not in rw[0].get_text() and "GİZLİ" in rw[0].get_text())
rw.close()

# KVKK penceresi: aynı seçenekler
KV = os.path.join(tmp, "kvkk.pdf")
kd = fitz.open()
kp = kd.new_page()
kp.insert_text((72, 100), "Eposta: ornek.kisi@example.com", fontsize=14)
kp.insert_text((72, 140), "Baska satir kalsin", fontsize=14)
kd.save(KV)
kd.close()
w.open_paths([KV])
pump(400)
ks = w.sessions[-1]
w.state.redact_label = ""
dlg = KvkkDialog(w, ks)
dlg.show()
pump(200)
check("KVKK penceresinde dolgu/etiket seçenekleri", isinstance(dlg.redact_opts, RedactOptions))
dlg.redact_opts.preset_btns[1][1].click()
dlg.redact_opts.label_combo.setCurrentText("KVKK")
check("KVKK seçenekleri ortak duruma yazar", w.state.redact_color.name() == "#404040" and w.state.redact_label == "KVKK")
dlg._scan()
check("KVKK taraması bitti", pump(until=lambda: dlg.btn_apply.isEnabled(), limit=20000), dlg.summary.text())
dlg._apply()
pump(300)
reds = [a for a in ks.annotations[0] if isinstance(a, RedactionAnnotation)]
check("KVKK kutuları seçilen dolgu + etiketle eklendi", len(reds) >= 1 and all(a.label == "KVKK" and a.fill_color.name() == "#404040" for a in reds))
outk = os.path.join(tmp, "kvkk_out.pdf")
ks.pdf.export_pdf(outk, ks.annotations, w.font_ctx)
rk = fitz.open(outk)
tk = rk[0].get_text()
check("KVKK çıktısı: e-posta silindi, etiket var, diğer satır duruyor", "example.com" not in tk and "KVKK" in tk and "Baska satir kalsin" in tk, repr(tk[:70]))
rk.close()

# ekran görüntüsü (sonda tek): sansür aracı + yumuşak kutu
w.switch_session(0)
pump(300)
w.state.redact_label = "GİZLİ"
w.redact_opts.refresh()
w._select_tool("redact", btn or w.btn_select)
pump(500)
shot = os.path.join(tempfile.gettempdir(), "i2_ekran.png")
w.grab().save(shot)

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
print("ekran:", shot)
sys.stdout.flush()
from PySide6.QtCore import QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
os._exit(0 if all(ok) else 1)
