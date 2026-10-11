import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


@pytest.fixture
def bs(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("bootstrap_under_test", ROOT / "bootstrap.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    (tmp_path / "requirements.txt").write_text("cryptography==1\n")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    return m


def test_installation_requise_puis_non(bs, tmp_path):
    assert bs.need_install()
    py = bs.venv_python()
    py.parent.mkdir(parents=True)
    py.write_text("")
    assert bs.need_install()                         # pas de marqueur
    bs.marker().write_text(bs.requirements_hash())
    assert not bs.need_install()
    (tmp_path / "requirements.txt").write_text("cryptography==2\n")
    assert bs.need_install()                         # dépendances modifiées -> réinstallation


def test_chemins_selon_le_systeme(bs):
    assert bs.venv_python().name in ("python.exe", "python")


def test_python_trop_ancien_message_clair(bs, monkeypatch, capsys):
    monkeypatch.setattr(bs.sys, "version_info", (3, 9, 0, "final", 0))
    assert not bs.python_ok()
    assert "3.11" in capsys.readouterr().out


def test_mode_check_sans_rien_installer():
    r = subprocess.run([sys.executable, str(ROOT / "bootstrap.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "Python" in r.stdout


def test_fichier_bat_ascii_crlf_et_cas_sans_python():
    raw = (ROOT / "Lancer-Pseudo-FEC.bat").read_bytes()
    raw.decode("ascii")                               # pas d'accent : aucun souci de page de code Windows
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    txt = raw.decode()
    assert "bootstrap.py" in txt and ":nopython" in txt and "9009" in txt and "Add python.exe to PATH" in txt


def test_page_de_demarrage_presente_et_autonome():
    html = (ROOT / "DEMARRER.html").read_text(encoding="utf-8")
    assert "Lancer-Pseudo-FEC" in html and "Python 3.13" in html and "Débloquer" in html
    assert "<script" not in html and "src=" not in html          # aucune ressource externe ni script
