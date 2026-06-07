"""Remplacement multi-termes, plus longue correspondance d'abord, insensible
à la casse. Utilisé dans les deux sens (pseudonymisation et ré-identification).
"""

from __future__ import annotations

import re
from typing import Iterable, List, Tuple


class Replacer:
    def __init__(self, pairs: Iterable[Tuple[str, str]], min_length: int = 2):
        cleaned: List[Tuple[str, str]] = []
        seen = set()
        for find, repl in pairs:
            if not find:
                continue
            find = find.strip()
            if len(find) < min_length:
                continue
            key = find.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append((find, repl))

        # Les chaînes les plus longues d'abord : évite qu'une chaîne courte ne
        # soit substituée à l'intérieur d'une chaîne plus longue.
        cleaned.sort(key=lambda p: len(p[0]), reverse=True)
        self._lookup = {find.lower(): repl for find, repl in cleaned}
        self._pattern = (
            re.compile("|".join(re.escape(f) for f, _ in cleaned), re.IGNORECASE)
            if cleaned
            else None
        )

    def __bool__(self) -> bool:
        return self._pattern is not None

    def apply(self, text: str) -> str:
        if not self._pattern or not text:
            return text
        return self._pattern.sub(lambda m: self._lookup[m.group(0).lower()], text)

    def contains(self, text: str) -> bool:
        return bool(self._pattern and text and self._pattern.search(text))
