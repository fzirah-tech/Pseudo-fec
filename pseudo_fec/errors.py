"""Exceptions de l'application.

Règle : un message d'erreur ne contient JAMAIS de donnée issue d'un fichier
(nom de tiers, libellé, montant). On y met uniquement des numéros de ligne,
des noms de colonnes ou des libellés génériques.
"""


class PseudoFecError(Exception):
    """Erreur applicative dont le message est sûr (aucune donnée réelle)."""


class PassphraseError(PseudoFecError):
    pass


class TableError(PseudoFecError):
    pass


class FecFormatError(PseudoFecError):
    pass


class DossierError(PseudoFecError):
    pass
