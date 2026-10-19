import os, sys, tempfile, time, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
import pymupdf as fitz
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QCheckBox

tmp = tempfile.mkdtemp(prefix="h1_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


import workflow as wfm
from workflow import Source, Workflow, WorkflowLibrary, run_file, run_batch, collect_files
from pdf_engine import resolve_font_ctx

app = QApplication.instance() or QApplication(sys.argv)
FC = resolve_font_ctx()


def mkpdf(path, pages=3, headings=True, title=None):
    d = fitz.open()
    for k in range(pages):
        pg = d.new_page()
        if headings:
            pg.insert_text((72, 90), f"{k + 1}. Bolum Basligi", fontsize=26)
        y = 140
        for _ in range(14):
            pg.insert_text((72, y), "Bu bir govde metnidir ve bolumun icerigini olusturur.", fontsize=11)
            y += 18
    if title is not None:
        d.set_metadata({"title": title})
    d.save(path)
    d.close()
    return path


def wf(*steps, name="t"):
    return Workflow(name, [wfm.Step(t, p) for t, p in steps])


def docx_text(path):
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode("utf-8", "ignore")


def lang_of(doc):
    return doc.xref_get_key(doc.pdf_catalog(), "Lang")[1]


# ---------------- adım şeması ----------------
check("STEP_ORDER = STEP_TYPES", sorted(wfm.STEP_ORDER) == sorted(wfm.STEP_TYPES) and len(set(wfm.STEP_ORDER)) == len(wfm.STEP_ORDER))
check("yeni adımlar kayıtlı", "a11y_fix" in wfm.STEP_ORDER and "to_word" in wfm.STEP_ORDER)
check("a11y_fix sayfa, to_word kayıtta (final) aşaması",
      wfm.STEP_TYPES["a11y_fix"].phase == "page" and wfm.STEP_TYPES["to_word"].phase == "final")
check("her adım: varsayılanlar + özet", all(isinstance(t.summary(t.defaults()), str) and t.sanitize(None) == t.defaults()
                                            for t in wfm.STEP_TYPES.values()))
a = wfm.STEP_TYPES["a11y_fix"]
check("a11y_fix şeması: dil, başlık ata, başlık, yer imi", [p.key for p in a.params] == ["lang", "set_title", "title", "bookmarks"])
check("bozuk parametre sessizce varsayılana", a.sanitize({"lang": 5, "set_title": "x", "bookmarks": None})
      == {"lang": "5", "set_title": True, "title": "", "bookmarks": False})
check("sanitize: bilinmeyen anahtar atılır", "zz" not in a.sanitize({"zz": 1}))

# ---------------- mevcut adımlar ----------------
SRC = mkpdf(os.path.join(tmp, "rapor.pdf"))
OUT = os.path.join(tmp, "out")


def run(w, src=None, **kw):
    return run_file(w, src or Source("rapor.pdf", SRC), OUT, font_ctx=FC, **kw)


r = run(wf(("rotate", {"degrees": 90, "scope": "range", "page_start": 2, "page_end": 3}), ("save", {"suffix": "_dondu"})))
d = fitz.open(r.output)
check("rotate: aralık döndürüldü", r.status == "ok" and [p.rotation for p in d] == [0, 90, 90], str(r.message))
check("save suffix: ad ve konum", os.path.basename(r.output) == "rapor_dondu.pdf" and os.path.dirname(r.output) == os.path.dirname(SRC))
d.close()

r = run(wf(("watermark", {"text": "GIZLI", "opacity": 40}), ("save", {"mode": "folder", "folder": OUT})))
d = fitz.open(r.output)
check("watermark: metin her sayfada", r.status == "ok" and all("GIZLI" in p.get_text() for p in d), r.message)
check("save folder: klasöre yazıldı", os.path.dirname(r.output) == OUT)
d.close()
r = run(wf(("watermark", {"text": "  "}), ("save", {"mode": "folder", "folder": OUT})))
check("watermark: boş metin hata (dosya yazılmaz)", r.status == "hata" and "Filigran" in r.message and r.output == "", r.message)

r = run(wf(("headfoot", {"f_center": "Sayfa {sayfa}/{toplam}"}), ("save", {"mode": "folder", "folder": OUT})))
d = fitz.open(r.output)
check("headfoot: numara yazıldı", r.status == "ok" and "Sayfa 2/3" in d[1].get_text().replace(" ", " "), r.message)
d.close()

big = os.path.join(tmp, "buyuk.pdf")
bd = fitz.open()
import numpy as np
for _ in range(2):
    pm = fitz.Pixmap(fitz.csRGB, 1600, 1200, bytes(np.random.default_rng(1).integers(0, 255, 1600 * 1200 * 3, dtype=np.uint8)), False)
    bd.new_page(width=800, height=600).insert_image(fitz.Rect(0, 0, 800, 600), pixmap=pm)
bd.save(big)
bd.close()
r = run(wf(("compress", {"level": "strong"}), ("save", {"mode": "folder", "folder": OUT})), Source("buyuk.pdf", big))
check("compress: çıktı küçüldü", r.status == "ok" and r.size_after < r.size_before * 0.7, f"{r.size_before}->{r.size_after}")

r = run(wf(("password", {"ask": False, "user_password": "abc123", "owner_password": "own", "allowed": ["print"]}),
           ("save", {"mode": "folder", "folder": OUT})))
d = fitz.open(r.output)
check("password: açma parolası ister", r.status == "ok" and d.needs_pass and d.authenticate("abc123") > 0 and d.page_count == 3, r.message)
d.close()
pwf = wf(("password", {"ask": True}), ("save", {"mode": "folder", "folder": OUT}))
r = run(pwf, overrides={"user_password": "sor42"})
d = fitz.open(r.output)
check("password ask: parola çalıştırırken gelir, şablona yazılmaz",
      d.needs_pass and d.authenticate("sor42") > 0 and pwf.steps[0].params["user_password"] == "")
d.close()

# kaydet kipleri
ov = mkpdf(os.path.join(tmp, "ezilecek.pdf"), pages=2)
before = os.path.getsize(ov)
r = run_file(wf(("rotate", {"degrees": 180}), ("save", {"mode": "overwrite", "backup": True})), Source("ezilecek.pdf", ov), OUT, font_ctx=FC)
d = fitz.open(ov)
check("overwrite: özgün güncellendi + yedek", r.status == "ok" and d[0].rotation == 180
      and any(f.startswith("ezilecek.yedek") for f in os.listdir(tmp)), r.message)
d.close()
op = mkpdf(os.path.join(tmp, "acik.pdf"), pages=1)
r = run_file(wf(("save", {"mode": "overwrite"})), Source("acik.pdf", op, data=open(op, "rb").read(), protect_original=True), OUT, font_ctx=FC)
check("overwrite: açık belge korunur (ada ek)", r.status == "ok" and r.output.endswith("acik_islendi.pdf") and os.path.getsize(op) > 0, r.output)
sub = os.path.join(tmp, "kok", "alt")
os.makedirs(sub)
mkpdf(os.path.join(sub, "x.pdf"), pages=1)
mkpdf(os.path.join(tmp, "kok", "y.pdf"), pages=1)
mkpdf(os.path.join(tmp, "kok", "y_islendi.pdf"), pages=1)
srcs = collect_files(os.path.join(tmp, "kok"))
check("collect_files: alt klasör var, ekli çıktı atlanır", sorted(s.name for s in srcs) == ["x.pdf", "y.pdf"] and
      next(s for s in srcs if s.name == "x.pdf").rel_dir == "alt", str([s.name for s in srcs]))
check("collect_files: özyinelemesiz", [s.name for s in collect_files(os.path.join(tmp, "kok"), recursive=False)] == ["y.pdf"])
rep = run_batch(wf(("save", {"mode": "folder", "folder": os.path.join(tmp, "cikti2"), "keep_structure": True})), srcs, "")
check("klasör yapısı korunur", rep.ok == 2 and os.path.exists(os.path.join(tmp, "cikti2", "alt", "x.pdf"))
      and os.path.exists(os.path.join(tmp, "cikti2", "y.pdf")), rep.summary())
check("save_suffix_of", wfm.save_suffix_of(wf(("save", {"suffix": "_z"}))) == "_z" and wfm.save_suffix_of(wf(("save", {"mode": "folder"}))) == "")

# ---------------- hazır şablonlar + kütüphane ----------------
st = QSettings(os.path.join(tmp, "k.ini"), QSettings.Format.IniFormat)
lib = WorkflowLibrary(st)
builtin_names = [w.name for w in wfm.BUILTINS]
check("hazır şablonlar listede (yeniler dahil)", all(n in lib.names() for n in builtin_names)
      and "Erişilebilir PDF" in builtin_names and "Word'e aktar" in builtin_names)
check("hazır şablonlar geçerli adımlardan oluşur", all(s.type in wfm.STEP_TYPES and s.params == s.stype.sanitize(s.params)
                                                      for w in wfm.BUILTINS for s in w.steps))
check("hazır şablon: kopya döner, düzenlemek asıl şablonu bozmaz", (lib.get("Arşiv paketi").add("rotate"),
                                                                    len(lib.get("Arşiv paketi").steps))[1] == 4)
check("hazır şablonlar uyarısız (doğrulama)", all(not [m for lv, m in w.validate() if lv == "uyarı"] for w in wfm.BUILTINS))
mine = wf(("rotate", {"degrees": 270}), ("a11y_fix", {"lang": "en-US"}), ("save", {"suffix": "_m"}), name="")
lib.save(mine, "Benim")
g = lib.get("Benim")
check("şablon kaydet/yükle", [s.type for s in g.steps] == ["rotate", "a11y_fix", "save"] and g.steps[1].params["lang"] == "en-US"
      and "Benim" in lib.names() and not lib.is_builtin("Benim"))
try:
    lib.save(mine, "Arşiv paketi")
    refused = False
except ValueError:
    refused = True
check("hazır şablonun üstüne yazılmaz", refused)
try:
    lib.save(mine, "  ")
    refused = False
except ValueError:
    refused = True
check("boş ad reddedilir", refused)
rt = WorkflowLibrary.import_json(WorkflowLibrary.export_json(g))
check("JSON dışa/içe aktarım", [s.type for s in rt.steps] == ["rotate", "a11y_fix", "save"])
for bad in ("{", '{"steps": 3}', '{"version": 99, "steps": []}'):
    try:
        WorkflowLibrary.import_json(bad)
        raised = False
    except ValueError:
        raised = True
    check(f"bozuk şablon reddedilir: {bad[:14]}", raised)
check("şablon sil", lib.delete("Benim") and "Benim" not in lib.names() and not lib.delete("Benim"))
st.setValue("workflows", "{bozuk")
check("bozuk ayar uygulamayı düşürmez", WorkflowLibrary(st).names() == builtin_names)
try:
    Workflow.from_dict({"steps": [{"type": "yok", "params": {}}]})
    raised = False
except ValueError:
    raised = True
check("bilinmeyen adım türü reddedilir", raised)

# ---------------- doğrulama uyarıları ----------------
w1 = wf(("watermark", {}), ("ocr", {}), ("save", {}))
check("uyarı: filigran OCR'dan önce", any("OCR" in m for lv, m in w1.validate() if lv == "uyarı"))
check("uyarı: etkin adım yok", Workflow("x", []).validate()[0][0] == "uyarı")
check("uyarı: iki sıkıştır", any("Birden çok" in m for _, m in wf(("compress", {}), ("compress", {})).validate()))
check("uyarı: yer imi OCR'dan önce", any("Yer imi" in m for _, m in wf(("a11y_fix", {"bookmarks": True}), ("ocr", {})).validate()))
check("yer imi OCR'dan sonra uyarı yok", not any("Yer imi" in m for _, m in wf(("ocr", {}), ("a11y_fix", {"bookmarks": True})).validate()))
check("uyarı: Word + sıkıştırma/parola", any("Word" in m for _, m in wf(("compress", {}), ("to_word", {})).validate())
      and any("Word" in m for _, m in wf(("password", {"ask": False, "user_password": "a"}), ("to_word", {})).validate())
      and not any("Word" in m for _, m in wf(("to_word", {})).validate()))

# ---------------- a11y_fix ----------------
r = run(wf(("a11y_fix", {"lang": "tr-TR", "set_title": True, "bookmarks": True}), ("save", {"mode": "folder", "folder": OUT})))
d = fitz.open(r.output)
toc = d.get_toc()
check("a11y_fix: dil", r.status == "ok" and "tr-TR" in lang_of(d), lang_of(d) + " " + r.message)
check("a11y_fix: başlık dosya adından", d.metadata.get("title") == "rapor", str(d.metadata))
check("a11y_fix: yer imleri 3 başlıktan", len(toc) == 3 and toc[0][0] == 1 and toc[0][2] == 1 and "Bolum" in toc[0][1], str(toc))
check("a11y_fix: adım mesajı özet", any("yer imi" in s.message for s in r.steps), str([s.message for s in r.steps]))
d.close()

r = run(wf(("a11y_fix", {"lang": "en-US", "set_title": True, "title": "Yillik Rapor", "bookmarks": False}),
           ("save", {"mode": "folder", "folder": OUT})))
d = fitz.open(r.output)
check("a11y_fix: özel başlık + dil, yer imi yok", d.metadata.get("title") == "Yillik Rapor" and "en-US" in lang_of(d) and d.get_toc() == [])
d.close()

good = mkpdf(os.path.join(tmp, "baslikli.pdf"), title="Mevcut Anlamli Baslik")
r = run(wf(("a11y_fix", {"set_title": True}), ("save", {"mode": "folder", "folder": OUT})), Source("baslikli.pdf", good))
d = fitz.open(r.output)
check("a11y_fix: anlamlı mevcut başlık korunur", d.metadata.get("title") == "Mevcut Anlamli Baslik", str(d.metadata))
d.close()
junk = mkpdf(os.path.join(tmp, "dosyaadi.pdf"), title="Microsoft Word - taslak.docx")
r = run(wf(("a11y_fix", {"set_title": True}), ("save", {"mode": "folder", "folder": OUT})), Source("dosyaadi.pdf", junk))
d = fitz.open(r.output)
check("a11y_fix: dosya adı gibi başlık yenilenir", d.metadata.get("title") == "dosyaadi", str(d.metadata))
d.close()

r = run(wf(("a11y_fix", {"lang": "", "set_title": False, "bookmarks": False}), ("save", {"mode": "folder", "folder": OUT})))
d = fitz.open(r.output)
check("a11y_fix: hepsi kapalı değişiklik yapmaz", r.status == "ok" and "Değişiklik yapılmadı" in r.steps[0].message
      and "tr-TR" not in lang_of(d) and not d.metadata.get("title"), r.steps[0].message)
d.close()

withtoc = mkpdf(os.path.join(tmp, "toclu.pdf"))
td = fitz.open(withtoc)
td.set_toc([[1, "Elle", 1]])
td.saveIncr()
td.close()
r = run(wf(("a11y_fix", {"bookmarks": True}), ("save", {"mode": "folder", "folder": OUT})), Source("toclu.pdf", withtoc))
d = fitz.open(r.output)
check("a11y_fix: var olan yer imine dokunmaz", d.get_toc() == [[1, "Elle", 1]] and "zaten var" in r.steps[0].message, r.steps[0].message)
d.close()
plain = mkpdf(os.path.join(tmp, "duz.pdf"), headings=False)
r = run(wf(("a11y_fix", {"bookmarks": True}), ("save", {"mode": "folder", "folder": OUT})), Source("duz.pdf", plain))
d = fitz.open(r.output)
check("a11y_fix: başlık yoksa hata vermez", r.status == "ok" and d.get_toc() == [] and "bulunamadı" in r.steps[0].message, r.steps[0].message)
d.close()

# ---------------- to_word ----------------
r = run(wf(("to_word", {}), ("save", {"mode": "folder", "folder": OUT})))
check("to_word: .docx yazıldı", r.status == "ok" and r.output.endswith(".docx") and os.path.getsize(r.output) > 2000, r.message)
check("to_word: içerik (başlık metni)", "Bolum Basligi" in docx_text(r.output))
check("to_word: PDF yazılmadı, boyut bilgisi", r.size_after == os.path.getsize(r.output) and r.pages == 3)
r2 = run(wf(("to_word", {}), ("save", {"mode": "folder", "folder": OUT})))
check("to_word: var olan ezilmez (2)", r2.output.endswith("rapor (2).docx") and os.path.exists(r.output), r2.output)
r3 = run(wf(("rotate", {"degrees": 90}), ("to_word", {}), ("save", {"suffix": "_w"})))
check("to_word: sayfa adımları önce uygulanır, ada ek", r3.status == "ok" and r3.output.endswith("rapor_w.docx"), r3.output)
sizes_before = os.path.getsize(SRC)
r4 = run_file(wf(("to_word", {}), ("save", {"mode": "overwrite", "backup": True})), Source("rapor.pdf", SRC), OUT, font_ctx=FC)
check("to_word + overwrite: özgün PDF ezilmez", r4.status == "ok" and r4.output.endswith(".docx") and os.path.getsize(SRC) == sizes_before
      and r4.output.endswith("rapor_islendi.docx"), r4.output)
r5 = run(wf(("to_word", {}), ("save", {"mode": "folder", "folder": OUT})), cancelled=lambda: True)
check("to_word: iptal -> dosya yok", r5.status == "iptal")
nf = [f for f in os.listdir(OUT) if f.endswith(".tmp") or f.endswith(".part")]
check("iptal: geçici dosya kalmadı", nf == [], str(nf))
# metinsiz (taranmış) sayfa: bilgilendirme notu
scn = os.path.join(tmp, "tarama.pdf")
sd = fitz.open()
pm = fitz.Pixmap(fitz.csRGB, 400, 300, bytes([230]) * (400 * 300 * 3), False)
sd.new_page(width=400, height=300).insert_image(fitz.Rect(0, 0, 400, 300), pixmap=pm)
sd.save(scn)
sd.close()
r6 = run(wf(("to_word", {}), ("save", {"mode": "folder", "folder": OUT})), Source("tarama.pdf", scn))
check("to_word: taranmış belgede OCR notu", r6.status == "ok" and "metin yok" in r6.message and "OCR" in r6.message, r6.message)
# hata: dönüştürülemeyen -> StepError benzeri sonuç, toplu iş sürer
rep = run_batch(wf(("to_word", {}), ("save", {"mode": "folder", "folder": OUT})),
                [Source("yok.pdf", os.path.join(tmp, "yok.pdf")), Source("rapor.pdf", SRC)], OUT, font_ctx=FC)
check("toplu: eksik dosya hata, diğeri sürer", [r.status for r in rep.results] == ["hata", "ok"] and "bulunamadı" in rep.results[0].message,
      str([(r.status, r.message) for r in rep.results]))

# ---------------- toplu: hata / iptal / rapor ----------------
corrupt = os.path.join(tmp, "bozuk.pdf")
open(corrupt, "wb").write(b"%PDF-1.4 bozuk icerik degil")
many = [Source(f"d{i}.pdf", mkpdf(os.path.join(tmp, f"d{i}.pdf"), pages=1)) for i in range(3)]
bw = wf(("rotate", {"degrees": 90}), ("save", {"mode": "folder", "folder": os.path.join(tmp, "toplu")}))
seen = []
rep = run_batch(bw, [many[0], Source("bozuk.pdf", corrupt), many[1]], "", font_ctx=FC, on_result=seen.append)
check("toplu: bozuk dosya hata, diğerleri tamam", [r.status for r in rep.results] == ["ok", "hata", "ok"] and rep.ok == 2 and rep.failed == 1
      and len(seen) == 3, rep.summary())
check("toplu: özet/rapor metni ve CSV", "2/3" in rep.summary() and "[HATA]" in rep.to_text() and rep.to_csv().count("\n") == 4)
n = {"i": 0}


def stop_after_first():
    return n["i"] > 0


def on_res(r):
    n["i"] += 1


rep = run_batch(bw, many, "", font_ctx=FC, cancelled=stop_after_first, on_result=on_res)
check("toplu iptal: ilk tamam, kalanlar iptal", [r.status for r in rep.results] == ["ok", "iptal", "iptal"] and rep.cancelled
      and "durduruldu" in rep.summary(), str([r.status for r in rep.results]))
prog = []
run_batch(bw, many[:1], "", font_ctx=FC, progress=lambda f, m: prog.append(f))
check("ilerleme 0..1 artan", prog and prog[-1] == 1.0 and all(0 <= f <= 1 for f in prog) and prog == sorted(prog))
r = run_file(wf(("save", {})), Source("x.pdf", os.path.join(tmp, "x.pdf")), OUT)
check("olmayan dosya: hata, istisna yok", r.status == "hata" and "bulunamadı" in r.message)
r = run_file(Workflow("bos", []), many[0], OUT)
check("boş zincir hata", r.status == "hata" and "etkin adım yok" in r.message)
off = wf(("rotate", {"degrees": 90}), ("save", {"mode": "folder", "folder": os.path.join(tmp, "kapali")}))
off.steps[0].enabled = False
r = run_file(off, many[0], "", font_ctx=FC)
d = fitz.open(r.output)
check("kapalı adım atlanır", r.status == "ok" and d[0].rotation == 0)
d.close()
r = run_file(wf(("save", {"mode": "folder", "folder": ""})), many[0], "", font_ctx=FC)
check("çıktı klasörü yoksa hata", r.status == "hata" and "klasör" in r.message.lower(), r.message)

# ---------------- OCR zinciri (kuruluysa) ----------------
import ocr
if ocr.find_tessdata():
    import cv2
    img = np.full((400, 900, 3), 255, np.uint8)
    cv2.putText(img, "RAPOR BASLIK", (30, 230), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 0), 7, cv2.LINE_AA)
    ip = os.path.join(tmp, "taranmis.png")
    cv2.imwrite(ip, img)
    r = run(wf(("ocr", {"language": "eng", "dpi": 200}), ("a11y_fix", {}), ("to_word", {}), ("save", {"mode": "folder", "folder": OUT})),
            Source("taranmis.png", ip))
    check("ocr -> a11y_fix -> to_word zinciri (görselden)", r.status == "ok" and r.output.endswith(".docx") and [x.status for x in r.steps] == ["ok"] * 4, r.message)
    r = run(wf(("ocr", {"language": "eng", "dpi": 200}), ("a11y_fix", {"set_title": True}), ("save", {"mode": "folder", "folder": OUT})),
            Source("taranmis.png", ip))
    d = fitz.open(r.output)
    check("ocr + a11y_fix: metin katmanı ve başlık", "RAPOR" in d[0].get_text().upper() and d.metadata.get("title") == "taranmis", d[0].get_text()[:40])
    d.close()
else:
    check("OCR kurulu değil: atlandı", True)

# ---------------- arayüz formu şemadan üretilir ----------------
import main_window as mw
from ui.workflow import WorkflowDialog

w = mw.MainWindow()
w.settings = QSettings(os.path.join(tmp, "t.ini"), QSettings.Format.IniFormat)
w.stamp_lib.settings = w.settings
w.sig_lib.settings = w.settings
w.resize(1300, 850)
w.show()


def pump(ms=150):
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.01)


dlg = WorkflowDialog(w)
dlg.show()
pump(300)
dlg.load_workflow(Workflow("", []))
sa = dlg.add_step("a11y_fix")
pump()
check("arayüz: adım zincire eklendi, form seçili adımı gösterir", sa in dlg.wf.steps and dlg.form._step is sa)
check("arayüz: a11y_fix formu şemadan (4 satır)", set(dlg.form._rows) == {"lang", "set_title", "title", "bookmarks"})
title_row = dlg.form._rows["title"]
check("arayüz: başlık satırı 'başlık ata' açıkken görünür", title_row.isVisibleTo(dlg.form))
dlg.form._rows["set_title"].findChild(QCheckBox).setChecked(False)
pump()
check("arayüz: 'başlık ata' kapanınca başlık satırı gizlenir, değer adıma yazılır",
      not title_row.isVisibleTo(dlg.form) and sa.params["set_title"] is False)
dlg.form._rows["bookmarks"].findChild(QCheckBox).setChecked(True)
check("arayüz: yer imi seçeneği adım parametresine yazıldı", sa.params["bookmarks"] is True)
sw = dlg.add_step("to_word")
pump()
check("arayüz: to_word (parametresiz) formu hata vermez", dlg.form._step is sw and dlg.form._rows == {})
keys = [dlg.palette.item(i).data(0x100) for i in range(dlg.palette.count())]
check("arayüz: palet yeni adımları içerir", "a11y_fix" in keys and "to_word" in keys and keys == wfm.STEP_ORDER, str(keys))
check("arayüz: doğrulama uyarısı çalışır", isinstance(dlg.wf.validate(), list))
dlg.close()

print(f"\nOZET: {sum(ok)}/{len(ok)} gecti")
sys.stdout.flush()
from PySide6.QtCore import QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
os._exit(0 if all(ok) else 1)
