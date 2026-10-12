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
    errors, warns = [], []      # la fiche est facultative : l'outil la complète à partir des propositions

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
    if s["raison_sociale"] or "soc" in by_uid:
        upsert("soc", "SOC", s["raison_sociale"] or by_uid["soc"]["nom"], _clean_list([n for n in names if n]),
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


def set_societe(payload: dict[str, Any], societe: dict[str, Any]) -> list[str]:
    """Renseigne l'identité de la société (après import du FEC) sans toucher aux autres éléments de la fiche."""
    fiche = {**payload["fiche"], "societe": {**payload["fiche"]["societe"], **{k: v for k, v in societe.items() if v is not None}}}
    return apply_fiche(payload, fiche)


def apply_fiche(payload: dict[str, Any], raw: dict[str, Any]) -> list[str]:
    fiche = normalize_fiche(raw)
    errors, warns = validate_fiche(fiche)
    if errors:
        raise DossierError(" ".join(errors))
    payload["fiche"] = fiche
    sync_entities(payload)
    return warns


# --- validation des noms candidats (jalon b) ---

def _entity_by_uid(payload: dict[str, Any], uid: str | None) -> dict[str, Any] | None:
    return next((e for e in payload["entities"] if uid and e["uid"] == uid), None)


def apply_validation(payload: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Enregistre les décisions de l'utilisateur sur les noms candidats.

    Chaque ligne : {uid?, nom, cat, checked, variantes[], source, touched?, absorbed_uids[]?}.
    - un pseudonyme n'est attribué qu'aux entités cochées, puis conservé à vie ;
    - la catégorie ne change plus une fois le pseudonyme attribué (il en porte le préfixe) ;
    - une fusion retire l'entité absorbée du matching mais garde son pseudonyme (anciennes sorties ré-identifiables).
    """
    from .detection import CATS
    from .textmatch import NameMatcher

    warnings: list[str] = []
    created = updated = 0
    by_fold = {fold(e["nom"]): e for e in payload["entities"] if not e.get("retired")}
    for row in rows:
        nom = re.sub(r"\s+", " ", str(row.get("nom", ""))).strip()
        cat = row.get("cat")
        if not nom or cat not in CATS or cat == "SOC" and not _entity_by_uid(payload, row.get("uid")):
            continue
        checked = bool(row.get("checked"))
        e = _entity_by_uid(payload, row.get("uid")) or by_fold.get(fold(nom))
        if e is None:
            if not checked and not row.get("touched") and row.get("source") not in ("aux", "compte", "manuel"):
                continue            # proposition heuristique ignorée : on ne la mémorise pas
            e = {"uid": secrets.token_hex(4), "pseudo": None, "cat": cat, "source": row.get("source", "detection"),
                 "nom": nom, "variantes": [], "ids": [], "a_pseudonymiser": checked, "retired": False}
            payload["entities"].append(e)
            created += 1
        else:
            updated += 1
            if e["pseudo"] and cat != e["cat"]:
                warnings.append("Catégorie inchangée pour un tiers déjà pseudonymisé (le pseudonyme en porte le préfixe).")
            elif not e["pseudo"]:
                e["cat"] = cat
        e["nom"] = nom if e["source"] != "fiche" else e["nom"]
        kept = _clean_list(row.get("variantes", []))
        if e["source"] == "fiche":
            kept = _clean_list([*e.get("variantes", []), *kept])
        e["variantes"] = [v for v in kept if fold(v) != fold(e["nom"])]
        if "parties" in row:
            e["parties"] = _clean_parties(row["parties"])
        e["a_pseudonymiser"] = checked
        if checked and not e["pseudo"]:
            e["pseudo"] = _alloc(payload, e["cat"])
        by_fold[fold(e["nom"])] = e
        for old in row.get("absorbed_uids", []):
            o = _entity_by_uid(payload, old)
            if o and o is not e:
                o["retired"], o["alias_of"], o["a_pseudonymiser"] = True, e["uid"], False

    conflicts = entity_conflicts(payload)
    return {"created": created, "updated": updated, "warnings": warnings, "conflicts": conflicts,
            "a_pseudonymiser": sum(1 for e in payload["entities"] if e.get("a_pseudonymiser") and not e.get("retired")),
            "bloquant": bool(conflicts)}


def _clean_parties(parts: Any) -> list[dict[str, Any]]:
    out, seen = [], set()
    for p in parts or []:
        t = re.sub(r"\s+", " ", str(p.get("texte", ""))).strip()
        if t and fold(t) not in seen:
            seen.add(fold(t))
            out.append({"texte": t, "portee": "partout" if p.get("portee") == "partout" else "contextes",
                        "actif": bool(p.get("actif"))})
    return out


def entity_conflicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Un même texte rattaché à deux entités : la pseudonymisation serait ambiguë (bloquant).
    Contrôlé pour le texte courant ET pour chaque contexte sensible (paie, comptes courants, provisions)."""
    from .contexts import CONTEXT_LABELS
    from .pseudonymize import build_matchers
    active = [e for e in payload["entities"] if e.get("a_pseudonymiser") and not e.get("retired")]
    names = {e["uid"]: e["nom"] for e in active}
    glob, ctx = build_matchers(active)
    out = [{"texte": " ".join(t), "entites": [names[u] for u in uids], "uids": list(uids), "contexte": None}
           for t, uids in glob.conflicts.items()]
    seen = {c["texte"]: c for c in out}
    for cx, m in ctx.items():
        for t, uids in m.conflicts.items():
            key = " ".join(t)
            if key in seen and seen[key]["contexte"] is None:
                continue                                   # déjà bloquant partout
            label = CONTEXT_LABELS[cx]
            if key in seen:
                seen[key]["contexte"] += " ; " + label
            else:
                seen[key] = {"texte": key, "entites": [names[u] for u in uids], "uids": list(uids), "contexte": label}
                out.append(seen[key])
    return out


def arbitrate(payload: dict[str, Any], texte: str, uid: str | None) -> list[dict[str, Any]]:
    """Attribue un texte ambigu à UNE entité (ou à aucune : laissé en clair) et retourne les conflits restants."""
    f = fold(texte)
    for e in payload["entities"]:
        keep = uid is not None and e["uid"] == uid
        if keep:
            parts = e.setdefault("parties", [])
            hit = next((p for p in parts if fold(p["texte"]) == f), None)
            if hit:
                hit["actif"] = True
            elif not any(fold(v) == f for v in [e["nom"], *e.get("variantes", [])]):
                parts.append({"texte": texte, "portee": "contextes", "actif": True})
        else:
            e["variantes"] = [v for v in e.get("variantes", []) if fold(v) != f]
            for p in e.get("parties", []):
                if fold(p["texte"]) == f:
                    p["actif"] = False
    return entity_conflicts(payload)
