"""Parties identifiantes d'un nom.

- personne : chaque mot du nom (nom de famille, prénom) et chaque composant d'un nom hyphéné ;
- société : la partie DISTINCTIVE d'un nom long (« HOLDING DESCHAMPS SAS » -> « DESCHAMPS »), une fois
  retirés les formes juridiques et les mots génériques (holding, groupe, immobilière…).

Ce sont des PROPOSITIONS : l'utilisateur les valide (cochées = pseudonymisées aussi).
"""

from __future__ import annotations

import re
from typing import Any

from .lexicon import GENERIC_COMPANY_WORDS
from .textmatch import LEGAL_FORMS, LINK_WORDS, fold

TOKEN_RE = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*")
TITLES = {"mme", "mr", "mlle", "monsieur", "madame", "mademoiselle", "me", "dr", "m"}


def looks_like_person(nom: str) -> bool:
    toks = TOKEN_RE.findall(nom)
    return 2 <= len(toks) <= 4 and not any(fold(t) in LEGAL_FORMS or fold(t) in GENERIC_COMPANY_WORDS for t in toks) \
        and any(t.isupper() for t in toks) and any(not t.isupper() for t in toks)


def person_parts(nom: str) -> list[dict[str, Any]]:
    out, seen = [], {fold(nom)}
    for tok in TOKEN_RE.findall(nom):
        f = fold(tok)
        if f in LINK_WORDS or f in TITLES or f in LEGAL_FORMS:
            continue
        kind = "nom" if tok.isupper() and len(tok) > 1 else ("prénom" if tok[:1].isupper() else "mot")
        cands = [tok] + ([c for c in re.split(r"[-'’]", tok) if len(c) >= 3] if re.search(r"[-'’]", tok) else [])
        for c in cands:
            if len(c) >= 3 and fold(c) not in seen and fold(c) not in LINK_WORDS and fold(c) not in TITLES:
                seen.add(fold(c))
                out.append({"texte": c, "kind": kind if c is tok else f"{kind} (composant)"})
    return out


def company_parts(nom: str) -> list[dict[str, Any]]:
    matches = list(TOKEN_RE.finditer(nom))
    keep = [m for m in matches if fold(m.group()) not in LEGAL_FORMS and fold(m.group()) not in LINK_WORDS]
    distinct = [m for m in keep if fold(m.group()) not in GENERIC_COMPANY_WORDS and len(m.group()) >= 4]
    out, seen = [], {fold(nom)}
    if len(keep) >= 2 and nom[keep[0].start():keep[-1].end()] and fold(nom[keep[0].start():keep[-1].end()]) not in seen:
        seen.add(fold(nom[keep[0].start():keep[-1].end()]))
        out.append({"texte": nom[keep[0].start():keep[-1].end()], "kind": "nom sans forme juridique"})
    for m in distinct:
        if fold(m.group()) not in seen:
            seen.add(fold(m.group()))
            out.append({"texte": m.group(), "kind": "partie distinctive"})
    return out


def derived_variants(texte: str) -> list[tuple[str, str]]:
    """Formes tronquées ou mal saisies d'un mot distinctif (DURAND -> DURAN, URAND), à proposer à la validation."""
    t = texte.strip()
    if len(t) < 6 or not re.fullmatch(r"[^\W\d_]+", t):
        return []
    return [(t[:-1], f"variante de « {t} » (dernière lettre omise)"),
            (t[1:], f"variante de « {t} » (première lettre omise)")]


def is_person(nom: str, cat: str) -> bool:
    return (cat in ("SAL", "ASS") and not any(fold(t) in LEGAL_FORMS for t in TOKEN_RE.findall(nom))) \
        or (cat in ("TIE", "CLI", "FRN") and looks_like_person(nom))


def parts_for(nom: str, cat: str) -> list[dict[str, Any]]:
    is_person_ = is_person(nom, cat)
    if cat == "SOC" and not nom:
        return []
    if is_person_:
        return person_parts(nom)
    parts = company_parts(nom)
    if cat in ("GRP", "SOC"):
        seen = {fold(nom), *(fold(p["texte"]) for p in parts)}
        for p in [p for p in parts if p["kind"] == "partie distinctive"]:
            for v, kind in derived_variants(p["texte"]):
                if fold(v) not in seen:
                    seen.add(fold(v))
                    parts.append({"texte": v, "kind": kind, "derive": True})
    return parts
