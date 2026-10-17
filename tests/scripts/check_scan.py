import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import numpy as np
import cv2
import fitz
from PIL import Image

tmp = tempfile.mkdtemp(prefix="g1_")
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("OK   " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


import scan

# ---- sentetik fotograf: koyu zemin + perspektifli beyaz kagit (yazi satirlari + golge gradyani)
PW, PH = 600, 800
paper = np.full((PH, PW, 3), 245, np.uint8)
rng = np.random.default_rng(1)
for y in range(80, PH - 60, 38):
    for x in range(60, PW - 60, 70):
        cv2.rectangle(paper, (x, y), (x + int(rng.integers(30, 60)), y + 12), (30, 30, 30), -1)
grad = np.linspace(1.0, 0.55, PW, dtype=np.float32)[None, :, None]       # sagdan sola golge
paper = (paper * grad).astype(np.uint8)
W, H = 1600, 1200
bg = np.full((H, W, 3), 45, np.uint8)
bg = np.clip(bg + rng.normal(0, 4, bg.shape), 0, 255).astype(np.uint8)
TRUE = np.array([[430, 120], [1130, 100], [1190, 1100], [380, 1080]], np.float32)   # SO, SaO, SaA, SA
M = cv2.getPerspectiveTransform(np.array([[0, 0], [PW - 1, 0], [PW - 1, PH - 1], [0, PH - 1]], np.float32), TRUE)
mask = cv2.warpPerspective(np.full((PH, PW), 255, np.uint8), M, (W, H))
photo = cv2.warpPerspective(paper, M, (W, H))
photo = np.where(mask[:, :, None] > 0, photo, bg)
photo_path = os.path.join(tmp, "foto.jpg")
Image.fromarray(photo).save(photo_path, quality=92)

# ---- load_image
im = scan.load_image(photo_path)
check("load_image: RGB uint8", im.ndim == 3 and im.shape[2] == 3 and im.dtype == np.uint8 and im.shape[:2] == (H, W))
big = os.path.join(tmp, "buyuk.png")
Image.fromarray(np.zeros((3600, 2400, 3), np.uint8)).save(big)
b = scan.load_image(big)
check("load_image: >3000 px kucultulur", max(b.shape[:2]) == 3000 and b.shape[:2] == (3000, 2000), str(b.shape))
ex = Image.new("RGB", (200, 100), (255, 0, 0))
exif = Image.Exif()
exif[0x0112] = 6
exp = os.path.join(tmp, "exif.jpg")
ex.save(exp, exif=exif)
check("load_image: EXIF yonu uygulanir", scan.load_image(exp).shape[:2] == (200, 100))
rgba = os.path.join(tmp, "a.png")
Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(rgba)
check("load_image: saydamlik beyaz", int(scan.load_image(rgba).min()) == 255)

# ---- order_points
sh = TRUE[[2, 0, 3, 1]]
check("order_points: karisik girdi -> SO,SaO,SaA,SA", np.allclose(scan.order_points(sh), TRUE))
ang = np.deg2rad(20)
Rm = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
base = np.array([[-200, -150], [200, -150], [200, 150], [-200, 150]], np.float32)
rot = (base @ Rm.T + 500).astype(np.float32)                                    # 20 derece donuk dikdortgen
check("order_points: donuk dortgen SO'dan saat yonunde", np.allclose(scan.order_points(rot[[2, 3, 0, 1]]), rot, atol=1e-3))

# ---- detect_corners
c = scan.detect_corners(im)
err = np.abs(c - TRUE) / np.array([W, H])
check("detect_corners: 4 kose, +-%3", c is not None and c.shape == (4, 2) and err.max() <= 0.03, f"{err.max():.3f}")
check("detect_corners: sirali", np.allclose(scan.order_points(c), c))
flat = np.full((400, 600, 3), 128, np.uint8)
cf = scan.detect_corners(flat)
check("detect_corners: bulunamazsa tum goruntu", np.allclose(cf, [[0, 0], [599, 0], [599, 399], [0, 399]]))
check("detect_corners: fallback=False -> None", scan.detect_corners(flat, fallback=False) is None)
check("detect_corners: PIL girdisi", scan.detect_corners(Image.fromarray(photo)).shape == (4, 2))

# ---- warp
w = scan.warp(im, c)
exp_ratio = PW / PH
got = w.shape[1] / w.shape[0]
check("warp: cikti orani ~ kagit orani", abs(got - exp_ratio) / exp_ratio < 0.12, f"{got:.3f} vs {exp_ratio:.3f}")
check("warp: kagit dolu (kenarda koyu zemin yok)", w[5:-5, 5:-5].mean() > 120 and min(w[4:7].mean(), w[-7:-4].mean(), w[:, 4:7].mean(), w[:, -7:-4].mean()) > 100, f"{w.mean():.0f}")
sq = scan.warp(im, np.array([[0, 0], [199, 0], [199, 99], [0, 99]], np.float32))
check("warp: boyut kenar uzunluklarindan", sq.shape[:2] == (99, 199), str(sq.shape))

# ---- rotate
r = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)
check("rotate 90: saat yonu", np.array_equal(scan.rotate(r, 90), np.rot90(r, -1)) and scan.rotate(r, 90).shape[:2] == (3, 2))
check("rotate 180/270/-90", scan.rotate(r, 180).shape == r.shape and scan.rotate(r, 270).shape[:2] == (3, 2)
      and np.array_equal(scan.rotate(r, -90), scan.rotate(r, 270)))
check("rotate 360 = ayni", np.array_equal(scan.rotate(r, 360), r))
r30 = scan.rotate(np.zeros((100, 200, 3), np.uint8), 30)
check("rotate 30: tuval buyur, kose beyaz", r30.shape[0] > 100 and r30.shape[1] > 200 and tuple(r30[0, 0]) == (255, 255, 255))

# ---- filtreler
for f in scan.FILTERS:
    o = scan.apply_filter(w, f)
    check(f"filtre {f}: sekil/tur korunur", o.shape == w.shape and o.dtype == np.uint8)
check("filtre orijinal: ayni icerik", np.array_equal(scan.apply_filter(w, "orijinal"), w))
g = scan.apply_filter(w, "gri")
check("filtre gri: kanallar esit", np.array_equal(g[:, :, 0], g[:, :, 1]) and np.array_equal(g[:, :, 1], g[:, :, 2]))
d = scan.apply_filter(w, "belge")
frac = np.isin(d, (0, 255)).mean()
check("filtre belge: >=%95 0/255", frac >= 0.95, f"{frac:.3f}")
check("filtre belge: zemin beyaz, yazi siyah var", (d == 255).mean() > 0.7 and (d == 0).mean() > 0.005, f"{(d==255).mean():.2f} {(d==0).mean():.3f}")
left, right = (d[:, :d.shape[1] // 3] == 255).mean(), (d[:, -d.shape[1] // 3:] == 255).mean()
check("filtre belge: golge kalkti (iki yan benzer)", abs(left - right) < 0.08, f"{left:.2f} {right:.2f}")
check("filtre ad: Turkce/ASCII/buyuk harf", np.array_equal(scan.apply_filter(w, "CANLI"), scan.apply_filter(w, "canlı"))
      and np.array_equal(scan.apply_filter(w, "golgesiz renkli"), scan.apply_filter(w, "Gölgesiz Renkli")))
try:
    scan.apply_filter(w, "yok")
    bad = False
except ValueError:
    bad = True
check("filtre: bilinmeyen ad ValueError", bad)
bright = scan.apply_filter(w, "orijinal", parlaklik=50)
dark = scan.apply_filter(w, "orijinal", parlaklik=-50)
check("parlaklik: yukari/asagi", bright.mean() > w.mean() > dark.mean())
hc = scan.apply_filter(w, "gri", kontrast=60)
check("kontrast: std artar", hc.std() > scan.apply_filter(w, "gri").std())
check("belge + parlaklik: hala 0/255", np.isin(scan.apply_filter(w, "belge", parlaklik=20, kontrast=20), (0, 255)).all())
colored = np.zeros((120, 160, 3), np.uint8)
colored[:, :80] = (200, 60, 60)
colored[:, 80:] = (60, 60, 200)
cv_ = scan.apply_filter(colored, "canlı")
check("filtre canli: renk korunur", cv_[10, 10, 0] > cv_[10, 10, 2] and cv_[10, 150, 2] > cv_[10, 150, 0])

# ---- to_pdf
pages = [w, scan.apply_filter(w, "belge"), scan.rotate(w, 90)]
doc = scan.to_pdf(pages, sayfa_boyutu="a4", kenar_bosluk_pt=20)
check("to_pdf: sayfa sayisi", doc.page_count == 3)
r0, r2 = doc[0].rect, doc[2].rect
check("to_pdf: A4 boyutu + yon otomatik", abs(r0.width - 595.276) < .5 and abs(r0.height - 841.89) < .5 and r2.width > r2.height)
ir = doc[0].get_image_info()[0]["bbox"]
check("to_pdf: kenar boslugu + orantili", ir[0] >= 19.9 and ir[1] >= 19.9 and ir[2] <= r0.width - 19.9 and ir[3] <= r0.height - 19.9
      and abs((ir[2] - ir[0]) / (ir[3] - ir[1]) - w.shape[1] / w.shape[0]) < 0.01, str(ir))
doc.close()
dl = scan.to_pdf([w], sayfa_boyutu="Letter")
check("to_pdf: letter", abs(dl[0].rect.width - 612) < .5 and abs(dl[0].rect.height - 792) < .5)
dl.close()
do = scan.to_pdf([w], sayfa_boyutu="orijinal")
check("to_pdf: orijinal oran", abs(do[0].rect.width / do[0].rect.height - w.shape[1] / w.shape[0]) < 0.01
      and max(do[0].rect.width, do[0].rect.height) <= 1600.5)
do.close()
out = os.path.join(tmp, "tara.pdf")
res = scan.to_pdf([photo_path, w], out, "a4", 0, 70)
chk = fitz.open(out)
check("to_pdf: dosyaya yazar (yol + dosya girdisi)", res == out and chk.page_count == 2 and not os.path.exists(out + ".part"))
chk.close()
lo = os.path.getsize(scan.to_pdf([w], os.path.join(tmp, "lo.pdf"), "a4", 0, 30))
hi = os.path.getsize(scan.to_pdf([w], os.path.join(tmp, "hi.pdf"), "a4", 0, 95))
check("to_pdf: jpeg_kalite boyutu etkiler", lo < hi, f"{lo} {hi}")
bw = os.path.getsize(scan.to_pdf([d], os.path.join(tmp, "bw.pdf"), "a4"))
check("to_pdf: siyah-beyaz kucuk (PNG)", bw < hi)
for bad_call, nm in ((lambda: scan.to_pdf([w], sayfa_boyutu="a0"), "boyut"), (lambda: scan.to_pdf([]), "bos liste")):
    try:
        bad_call()
        raised = False
    except ValueError:
        raised = True
    check(f"to_pdf: gecersiz {nm} ValueError", raised)

print(f"OZET: {sum(ok)}/{len(ok)} gecti")
