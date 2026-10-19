"""Yayın dosyalarını üretir: kurucunun SHA-256'sı + dist\\latest.json (sürüm appinfo.py'den).

Kullanım:  python tools\\make_release.py [--base https://github.com/SAHIP/DEPO/releases/download/vSURUM] [--notes notlar.md]
`--base` verilmezse UPDATE_URL bir GitHub API adresiyse ondan türetilir.
Çıktı: dist\\PDF-Annotator-Setup-<sürüm>.exe.sha256 ve dist\\latest.json (GitHub Release'e kurucuyla birlikte yükleyin)."""
import argparse
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import appinfo


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def base_from_update_url(url, version):
    m = re.match(r"https://api\.github\.com/repos/([^/]+)/([^/]+)/releases", url or "")
    return f"https://github.com/{m.group(1)}/{m.group(2)}/releases/download/v{version}" if m else ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="")
    ap.add_argument("--notes", default="")
    a = ap.parse_args(argv)
    v = appinfo.VERSION
    setup = os.path.join(ROOT, "dist", f"PDF-Annotator-Setup-{v}.exe")
    if not os.path.isfile(setup):
        sys.exit(f"Kurucu yok: {setup} (önce build.bat)")
    base = (a.base or base_from_update_url(appinfo.UPDATE_URL, v)).rstrip("/")
    if not base.startswith("https://"):
        sys.exit("--base (https://…/releases/download/vSÜRÜM) gerekli.")
    sha = sha256_file(setup)
    notes = open(a.notes, encoding="utf-8").read() if a.notes else ""
    info = {"version": v, "url": f"{base}/{os.path.basename(setup)}", "sha256": sha,
            "notes": notes, "size": os.path.getsize(setup)}
    out = os.path.join(ROOT, "dist", "latest.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    with open(setup + ".sha256", "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{sha}  {os.path.basename(setup)}\n")
    print(f"SHA-256: {sha}\nYazıldı: {out}")


if __name__ == "__main__":
    main()
