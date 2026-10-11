"""Liste blanche : tiers génériques (organismes, grandes banques, énergéticiens…)
non pseudonymisés par défaut. Commune au cabinet, éditable, ajouts tracés.
"""

from __future__ import annotations

import datetime as dt
import getpass
import json
import os
from pathlib import Path
from typing import Any

from .config import Config
from .errors import PseudoFecError
from .textmatch import name_key, tokens


class Whitelist:
    def __init__(self, entries: list[str]):
        self.entries = list(entries)
        self._exact = {name_key(e) for e in entries if name_key(e)}
        self._prefixes = [tuple(sorted(tokens(e))) for e in entries]
        # entrées d'au moins 6 caractères : « ORANGE SA » ou « EDF ENTREPRISES » sont reconnus ;
        # les entrées courtes (« FREE », « AXA ») exigent une correspondance exacte.
        self._long = [t for t in (tokens(e) for e in entries) if sum(map(len, t)) >= 6]

    def matches(self, name: str) -> str | None:
        """Retourne l'entrée de la liste blanche couvrant ce tiers, sinon None."""
        key = name_key(name)
        if not key:
            return None
        if key in self._exact:
            return next(e for e in self.entries if name_key(e) == key)
        toks = [t for t in tokens(name)]
        for entry_tokens in self._long:
            n = len(entry_tokens)
            if toks[:n] == entry_tokens:
                return " ".join(entry_tokens).upper()
        return None


def add_entry(cfg: Config, name: str, dossier_code: str) -> dict[str, Any]:
    """Ajoute un tiers à la liste blanche du cabinet (fichier de configuration) et retourne la trace."""
    name = " ".join(name.split()).upper()
    if not name:
        raise PseudoFecError("Nom vide.")
    wl = cfg.cabinet.setdefault("whitelist", [])
    if name_key(name) in {name_key(e) for e in wl}:
        raise PseudoFecError("Ce tiers figure déjà dans la liste blanche.")
    wl.append(name)
    path = cfg.cabinet_file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(cfg.cabinet, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return {"date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "utilisateur": _user(),
            "dossier": dossier_code, "action": "ajout_liste_blanche", "nom": name}


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "inconnu"
