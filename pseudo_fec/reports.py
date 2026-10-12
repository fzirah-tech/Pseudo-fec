"""Rapport de pseudonymisation et « consigne Claude » à coller avec le FEC.

Les textes produits ici sont destinés à sortir de l'outil (consigne) ou à être archivés (rapport) :
ils ne contiennent AUCUN nom réel, uniquement des pseudonymes et des compteurs.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import __version__
from .detection import CATS
from .pseudonymize import FileResult

SENSIBLES = {"IBAN": "IBAN", "BIC": "BIC", "SIRET": "SIRET", "SIREN": "SIREN", "NIR": "n° de sécurité sociale",
             "EMAIL": "adresses e-mail", "TEL": "numéros de téléphone", "TVA": "n° de TVA intracommunautaire"}


def consigne_claude(payload: dict[str, Any], whitelist_note: bool = True) -> str:
    """Texte à coller avec le FEC pseudonymisé dans Claude (chat)."""
    prefixes = sorted({e["pseudo"].split("-")[0] for e in payload["entities"]
                       if e.get("a_pseudonymiser") and not e.get("retired") and e.get("pseudo")})
    legend = "\n".join(f"  - {p}-nnnn : {CATS[p].lower()}" for p in prefixes)
    lines = [
        "CONSIGNE POUR L'ANALYSE DU FEC PSEUDONYMISÉ",
        "",
        "Le fichier joint est un FEC dont les noms réels ont été remplacés par des pseudonymes de la forme CAT-0000.",
        "Catégories présentes :",
        legend or "  (aucune)",
        "",
        "Règles impératives :",
        "1. Reproduis les pseudonymes EXACTEMENT, au format CAT-0000 (par exemple FRN-0007), dans toutes tes restitutions :",
        "   tableaux, graphiques, légendes, noms d'onglets, titres, notes et commentaires.",
        "2. Ne les abrège jamais (pas de « FRN 7 », « FRN7 » ni « fournisseur 0007 »), ne les reformule pas, ne les traduis pas,",
        "   ne les remplace pas par une description.",
        "3. Ne cherche pas à identifier les entités réelles qu'ils désignent, ne formule aucune hypothèse à ce sujet",
        "   et ne déduis pas d'identité à partir des montants, des dates ou des libellés.",
        "4. Si une information semble permettre d'identifier une personne ou une société, signale-le sans l'exploiter.",
        "5. Les jetons [IBAN], [SIRET], [SIREN], [NIR], [EMAIL], [TEL], [TVA], [BIC] remplacent des données masquées : conserve-les tels quels.",
        "6. Les montants, dates, numéros de compte, codes journaux, numéros d'écriture et lettrages sont inchangés : analyse-les normalement.",
    ]
    if whitelist_note:
        lines.append("7. Quelques tiers génériques (organismes sociaux et fiscaux, banques, énergéticiens, opérateurs) sont volontairement "
                     "laissés en clair : ils ne sont pas pseudonymisés.")
    lines += ["", "Les restitutions seront ré-identifiées localement par le cabinet : toute altération d'un pseudonyme empêcherait cette ré-identification."]
    return "\n".join(lines) + "\n"


def report_text(code: str, results: list[tuple[str, FileResult]], payload: dict[str, Any], user: str = "") -> str:
    """Rapport archivable : pseudonymes et compteurs uniquement (aucun nom réel, aucun libellé du FEC)."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cat_of = {e["pseudo"]: e["cat"] for e in payload["entities"] if e.get("pseudo")}
    out = [f"RAPPORT DE PSEUDONYMISATION — dossier {code}", f"Pseudo-FEC {__version__} · {now}" + (f" · {user}" if user else ""), ""]
    for name, r in results:
        out += [f"Fichier produit : {name}", f"  lignes : {r.lignes} (identique à la source)",
                f"  total débit : {r.total_debit} · total crédit : {r.total_credit} (identiques à la source)",
                f"  SHA-256 entrée : {r.sha256_entree}", f"  SHA-256 sortie : {r.sha256_sortie}",
                f"  cellules modifiées par champ : " + (", ".join(f"{k} {v}" for k, v in r.champs.items()) or "aucune"),
                f"  numéros de compte remplacés : " + (", ".join(f"{k} {v}" for k, v in r.codes_remplaces.items()) or "aucun")]
        if r.sensibles:
            out.append("  motifs sensibles remplacés : " + ", ".join(f"{SENSIBLES.get(k, k)} {v}" for k, v in r.sensibles.items()))
        out.append("  remplacements par entité :")
        out += [f"    {p} ({CATS.get(cat_of.get(p, ''), '?')}) : {n}" for p, n in r.remplacements.items()]
        if r.alertes:
            out.append("  alertes :")
            out += [f"    [{a['level']}] {a['message']}" for a in r.alertes]
        out.append("")
    out += ["Ce rapport ne contient aucun nom réel. Les noms résiduels éventuels sont listés à l'écran, en local uniquement."]
    return "\n".join(out) + "\n"
