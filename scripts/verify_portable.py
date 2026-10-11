#!/usr/bin/env python3
"""Contrôle statique et dynamique d'une archive portable Windows de Pseudo-FEC.

Ce que ce contrôle PROUVE : structure complète, exécutables Windows 64 bits, imports de l'application
résolus dans le Python embarqué, aucun fichier sensible, version cohérente, application extraite démarrable
(avec l'interpréteur courant) et auto-diagnostic réussi.
Ce qu'il ne prouve PAS : l'exécution sous Windows (python.exe ne peut pas tourner ici).

Usage : python scripts/verify_portable.py archive.zip [--forbid TEXTE ...] [--smoke]
"""

from __future__ import annotations

import argparse
import ast
import http.client
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

FOLDER = "Pseudo-FEC"
REQUIRED = ["Lancer-Pseudo-FEC.bat", "DEMARRER.html", "VERSION.txt", "INVENTAIRE-COMPOSANTS.txt",
            "python/python.exe", "python/python313.dll", "python/vcruntime140.dll", "python/Lib/os.py",
            "app/pseudo_fec/__init__.py", "app/pseudo_fec/ui/static/index.html", "app/pseudo_fec/ui/static/app.js",
            "app/pseudo_fec/ui/static/style.css", "app/pseudo_fec/demo_data.py"]
SITE_REQUIRED = ["cryptography", "cffi", "pycparser"]
FORBIDDEN = [r"\.enc$", r"keyring\.json$", r"cabinet\.(json|canary)$", r"(^|/)\.env$", r"\.pem$", r"(^|/)\.git(/|$)",
             r"(^|/)tests?/", r"(^|/)\.venv/", r"FEC.*\.txt$", r"\.so(\.\d+)*$", r"\.dylib$", r"prefs\.json$",
             r"app/.*__pycache__", r"app/.*\.pyc$"]
# modules intégrés à python313.dll sous Windows (pas de fichier .py/.pyd séparé)
BUILTIN = {"sys", "time", "math", "itertools", "zlib", "binascii", "array", "marshal", "atexit", "errno", "gc", "nt",
           "msvcrt", "winreg", "_winapi", "_thread", "builtins", "_io", "_abc", "_codecs", "_collections", "_functools",
           "_locale", "_operator", "_signal", "_sre", "_stat", "_string", "_weakref", "_warnings", "cmath", "mmap",
           "faulthandler", "_random", "_struct", "_bisect", "_heapq", "_json", "_datetime", "_csv", "_pickle",
           "_md5", "_sha1", "_sha2", "_sha3", "_blake2", "_statistics", "_contextvars", "_opcode", "xxsubtype",
           "_imp", "_sysconfig", "_tokenize", "_tracemalloc", "_typing", "_symtable", "_ast", "_bz2", "_lzma"}


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, str]] = []

    def check(self, ok: bool, label: str) -> None:
        self.rows.append((ok, label))
        print(f"[{'OK' if ok else 'ÉCHEC'}] {label}")

    @property
    def ok(self) -> bool:
        return all(ok for ok, _ in self.rows)


def pe_machine(data: bytes) -> str | None:
    if data[:2] != b"MZ" or len(data) < 64:
        return None
    off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[off:off + 4] != b"PE\0\0":
        return None
    return {0x8664: "AMD64", 0x14C: "x86", 0xAA64: "ARM64"}.get(struct.unpack_from("<H", data, off + 4)[0], "autre")


def imports_of(tree: ast.AST) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def verify(zip_path: Path, forbid: list[str], smoke: bool) -> bool:
    r = Report()
    with zipfile.ZipFile(zip_path) as z:
        def rd(p: str) -> bytes:
            try:
                return z.read(f"{FOLDER}/{p}")
            except KeyError:
                return b""

        r.check(z.testzip() is None, "Archive ZIP intègre")
        names = z.namelist()
        r.check(all(n.startswith(FOLDER + "/") and ".." not in PurePosixPath(n).parts and not n.startswith("/") for n in names),
                "Chemins sûrs (un seul dossier racine, aucun « .. »)")
        rel = {n[len(FOLDER) + 1:] for n in names if not n.endswith("/")}
        missing = [p for p in REQUIRED if p not in rel]
        r.check(not missing, "Fichiers indispensables présents" + (f" — manquants : {missing}" if missing else ""))
        site = [p for p in rel if p.startswith("python/Lib/site-packages/")]
        site_top = {p.split("/")[3] for p in site if p.count("/") >= 3}
        r.check(all(any(t == c or t.startswith(c + "-") or t.startswith(c + ".") for t in site_top) for c in SITE_REQUIRED),
                "Composants Windows installés : " + ", ".join(sorted(t for t in site_top if t.endswith(".dist-info"))))
        r.check(any(p.startswith("python/Lib/site-packages/_cffi_backend") and p.endswith("win_amd64.pyd") for p in rel)
                and any(p.endswith("hazmat/bindings/_rust.pyd") for p in rel), "Extensions compilées Windows 64 bits (cffi, cryptography)")

        # formats des exécutables
        bad_pe = []
        for p in rel:
            if p.endswith((".exe", ".dll", ".pyd")):
                m = pe_machine(z.read(f"{FOLDER}/{p}")[:4096])
                if m != "AMD64":
                    bad_pe.append(f"{p}:{m}")
        r.check(not bad_pe, "Tous les .exe/.dll/.pyd sont des exécutables Windows AMD64" + (f" — anomalies : {bad_pe[:3]}" if bad_pe else ""))

        # fichiers interdits
        bad = [p for p in rel if any(re.search(rx, p, re.I) for rx in FORBIDDEN)]
        r.check(not bad, "Aucun fichier sensible ou parasite (tables, clés, FEC, .so, tests, caches)" + (f" — trouvés : {bad[:3]}" if bad else ""))

        # lanceur
        bat = rd("Lancer-Pseudo-FEC.bat")
        try:
            txt = bat.decode("ascii")
            ascii_ok = True
        except UnicodeDecodeError:
            txt, ascii_ok = "", False
        r.check(ascii_ok and b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b""), "Lanceur .bat : ASCII et fins de ligne CRLF")
        r.check(all(k in txt for k in ("pushd", "PYTHONPATH", "python\\python.exe", "-m pseudo_fec", "PYTHONNOUSERSITE")),
                "Lanceur .bat : utilise le Python embarqué et l'application locale (sans Python système)")

        # version
        init = rd("app/pseudo_fec/__init__.py").decode()
        ver = re.search(r'__version__ = "([^"]+)"', init)
        vtxt = rd("VERSION.txt").decode()
        r.check(bool(ver) and vtxt.startswith(f"Pseudo-FEC {ver.group(1)}"), f"Version cohérente ({ver.group(1) if ver else '?'})")

        # imports de l'application résolus dans le Python embarqué
        unresolved: list[str] = []
        third = set()
        for p in rel:
            if p.startswith("app/") and p.endswith(".py"):
                for mod in imports_of(ast.parse(z.read(f"{FOLDER}/{p}").decode("utf-8"))):
                    if mod == "pseudo_fec" or mod in BUILTIN:
                        continue
                    in_lib = f"python/Lib/{mod}.py" in rel or any(x.startswith(f"python/Lib/{mod}/") for x in rel)
                    in_dll = any(x.startswith(f"python/DLLs/{mod}") and x.endswith(".pyd") for x in rel) or f"python/DLLs/{mod}.pyd" in rel
                    in_site = mod in site_top or any(t.startswith(mod + ".") or t.startswith(mod + "-") for t in site_top)
                    if not (in_lib or in_dll or in_site):
                        unresolved.append(f"{mod} ({p})")
                    if in_site and not in_lib:
                        third.add(mod)
        r.check(not unresolved, "Tous les imports de l'application sont disponibles dans le dossier"
                + (f" — introuvables : {sorted(set(unresolved))[:4]}" if unresolved else f" (composants tiers : {sorted(third)})"))

        # textes interdits (ex. phrase secrète) : jamais dans l'archive
        leaks = []
        for p in rel:
            if p.endswith((".py", ".js", ".html", ".css", ".txt", ".bat", ".json", ".md")):
                content = z.read(f"{FOLDER}/{p}").decode("utf-8", "ignore").lower()
                leaks += [p for t in forbid if t.lower() in content]
        r.check(not leaks, f"Aucun texte interdit dans l'archive ({len(forbid)} motif(s) recherché(s))")

        if smoke:
            with tempfile.TemporaryDirectory() as tmp:
                z.extractall(tmp)
                r.check(smoke_run(Path(tmp) / FOLDER / "app"), "Application extraite : démarre et auto-diagnostic réussi (interpréteur courant)")
    print(f"\n{'TOUS LES CONTRÔLES PASSENT' if r.ok else 'AU MOINS UN CONTRÔLE A ÉCHOUÉ'} ({sum(ok for ok, _ in r.rows)}/{len(r.rows)})")
    return r.ok


def smoke_run(app_dir: Path) -> bool:
    env = dict(os.environ, PYTHONPATH=str(app_dir), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    with tempfile.TemporaryDirectory() as data:
        env.update(XDG_DATA_HOME=data, LOCALAPPDATA=data, PSEUDOFEC_PREFS=str(Path(data) / "prefs.json"),
                   HOME=data, USERPROFILE=data)
        proc = subprocess.Popen([sys.executable, "-m", "pseudo_fec", "--no-browser"], cwd=app_dir, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            url = None
            t0 = time.time()
            while time.time() - t0 < 30 and url is None:
                line = proc.stdout.readline()
                m = re.search(r"http://127\.0\.0\.1:(\d+)/\?t=([\w-]+)", line or "")
                if m:
                    url = (int(m.group(1)), m.group(2))
            if url is None:
                return False
            port, tok = url
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
            c.request("GET", "/api/diagnostic", headers={"Host": f"127.0.0.1:{port}", "Cookie": f"pf_token={tok}", "X-PF-Token": tok})
            resp = c.getresponse()
            body = resp.read().decode("utf-8")
            return resp.status == 200 and '"ok": true' in body
        finally:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive")
    ap.add_argument("--forbid", action="append", default=[], help="texte qui ne doit apparaître nulle part (répétable)")
    ap.add_argument("--smoke", action="store_true", help="démarre l'application extraite et lance l'auto-diagnostic")
    a = ap.parse_args()
    sys.exit(0 if verify(Path(a.archive), a.forbid, a.smoke) else 1)
