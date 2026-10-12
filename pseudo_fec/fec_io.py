"""Lecture, contrôle et réécriture fidèle d'un FEC (art. A47 A-1 du LPF).

Principes :
- tolérance aux variantes réelles (en-têtes avec espaces, dates mixtes,
  montants « 1 234,56 », « - » pour zéro, encodages 8 bits, CRLF/LF) ;
- réécriture à l'identique : même séparateur, encodage, fins de ligne ;
- aucune donnée du fichier dans les messages d'erreur.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

from .errors import FecFormatError
from .textmatch import fold_key

CANON = ("JournalCode", "JournalLib", "EcritureNum", "EcritureDate", "CompteNum", "CompteLib",
         "CompAuxNum", "CompAuxLib", "PieceRef", "PieceDate", "EcritureLib", "Debit", "Credit",
         "EcritureLet", "DateLet", "ValidDate", "Montantdevise", "Idevise")
ESSENTIAL = ("EcritureDate", "CompteNum", "CompteLib", "CompAuxNum", "CompAuxLib", "PieceRef",
             "EcritureLib", "Debit", "Credit", "JournalCode", "EcritureNum")
DATE_COLS = ("EcritureDate", "PieceDate", "DateLet", "ValidDate")

_KEYS = {fold_key(c): c for c in CANON}
_ALIASES = {"devise": "Idevise", "montantdevises": "Montantdevise", "datelettrage": "DateLet",
            "lettrage": "EcritureLet", "compteauxnum": "CompAuxNum", "compteauxlib": "CompAuxLib",
            "datevalidation": "ValidDate", "datevalid": "ValidDate"}
_FILENAME_RE = re.compile(r"(?<!\d)(\d{9})FEC(\d{8})(?!\d)", re.I)
_AMOUNT_RE = re.compile(r"^-?\d+(\.\d+)?$")


# ---------------------------------------------------------------- encodage / format

def detect_encoding(data: bytes) -> tuple[str, bool]:
    """Retourne (codec Python, BOM présent). La ré-encodage à l'identique est vérifié par l'appelant."""
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8", True
    try:
        data.decode("utf-8")
        return "utf-8", False
    except UnicodeDecodeError:
        pass
    high = {b for b in data if b >= 0x80}
    if high & set(range(0x80, 0xA0)):
        return "cp1252", False
    if high & {0xA4, 0xA6, 0xA8, 0xB4, 0xB8, 0xBC, 0xBD, 0xBE}:
        return "iso-8859-15", False
    return "cp1252", False


def parse_amount(s: str) -> Decimal | None:
    """Montant -> Decimal ; '' et '-' valent 0 ; None si illisible."""
    s = s.strip().replace(" ", "").replace(" ", "").replace(" ", "")
    if s in ("", "-"):
        return Decimal(0)
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        s = s.replace(thou, "").replace(dec, ".")
    else:
        s = s.replace(",", ".")
    if not _AMOUNT_RE.match(s):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def date_kind(s: str) -> str | None:
    """Reconnaît le format d'une date ; None si vide ou non reconnu."""
    n = len(s)
    if n == 8 and s.isdigit():
        if s[:2] in ("19", "20"):
            return "AAAAMMJJ"
        if s[4:6] in ("19", "20"):
            return "JJMMAAAA"
        return None
    if n == 10:
        digits = s[:2] + s[3:5] + s[6:]
        if s[2] == s[5] == "/" and digits.isdigit():
            return "JJ/MM/AAAA"
        if s[2] == s[5] == "-" and digits.isdigit():
            return "JJ-MM-AAAA"
        if s[2] == s[5] == "." and digits.isdigit():
            return "JJ.MM.AAAA"
        if s[4] == s[7] == "-" and (s[:4] + s[5:7] + s[8:]).isdigit():
            return "AAAA-MM-JJ"
    return None


def date_parts(s: str, kind: str) -> tuple[int, int, int] | None:
    try:
        if kind == "AAAAMMJJ":
            y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
        elif kind == "JJMMAAAA":
            d, m, y = int(s[:2]), int(s[2:4]), int(s[4:8])
        elif kind == "AAAA-MM-JJ":
            y, m, d = int(s[:4]), int(s[5:7]), int(s[8:10])
        else:  # JJ/MM/AAAA, JJ-MM-AAAA, JJ.MM.AAAA
            d, m, y = int(s[:2]), int(s[3:5]), int(s[6:10])
    except ValueError:
        return None
    if 1 <= m <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100:
        return y, m, d
    return None


@dataclass
class FecFormat:
    encoding: str
    bom: bool
    sep: str
    newline: str
    final_newline: bool
    header_raw: list[str]
    columns: dict[str, int]
    extras: list[str] = field(default_factory=list)


@dataclass
class Issue:
    level: str  # "erreur" | "avertissement" | "info"
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"level": self.level, "code": self.code, "message": self.message}


class FecFile:
    """FEC décodé en mémoire. Les lignes sont découpées à la demande."""

    def __init__(self, filename: str, sha256: str, size: int, fmt: FecFormat,
                 lines: list[str], issues: list[Issue], blank_lines: int):
        self.filename, self.sha256, self.size, self.fmt = filename, sha256, size, fmt
        self._lines = lines  # sans l'en-tête
        self.issues = issues
        self.blank_lines = blank_lines

    @property
    def n_columns(self) -> int:
        return len(self.fmt.header_raw)

    def __len__(self) -> int:
        return len(self._lines)

    def rows(self) -> Iterator[list[str]]:
        sep = self.fmt.sep
        for line in self._lines:
            yield line.split(sep)

    def serialize(self, rows: Iterator[list[str]]) -> bytes:
        f = self.fmt
        parts = [f.sep.join(f.header_raw)]
        parts.extend(f.sep.join(r) for r in rows)
        text = f.newline.join(parts) + (f.newline if f.final_newline else "")
        out = text.encode(f.encoding)
        return (b"\xef\xbb\xbf" + out) if f.bom else out


def parse_fec(data: bytes, filename: str = "") -> FecFile:
    if not data.strip():
        raise FecFormatError("Fichier vide.")
    enc, bom = detect_encoding(data)
    try:
        text = data.decode("utf-8-sig" if bom else enc)
    except UnicodeDecodeError:
        enc = "latin-1"
        text = data.decode(enc)
    issues: list[Issue] = []

    crlf, lf, cr = text.count("\r\n"), text.count("\n") - text.count("\r\n"), text.count("\r") - text.count("\r\n")
    counts = {"\r\n": crlf, "\n": lf, "\r": cr}
    newline = max(counts, key=lambda k: counts[k])
    if sum(1 for v in counts.values() if v) > 1:
        issues.append(Issue("avertissement", "EOL_MIXTE",
                            "Fins de ligne mixtes : elles seront uniformisées en sortie."))
    parts = text.split(newline)
    final_newline = parts[-1] == ""
    if final_newline:
        parts.pop()
    header_line, body = parts[0], parts[1:]

    seps = {"\t": header_line.count("\t"), "|": header_line.count("|"), ";": header_line.count(";")}
    sep = max(seps, key=lambda k: seps[k])
    if seps[sep] < 5:
        raise FecFormatError("Séparateur non reconnu (tabulation ou barre verticale attendue).")
    if sep == ";":
        issues.append(Issue("avertissement", "SEP_PV", "Séparateur point-virgule : hors norme (tabulation ou |)."))

    header_raw = header_line.split(sep)
    columns: dict[str, int] = {}
    extras: list[str] = []
    variants = 0
    for i, h in enumerate(header_raw):
        key = fold_key(h)
        canon = _KEYS.get(key) or _ALIASES.get(key)
        if canon and canon not in columns:
            columns[canon] = i
            if h != canon:
                variants += 1
        else:
            extras.append(f"colonne {i + 1}")
    missing = [c for c in CANON if c not in columns]
    if variants:
        issues.append(Issue("info", "ENTETES_VARIANTES",
                            f"{variants} en-tête(s) écrit(s) différemment de la norme (espaces, casse) : tolérés."))
    for c in missing:
        lvl = "erreur" if c in ESSENTIAL else "avertissement"
        issues.append(Issue(lvl, "COLONNE_ABSENTE", f"Colonne normée absente : {c}."))
    if extras:
        issues.append(Issue("avertissement", "COLONNES_EN_PLUS",
                            f"{len(extras)} colonne(s) non normée(s) ou en doublon, conservée(s) telle(s) quelle(s)."))
    if any(i.level == "erreur" for i in issues):
        raise FecFormatError("; ".join(i.message for i in issues if i.level == "erreur"))

    blank = sum(1 for ln in body if not ln.strip())
    if blank:
        body = [ln for ln in body if ln.strip()]
        issues.append(Issue("avertissement", "LIGNES_VIDES", f"{blank} ligne(s) vide(s) ignorée(s) (non reproduites en sortie)."))

    fmt = FecFormat(enc, bom, sep, newline, final_newline, header_raw, columns, extras)
    f = FecFile(filename, hashlib.sha256(data).hexdigest(), len(data), fmt, body, issues, blank)
    # Garantie de réécriture fidèle : le décodage doit pouvoir être ré-encodé à l'identique.
    if not blank and len(set(k for k, v in counts.items() if v)) <= 1:
        if f.serialize(f.rows()) != data:
            raise FecFormatError("Réécriture à l'identique impossible avec cet encodage.")
    return f


# ---------------------------------------------------------------- contrôles

def filename_info(filename: str) -> tuple[str | None, str | None]:
    m = _FILENAME_RE.search(filename or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def analyse(fec: FecFile, class_prefixes: dict[str, list[str]],
            fiche_siren: str = "") -> dict[str, Any]:
    """Contrôles d'intégrité (un seul passage). Le résultat ne contient aucun nom de tiers."""
    cols = fec.fmt.columns
    ix = {c: cols.get(c) for c in CANON}
    ncol = fec.n_columns
    iD, iC, iN, iCpt, iAux, iAuxL, iCptL, iJ, iE = (
        ix["Debit"], ix["Credit"], ix["EcritureNum"], ix["CompteNum"], ix["CompAuxNum"],
        ix["CompAuxLib"], ix["CompteLib"], ix["JournalCode"], ix["EcritureDate"])
    prefix_class = {p: cls for cls, lst in class_prefixes.items() for p in lst}

    total_d = total_c = Decimal(0)
    n = bad_cols = bad_amounts = neg = 0
    comptes: set[str] = set()
    auxs: set[str] = set()
    journals: Counter[str] = Counter()
    ecr: dict[tuple[str, str], Decimal] = {}
    kinds = {c: Counter() for c in DATE_COLS if ix[c] is not None}
    bad_dates: Counter[str] = Counter()
    d_min = d_max = None
    cls_stats: dict[str, dict[str, Any]] = {}
    comma = dot = 0

    for r in fec.rows():
        n += 1
        if len(r) != ncol:
            bad_cols += 1
            continue
        deb, cre = r[iD], r[iC]
        if "," in deb or "," in cre:
            comma += 1
        elif "." in deb or "." in cre:
            dot += 1
        d, c = parse_amount(deb), parse_amount(cre)
        if d is None or c is None:
            bad_amounts += 1
            continue
        if d < 0 or c < 0:
            neg += 1
        total_d += d
        total_c += c
        cpt = r[iCpt].strip()
        comptes.add(cpt)
        aux = r[iAux].strip()
        if aux:
            auxs.add(aux)
        journals[r[iJ].strip()] += 1
        key = (r[iJ].strip(), r[iN].strip())
        ecr[key] = ecr.get(key, Decimal(0)) + d - c
        for col, cnt in kinds.items():
            v = r[ix[col]].strip()
            if v:
                cnt[date_kind(v) or "?"] += 1
        # classes de comptes de tiers
        cls = prefix_class.get(cpt[:3])
        if cls:
            st = cls_stats.setdefault(cls, {"lignes": 0, "avec_aux": 0, "comptes": set(),
                                            "libelles": set(), "aux": set()})
            st["lignes"] += 1
            st["comptes"].add(cpt)
            st["libelles"].add(r[iCptL].strip())
            if aux or r[iAuxL].strip():
                st["avec_aux"] += 1
                st["aux"].add(aux)

    # formats de date par colonne et bornes de l'exercice
    date_formats: dict[str, str] = {}
    for col, cnt in kinds.items():
        if cnt:
            date_formats[col] = cnt.most_common(1)[0][0]
    if "EcritureDate" in date_formats and date_formats["EcritureDate"] != "?":
        k = date_formats["EcritureDate"]
        for r in fec.rows():
            if len(r) != ncol:
                continue
            p = date_parts(r[iE].strip(), k)
            if p is None:
                bad_dates["EcritureDate"] += 1
                continue
            d_min = p if d_min is None or p < d_min else d_min
            d_max = p if d_max is None or p > d_max else d_max
    for col, cnt in kinds.items():
        bad_dates[col] += cnt.get("?", 0)
        if len([k for k in cnt if k != "?"]) > 1:
            fec.issues.append(Issue("avertissement", "DATES_MIXTES",
                                    f"Colonne {col} : plusieurs formats de date mélangés."))

    issues = list(fec.issues)
    balanced = total_d == total_c
    if not balanced:
        issues.append(Issue("erreur", "DESEQUILIBRE", "Total des débits différent du total des crédits."))
    unbalanced = sum(1 for v in ecr.values() if v != 0)
    if unbalanced:
        issues.append(Issue("avertissement", "ECRITURES_DESEQUILIBREES",
                            f"{unbalanced} écriture(s) (journal + numéro) non équilibrée(s)."))
    if bad_cols:
        issues.append(Issue("erreur", "NB_COLONNES", f"{bad_cols} ligne(s) avec un nombre de colonnes incorrect."))
    if bad_amounts:
        issues.append(Issue("erreur", "MONTANTS", f"{bad_amounts} ligne(s) avec un montant illisible."))
    for col in bad_dates:
        if bad_dates[col]:
            issues.append(Issue("avertissement", "DATES_ILLISIBLES", f"{bad_dates[col]} date(s) illisible(s) dans {col}."))
    for col, k in date_formats.items():
        if k != "AAAAMMJJ" and k != "?":
            issues.append(Issue("avertissement", "DATE_HORS_NORME",
                                f"Colonne {col} au format {k} (la norme A47 A-1 prévoit AAAAMMJJ)."))
    if neg:
        issues.append(Issue("avertissement", "MONTANTS_NEGATIFS", f"{neg} ligne(s) avec montant négatif."))

    siren, closing = filename_info(fec.filename)
    if not siren:
        siren_check = "nom de fichier hors norme (SIRENFECAAAAMMJJ) : non vérifiable"
    elif not fiche_siren:
        siren_check = "SIREN lu dans le nom du fichier : à confirmer à l'étape « Noms à valider »"
    elif siren == fiche_siren:
        siren_check = "concordant"
    else:
        siren_check = "DIFFÉRENT"
        issues.append(Issue("erreur", "SIREN_DIFFERENT", "Le SIREN du nom de fichier diffère de celui du dossier (fiche ou autres FEC déjà importés)."))

    classes = {}
    for cls, st in cls_stats.items():
        share = st["avec_aux"] / st["lignes"] if st["lignes"] else 0
        mode = "auxiliaire" if share >= 0.9 else ("compte / libellé" if share <= 0.1 else "mixte")
        classes[cls] = {"lignes": st["lignes"], "mode": mode, "comptes": len(st["comptes"]),
                        "libelles_distincts": len(st["libelles"]), "auxiliaires": len(st["aux"])}

    exercice = None
    if d_min and d_max:
        exercice = (str(d_min[0]) if d_min[0] == d_max[0] else f"{d_min[0]}-{d_max[0]}")
    return {
        "filename": fec.filename, "sha256": fec.sha256, "size": fec.size,
        "encoding": fec.fmt.encoding + (" (BOM)" if fec.fmt.bom else ""),
        "separator": {"\t": "tabulation", "|": "barre verticale", ";": "point-virgule"}[fec.fmt.sep],
        "newline": {"\r\n": "CRLF", "\n": "LF", "\r": "CR"}[fec.fmt.newline],
        "decimal": "virgule" if comma >= dot else "point",
        "lignes": n, "total_debit": str(total_d), "total_credit": str(total_c),
        "equilibre": balanced, "ecritures_desequilibrees": unbalanced,
        "comptes": len(comptes), "auxiliaires": len(auxs), "journaux": len(journals),
        "date_min": "%04d-%02d-%02d" % d_min if d_min else None,
        "date_max": "%04d-%02d-%02d" % d_max if d_max else None,
        "exercice": exercice, "formats_dates": date_formats,
        "siren_nom_fichier": siren, "date_cloture_nom_fichier": closing, "siren_controle": siren_check,
        "classes_tiers": classes,
        "issues": [i.as_dict() for i in issues],
        "bloquant": any(i.level == "erreur" for i in issues),
    }
