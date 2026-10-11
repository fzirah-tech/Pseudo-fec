#!/usr/bin/env python3
"""Construit le dossier PORTABLE Windows de Pseudo-FEC : Python officiel + composants + application.

Fonctionne depuis n'importe quel système (Linux, macOS, Windows) avec un accès à PyPI et NuGet,
UNIQUEMENT au moment de la construction. Le dossier produit, lui, est autonome et hors ligne.

Sources :
- Python : paquet « python » de la Python Software Foundation sur nuget.org (distribution Windows complète) ;
- composants : roues Windows (win_amd64) de PyPI, versions épinglées dans requirements.txt.

Usage : python scripts/build_portable.py [--out dist] [--python-prefix 3.13]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NUGET = "https://api.nuget.org/v3-flatcontainer/python"
FOLDER = "Pseudo-FEC"
# éléments de la distribution Python inutiles à l'exécution (outils de compilation, pip, aide intégrée)
PRUNE = ["include", "libs", "Lib/ensurepip", "Lib/pydoc_data", "Lib/venv", "Lib/test", "Lib/idlelib",
         "Lib/turtledemo", "Lib/tkinter"]
PRUNE_GLOBS = ["Lib/site-packages/pip", "Lib/site-packages/pip-*.dist-info"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as fh:  # noqa: S310 (https, hôtes fixes)
        shutil.copyfileobj(r, fh)


def latest_python(prefix: str) -> str:
    with urllib.request.urlopen(f"{NUGET}/index.json", timeout=60) as r:  # noqa: S310
        versions = json.load(r)["versions"]
    stable = [v for v in versions if v.startswith(prefix + ".") and "-" not in v]
    if not stable:
        raise SystemExit(f"Aucune version stable de Python {prefix} sur NuGet.")
    return sorted(stable, key=lambda v: [int(x) for x in v.split(".")])[-1]


def extract_python(nupkg: Path, dest: Path) -> None:
    with zipfile.ZipFile(nupkg) as z:
        if z.testzip() is not None:
            raise SystemExit("Archive Python corrompue.")
        for info in z.infolist():
            if info.filename.startswith("tools/") and not info.is_dir():
                target = dest / info.filename[len("tools/"):]
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    for rel in PRUNE:
        shutil.rmtree(dest / rel, ignore_errors=True)
    for pattern in PRUNE_GLOBS:
        for p in dest.glob(pattern):
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()


def download_wheels(requirements: Path, target: Path, pyver: str) -> list[Path]:
    cmd = [sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "-q", "--only-binary=:all:",
           "--platform", "win_amd64", "--python-version", pyver, "--implementation", "cp",
           "--abi", "cp" + pyver.replace(".", ""), "-r", str(requirements), "-d", str(target)]
    subprocess.run(cmd, check=True)
    return sorted(target.glob("*.whl"))


def install_wheels(wheels: list[Path], site: Path) -> None:
    site.mkdir(parents=True, exist_ok=True)
    for w in wheels:
        with zipfile.ZipFile(w) as z:
            z.extractall(site)


def wheel_info(w: Path) -> dict[str, str]:
    with zipfile.ZipFile(w) as z:
        meta = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
        fields: dict[str, str] = {}
        for line in z.read(meta).decode("utf-8", "replace").splitlines():
            if not line:
                break
            k, _, v = line.partition(": ")
            fields.setdefault(k, v)
    lic = fields.get("License-Expression") or fields.get("License") or next(
        (x for x in fields.get("Classifier", "").split("\n") if "License" in x), "voir le fichier de licence du composant")
    return {"nom": fields.get("Name", w.name), "version": fields.get("Version", "?"), "licence": lic[:80],
            "fichier": w.name, "sha256": sha256(w)}


def copy_app(dest: Path) -> None:
    shutil.copytree(ROOT / "pseudo_fec", dest / "pseudo_fec",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.enc"))


def write_text(path: Path, text: str, crlf: bool = False) -> None:
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def build(out_dir: Path, prefix: str) -> Path:
    sys.path.insert(0, str(ROOT))
    from pseudo_fec import __version__

    pyver = latest_python(prefix)
    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        pkg = tmp / FOLDER
        print(f"→ Python {pyver} (nuget.org, Python Software Foundation)")
        nupkg = tmp / "python.nupkg"
        fetch(f"{NUGET}/{pyver}/python.{pyver}.nupkg", nupkg)
        nupkg_hash = sha256(nupkg)
        extract_python(nupkg, pkg / "python")
        print("→ Composants Windows (PyPI)")
        wheels = download_wheels(ROOT / "requirements.txt", tmp / "wheels", prefix)
        install_wheels(wheels, pkg / "python" / "Lib" / "site-packages")
        print("→ Application")
        copy_app(pkg / "app")
        shutil.copy(ROOT / "packaging" / "Lancer-Pseudo-FEC.bat", pkg / "Lancer-Pseudo-FEC.bat")
        shutil.copy(ROOT / "packaging" / "DEMARRER-portable.html", pkg / "DEMARRER.html")
        infos = [wheel_info(w) for w in wheels]
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        write_text(pkg / "VERSION.txt",
                   f"Pseudo-FEC {__version__}\nConstruit le {now}\nPython {pyver} (nuget.org / Python Software Foundation)\n"
                   f"SHA-256 de l'archive Python : {nupkg_hash}\n\nComposants (SHA-256 des roues d'origine) :\n"
                   + "\n".join(f"  {i['fichier']}  {i['sha256']}" for i in infos) + "\n", crlf=True)
        write_text(pkg / "INVENTAIRE-COMPOSANTS.txt",
                   "Composants embarqués et licences (à conserver pour la conformité de l'usage professionnel)\n\n"
                   f"Python {pyver} : licence PSF (voir python\\LICENSE.txt)\n"
                   + "\n".join(f"{i['nom']} {i['version']} : {i['licence']}" for i in infos)
                   + "\n\nLes fichiers de licence de chaque composant figurent dans python\\Lib\\site-packages\\"
                     "<composant>.dist-info\\.\n", crlf=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        zip_path = out_dir / f"Pseudo-FEC-{__version__}-windows-portable.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for f in sorted(pkg.rglob("*")):
                if f.is_file():
                    z.write(f, f"{FOLDER}/{f.relative_to(pkg).as_posix()}")
        (out_dir / (zip_path.name + ".sha256")).write_text(f"{sha256(zip_path)}  {zip_path.name}\n")
    print(f"✓ {zip_path} ({zip_path.stat().st_size / 1e6:.1f} Mo)")
    return zip_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="dist")
    ap.add_argument("--python-prefix", default="3.13")
    a = ap.parse_args()
    build(Path(a.out), a.python_prefix)
