"""Contextes sensibles d'une écriture : paie, comptes courants / groupe, provisions.

Les libellés de ces écritures citent souvent un nom de façon partielle (nom de famille seul, prénom seul,
partie distinctive d'une société) : dans ce contexte, une telle mention est attribuable à la personne ou à la
société concernée. Le contexte est déterminé au niveau de l'ÉCRITURE (journal + numéro) : si l'une de ses lignes
porte un compte de paie, toutes les lignes de l'écriture (banque comprise) sont en contexte de paie.
"""

from __future__ import annotations

from typing import Iterable

CONTEXT_LABELS = {
    "paie": "Libellés de paie et charges de personnel",
    "compte_courant": "Comptes courants d'associés et groupe",
    "provisions": "Provisions et dépréciations",
    "autres": "Autres libellés (banque, achats, ventes…)",
}
# priorité quand une écriture relève de plusieurs contextes
PRIORITY = ("paie", "compte_courant", "provisions")

DEFAULT_CONTEXTS: dict[str, list[str]] = {
    "paie": ["421", "422", "424", "425", "427", "428", "431", "437", "641", "645", "647", "648"],
    "compte_courant": ["451", "455", "456", "457", "458", "168", "26", "274", "275", "467"],
    "provisions": ["15", "29", "39", "49", "681", "686", "687", "781", "786", "787"],
}


def contexts_for_accounts(accounts: Iterable[str], contexts: dict[str, list[str]] | None = None) -> frozenset[str]:
    ctx = contexts or DEFAULT_CONTEXTS
    found = set()
    for acc in accounts:
        a = acc.strip()
        for cid, prefixes in ctx.items():
            if any(a.startswith(p) for p in prefixes):
                found.add(cid)
    return frozenset(found) if found else frozenset({"autres"})


def main_context(ctxs: Iterable[str]) -> str | None:
    """Contexte déterminant (paie > compte courant > provisions) ou None si l'écriture est « ordinaire »."""
    s = set(ctxs)
    return next((c for c in PRIORITY if c in s), None)
