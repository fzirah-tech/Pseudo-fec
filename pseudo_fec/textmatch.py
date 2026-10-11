"""Normalisation de texte (sans accents, sans casse, espaces regroupés)."""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def fold(s: str) -> str:
    """Forme de comparaison : sans accents, minuscules, espaces regroupés."""
    return _WS.sub(" ", strip_accents(s).casefold()).strip()


def fold_key(s: str) -> str:
    """Forme très compacte (lettres et chiffres seulement) pour les en-têtes."""
    return re.sub(r"[^a-z0-9]", "", strip_accents(s).casefold())
