"""Paramètres : cabinet (fichier partagé) et préférences locales (par utilisateur).

Priorité : valeurs par défaut < cabinet.json < préférences locales
(les préférences locales ne peuvent surcharger que les emplacements et
quelques réglages d'affichage, jamais la liste blanche ni les préfixes).
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

from .contexts import DEFAULT_CONTEXTS
from .errors import PseudoFecError

PREF_KEYS = {"tables_root", "outputs_root", "last_dossier", "idle_timeout_s"}

DEFAULT_CABINET: dict[str, Any] = {
    "version": 1,
    "tables_root": "",      # vide = emplacement local par défaut (pilote)
    "outputs_root": "",
    "max_fec_mb": 200,
    "versions_keep": 50,
    "lock_timeout_s": 300,
    "contexts": DEFAULT_CONTEXTS,    # comptes qui définissent les contextes sensibles (paie, comptes courants, provisions)
    "priority_prefixes": {
        "tiers_commerciaux": ["401", "403", "404", "408", "409", "411", "413", "416", "418", "419"],
        "personnel": ["421", "422", "425", "427", "428"],
        "groupe_associes": ["451", "455", "456", "457", "458"],
        "divers": ["467", "468", "471", "486", "487"],
        "participations_prets": ["260", "261", "262", "263", "264", "265", "266", "267", "268", "269", "271", "274", "275"],
        "emprunts": ["164", "165", "168"],
    },
    # Liste initiale À VALIDER par le cabinet (correspondance sur le tiers entier,
    # jamais en sous-chaîne : « FREE » ne doit pas masquer un mot courant).
    "whitelist": [
        "URSSAF", "DGFIP", "SIE", "TRESOR PUBLIC", "IMPOTS", "AGIRC-ARRCO", "MALAKOFF HUMANIS",
        "KLESIA", "AG2R LA MONDIALE", "HARMONIE MUTUELLE", "SOCIETE GENERALE", "BNP PARIBAS",
        "CREDIT AGRICOLE", "CREDIT MUTUEL", "LCL", "CAISSE D EPARGNE", "BANQUE POPULAIRE", "CIC",
        "LA BANQUE POSTALE", "QONTO", "EDF", "ENGIE", "TOTALENERGIES", "ORANGE", "SFR",
        "BOUYGUES TELECOM", "FREE", "LA POSTE", "AMAZON", "GOOGLE", "MICROSOFT", "APPLE",
        "PAYPAL", "STRIPE", "PENNYLANE", "SNCF", "AIR FRANCE", "AXA", "ALLIANZ", "MMA", "MAIF",
        "GENERALI",
    ],
}


def app_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "PseudoFEC"


def prefs_path() -> Path:
    return Path(os.environ.get("PSEUDOFEC_PREFS") or app_data_dir() / "prefs.json")


def cabinet_path() -> Path:
    env = os.environ.get("PSEUDOFEC_CONFIG")
    if env:
        return Path(env)
    exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    return exe_dir / "cabinet.json"


def _read_json(p: Path) -> dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise PseudoFecError("Fichier de configuration illisible.") from None


class Config:
    def __init__(self, cabinet: dict[str, Any], prefs: dict[str, Any],
                 cabinet_file: Path, prefs_file: Path):
        self.cabinet = cabinet
        self.prefs = prefs
        self.cabinet_file = cabinet_file
        self.prefs_file = prefs_file

    @classmethod
    def load(cls, cabinet_file: Path | None = None, prefs_file: Path | None = None) -> "Config":
        cf, pf = cabinet_file or cabinet_path(), prefs_file or prefs_path()
        cab = copy.deepcopy(DEFAULT_CABINET)
        cab.update(_read_json(cf))
        prefs = {k: v for k, v in _read_json(pf).items() if k in PREF_KEYS}
        return cls(cab, prefs, cf, pf)

    def get(self, key: str) -> Any:
        if key in PREF_KEYS and self.prefs.get(key) not in (None, ""):
            return self.prefs[key]
        return self.cabinet.get(key)

    @property
    def tables_root(self) -> Path:
        v = self.get("tables_root")
        return Path(v) if v else app_data_dir() / "tables"

    @property
    def outputs_root(self) -> Path:
        v = self.get("outputs_root")
        return Path(v) if v else Path.home() / "Documents" / "PseudoFEC" / "sorties"

    @property
    def contexts(self) -> dict[str, list[str]]:
        return self.cabinet.get("contexts") or DEFAULT_CONTEXTS

    @property
    def priority_prefixes(self) -> dict[str, list[str]]:
        return self.cabinet["priority_prefixes"]

    def all_priority_prefixes(self) -> list[str]:
        return sorted({p for lst in self.priority_prefixes.values() for p in lst})

    def set_pref(self, key: str, value: Any) -> None:
        if key not in PREF_KEYS:
            raise PseudoFecError("Préférence inconnue.")
        self.prefs[key] = value
        self.prefs_file.parent.mkdir(parents=True, exist_ok=True)
        self.prefs_file.write_text(json.dumps(self.prefs, ensure_ascii=False, indent=2), encoding="utf-8")
