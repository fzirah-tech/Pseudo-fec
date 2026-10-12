"""Relevé des noms candidats à pseudonymiser (propositions soumises à validation).

Sources, par ordre de fiabilité :
1. fiche dossier et table existante (entités déjà connues) ;
2. CompAuxLib (comptes auxiliaires) ;
3. CompteLib des comptes de tiers individualisés (421, 455, 164…) ;
4. EcritureLib / PieceRef : retrouvent les tiers connus (variantes comprises) et
   proposent des noms propres inconnus par heuristiques (« Prénom NOM », forme
   juridique, répétition) — confiance indiquée, jamais cochés d'office si faible.

La détection est une aide : elle n'offre aucune garantie d'exhaustivité.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

try:                                    # accélérateur facultatif : l'outil fonctionne sans lui
    from rapidfuzz import fuzz as _fuzz

    def _similarity(a: str, b: str) -> float:
        return _fuzz.token_sort_ratio(a, b)
except ImportError:  # pragma: no cover - dépend de l'installation
    _fuzz = None
    from difflib import SequenceMatcher

    def _similarity(a: str, b: str) -> float:
        return _similarity_fallback(a, b)

from . import redact
from .contexts import CONTEXT_LABELS, DEFAULT_CONTEXTS, contexts_for_accounts
from .parties import is_person, parts_for
from .fec_io import FecFile
from .generic_list import Whitelist
from .lexicon import GENERIC_ACCOUNT_WORDS, PAYROLL_PREFIXES, SALARY_WORDS, STOPWORDS
from .textmatch import LEGAL_FORMS, LINK_WORDS, NameMatcher, fold, fold_text, name_key, tokens

TOKEN_RE = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*")
CATS = {"CLI": "Client", "FRN": "Fournisseur", "SAL": "Salarié", "ASS": "Associé / dirigeant",
        "GRP": "Société liée", "TIE": "Autre tiers", "SOC": "L'entité"}
MAX_LIBS_EXAMPLES = 3


def category_for_prefix(p3: str) -> str:
    if p3[:2] == "40":
        return "FRN"
    if p3[:2] == "41":
        return "CLI"
    if p3[:2] == "42":
        return "SAL"
    if p3 in ("451", "456"):
        return "GRP"
    if p3[:2] == "45":
        return "ASS"
    if p3[:2] in ("26", "27"):
        return "GRP"
    return "TIE"


def _similarity_fallback(a: str, b: str) -> float:
    """Similarité 0-100 (mots triés) avec la seule bibliothèque standard."""
    from difflib import SequenceMatcher
    return 100 * SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio()


# ------------------------------------------------------------------ relevé dans un FEC

@dataclass
class Harvest:
    n_lines: int = 0
    aux: Counter = field(default_factory=Counter)            # (CompAuxLib, préfixe) -> lignes
    aux_nums: dict[str, str] = field(default_factory=dict)   # CompAuxNum alphabétique -> CompAuxLib
    comptes: Counter = field(default_factory=Counter)        # (CompteNum, CompteLib) -> lignes (sans auxiliaire)
    libs: dict[str, dict] = field(default_factory=dict)      # EcritureLib -> {n, j, p, acc}
    pieces: Counter = field(default_factory=Counter)
    vocab: Counter = field(default_factory=Counter)          # mots de JournalLib / CompteLib non tiers
    alpha_comptes: set[str] = field(default_factory=set)     # CompteNum contenant des lettres
    tier_prefixes: set[str] = field(default_factory=set)
    ctx: Counter = field(default_factory=Counter)            # (tiers, variante rencontrée dans l'écriture) -> lignes
    lib_ctx: dict[str, Counter] = field(default_factory=dict)   # EcritureLib -> {contexte: lignes}
    ctx_lines: Counter = field(default_factory=Counter)      # contexte -> lignes


def harvest(fec: FecFile, tier_prefixes: Iterable[str], contexts: dict[str, list[str]] | None = None) -> Harvest:
    c = fec.fmt.columns
    iJL, iCpt, iCptL, iAux, iAuxL, iPiece, iLib, iJ = (
        c["JournalLib"] if "JournalLib" in c else None, c["CompteNum"], c["CompteLib"], c["CompAuxNum"],
        c["CompAuxLib"], c["PieceRef"], c["EcritureLib"], c["JournalCode"])
    tp = set(tier_prefixes)
    h = Harvest(tier_prefixes=tp)
    ncol = fec.n_columns
    iN = c["EcritureNum"]
    ecr: dict[tuple[str, str], list] = {}
    for r in fec.rows():
        if len(r) != ncol:
            continue
        h.n_lines += 1
        cpt, cptl = r[iCpt].strip(), r[iCptL].strip()
        aux, auxl = r[iAux].strip(), r[iAuxL].strip()
        p3 = cpt[:3]
        if re.search(r"[A-Za-z]", cpt):
            h.alpha_comptes.add(cpt)
        if auxl:
            h.aux[(auxl, p3)] += 1
        if aux and re.search(r"[A-Za-z]", aux) and auxl:
            h.aux_nums[aux] = auxl
        if p3 in tp:
            if cptl and not auxl:
                h.comptes[(cpt, cptl)] += 1
        elif cptl:
            for t in tokens(cptl):
                if len(t) >= 3:
                    h.vocab[t] += 1
        if iJL is not None and r[iJL].strip():
            for t in tokens(r[iJL]):
                if len(t) >= 3:
                    h.vocab[t] += 1
        lib = r[iLib].strip()
        if lib and lib != '""':
            e = h.libs.get(lib)
            if e is None:
                e = h.libs[lib] = {"n": 0, "j": set(), "p": set(), "acc": Counter()}
            e["n"] += 1
            if len(e["j"]) < 4:
                e["j"].add(r[iJ].strip())
            if len(e["p"]) < 6:
                e["p"].add(p3)
            if len(e["acc"]) < 6:
                e["acc"][cpt] += 1
        pr = r[iPiece].strip()
        if pr:
            h.pieces[pr] += 1
        d = ecr.setdefault((r[iJ].strip(), r[iN].strip()), [set(), Counter(), set(), 0])
        if auxl:
            d[0].add(auxl)
        if lib and lib != '""':
            d[1][lib] += 1
        d[2].add(cpt)
        d[3] += 1
    for tiers, libs, accs, nlines in ecr.values():
        ctxs = contexts_for_accounts(accs, contexts)          # contexte de l'écriture entière (paie, provisions…)
        for cx in ctxs:
            h.ctx_lines[cx] += nlines
        for lib, n in libs.items():
            lc = h.lib_ctx.setdefault(lib, Counter())
            for cx in ctxs:
                lc[cx] += n
    for tiers, libs, accs, nlines in ecr.values():       # libellés d'une écriture portant un tiers : variantes probables de son nom
        if not tiers:
            continue
        for lib, n in libs.items():
            for t in tiers:
                v = _overlap(lib, t)
                if v:
                    h.ctx[(t, v)] += n
    return h


def _overlap(lib: str, tier: str) -> str | None:
    """Plus longue suite de mots du libellé qui figure aussi, telle quelle, dans le nom du tiers."""
    lt = [(fold(m.group()), m.start(), m.end()) for m in TOKEN_RE.finditer(lib)]
    tt = [fold(m.group()) for m in TOKEN_RE.finditer(tier)]
    best, best_len = None, 0
    for i in range(len(lt)):
        for j in range(len(tt)):
            k = 0
            while i + k < len(lt) and j + k < len(tt) and lt[i + k][0] == tt[j + k]:
                k += 1
            while k and (lt[i + k - 1][0] in LEGAL_FORMS or lt[i + k - 1][0] in LINK_WORDS):
                k -= 1
            if k:
                words = [lt[i + x][0] for x in range(k)]
                if lt[i][0] in LEGAL_FORMS or lt[i][0] in LINK_WORDS:
                    continue
                n = sum(len(w) for w in words)
                if n > best_len and n >= 4:
                    best, best_len = lib[lt[i][1]:lt[i + k - 1][2]], n
    if best is None or fold(best) == fold(tier):
        return None
    return best


def merge_harvests(hs: list[Harvest]) -> Harvest:
    out = Harvest(tier_prefixes=hs[0].tier_prefixes if hs else set())
    for h in hs:
        out.n_lines += h.n_lines
        out.aux.update(h.aux)
        out.aux_nums.update(h.aux_nums)
        out.comptes.update(h.comptes)
        out.pieces.update(h.pieces)
        out.vocab.update(h.vocab)
        out.alpha_comptes |= h.alpha_comptes
        out.ctx.update(h.ctx)
        out.ctx_lines.update(h.ctx_lines)
        for lib, lc in h.lib_ctx.items():
            out.lib_ctx.setdefault(lib, Counter()).update(lc)
        for lib, e in h.libs.items():
            o = out.libs.setdefault(lib, {"n": 0, "j": set(), "p": set(), "acc": Counter()})
            o["n"] += e["n"]
            o["j"] |= e["j"]
            o["p"] |= e["p"]
            o["acc"].update(e["acc"])
    return out


# ------------------------------------------------------------------ candidats

@dataclass
class Candidate:
    key: str
    nom: str
    cat: str
    source: str                       # fiche | table | aux | compte | libelle | manuel
    uid: str | None = None
    pseudo: str | None = None
    variants: Counter = field(default_factory=Counter)   # texte rencontré -> occurrences
    var_origin: dict[str, str] = field(default_factory=dict)   # texte -> contexte | libelle | compte | fiche
    var_risk: set[str] = field(default_factory=set)
    champs: Counter = field(default_factory=Counter)     # champ -> occurrences
    comptes: Counter = field(default_factory=Counter)
    exemples: list[str] = field(default_factory=list)
    variantes_proposees: list[dict[str, Any]] = field(default_factory=list)
    contextes: Counter = field(default_factory=Counter)            # où le nom apparaît : contexte -> lignes
    parties: list[dict[str, Any]] = field(default_factory=list)     # parties identifiantes proposées
    saved_parties: dict[str, dict[str, Any]] = field(default_factory=dict)
    occurrences: int = 0
    confiance: str = "haute"
    statut: str = "nouveau"           # nouveau | connu | liste_blanche
    liste_blanche: str | None = None
    checked: bool = True
    notes: list[str] = field(default_factory=list)
    merge_with: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "nom": self.nom, "cat": self.cat, "source": self.source, "uid": self.uid,
            "pseudo": self.pseudo,
            "variantes": [{"texte": t, "n": n, "origine": self.var_origin.get(t, "libelle"),
                           "risque": t in self.var_risk, "coche": t not in self.var_risk}
                          for t, n in self.variants.most_common(20)],
            "champs": dict(self.champs), "comptes": [k for k, _ in self.comptes.most_common(5)],
            "nb_comptes": len(self.comptes), "exemples": self.exemples, "occurrences": self.occurrences,
            "confiance": self.confiance, "statut": self.statut, "liste_blanche": self.liste_blanche,
            "checked": self.checked, "notes": self.notes, "merge_with": self.merge_with,
            "variantes_proposees": self.variantes_proposees, "contextes": dict(self.contextes), "parties": self.parties,
        }


def _strip_generic_edges(label: str) -> str:
    """Retire les mots génériques en tête/queue d'un libellé de compte (« Associé - X »)."""
    toks = list(TOKEN_RE.finditer(label))
    lo, hi = 0, len(toks)
    while lo < hi and fold(toks[lo].group()) in GENERIC_ACCOUNT_WORDS:
        lo += 1
    while hi > lo and fold(toks[hi - 1].group()) in GENERIC_ACCOUNT_WORDS:
        hi -= 1
    if lo >= hi:
        return ""
    return label[toks[lo].start():toks[hi - 1].end()]


def _kind(tok: str) -> str:
    if tok.upper() == tok:
        return "U"
    return "C" if tok[0].isupper() else "x"


def _unknown_phrases(lib: str, covered: list[tuple[int, int]], is_vocab=lambda f: False) -> list[tuple[str, str, bool]]:
    """Noms propres probables dans un libellé : (texte, forme, présence d'une forme juridique).

    Les mots déjà reconnus comme tiers connus (``covered``) comptent comme parties du nom :
    « MARTIN Sophie » est proposé en entier même si « MARTIN » est un fournisseur connu.
    Un groupe entièrement couvert par des tiers connus n'est pas reproposé.
    """
    out = []
    toks = []
    solid = [(a, b) for a, b in covered if len(TOKEN_RE.findall(lib[a:b])) >= 2]   # noms multi-mots déjà connus : bornes
    for m in TOKEN_RE.finditer(lib):
        if (m.start() > 0 and lib[m.start() - 1].isdigit()) or (m.end() < len(lib) and lib[m.end()].isdigit()):
            continue   # codes alphanumériques (FA0012, FR76…) : pas des noms
        if any(a <= m.start() < b for a, b in solid):
            toks.append((m, None))        # fait partie d'un nom connu complet : coupe le groupe
        elif any(a <= m.start() < b for a, b in covered if b - a):
            toks.append((m, True))
        else:
            toks.append((m, False))

    def namelike(m: re.Match, cov: bool | None) -> bool:
        f = fold(m.group())
        if cov is None:
            return False
        if cov:
            return True
        return (_kind(m.group()) != "x" and f not in STOPWORDS and len(f) >= 2 and f not in LINK_WORDS
                and not is_vocab(f))

    i = 0
    while i < len(toks):
        m, cov = toks[i]
        if not namelike(m, cov):
            i += 1
            continue
        run = [toks[i]]
        j = i + 1
        while j < len(toks):
            nxt, ncov = toks[j]
            gap = lib[run[-1][0].end():nxt.start()]
            if not re.fullmatch(r"[ \t.]*", gap) or len(gap) > 4:
                break
            fn = fold(nxt.group())
            if fn in ("et", "de", "du", "des", "d", "l", "la", "le") and j + 1 < len(toks) and namelike(*toks[j + 1]):
                run.append(toks[j])
                j += 1
                continue
            if not namelike(nxt, ncov):
                break
            run.append(toks[j])
            j += 1
        while run and fold(run[-1][0].group()) in LINK_WORDS and not run[-1][1]:
            run.pop()
        if run and any(not c for _, c in run):
            txt = lib[run[0][0].start():run[-1][0].end()]
            real = [t for t, _ in run if fold(t.group()) not in LEGAL_FORMS and fold(t.group()) not in LINK_WORDS]
            kinds = {_kind(t.group()) for t in real}
            has_legal = any(fold(t.group()) in LEGAL_FORMS for t, _ in run)
            if real:
                out.append((txt, "personne" if kinds == {"U", "C"} and len(real) >= 2 else
                            ("multi" if len(real) >= 2 else "seul"), has_legal))
        i = max(j, i + 1)
    return out


@dataclass
class DetectionResult:
    candidates: list[Candidate]
    sensibles: dict[str, Any]
    incrustations: dict[str, Any]
    conflits: list[dict[str, Any]]
    stats: dict[str, Any]
    synthese: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"candidats": [c.as_dict() for c in self.candidates], "sensibles": self.sensibles,
                "incrustations": self.incrustations, "conflits": self.conflits, "stats": self.stats,
                "synthese": self.synthese}


def detect(fecs: list[FecFile], payload: dict[str, Any], priority_prefixes: dict[str, list[str]],
           whitelist: Whitelist, extra_sirens: frozenset[str] = frozenset(),
           contexts: dict[str, list[str]] | None = None) -> DetectionResult:
    tier_prefixes = {p for lst in priority_prefixes.values() for p in lst}
    hv = merge_harvests([harvest(f, tier_prefixes, contexts) for f in fecs])
    cands: dict[str, Candidate] = {}

    def get(key: str, nom: str, cat: str, source: str, **kw: Any) -> Candidate:
        k = fold(nom)
        c = cands.get(k)
        if c is None:
            c = cands[k] = Candidate(key=k, nom=nom, cat=cat, source=source, **kw)
        return c

    # 1. entités connues (fiche + table)
    for e in payload.get("entities", []):
        if e.get("retired"):
            continue
        c = get(e["nom"], e["nom"], e["cat"], e.get("source", "table"), uid=e["uid"], pseudo=e.get("pseudo"))
        c.uid, c.pseudo, c.statut = e["uid"], e.get("pseudo"), "connu"
        c.checked = bool(e.get("a_pseudonymiser", True))
        c.source = e.get("source", "table")
        for v in e.get("variantes", []):
            c.variants.setdefault(v, 0)
        for i in e.get("ids", []):
            c.variants.setdefault(i, 0)
        c.saved_parties = {fold(x["texte"]): x for x in e.get("parties", [])}

    # 2. CompAuxLib
    aux_by_name: dict[str, Counter] = defaultdict(Counter)
    for (name, p3), n in hv.aux.items():
        aux_by_name[name][p3] += n
    for name, prefs in aux_by_name.items():
        cat = category_for_prefix(prefs.most_common(1)[0][0])
        c = get(name, name, cat, "aux")
        c.variants.setdefault(name, 0)
        c.champs["CompAuxLib"] += sum(prefs.values())
        c.occurrences += sum(prefs.values())
        c.comptes.update({p: n for p, n in prefs.items()})

    # 3. CompteLib de tiers individualisés
    by_prefix: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for (cpt, lib), n in hv.comptes.items():
        by_prefix[cpt[:3]].append((cpt, lib, n))
    for p3, items in by_prefix.items():
        for cpt, lib, n in items:
            name = _strip_generic_edges(lib)
            if not name or fold(name) in STOPWORDS:
                continue
            c = get(name, name, category_for_prefix(p3), "compte")
            if all(_kind(t) == "x" for t in TOKEN_RE.findall(name)) and c.statut != "connu":
                c.confiance = "faible"        # intitulé tout en minuscules : plutôt descriptif (« salaires 2022 ») qu'un nom
                c.notes.append("Intitulé de compte en minuscules : probablement descriptif, non coché par défaut.")
            c.variants.setdefault(name, 0)
            c.champs["CompteLib"] += n
            c.occurrences += n
            c.comptes[cpt] += n
            if c.source == "aux":
                pass

    # 4. libellés : tiers connus puis noms propres inconnus
    # fréquence des mots : un mot très fréquent dans les libellés est du vocabulaire, pas un nom
    word_freq: Counter = Counter()
    lower_words: set[str] = set()      # un nom propre s'écrit rarement en minuscules : mot courant
    for lib, e in hv.libs.items():
        for t in set(tokens(lib)):
            word_freq[t] += e["n"]
        for m in TOKEN_RE.finditer(lib):
            if m.group()[0].islower() and len(m.group()) >= 3:
                lower_words.add(fold(m.group()))
    total_lines = max(hv.n_lines, 1)

    def is_common(f: str) -> bool:
        return (f in STOPWORDS or f in hv.vocab or f in lower_words
                or (word_freq[f] >= 30 and word_freq[f] / total_lines >= 0.01))

    known_tokens = {t for c in cands.values() for t in tokens(c.nom)}

    def is_vocab(f: str) -> bool:
        return f not in known_tokens and is_common(f)

    # variantes du nom d'un tiers trouvées dans les libellés de SES écritures (contexte)
    tok_owner: Counter = Counter(t for c in cands.values() for t in set(tokens(c.nom)))
    for (tier, text), n in hv.ctx.items():
        ck = fold(tier)
        c = cands.get(ck)
        if c is None:
            continue
        words = [t for t in tokens(text) if t not in LEGAL_FORMS and t not in LINK_WORDS]
        if not words or all(is_common(w) for w in words):
            continue
        c.variants[text] += 0
        c.var_origin.setdefault(text, "contexte")
        if len(words) == 1 and tok_owner[words[0]] > 1:
            c.var_risk.add(text)          # un seul mot partagé avec un autre tiers : homonymie possible

    matcher = NameMatcher((v, k) for k, c in cands.items() for v in {c.nom, *c.variants})
    sirens_all = extra_sirens | frozenset(i[:9] for e in payload.get("entities", []) if e["cat"] == "SOC" for i in e.get("ids", []) if len(i) >= 9)
    covered_by_lib: dict[str, list[tuple[int, int]]] = {}
    payroll_libs: set[str] = set()
    for lib, e in hv.libs.items():
        ftoks = set(tokens(lib))
        if ftoks & SALARY_WORDS or e["p"] & PAYROLL_PREFIXES:
            payroll_libs.add(lib)
        hits = matcher.find(lib)
        covered_by_lib[lib] = [(a, b) for a, b, _ in hits] + [(h.start, h.end) for h in redact.scan(lib, sirens_all)]
        for a, b, key in hits:
            c = cands[key]
            c.variants[lib[a:b]] += e["n"]
            c.var_origin.setdefault(lib[a:b], "libelle")
            c.champs["EcritureLib"] += e["n"]
            c.occurrences += e["n"]
            for cx, n in hv.lib_ctx.get(lib, {}).items():
                c.contextes[cx] += n
            for acc, n in e["acc"].items():
                c.comptes[acc] += 0
            if len(c.exemples) < MAX_LIBS_EXAMPLES and lib not in c.exemples:
                c.exemples.append(lib)
    for pr, n in hv.pieces.items():
        for a, b, key in matcher.find(pr):
            c = cands[key]
            c.variants[pr[a:b]] += n
            c.champs["PieceRef"] += n
            c.occurrences += n

    unknown: dict[str, Candidate] = {}
    for lib, e in hv.libs.items():
        for txt, shape, legal in _unknown_phrases(lib, covered_by_lib[lib], is_vocab):
            toks = [t for t in tokens(txt) if t not in LEGAL_FORMS and t not in LINK_WORDS]
            if not toks:
                continue
            if sum(map(len, toks)) < 4:
                continue
            pay = lib in payroll_libs
            k = fold(txt)
            if k in cands:
                cands[k].variants[txt] += e["n"]
                continue
            u = unknown.get(k)
            if u is None:
                cat = "SAL" if pay and shape in ("personne", "multi", "seul") else (
                    category_for_prefix(next(iter(e["p"] or {"000"}), "000")) if e["p"] else "TIE")
                if cat in ("GRP", "ASS"):
                    cat = "TIE"
                u = unknown[k] = Candidate(key=k, nom=txt, cat=cat, source="libelle", confiance="faible", checked=False)
                u.notes.append(f"forme : {shape}")
            u.variants[txt] += e["n"]
            u.champs["EcritureLib"] += e["n"]
            u.occurrences += e["n"]
            for cx, n in hv.lib_ctx.get(lib, {}).items():
                u.contextes[cx] += n
            if shape == "personne" and pay:
                u.confiance = "haute"
            elif legal or (shape == "personne" and u.confiance != "haute"):
                u.confiance = "moyenne" if u.confiance == "faible" else u.confiance
            elif u.occurrences >= 3 and u.confiance == "faible" and sum(map(len, toks)) >= 5:
                u.confiance = "moyenne"
            if pay and u.cat == "TIE":
                u.cat = "SAL" if shape in ("personne", "multi") else u.cat
            if len(u.exemples) < MAX_LIBS_EXAMPLES and lib not in u.exemples:
                u.exemples.append(lib)
    for k, u in unknown.items():
        cands[k] = u
    # nom propre isolé non confirmé : bruit probable -> on ne garde que les plus répétés
    for k in [k for k, u in cands.items() if u.source == "libelle" and u.confiance == "faible" and u.occurrences < 2
              and "forme : seul" in u.notes]:
        del cands[k]

    # 4b. mots isolés relevés dans les contextes sensibles (nom de famille seul, prénom seul…)
    sens_ctx = ("paie", "compte_courant", "provisions")
    phrase_tokens = {t for c in cands.values() for t in tokens(c.nom)}
    words: dict[str, Candidate] = {}
    for lib, e in hv.libs.items():
        lc = hv.lib_ctx.get(lib)
        if not lc or not any(cx in lc for cx in sens_ctx):
            continue
        cov = covered_by_lib.get(lib, [])
        for m in TOKEN_RE.finditer(lib):
            tok = m.group()
            f = fold(tok)
            if len(tok) < 3 or _kind(tok) == "x" or f in STOPWORDS or f in LEGAL_FORMS or f in LINK_WORDS:
                continue
            if is_vocab(f) or all(t in phrase_tokens for t in tokens(tok)) or whitelist.matches(tok):
                continue
            if (m.start() > 0 and lib[m.start() - 1].isdigit()) or (m.end() < len(lib) and lib[m.end()].isdigit()):
                continue
            if any(a <= m.start() < b for a, b in cov):
                continue
            w = words.get(f)
            if w is None:
                w = words[f] = Candidate(key=f, nom=tok, cat="SAL" if "paie" in lc else "TIE", source="contexte",
                                         confiance="moyenne", checked=False)
                w.notes.append("Mot isolé relevé dans une écriture de " + ("paie" if "paie" in lc else "provision / compte courant")
                               + " : nom de famille, prénom ou nom partiel ?")
            w.variants[tok] += e["n"]
            w.champs["EcritureLib"] += e["n"]
            w.occurrences += e["n"]
            for cx, n in lc.items():
                w.contextes[cx] += n
            if len(w.exemples) < MAX_LIBS_EXAMPLES and lib not in w.exemples:
                w.exemples.append(lib)
    for f, w in words.items():
        cands.setdefault(f, w)

    # 5. liste blanche, pré-cochage, exemples
    for c in cands.values():
        if c.statut == "connu" and c.uid:
            continue
        wl = whitelist.matches(c.nom)
        if wl:
            c.statut, c.liste_blanche, c.checked = "liste_blanche", wl, False
            c.notes.append(f"Tiers usuel maintenu (liste blanche : {wl}) — cochez pour le pseudonymiser quand même.")
        else:
            c.checked = c.source == "aux" or (c.source == "compte" and c.confiance != "faible") or c.confiance == "haute"
        if not c.exemples:
            c.exemples = _examples_for(c, hv)

    # 6. propositions de fusion
    _suggest_merges(list(cands.values()))

    # 5b. parties identifiantes (nom de famille, prénom, partie distinctive d'une société)
    _attach_parties(cands, hv, lambda f: f in STOPWORDS or f in hv.vocab or f in lower_words)

    _note_overlaps(list(cands.values()))
    _propose_person_variants(list(cands.values()), hv)

    # 7. conflits de variantes (même texte pour deux entités)
    conflits = []
    full = NameMatcher((v, c.key) for c in cands.values() for v in {c.nom, *c.variants})
    for toks, keys in full.conflicts.items():
        conflits.append({"texte": " ".join(toks), "entites": [cands[k].nom for k in keys if k in cands]})

    sens, incr = _sensitive_and_incrustations(hv, payload, cands, extra_sirens)
    stats = {"lignes": hv.n_lines, "libelles_distincts": len(hv.libs), "candidats": len(cands),
             "societe_suggestions": _societe_suggestions(cands)}
    order = {"aux": 0, "compte": 1, "fiche": 2, "table": 2, "manuel": 2, "libelle": 3}
    order["contexte"] = 4
    lst = sorted(cands.values(), key=lambda c: (c.statut == "liste_blanche", order.get(c.source, 4), -c.occurrences))
    ctx_libs: Counter = Counter()
    for lc in hv.lib_ctx.values():
        for cx in lc:
            ctx_libs[cx] += 1
    top: dict[str, Counter] = defaultdict(Counter)
    for lib, lc in hv.lib_ctx.items():
        for cx, n in lc.items():
            top[cx][lib] = n
    synthese = {"contextes": [{"id": cx, "label": CONTEXT_LABELS[cx], "lignes": hv.ctx_lines.get(cx, 0),
                               "libelles": ctx_libs.get(cx, 0),
                               "exemples": [{"texte": t, "n": n} for t, n in top[cx].most_common(8)]}
                              for cx in ("paie", "compte_courant", "provisions", "autres")]}
    return DetectionResult(lst, sens, incr, conflits, stats, synthese)


_SOURCE_RANK = {"aux": 0, "compte": 1, "fiche": 2, "table": 2, "manuel": 2, "libelle": 3, "contexte": 4}


def _lead(c: Candidate, cands: dict[str, Candidate], group: set[str]) -> Candidate:
    members = [cands[k] for k in group if k in cands]
    return min(members, key=lambda x: (x.statut != "connu", _SOURCE_RANK.get(x.source, 5), -x.occurrences, x.key))


def _attach_parties(cands: dict[str, Candidate], hv: Harvest, is_common) -> None:
    """Propose, pour chaque nom, ses parties identifiantes avec leur fréquence dans le FEC et leurs risques."""
    pool = [c for c in cands.values() if c.statut != "liste_blanche" and c.source != "contexte"]
    owners: dict[str, set[str]] = defaultdict(set)
    for c in pool:
        if c.source in ("libelle", "contexte") and len(tokens(c.nom)) == 1:
            continue          # simple mot isolé : mention partielle d'un nom, pas un nom distinct
        for t in tokens(c.nom):
            owners[t].add(c.key)
    same = {c.key: {c.key, *c.merge_with} for c in pool}          # « Karim BENALI » et « BENALI Karim » : même personne
    items = []
    for c in pool:
        c.parties = [{**p, "n": 0, "ctx": {}, "risque": []} for p in parts_for(c.nom, c.cat)[:10]]
        items += [(p["texte"], (c.key, i)) for i, p in enumerate(c.parties)]
    matcher = NameMatcher(items)
    for lib, e in hv.libs.items():
        lc = hv.lib_ctx.get(lib, {})
        for _, _, (ck, i) in matcher.find(lib):
            p = cands[ck].parties[i]
            p["n"] += e["n"]
            for cx, n in lc.items():
                p["ctx"][cx] = p["ctx"].get(cx, 0) + n
    for c in pool:
        person = is_person(c.nom, c.cat)
        for p in c.parties:
            toks = [t for t in tokens(p["texte"]) if t not in LINK_WORDS and t not in LEGAL_FORMS]
            if toks and all(is_common(t) for t in toks):
                p["risque"].append("mot courant")
            others = sorted({cands[k].nom for t in toks for k in owners.get(t, ()) if k not in same[c.key] and k in cands})
            if others:
                p["risque"].append("partagé avec un autre nom")
                p["partage_avec"] = others[:3]
            if len(p["texte"]) < (3 if person else 5):
                p["risque"].append("trop court")
            if c.cat in ("GRP", "SOC"):
                p["portee"], p["actif"] = "partout", not p["risque"]
            elif person and c.cat in ("SAL", "ASS"):
                p["portee"], p["actif"] = "contextes", "mot courant" not in p["risque"]
            else:       # société ordinaire ou personne « supposée » : proposé, à activer par l'utilisateur
                p["portee"], p["actif"] = "contextes", False
            lead = _lead(c, cands, same[c.key])
            if lead is not c:         # même personne proposée sous deux écritures : seule la principale active ses parties
                p["actif"] = False
                p["risque"].append(f"même personne que « {lead.nom} »")
            sv = c.saved_parties.get(fold(p["texte"]))
            if sv:
                p["portee"], p["actif"] = sv.get("portee", p["portee"]), bool(sv.get("actif", p["actif"]))
        have = {fold(p["texte"]) for p in c.parties}
        for f, sv in c.saved_parties.items():
            if f not in have:
                c.parties.append({"texte": sv["texte"], "kind": "ajoutée", "n": 0, "ctx": {}, "risque": [],
                                  "portee": sv.get("portee", "contextes"), "actif": bool(sv.get("actif", True))})
        c.parties.sort(key=lambda p: (-p["n"], p["texte"]))
    owner_of = {fold(p["texte"]): c.key for c in pool for p in c.parties}
    for k in [k for k, c in cands.items() if c.source in ("libelle", "contexte") and c.statut != "connu"
              and owner_of.get(fold(c.nom), k) != k]:
        del cands[k]       # nom de famille / prénom seul : c'est la partie d'un nom déjà proposé


def _examples_for(c: Candidate, hv: Harvest) -> list[str]:
    out = []
    rx = NameMatcher((v, 1) for v in {c.nom, *c.variants})
    for lib in hv.libs:
        if rx.find(lib):
            out.append(lib)
            if len(out) >= MAX_LIBS_EXAMPLES:
                break
    return out


# ------------------------------------------------------------------ fusions proposées

_INITIAL = re.compile(r"^[a-z]$")


def _same_person_tokens(a: list[str], b: list[str]) -> bool:
    if len(a) != len(b):
        return False
    rest = list(b)
    for t in a:
        for u in rest:
            if t == u or (len(t) == 1 and u.startswith(t)) or (len(u) == 1 and t.startswith(u)):
                rest.remove(u)
                break
        else:
            return False
    return True


def _suggest_merges(cands: list[Candidate]) -> None:
    """Propose (sans appliquer) le regroupement de variantes d'un même tiers."""
    blocks: dict[str, list[Candidate]] = defaultdict(list)
    for c in cands:
        toks = [t for t in tokens(c.nom) if t not in LEGAL_FORMS and t not in LINK_WORDS]
        if toks:
            blocks[max(toks, key=lambda t: (len(t), t))[:4]].append(c)
    for group in blocks.values():
        for i, a in enumerate(group):
            ta = [t for t in tokens(a.nom) if t not in LEGAL_FORMS and t not in LINK_WORDS]
            for b in group[i + 1:]:
                if a.cat == "SAL" and b.cat != "SAL" or a.statut == "liste_blanche" or b.statut == "liste_blanche":
                    continue
                tb = [t for t in tokens(b.nom) if t not in LEGAL_FORMS and t not in LINK_WORDS]
                ka, kb = " ".join(sorted(ta)), " ".join(sorted(tb))
                ok = ka == kb or _same_person_tokens(ta, tb) or (
                    min(len(ka), len(kb)) >= 8 and _similarity(ka, kb) >= 93)
                if ok:
                    a.merge_with.append(b.key)
                    b.merge_with.append(a.key)


def _person_forms(nom: str) -> list[tuple[str, bool]]:
    """Formes usuelles d'un nom de personne : (texte, risqué). « Prénom NOM » -> « NOM Prénom », « NOM P. »…"""
    toks = [t.group() for t in TOKEN_RE.finditer(nom)]
    if len(toks) < 2:
        return []
    first, last = " ".join(toks[:-1]), toks[-1]
    f0 = toks[0][0]
    forms = [(f"{last} {first}", False), (f"{last} {f0}.", False), (f"{last} {f0}", False),
             (f"{f0}. {last}", False), (f"{f0} {last}", False), (last, True), (toks[0], True)]
    seen, out = {fold(nom)}, []
    for t, risky in forms:
        if fold(t) not in seen:
            seen.add(fold(t))
            out.append((t, risky))
    return out


def _propose_person_variants(cands: list[Candidate], hv: Harvest) -> None:
    """Variantes d'écriture de salariés / associés rencontrées dans les libellés (à valider)."""
    persons = [c for c in cands if c.cat in ("SAL", "ASS") and c.statut != "liste_blanche"]
    if not persons:
        return
    taken = {fold(c.nom) for c in cands} | {fold(v) for c in cands for v in c.variants}
    items, meta = [], {}
    for c in persons:
        for text, risky in _person_forms(c.nom):
            if fold(text) in taken:
                continue
            items.append((text, (c.key, text)))
            meta[(c.key, text)] = risky
    matcher = NameMatcher(items)
    counts: Counter = Counter()
    for lib, e in hv.libs.items():
        for _, _, key in matcher.find(lib):
            counts[key] += e["n"]
    by_key = {c.key: c for c in persons}
    for (ckey, text), n in counts.items():
        by_key[ckey].variantes_proposees.append(
            {"texte": text, "n": n, "risque": meta[(ckey, text)],
             "coche": not meta[(ckey, text)]})
    for c in persons:
        c.variantes_proposees.sort(key=lambda v: (v["risque"], -v["n"]))


def _note_overlaps(cands: list[Candidate]) -> None:
    """Signale les noms inclus dans d'autres noms (MARTIN / Sophie MARTIN) : le plus long est appliqué en premier."""
    sets = [(c, frozenset(tokens(c.nom)) - LEGAL_FORMS - LINK_WORDS) for c in cands]
    by_token: dict[str, list[int]] = defaultdict(list)
    for i, (_, st) in enumerate(sets):
        for t in st:
            by_token[t].append(i)
    for i, (a, sa) in enumerate(sets):
        if not sa:
            continue
        for j in set.intersection(*(set(by_token[t]) for t in sa)):
            if j != i and sa < sets[j][1]:
                a.notes.append(f"Recoupement : ce nom est inclus dans « {sets[j][0].nom} » "
                               "(l'occurrence la plus longue est traitée en premier).")


# ------------------------------------------------------------------ motifs sensibles, incrustations

def _societe_suggestions(cands: dict[str, Candidate]) -> list[dict[str, Any]]:
    """Raisons sociales possibles de l'entité : noms à forme juridique cités dans les libellés d'écritures
    (refacturations, virements internes…) et non rattachés à un tiers connu. Simple aide à la saisie."""
    out = []
    for c in cands.values():
        if c.statut == "connu" or c.source != "libelle":
            continue
        if any(t in LEGAL_FORMS for t in tokens(c.nom)):
            out.append({"nom": c.nom, "occurrences": c.occurrences})
    return sorted(out, key=lambda x: -x["occurrences"])[:6]


def _sensitive_and_incrustations(hv: Harvest, payload: dict[str, Any], cands: dict[str, Candidate],
                                 extra_sirens: frozenset[str] = frozenset()) -> tuple[dict[str, Any], dict[str, Any]]:
    sirens = extra_sirens | frozenset(i for e in payload.get("entities", []) if e["cat"] == "SOC" for i in e.get("ids", []) if len(i) == 9)
    sirens |= frozenset(i[:9] for e in payload.get("entities", []) if e["cat"] == "SOC" for i in e.get("ids", []) if len(i) == 14)
    counts: Counter = Counter()
    champs: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, str] = {}
    for field_name, strings in (("EcritureLib", hv.libs), ("PieceRef", hv.pieces)):
        for s, e in strings.items():
            n = e["n"] if isinstance(e, dict) else e
            for h in redact.scan(s, sirens):
                counts[h.kind] += n
                champs[h.kind][field_name] += n
                examples.setdefault(h.kind, redact.mask_example(s, h))
    names_fold = {c.key.replace(" ", "") for c in cands.values()}
    incr_aux = 0
    for num, lib in hv.aux_nums.items():
        letters = re.sub(r"[^a-z]", "", fold(num))
        if len(letters) >= 3 and re.sub(r"[^a-z]", "", fold(lib)).startswith(letters[:3]):
            incr_aux += 1
    sens = {"total": sum(counts.values()), "types": [
        {"type": k, "n": v, "champs": dict(champs[k]), "exemple": examples.get(k, ""),
         "remplacement": redact.TOKENS[k]} for k, v in counts.most_common()],
        "siren_entite": any(h for k in counts if k in ("SIREN", "SIRET"))}
    incr = {"CompAuxNum": incr_aux, "CompteNum": len(hv.alpha_comptes),
            "message": ("Des numéros de compte contiennent du texte lié à un nom : ils seront remplacés par un code "
                        "neutre cohérent lors de la pseudonymisation.") if incr_aux or hv.alpha_comptes else ""}
    return sens, incr
