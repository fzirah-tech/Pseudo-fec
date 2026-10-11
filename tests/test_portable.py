import ast
import importlib.util
import struct
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fake_pe(machine=0x8664):
    head = bytearray(b"MZ" + b"\0" * 62)
    head[0x3C:0x40] = struct.pack("<I", 0x80)
    return bytes(head) + b"\0" * (0x80 - 64) + b"PE\0\0" + struct.pack("<H", machine) + b"\0" * 200


def test_detection_du_format_des_executables():
    v = load("verify_portable")
    assert v.pe_machine(fake_pe(0x8664)) == "AMD64" and v.pe_machine(fake_pe(0x14C)) == "x86"
    assert v.pe_machine(b"\x7fELF" + b"\0" * 100) is None          # un binaire Linux est refusé


def test_analyse_des_imports():
    v = load("verify_portable")
    mods = v.imports_of(ast.parse("import os.path\nimport json, re\nfrom http.server import X\nfrom . import y\nfrom .z import w"))
    assert mods == {"os", "json", "re", "http"}


def test_archive_incomplete_ou_dangereuse_refusee(tmp_path):
    v = load("verify_portable")
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Pseudo-FEC/Lancer-Pseudo-FEC.bat", "echo")
        f.writestr("Pseudo-FEC/../evil.txt", "x")
        f.writestr("Pseudo-FEC/tables/keyring.json", "{}")
    assert v.verify(z, [], False) is False


def test_texte_interdit_detecte(tmp_path):
    v = load("verify_portable")
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Pseudo-FEC/app/pseudo_fec/__init__.py", '__version__ = "0.0.0"\nSECRET = "ma phrase secrète"\n')
    assert v.verify(z, ["MA PHRASE SECRÈTE"], False) is False


def test_lanceur_portable_conforme():
    raw = (ROOT / "packaging" / "Lancer-Pseudo-FEC.bat").read_bytes()
    txt = raw.decode("ascii")
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    for k in ("pushd", 'set "PYTHONPATH=%CD%\\app"', "PYTHONNOUSERSITE=1", '"python\\python.exe" -m pseudo_fec', ":manque"):
        assert k in txt, k


def test_guide_portable_autonome():
    html = (ROOT / "packaging" / "DEMARRER-portable.html").read_text(encoding="utf-8")
    assert "Débloquer" in html and "Lancer-Pseudo-FEC" in html and "<script" not in html and "src=" not in html


def test_script_de_construction_utilise_des_sources_epinglees():
    src = (ROOT / "scripts" / "build_portable.py").read_text(encoding="utf-8")
    assert "api.nuget.org" in src and "--only-binary=:all:" in src and "win_amd64" in src and "requirements.txt" in src
