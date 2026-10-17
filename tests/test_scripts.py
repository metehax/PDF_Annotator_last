"""tests/scripts/check_*.py denetim betiklerini pytest altında çalıştırır.

Her betik kendi sürecinde çalışır (Qt uygulaması/`os._exit` içerir), "OK/FAIL" satırları yazar ve
başarısızlıkta 1 ile çıkar. Başarısız olursa yalnızca FAIL satırları + özet gösterilir.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

_WORKSPACE = tempfile.mkdtemp(prefix="pdfann_ws_")
SCRIPTS = sorted((pathlib.Path(__file__).parent / "scripts").glob("check_*.py"))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.stem)
def test_script(script):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env["PDF_ANNOTATOR_WORKSPACE"] = _WORKSPACE        # betikler kullanıcının Belgeler klasörüne yazmasın
    env.setdefault("QT_QPA_PLATFORM", "windows")
    r = subprocess.run([sys.executable, "-u", str(script)], capture_output=True, env=env, timeout=600)
    out = r.stdout.decode("utf-8", "replace").splitlines()
    err = r.stderr.decode("utf-8", "replace").splitlines()
    fails = [ln for ln in out if ln.startswith("FAIL")]
    summary = [ln for ln in out if ln.startswith("OZET")]
    assert summary, "betik OZET satırı üretmedi\n" + "\n".join(err[-15:])
    # Sonuç OZET satırından okunur ("OZET: 40/40 gecti"); Qt'li betikler os._exit ile çıktığından
    # çıkış kodu (ör. çıkışta iş parçacığı çökmesi) tek başına güvenilir değildir.
    passed, total = summary[-1].split(":")[1].split()[0].split("/")
    assert passed == total and not fails, "\n".join(fails + summary + err[-15:])
