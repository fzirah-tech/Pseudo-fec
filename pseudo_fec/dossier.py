"""Fiche dossier : société, dirigeants/associés, sociétés liées.

Les noms réels n'existent que dans la table chiffrée (jamais dans le chemin,
les journaux ou les sorties). Pseudonymes réservés :
    SOC-0001 : l'entité ; GRP-nnnn : sociétés liées ; ASS-nnnn : dirigeants et associés.
Un pseudonyme attribué n'est jamais réutilisé ni supprimé.
"""

from __future__ import annotations

import datetime as dt
import re
import secrets
from typing import Any

from .errors import DossierError
from .textmatch import fold

LIENS = {"mere": "Société mère", "filiale": "Filiale", "soeur": "Société sœur",
         "sci": "SCI / société patrimoniale de l'associé", "autre": "Autre société liée"}
ROLES = {"dirigeant": "Dirigeant", "associe": "Associé"}


def new_payload(code: str) -> dict[str, Any]:
    return {
        "schema": 1, "code": code,
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "fiche": {"societe": {"raison_sociale": "", "nom_commercial": "", "sigle": "",
                              "variantes": [], "siren": "", "sirets": []},
                  "personnes": [], "liees": []},
        "entities": [], "counters": {}, "whitelist_additions": [], "fec": [],
    }


def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def luhn_ok(num: str) -> bool:
    if not num.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _clean_list(values: Any) -> list[str]:
    if isinstance(values, str):
        values = values.splitlines()
    seen, out = set(), []
    for v in values or []:
        v = re.sub(r"\s+", " ", str(v)).strip()
        if v and fold(v) not in seen:
            seen.add(fold(v))
            out.append(v)
    return out


def normalize_fiche(raw: dict[str, Any]) -> dict[str, Any]:
    """Nettoie la saisie ; donne un identifiant stable (uid) aux nouvelles personnes/sociétés."""
    s = raw.get("societe", {})
    societe = {
        "raison_sociale": re.sub(r"\s+", " ", s.get("raison_sociale", "")).strip(),
        "nom_commercial": re.sub(r"\s+", " ", s.get("nom_commercial", "")).strip(),
        "sigle": re.sub(r"\s+", " ", s.get("sigle", "")).strip(),
        "variantes": _clean_list(s.get("variantes")),
        "siren": digits(s.get("siren", "")),
        "sirets": [digits(x) for x in _clean_list(s.get("sirets")) if digits(x)],
    }
    personnes = []
    for p in raw.get("personnes", []):
        nom = re.sub(r"\s+", " ", p.get("nom", "")).strip()
        if nom:
            personnes.append({"uid": p.get("uid") or secrets.token_hex(4), "nom": nom,
                              "role": p.get("role") if p.get("role") in ROLES else "associe",
                              "variantes": _clean_list(p.get("variantes"))})
    liees = []
    for c in raw.get("liees", []):
        rs = re.sub(r"\s+", " ", c.get("raison_sociale", "")).strip()
        if rs:
            liees.append({"uid": c.get("uid") or secrets.token_hex(4), "raison_sociale": rs,
                          "lien": c.get("lien") if c.get("lien") in LIENS else "autre",
                          "variantes": _clean_list(c.get("variantes")),
                          "siren": digits(c.get("siren", "")),
                          "sirets": [digits(x) for x in _clean_list(c.get("sirets")) if digits(x)]})
    return {"societe": societe, "personnes": personnes, "liees": liees}


def validate_fiche(f: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Retourne (erreurs bloquantes, avertissements)."""
    errors, warns = [], []
    if not f["societe"]["raison_sociale"]:
        errors.append("La raison sociale de la société est obligatoire.")

    def chk(label: str, siren: str, sirets: list[str]) -> None:
        if siren and (len(siren) != 9 or not luhn_ok(siren)):
            warns.append(f"{label} : SIREN invalide (9 chiffres, clé de Luhn).")
        for s in sirets:
            if len(s) != 14 or not luhn_ok(s):
                warns.append(f"{label} : SIRET invalide (14 chiffres, clé de Luhn).")
            elif siren and not s.startswith(siren):
                warns.append(f"{label} : un SIRET ne commence pas par le SIREN.")

    chk("Société", f["societe"]["siren"], f["societe"]["sirets"])
    for i, c in enumerate(f["liees"], 1):
        chk(f"Société liée n°{i}", c["siren"], c["sirets"])
    return errors, warns


# --- entités et pseudonymes ---

def _alloc(payload: dict[str, Any], cat: str) -> str:
    n = payload["counters"].get(cat, 0) + 1
    payload["counters"][cat] = n
    return f"{cat}-{n:04d}"


def sync_entities(payload: dict[str, Any]) -> None:
    """Aligne les entités de la table sur la fiche. Enrichit, ne supprime jamais."""
    fiche = payload["fiche"]
    by_uid = {e["uid"]: e for e in payload["entities"]}

    def upsert(uid: str, cat: str, nom: str, variantes: list[str], ids: list[str], extra=None) -> None:
        e = by_uid.get(uid)
        if e is None:
            e = {"uid": uid, "pseudo": _alloc(payload, cat), "cat": cat, "source": "fiche",
                 "a_pseudonymiser": True}
            payload["entities"].append(e)
            by_uid[uid] = e
        e.update({"nom": nom, "variantes": variantes, "ids": ids, "retired": False, **(extra or {})})

    s = fiche["societe"]
    names = [s["nom_commercial"], s["sigle"], *s["variantes"]]
    upsert("soc", "SOC", s["raison_sociale"], _clean_list([n for n in names if n]),
           [x for x in [s["siren"], *s["sirets"]] if x])
    for c in fiche["liees"]:
        upsert(c["uid"], "GRP", c["raison_sociale"], c["variantes"],
               [x for x in [c["siren"], *c["sirets"]] if x], {"lien": c["lien"]})
    for p in fiche["personnes"]:
        upsert(p["uid"], "ASS", p["nom"], p["variantes"], [], {"role": p["role"]})
    current = {"soc"} | {c["uid"] for c in fiche["liees"]} | {p["uid"] for p in fiche["personnes"]}
    for e in payload["entities"]:
        if e["source"] == "fiche" and e["uid"] not in current:
            e["retired"] = True  # conservé : les anciennes sorties restent ré-identifiables


def apply_fiche(payload: dict[str, Any], raw: dict[str, Any]) -> list[str]:
    fiche = normalize_fiche(raw)
    errors, warns = validate_fiche(fiche)
    if errors:
        raise DossierError(" ".join(errors))
    payload["fiche"] = fiche
    sync_entities(payload)
    return warns
