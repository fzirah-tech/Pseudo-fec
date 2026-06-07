"""Vérification anti-fuite d'un FEC pseudonymisé.

Deux contrôles :
1. Aucune ``valeur_reelle`` ni ``code_aux_origine`` (alphabétique) du mapping ne
   doit subsister dans le FEC pseudonymisé — sinon fuite (code de sortie ≠ 0).
2. Scan du texte libre : signale les mots à capitale initiale hors dictionnaire,
   candidats à des noms non masqués (avis, sans effet sur le code de sortie).
"""

from __future__ import annotations

import re
from typing import List, Tuple

from .mapping import TOKEN_RE, Mapping
from .pseudonymize import read_fec

# Mots fréquents du texte comptable, à exclure du scan « noms potentiels ».
STOPWORDS = {
    "FACTURE", "FACT", "FACTURES", "AVOIR", "AVOIRS", "REGLEMENT", "REGLT",
    "VIREMENT", "VIR", "CHEQUE", "CHQ", "PRELEVEMENT", "PRLV", "TVA", "HT",
    "TTC", "TTC.", "ACHAT", "ACHATS", "VENTE", "VENTES", "SALAIRE", "SALAIRES",
    "PAIE", "BANQUE", "CAISSE", "CLIENT", "CLIENTS", "FOURNISSEUR",
    "FOURNISSEURS", "FRAIS", "NOTE", "NOTES", "REMBOURSEMENT", "ABONNEMENT",
    "LOYER", "ASSURANCE", "COTISATION", "URSSAF", "IMPOT", "IMPOTS", "TAXE",
    "TAXES", "INTERETS", "AMORTISSEMENT", "DOTATION", "REPRISE", "ECRITURE",
    "BORDEREAU", "RELEVE", "ECHEANCE", "MOIS", "TRIMESTRE", "ACOMPTE",
    "SOLDE", "REPORT", "DIVERS", "OPERATION", "OPERATIONS", "CARTE",
    "ESPECES", "TIMBRE", "PORT", "TRANSPORT", "ENERGIE", "TELEPHONE",
    "INTERNET", "MAINTENANCE", "ENTRETIEN", "FOURNITURES", "MATERIEL",
    "JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET", "AOUT",
    "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE",
}

_CAP_WORD = re.compile(
    r"\b([A-ZÀ-Ý][a-zà-ÿ'’\-]{2,}|[A-ZÀ-Ý]{4,})\b"
)


def _scan_freetext_word(value: str) -> List[str]:
    if not value:
        return []
    # Retire les pseudonymes avant l'analyse.
    cleaned = TOKEN_RE.sub(" ", value)
    found = []
    for m in _CAP_WORD.finditer(cleaned):
        word = m.group(1)
        if word.upper() in STOPWORDS:
            continue
        if word.isdigit():
            continue
        found.append(word)
    return found


def verify(fec_path: str, mapping: Mapping) -> Tuple[List[dict], List[dict]]:
    """Retourne (fuites, suspects).

    fuites  : [{"valeur", "type", "occurrences"}]
    suspects: [{"mot", "occurrences"}]
    """
    fec = read_fec(fec_path)
    raw = fec.raw_text
    raw_lower = raw.lower()

    # 1) Fuites : valeurs réelles résiduelles.
    leaks: List[dict] = []
    seen = set()
    for value, kind in mapping.real_values():
        v = (value or "").strip()
        if len(v) < 3:
            continue
        # Un code purement numérique n'est pas nominatif : on l'ignore pour
        # éviter les faux positifs avec les montants/numéros.
        if kind == "code_aux_origine" and not re.search(r"[A-Za-z]", v):
            continue
        dedup = (v.lower(), kind)
        if dedup in seen:
            continue
        seen.add(dedup)
        count = raw_lower.count(v.lower())
        if count > 0:
            leaks.append({"valeur": v, "type": kind, "occurrences": count})

    # 2) Noms potentiels non masqués dans le texte libre.
    f_ecrlib = fec.field("EcritureLib")
    f_pieceref = fec.field("PieceRef")
    counter = {}
    for row in fec.rows:
        for fld in (f_ecrlib, f_pieceref):
            if not fld:
                continue
            val = row.get(fld, "")
            if not isinstance(val, str):
                continue
            for word in _scan_freetext_word(val):
                counter[word] = counter.get(word, 0) + 1
    suspects = [
        {"mot": w, "occurrences": c}
        for w, c in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return leaks, suspects
