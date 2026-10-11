"""Auto-diagnostic : vérifie que l'installation fonctionne, sans toucher à aucune donnée réelle.

Le rapport ne contient aucun nom de tiers ; le répertoire personnel est masqué (« ~ »).
"""

from __future__ import annotations

import importlib.metadata as md
import platform
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from . import __version__, crypto
from .config import Config
from .demo_data import DEMO_FICHE, make_fec
from .detection import detect
from .dossier import apply_fiche, new_payload
from .fec_io import analyse, parse_fec
from .generic_list import Whitelist


def mask(path: Path | str) -> str:
    s = str(path)
    home = str(Path.home())
    return s.replace(home, "~") if home and home in s else s


def _check(name: str, fn) -> dict[str, Any]:
    try:
        ok, detail = fn()
        return {"nom": name, "ok": bool(ok), "detail": detail}
    except Exception as e:  # message générique : jamais de contenu de fichier
        return {"nom": name, "ok": False, "detail": f"Échec ({type(e).__name__})."}


def _writable(folder: Path) -> tuple[bool, str]:
    folder.mkdir(parents=True, exist_ok=True)
    probe = folder / f".diag-{uuid.uuid4().hex}.tmp"
    probe.write_bytes(b"ok")
    assert probe.read_bytes() == b"ok"
    probe.unlink()
    free = shutil.disk_usage(folder).free // (1024 * 1024)
    return True, f"{mask(folder)} — écriture et lecture OK, {free:,} Mo libres".replace(",", " ")


def run_checks(cfg: Config, listen: tuple[str, int] | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    out.append(_check("Python", lambda: (sys.version_info >= (3, 11), f"{platform.python_version()} sur {platform.system()} {platform.release()}"
                                         + ("" if sys.version_info >= (3, 11) else " — Python 3.11 ou plus requis"))))
    def components():
        parts = [f"cryptography {md.version('cryptography')}"]
        try:
            import rapidfuzz  # noqa: F401
            parts.append(f"rapidfuzz {md.version('rapidfuzz')}")
        except ImportError:
            parts.append("rapidfuzz absent (comparaison de noms en mode de secours, sans conséquence sur la sécurité)")
        return True, ", ".join(parts)
    out.append(_check("Composants", components))

    def crypto_check():
        saved = dict(crypto.KDF_DEFAULT)
        t0 = time.perf_counter()
        kr, dek = crypto.create_keyring("DIAG", "phrase de diagnostic", saved)      # paramètres réels du cabinet
        crypto.unlock_keyring(kr, "phrase de diagnostic")
        dt = time.perf_counter() - t0
        blob = crypto.encrypt_blob(dek, b"contenu", "DIAG")
        assert crypto.decrypt_blob(dek, blob, "DIAG") == b"contenu"
        return True, f"AES-256-GCM + scrypt (n={saved['n']}) : aller-retour OK, déverrouillage ≈ {dt:.1f} s"
    out.append(_check("Chiffrement des tables", crypto_check))
    out.append(_check("Dossier des tables", lambda: _writable(cfg.tables_root)))
    out.append(_check("Dossier des sorties", lambda: _writable(cfg.outputs_root)))

    def fec_check():
        n = 0
        for style in ("cabinet", "pennylane", "standard", "compte_individualise"):
            s = make_fec(style, "cp1252" if style == "cabinet" else "utf-8")
            f = parse_fec(s.data, s.filename)
            rep = analyse(f, cfg.priority_prefixes, "")
            assert f.serialize(f.rows()) == s.data and rep["equilibre"]
            n += 1
        return True, f"{n} FEC fictifs lus, contrôlés et réécrits à l'identique"
    out.append(_check("Lecture et réécriture de FEC", fec_check))

    def detect_check():
        s = make_fec("cabinet", "cp1252")
        p = new_payload("DIAG")
        apply_fiche(p, DEMO_FICHE)
        r = detect([parse_fec(s.data, s.filename)], p, cfg.priority_prefixes, Whitelist(cfg.cabinet.get("whitelist", [])))
        sal = sum(c.cat == "SAL" for c in r.candidates)
        return len(r.candidates) > 5 and sal >= 2, f"{len(r.candidates)} noms proposés dont {sal} salarié(s) sur un FEC fictif"
    out.append(_check("Détection des noms", detect_check))

    if listen is not None:
        out.append(_check("Réseau", lambda: (listen[0] == "127.0.0.1",
                                              f"Serveur local sur {listen[0]}:{listen[1]} (aucun accès depuis un autre poste)")))
    out.append(_check("Configuration", lambda: (True, f"liste blanche : {len(cfg.cabinet.get('whitelist', []))} tiers · "
                                                      f"fichier cabinet : {'présent' if cfg.cabinet_file.exists() else 'absent (valeurs par défaut)'}")))
    return out


def as_text(checks: list[dict[str, Any]]) -> str:
    lines = [f"Pseudo-FEC {__version__} — rapport d'auto-diagnostic (aucune donnée de dossier)"]
    lines += [f"[{'OK' if c['ok'] else 'ÉCHEC'}] {c['nom']} : {c['detail']}" for c in checks]
    return "\n".join(lines)
