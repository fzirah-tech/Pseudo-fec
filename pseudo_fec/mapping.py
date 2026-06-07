"""Gestion de la clé de correspondance (mapping) pseudonyme <-> valeur réelle.

LE FICHIER DE MAPPING EST L'ÉLÉMENT SENSIBLE DE LA CHAÎNE : il contient les
valeurs réelles et permet la ré-identification. Il est écrit localement
(dossier ``_local_mapping/``) et NE DOIT JAMAIS être transmis dans le cloud.

Le mapping est persistant et incrémental : un nouveau passage sur le même
dossier réutilise les pseudonymes existants et n'en attribue de nouveaux qu'aux
entités inédites.
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

# Types de tiers gérés.
TYPES = ("CLI", "FRN", "TIE", "SAL", "REF")

# Délimiteurs de pseudonyme. ``§`` est très rare en comptabilité et visuellement
# repérable ; ``~`` est le repli ASCII (option --ascii).
DELIM_UNICODE = "§"
DELIM_ASCII = "~"

# Détecte un pseudonyme complet délimité, dans les deux variantes.
TOKEN_RE = re.compile(r"[§~](CLI|FRN|TIE|SAL|REF)(\d{4})[§~]")
# Détecte un pseudonyme « nu » concaténé dans un CompteNum (ex. 411CLI0001).
BARE_COMPTE_RE = re.compile(r"^\d{2,5}(CLI|FRN|TIE|SAL)\d{4}$")


class CollisionError(Exception):
    """Levée si un pseudonyme à attribuer apparaît déjà dans le contenu source."""


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


def make_token(type_: str, num: int, ascii_mode: bool = False) -> str:
    delim = DELIM_ASCII if ascii_mode else DELIM_UNICODE
    return f"{delim}{type_}{num:04d}{delim}"


def bare_pseudo(token: str) -> str:
    """Retourne la forme nue (sans délimiteur) d'un token, ex. §CLI0001§ -> CLI0001."""
    m = TOKEN_RE.search(token)
    return f"{m.group(1)}{m.group(2)}" if m else token.strip("§~")


def is_pseudo_value(value: str) -> bool:
    """Vrai si la valeur est déjà un pseudonyme (token délimité ou compte nu)."""
    v = (value or "").strip()
    if not v:
        return False
    return bool(TOKEN_RE.fullmatch(v)) or bool(BARE_COMPTE_RE.fullmatch(v))


class MappingEntry:
    def __init__(
        self,
        pseudo: str,
        type_: str,
        valeur_reelle: str,
        champ_source: str,
        code_aux_origine: str,
        occurrences: int = 0,
        date_creation: str = "",
    ):
        self.pseudo = pseudo  # token délimité complet, ex. "§CLI0001§"
        self.type = type_
        self.valeur_reelle = valeur_reelle
        self.champ_source = champ_source
        self.code_aux_origine = code_aux_origine
        self.occurrences = occurrences
        self.date_creation = date_creation or date.today().isoformat()

    @property
    def num(self) -> int:
        m = TOKEN_RE.search(self.pseudo)
        return int(m.group(2)) if m else 0

    @property
    def bare(self) -> str:
        return bare_pseudo(self.pseudo)

    def to_row(self) -> dict:
        return {
            "pseudo": self.pseudo,
            "type": self.type,
            "valeur_reelle": self.valeur_reelle,
            "champ_source": self.champ_source,
            "code_aux_origine": self.code_aux_origine,
            "occurrences": str(self.occurrences),
            "date_creation": self.date_creation,
        }


# Colonnes du fichier de mapping (ordre fixe).
MAPPING_COLUMNS = [
    "pseudo",
    "type",
    "valeur_reelle",
    "champ_source",
    "code_aux_origine",
    "occurrences",
    "date_creation",
]


def _key_for_entry(entry: MappingEntry) -> Tuple[str, str]:
    """Reconstruit la clé d'identité d'une entrée chargée depuis le mapping."""
    if entry.type == "REF":
        return ("ref", normalize(entry.valeur_reelle))
    if entry.champ_source == "CompteLib":
        return ("cpt", entry.code_aux_origine.upper())
    return ("aux", entry.code_aux_origine.upper() or normalize(entry.valeur_reelle))


class Mapping:
    """Conteneur des correspondances, indexé par clé d'identité."""

    def __init__(self, ascii_mode: bool = False):
        self.ascii_mode = ascii_mode
        self.entries: Dict[Tuple[str, str], MappingEntry] = {}
        self.counters: Dict[str, int] = {t: 0 for t in TYPES}
        self.meta: dict = {}

    # ------------------------------------------------------------------ #
    # Chargement / sauvegarde
    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, csv_path: str) -> "Mapping":
        m = cls()
        if not csv_path or not os.path.exists(csv_path):
            return m
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                entry = MappingEntry(
                    pseudo=row.get("pseudo", ""),
                    type_=row.get("type", ""),
                    valeur_reelle=row.get("valeur_reelle", ""),
                    champ_source=row.get("champ_source", ""),
                    code_aux_origine=row.get("code_aux_origine", ""),
                    occurrences=int(row.get("occurrences") or 0),
                    date_creation=row.get("date_creation", ""),
                )
                key = _key_for_entry(entry)
                m.entries[key] = entry
                m.counters[entry.type] = max(m.counters.get(entry.type, 0), entry.num)
                if DELIM_ASCII in entry.pseudo:
                    m.ascii_mode = True
        return m

    def save(self, csv_path: str, json_path: Optional[str] = None) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(csv_path)) or ".", exist_ok=True)
        entries = self.sorted_entries()
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=MAPPING_COLUMNS)
            writer.writeheader()
            for e in entries:
                writer.writerow(e.to_row())

        if json_path is None:
            json_path = os.path.splitext(csv_path)[0] + ".json"
        data = {
            "version": 1,
            "ascii_mode": self.ascii_mode,
            "meta": self.meta,
            "entries": [e.to_row() for e in entries],
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def sorted_entries(self) -> List[MappingEntry]:
        order = {t: i for i, t in enumerate(TYPES)}
        return sorted(
            self.entries.values(),
            key=lambda e: (order.get(e.type, 99), e.num),
        )

    # ------------------------------------------------------------------ #
    # Attribution des pseudonymes
    # ------------------------------------------------------------------ #
    def get_or_create(
        self,
        key: Tuple[str, str],
        type_: str,
        valeur_reelle: str,
        champ_source: str,
        code_aux_origine: str,
        source_content: str = "",
    ) -> MappingEntry:
        if key in self.entries:
            entry = self.entries[key]
            # Complète un libellé réel manquant si on en trouve un meilleur.
            if not entry.valeur_reelle and valeur_reelle:
                entry.valeur_reelle = valeur_reelle
            return entry

        self.counters[type_] = self.counters.get(type_, 0) + 1
        num = self.counters[type_]
        token = make_token(type_, num, self.ascii_mode)

        # Garantie anti-collision : le pseudonyme ne doit pas déjà figurer dans
        # le contenu source.
        if source_content and token in source_content:
            raise CollisionError(
                f"Le pseudonyme {token} est déjà présent dans le fichier source. "
                f"Utilisez --ascii ou modifiez la source."
            )

        entry = MappingEntry(
            pseudo=token,
            type_=type_,
            valeur_reelle=valeur_reelle,
            champ_source=champ_source,
            code_aux_origine=code_aux_origine,
            occurrences=0,
        )
        self.entries[key] = entry
        return entry

    # ------------------------------------------------------------------ #
    # Aides pour la pseudonymisation et la ré-identification
    # ------------------------------------------------------------------ #
    def forward_pairs(self) -> List[Tuple[str, str]]:
        """Paires (valeur_réelle, token) pour le remplacement en texte libre.

        On inclut le libellé réel ET le code auxiliaire d'origine s'il est
        alphabétique (un code purement numérique n'est pas remplacé en texte
        libre pour éviter les faux positifs).
        """
        pairs: List[Tuple[str, str]] = []
        for e in self.entries.values():
            if e.type == "REF":
                continue
            if e.valeur_reelle:
                pairs.append((e.valeur_reelle, e.pseudo))
            code = e.code_aux_origine
            if code and re.search(r"[A-Za-z]", code) and len(code) >= 4:
                pairs.append((code, e.pseudo))
        return pairs

    def reverse_pairs(self) -> List[Tuple[str, str]]:
        """Paires (token, valeur_réelle) pour la ré-identification."""
        pairs: List[Tuple[str, str]] = []
        for e in self.entries.values():
            if e.pseudo and e.valeur_reelle:
                pairs.append((e.pseudo, e.valeur_reelle))
        return pairs

    def real_values(self) -> List[Tuple[str, str]]:
        """(valeur, type_de_valeur) à contrôler par la vérification anti-fuite."""
        out: List[Tuple[str, str]] = []
        for e in self.entries.values():
            if e.valeur_reelle:
                out.append((e.valeur_reelle, "valeur_reelle"))
            if e.code_aux_origine:
                out.append((e.code_aux_origine, "code_aux_origine"))
        return out
