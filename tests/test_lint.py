"""pyflakes: kullanılmayan içe aktarma, tanımsız ad gibi hataları yakalar."""
import pathlib
import subprocess
import sys

import pytest

pytest.importorskip("pyflakes")
ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_pyflakes_temiz():
    files = [str(p) for p in [*(ROOT / "src").glob("*.py"), *(ROOT / "src" / "ui").glob("*.py"), *(ROOT / "tools").glob("*.py"), *(ROOT / "packaging").glob("*.py")]]
    r = subprocess.run([sys.executable, "-m", "pyflakes", *files], capture_output=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout.decode("utf-8", "replace")[-2000:]
