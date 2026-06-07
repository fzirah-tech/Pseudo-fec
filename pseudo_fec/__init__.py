"""pseudo-fec — Pseudonymisation et ré-identification LOCALE de fichiers FEC.

Outil 100 % local et hors-ligne : aucune communication réseau. Permet de
pseudonymiser les identités d'un Fichier des Écritures Comptables (FEC) avant
analyse dans un environnement cloud, puis de ré-identifier localement les
livrables (Word/Excel/texte) à l'aide de la clé de correspondance.
"""

from .mapping import Mapping
from .pseudonymize import FecData, Pseudonymizer, read_fec, write_fec, FEC_FIELDS
from .reidentify import reidentify_file
from .verify import verify

__all__ = [
    "Mapping",
    "FecData",
    "Pseudonymizer",
    "read_fec",
    "write_fec",
    "FEC_FIELDS",
    "reidentify_file",
    "verify",
]

__version__ = "0.1.0"
