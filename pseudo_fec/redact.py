"""Motifs sensibles : IBAN, BIC, SIREN/SIRET, n° de sécurité sociale, e-mail, téléphone, TVA intracommunautaire.

Détectés et signalés séparément ; ils sont remplacés par des jetons neutres non réversibles
([IBAN], [SIRET]…), sauf le SIREN de l'entité (remplacé par SOC-0001).
Chaque motif est validé (somme de contrôle) pour limiter les faux positifs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .dossier import luhn_ok

TOKENS = {"IBAN": "[IBAN]", "BIC": "[BIC]", "SIRET": "[SIRET]", "SIREN": "[SIREN]", "NIR": "[NIR]",
          "EMAIL": "[EMAIL]", "TEL": "[TEL]", "TVA": "[TVA]"}

_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?:[ ]?[A-Za-z0-9]{4}){2,7}(?:[ ]?[A-Za-z0-9]{1,4})?(?![A-Za-z0-9])")
_BIC = re.compile(r"(?i)\bBIC\b[\s:=-]*([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b")
_SIRET = re.compile(r"(?<!\d)(\d{3}[ .]?\d{3}[ .]?\d{3}[ .]?\d{5})(?!\d)")
_SIREN = re.compile(r"(?<!\d)(\d{3}[ .]?\d{3}[ .]?\d{3})(?!\d)")
_NIR = re.compile(r"(?<!\d)([12][ ]?\d{2}[ ]?(?:0[1-9]|1[0-2]|[2-9]\d)[ ]?(?:\d{2}|2[AB])[ ]?\d{3}[ ]?\d{3}[ ]?\d{2})(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TEL = re.compile(r"(?<![\d])(?:\+33[ .]?|0033[ .]?|0)[1-9](?:[ .-]?\d{2}){4}(?![\d])")
_CTX = re.compile(r"(?i)siren|siret|n°\s*ent")
_TVA = re.compile(r"(?<![A-Za-z0-9])FR[ ]?[0-9A-Z]{2}[ ]?\d{3}[ .]?\d{3}[ .]?\d{3}(?![A-Za-z0-9])")


@dataclass(frozen=True)
class Hit:
    kind: str
    start: int
    end: int


def iban_ok(s: str) -> bool:
    s = re.sub(r"\s", "", s).upper()
    if not (15 <= len(s) <= 34):
        return False
    n = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(n) % 97 == 1


def nir_ok(s: str) -> bool:
    s = re.sub(r"\s", "", s).upper().replace("2A", "19").replace("2B", "18")
    if len(s) != 15 or not s.isdigit():
        return False
    return 97 - int(s[:13]) % 97 == int(s[13:])


def scan(text: str, entity_sirens: frozenset[str] = frozenset()) -> list[Hit]:
    """Motifs sensibles validés, sans chevauchement (le plus spécifique l'emporte)."""
    hits: list[Hit] = []

    def add(kind: str, m: re.Match, grp: int = 0) -> None:
        hits.append(Hit(kind, m.start(grp), m.end(grp)))

    for m in _IBAN.finditer(text):
        if iban_ok(m.group()):
            add("IBAN", m)
    for m in _BIC.finditer(text):
        add("BIC", m, 1)
    for m in _EMAIL.finditer(text):
        add("EMAIL", m)
    for m in _TVA.finditer(text):
        add("TVA", m)
    for m in _NIR.finditer(text):
        if nir_ok(m.group(1)):
            add("NIR", m, 1)
    for m in _SIRET.finditer(text):
        d = re.sub(r"\D", "", m.group(1))
        if d[:9] in entity_sirens or (luhn_ok(d) and _CTX.search(text[max(0, m.start(1) - 24):m.start(1)])):
            add("SIRET", m, 1)
    for m in _SIREN.finditer(text):
        d = re.sub(r"\D", "", m.group(1))
        # 1 nombre à 9 chiffres sur 10 vérifie la clé de Luhn par hasard : exiger le SIREN d'une entité connue ou le mot SIREN
        if d in entity_sirens or (luhn_ok(d) and _CTX.search(text[max(0, m.start(1) - 24):m.start(1)])):
            add("SIREN", m, 1)
    for m in _TEL.finditer(text):
        add("TEL", m)
    hits.sort(key=lambda h: (h.start, -(h.end - h.start)))
    out: list[Hit] = []
    for h in hits:
        if out and h.start < out[-1].end:
            continue
        out.append(h)
    return out


def mask_example(text: str, hit: Hit) -> str:
    """Exemple affichable : la valeur est masquée, le contexte conservé."""
    v = text[hit.start:hit.end]
    keep = v[-2:] if len(v) > 6 else ""
    return (text[max(0, hit.start - 12):hit.start] + "•" * max(len(v) - len(keep), 3) + keep
            + text[hit.end:hit.end + 12]).strip()
