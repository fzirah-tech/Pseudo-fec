"""Normalisation et recherche de noms dans du texte.

``fold_text`` conserve la LONGUEUR de la chaîne (un caractère -> un caractère) :
les positions trouvées dans le texte normalisé sont donc valables dans le texte
d'origine, ce qui permet de remplacer sans altérer le reste du libellé.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any, Iterable

_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"[^\W_]+")
_LIGATURES = (("œ", "oe"), ("æ", "ae"), ("ß", "ss"))

LEGAL_FORMS = {"sarl", "sas", "sasu", "eurl", "sa", "snc", "sci", "scp", "scm", "selarl", "selas", "sccv",
               "ei", "eirl", "ets", "etablissements", "etablissement", "ste", "societe", "cie", "compagnie",
               "gie", "association", "asso", "mr", "mme", "mlle", "m", "monsieur", "madame", "mademoiselle",
               "me", "dr", "sci", "groupe"}
LINK_WORDS = {"et", "de", "du", "des", "la", "le", "les", "d", "l", "sur", "en", "au", "aux"}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def fold(s: str) -> str:
    """Forme de comparaison : sans accents, minuscules, espaces regroupés."""
    return _WS.sub(" ", strip_accents(s).casefold()).strip()


def fold_key(s: str) -> str:
    """Forme très compacte (lettres et chiffres seulement) pour les en-têtes."""
    return re.sub(r"[^a-z0-9]", "", strip_accents(s).casefold())


@lru_cache(maxsize=None)
def _fold_char(c: str) -> str:
    base = unicodedata.normalize("NFD", c)[0]
    low = base.lower()
    if len(low) != 1:
        low = c.lower()[:1] or c
    return " " if low.isspace() else low


def fold_text(s: str) -> str:
    """Normalise sans changer la longueur (positions conservées)."""
    return "".join(map(_fold_char, s))


def tokens(s: str) -> list[str]:
    return _TOKEN.findall(fold_text(s))


def name_key(s: str) -> str:
    """Clé de regroupement : sans forme juridique ni mots de liaison, tokens triés."""
    toks = [t for t in tokens(s) if t not in LEGAL_FORMS and t not in LINK_WORDS]
    return " ".join(sorted(toks))


class NameMatcher:
    """Recherche de variantes de noms : insensible à la casse et aux accents,
    limites de mots respectées (MARTIN ne touche pas MARTINEZ), variantes les
    plus longues prioritaires, tolérante aux espaces multiples et aux séparateurs.
    """

    SEP = r"[\W_]{0,6}"   # espaces multiples, tirets, points, apostrophes

    def __init__(self, items: Iterable[tuple[str, Any]]):
        by_tokens: dict[tuple[str, ...], list[Any]] = {}
        expanded: list[tuple[str, Any]] = []
        for text, key in items:
            expanded.append((text, key))
            t2 = fold_text(text)
            for lig, rep in _LIGATURES:       # « ŒUVRES » doit aussi retrouver « OEUVRES »
                if lig in t2:
                    t2 = t2.replace(lig, rep)
                    expanded.append((t2, key))
        for text, key in expanded:
            toks = tuple(tokens(text))
            if not toks or not any(len(t) > 1 or t.isdigit() for t in toks):
                continue
            keys = by_tokens.setdefault(toks, [])
            if key not in keys:
                keys.append(key)
        self.conflicts: dict[tuple[str, ...], list[Any]] = {t: k for t, k in by_tokens.items() if len(k) > 1}
        ordered = sorted(by_tokens, key=lambda t: (-sum(len(x) for x in t), t))
        self._variants = ordered
        self._keys = [by_tokens[t][0] for t in ordered]
        if ordered:
            parts = ["(" + self.SEP.join(re.escape(x) for x in t) + ")" for t in ordered]
            self._rx = re.compile(r"(?<![^\W_])(?:" + "|".join(parts) + r")(?![^\W_])")
        else:
            self._rx = None

    def __len__(self) -> int:
        return len(self._variants)

    def find(self, text: str) -> list[tuple[int, int, Any]]:
        """Occurrences non chevauchantes : (début, fin, clé), positions du texte d'origine."""
        if self._rx is None:
            return []
        folded = fold_text(text)
        return [(m.start(), m.end(), self._keys[m.lastindex - 1]) for m in self._rx.finditer(folded)]

    def replace(self, text: str, mapper) -> tuple[str, int]:
        hits = self.find(text)
        if not hits:
            return text, 0
        out, last = [], 0
        for a, b, key in hits:
            out.append(text[last:a])
            out.append(mapper(key, text[a:b]))
            last = b
        out.append(text[last:])
        return "".join(out), len(hits)
