"""Pseudonymisation d'un FEC (jalon c).

Règles :
- remplacement dans CompAuxLib, CompteLib, EcritureLib, PieceRef (et JournalLib) : insensible à la casse et
  aux accents, limites de mots respectées (MARTIN ne touche pas MARTINEZ), variantes les plus longues d'abord ;
- motifs sensibles (IBAN, SIRET, e-mail…) -> jetons neutres non réversibles ; SIREN de l'entité -> SOC-0001 ;
- JAMAIS modifiés : montants, dates, codes journaux, numéros d'écritures, lettrage, numéros de compte
  (sauf numéro alphabétique portant un nom : remplacé par un code neutre cohérent) ;
- sortie : même structure, même séparateur, même encodage, même fin de ligne ;
- contrôles BLOQUANTS : nombre de lignes et totaux débit/crédit identiques à la source.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from . import redact
from .contexts import DEFAULT_CONTEXTS, PRIORITY, contexts_for_accounts, main_context
from .detection import detect
from .errors import PseudoFecError
from .fec_io import FecFile, analyse, parse_fec
from .generic_list import Whitelist
from .lexicon import STOPWORDS
from .parties import expand_truncations
from .textmatch import LEGAL_FORMS, LINK_WORDS, NameMatcher, fold, tokens

PROTECTED = ("JournalCode", "EcritureNum", "EcritureDate", "PieceDate", "Debit", "Credit", "EcritureLet",
             "DateLet", "ValidDate", "Montantdevise", "Idevise")
TEXT_FIELDS = ("JournalLib", "CompteLib", "CompAuxLib", "PieceRef", "EcritureLib")
PSEUDO_RE = re.compile(r"^[A-Z]{3}-\d{4,}$")
_ALPHA = re.compile(r"[A-Za-z]")
_NO_ENTITY: tuple = ()


class PseudonymizationError(PseudoFecError):
    pass


def compact(pseudo: str) -> str:
    """FRN-0007 -> FRN0007 (code neutre utilisable dans un numéro de compte)."""
    return pseudo.replace("-", "")


def output_name(code: str, soc_pseudo: str | None, exercice: str | None, filename: str) -> str:
    base = f"DOSSIER-{compact(soc_pseudo)}" if soc_pseudo else f"DOSSIER-{code}"
    ext = ".txt"
    m = re.search(r"\.(txt|csv|fec)$", filename or "", re.I)
    if m:
        ext = "." + m.group(1).lower()
    return f"{base}_FEC_{(exercice or 'XXXX').replace('/', '-')}_PSEUDO{ext}"


PREFERRED = {"paie": ("SAL",), "compte_courant": ("ASS", "GRP", "DIV"), "provisions": ()}


def _truncations(ents: list[dict[str, Any]], base: list[tuple[str, str, int]]) -> list[tuple[str, str, int]]:
    """Formes tronquées en fin de libellé des sociétés (liées ou entité) : ignorées si elles désignent deux entités."""
    cats = {e["uid"]: e["cat"] for e in ents}
    exact = {}
    for t, u, _ in base:
        exact.setdefault(" ".join(tokens(t)), set()).add(u)
    found: dict[str, set[str]] = {}
    for t, u, _ in base:
        if cats.get(u) in ("GRP", "SOC", "DIV"):
            for x in expand_truncations(t):
                found.setdefault(" ".join(tokens(x)), set()).add(u)
    return [(x, next(iter(us)), 1) for x, us in found.items()
            if len(us) == 1 and not (exact.get(x, set()) - us)]


def build_matchers(ents: list[dict[str, Any]]) -> tuple[NameMatcher, dict[str, NameMatcher]]:
    """Matcher global (noms, variantes, parties « partout ») et un matcher par contexte sensible.

    Dans un contexte, les parties « contextes » sont ajoutées : en paie le salarié l'emporte sur un homonyme
    (MARTIN fournisseur / MARTIN salariée), en compte courant les associés et sociétés liées. À rang égal,
    c'est un conflit à arbitrer."""
    base = []
    for e in ents:
        for v in {e["nom"], *e.get("variantes", [])}:
            if _ALPHA.search(v):
                base.append((v, e["uid"], 1))
        for p in e.get("parties", []):
            if p.get("actif") and p.get("portee") == "partout" and _ALPHA.search(p["texte"]):
                base.append((p["texte"], e["uid"], 1))
    base += _truncations(ents, base)
    glob = NameMatcher(base)
    ctx = {}
    for cx in PRIORITY:
        items = list(base)
        for e in ents:
            for p in e.get("parties", []):
                if p.get("actif") and p.get("portee") == "contextes" and _ALPHA.search(p["texte"]):
                    items.append((p["texte"], e["uid"], 0 if e["cat"] in PREFERRED[cx] else 2))
        ctx[cx] = NameMatcher(items)
    return glob, ctx


@dataclass
class Plan:
    by_uid: dict[str, dict[str, Any]]
    matcher: NameMatcher
    ctx_matchers: dict[str, NameMatcher]
    kept: list[dict[str, Any]]
    kept_matcher: NameMatcher
    soc_pseudo: str | None
    soc_sirens: frozenset[str]
    all_sirens: frozenset[str]
    replace_codes: bool = True

    @property
    def conflicts(self) -> list[dict[str, Any]]:
        names = {u: e["nom"] for u, e in self.by_uid.items()}
        out = [{"texte": " ".join(t), "entites": [names[k] for k in keys if k in names]}
               for t, keys in self.matcher.conflicts.items()]
        seen = {c["texte"] for c in out}
        for m in self.ctx_matchers.values():
            for t, keys in m.conflicts.items():
                if " ".join(t) not in seen:
                    seen.add(" ".join(t))
                    out.append({"texte": " ".join(t), "entites": [names[k] for k in keys if k in names]})
        return out


def build_plan(payload: dict[str, Any], replace_codes: bool = True) -> Plan:
    ents = [e for e in payload["entities"] if e.get("a_pseudonymiser") and not e.get("retired") and e.get("pseudo")]
    kept = [e for e in payload["entities"] if not e.get("a_pseudonymiser") and not e.get("retired")]

    def items(es):
        return [(v, e["uid"]) for e in es for v in {e["nom"], *e.get("variantes", [])} if _ALPHA.search(v)]
    soc = next((e for e in ents if e["cat"] == "SOC"), None)
    soc_sirens = frozenset(i[:9] for i in (soc or {}).get("ids", []) if len(i) >= 9)
    all_sirens = frozenset(i[:9] for e in payload["entities"] for i in e.get("ids", []) if len(i) >= 9) | soc_sirens
    glob, ctx = build_matchers(ents)
    return Plan({e["uid"]: e for e in ents}, glob, ctx, kept, NameMatcher(items(kept)),
                soc["pseudo"] if soc else None, soc_sirens, all_sirens, replace_codes)


@dataclass
class FileResult:
    output_name: str
    data: bytes
    lignes: int
    total_debit: str
    total_credit: str
    remplacements: dict[str, int]          # pseudonyme -> nombre de remplacements
    sensibles: dict[str, int]              # type -> nombre
    champs: dict[str, int]                 # champ -> nombre de cellules modifiées
    codes_remplaces: dict[str, int]
    non_cochees: list[dict[str, Any]]
    alertes: list[dict[str, str]]
    residuels: list[dict[str, Any]]
    prenoms: list[dict[str, Any]]
    sha256_entree: str = ""
    sha256_sortie: str = ""
    contextes: dict[str, int] = field(default_factory=dict)


class Pseudonymizer:
    def __init__(self, plan: Plan, whitelist: Whitelist | None = None):
        self.plan = plan
        self.whitelist = whitelist
        self.cache: dict[tuple, tuple[str, tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]]] = {}
        self.counts: Counter = Counter()
        self.kept_counts: Counter = Counter()
        self.fields: Counter = Counter()
        self.codes: Counter = Counter()
        self.unprocessed_codes = 0
        self.account_pseudos: dict[str, set[str]] = defaultdict(set)
        self.row_ctx: dict[tuple[str, str], str | None] = {}     # écriture -> contexte sensible (paie, provisions…)
        self.ctx_hits: Counter = Counter()

    # -- un texte
    def text(self, value: str, ctx: str | None = None) -> tuple[str, Counter, Counter]:
        p = self.plan
        if not value.strip() or value == '""':
            return value, Counter(), Counter()
        sens = redact.scan(value, p.all_sirens)
        names = (p.ctx_matchers.get(ctx) or p.matcher).find(value)
        kept = p.kept_matcher.find(value) if p.kept else []
        kc: Counter = Counter()
        for _, _, uid in kept:
            kc[uid] += 1
        if not sens and not names:
            return value, Counter(), kc
        spans: list[tuple[int, int, str, str]] = [(h.start, h.end, "S", h.kind) for h in sens]
        for a, b, uid in names:
            if not any(a < h.end and h.start < b for h in sens):
                spans.append((a, b, "N", uid))
        spans.sort()
        out, last, cnt = [], 0, Counter()
        for a, b, kind, v in spans:
            out.append(value[last:a])
            if kind == "S":
                digits = re.sub(r"\D", "", value[a:b])
                if v in ("SIREN", "SIRET") and p.soc_pseudo and digits[:9] in p.soc_sirens:
                    rep = p.soc_pseudo
                    cnt["E:" + rep] += 1
                else:
                    rep = redact.TOKENS[v]
                    cnt["S:" + v] += 1
            else:
                rep = p.by_uid[v]["pseudo"]
                cnt["E:" + rep] += 1
            out.append(rep)
            last = b
        out.append(value[last:])
        return "".join(out), cnt, kc

    def _cached(self, field_name: str, value: str, ctx: str | None = None):
        key = (field_name, value, ctx)
        hit = self.cache.get(key)
        if hit is None:
            new, cnt, kc = self.text(value, ctx)
            hit = self.cache[key] = (new, tuple(cnt.items()), tuple(kc.items()))
        return hit

    def entity_in(self, value: str) -> str | None:
        """Pseudonyme de l'entité citée dans le champ (le libellé peut porter une précision : « NOM (Lyon) »).
        Si plusieurs entités y figurent, la première est retenue."""
        s = value.strip()
        if not s:
            return None
        hits = self.plan.matcher.find(s)
        return self.plan.by_uid[hits[0][2]]["pseudo"] if hits else None

    # -- une ligne
    def row(self, r: list[str], cols: dict[str, int]) -> list[str]:
        new = list(r)
        ctx = self.row_ctx.get((r[cols["JournalCode"]].strip(), r[cols["EcritureNum"]].strip()))
        for f in TEXT_FIELDS:
            i = cols.get(f)
            if i is None:
                continue
            v = r[i]
            nv, cnt, kc = self._cached(f, v, ctx)
            if kc:
                for uid, n in kc:
                    self.kept_counts[uid] += n
            if cnt:
                new[i] = nv
                self.fields[f] += 1
                for k, n in cnt:
                    self.counts[k] += n
                    if ctx and k.startswith("E:"):
                        self.ctx_hits[ctx] += n
        if self.plan.replace_codes:
            self._codes(r, new, cols)
        cpt = r[cols["CompteNum"]].strip()
        if cpt[:3].isdigit():
            for f in ("CompAuxLib", "CompteLib"):
                i = cols.get(f)
                if i is not None:
                    for k, _ in self._cached(f, r[i])[1]:
                        if k.startswith("E:"):
                            self.account_pseudos[cpt].add(k[2:])
        return new

    def _codes(self, r: list[str], new: list[str], cols: dict[str, int]) -> None:
        ia, il, ic, icl = cols["CompAuxNum"], cols["CompAuxLib"], cols["CompteNum"], cols["CompteLib"]
        aux = r[ia].strip()
        if aux and _ALPHA.search(aux):
            pseudo = self.entity_in(r[il])
            if pseudo:
                new[ia] = compact(pseudo)
                self.codes["CompAuxNum"] += 1
            elif not self._kept_or_usual(r[il]):
                self.unprocessed_codes += 1
        cpt = r[ic].strip()
        if cpt and _ALPHA.search(cpt):
            pseudo = self.entity_in(r[icl])
            if pseudo:
                root = re.match(r"\d*", cpt).group()
                new[ic] = root + compact(pseudo)
                self.codes["CompteNum"] += 1
            elif not self._kept_or_usual(r[icl]):
                self.unprocessed_codes += 1

    def _kept_or_usual(self, label: str) -> bool:
        """Entité volontairement non pseudonymisée ou tiers usuel (liste blanche) : numéro laissé tel quel."""
        return bool(self.plan.kept_matcher.find(label)) or bool(self.whitelist and self.whitelist.matches(label.strip()))


def pseudonymize_fec(fec: FecFile, payload: dict[str, Any], code: str, replace_codes: bool = True,
                     whitelist: Whitelist | None = None, priority_prefixes: dict[str, list[str]] | None = None,
                     contexts: dict[str, list[str]] | None = None) -> FileResult:
    plan = build_plan(payload, replace_codes)
    if plan.conflicts:
        raise PseudonymizationError("Des conflits de variantes subsistent : résolvez-les à l'étape « Noms à valider ».")
    if not plan.by_uid:
        raise PseudonymizationError("Aucune entité à pseudonymiser : validez d'abord les noms.")
    prefixes = priority_prefixes or {}
    src_rep = analyse(fec, prefixes)
    if src_rep["bloquant"]:
        raise PseudonymizationError("Le FEC source présente des erreurs bloquantes.")
    cols = fec.fmt.columns
    wl0 = whitelist or Whitelist([])
    ps = Pseudonymizer(plan, wl0)
    protected = [cols[c] for c in PROTECTED if c in cols]
    accounts: dict[tuple[str, str], set[str]] = defaultdict(set)      # contexte sensible déterminé par écriture
    for r in fec.rows():
        accounts[(r[cols["JournalCode"]].strip(), r[cols["EcritureNum"]].strip())].add(r[cols["CompteNum"]].strip())
    ps.row_ctx = {k: main_context(contexts_for_accounts(v, contexts)) for k, v in accounts.items()}

    def rows():
        for r in fec.rows():
            nr = ps.row(r, cols)
            for i in protected:
                if nr[i] != r[i]:
                    raise PseudonymizationError("Une colonne protégée a été modifiée : traitement annulé.")
            yield nr

    data = fec.serialize(rows())
    out = parse_fec(data, "pseudo")
    out_rep = analyse(out, prefixes)
    if (out_rep["lignes"], out_rep["total_debit"], out_rep["total_credit"]) != (
            src_rep["lignes"], src_rep["total_debit"], src_rep["total_credit"]):
        raise PseudonymizationError("Contrôle bloquant : nombre de lignes ou totaux différents de la source.")

    # --- seconde passe sur la sortie
    from .generic_list import Whitelist as _W
    wl = whitelist or _W([])
    alertes, residuels, prenoms = second_pass(out, plan, payload, ps, prefixes, wl)
    non_cochees, usuels = [], []
    for e in plan.kept:
        n = ps.kept_counts.get(e["uid"], 0)
        if n:
            (usuels if wl0.matches(e["nom"]) else non_cochees).append(
                {"nom": e["nom"], "cat": e["cat"], "occurrences": n})
    if non_cochees:
        alertes.append({"level": "avertissement", "code": "NON_COCHEES",
                        "message": f"{len(non_cochees)} entité(s) non cochée(s) apparaissent en clair "
                                   f"({sum(x['occurrences'] for x in non_cochees)} occurrence(s)) : volontaire ?"})
    if usuels:
        alertes.append({"level": "info", "code": "TIERS_USUELS",
                        "message": f"{len(usuels)} tiers usuel(s) maintenu(s) en clair (liste blanche)."})
    if not plan.soc_pseudo:
        alertes.append({"level": "avertissement", "code": "SOC_ABSENTE",
                        "message": "La société n'est pas identifiée : sa raison sociale n'a pas été remplacée."})
    if ps.unprocessed_codes:
        alertes.append({"level": "avertissement", "code": "NUMEROS_NON_TRAITES",
                        "message": f"{ps.unprocessed_codes} numéro(s) de compte contenant des lettres n'ont pas pu être rattachés à une entité."})
    n_sal = len({k[2:] for k in ps.counts if k.startswith("E:SAL-")})
    if 0 < n_sal <= 2:
        alertes.append({"level": "avertissement", "code": "PEU_DE_SALARIES",
                        "message": f"Seulement {n_sal} salarié(s) pseudonymisé(s) : identifiables par le montant des salaires."})
    class_of = {p: cls for cls, lst in prefixes.items() for p in lst}
    uniques = [(acc, next(iter(ps_))) for acc, ps_ in sorted(ps.account_pseudos.items())
               if len(ps_) == 1 and class_of.get(acc[:3]) not in (None, "tiers_commerciaux")]
    if uniques:
        listed = ", ".join(f"{acc} ({pseudo})" for acc, pseudo in uniques[:8]) + (" …" if len(uniques) > 8 else "")
        alertes.append({"level": "info", "code": "TIERS_UNIQUE",
                        "message": f"{len(uniques)} compte(s) ne portent qu'un seul tiers, identifiable par le montant : {listed}."})
    return FileResult(
        output_name="", data=data, lignes=src_rep["lignes"], total_debit=src_rep["total_debit"],
        total_credit=src_rep["total_credit"],
        remplacements={k[2:]: n for k, n in sorted(ps.counts.items()) if k.startswith("E:")},
        sensibles={k[2:]: n for k, n in sorted(ps.counts.items()) if k.startswith("S:")},
        champs=dict(ps.fields), codes_remplaces=dict(ps.codes), non_cochees=non_cochees, alertes=alertes,
        residuels=residuels, prenoms=prenoms, sha256_entree=fec.sha256, sha256_sortie=out.sha256,
        contextes=dict(ps.ctx_hits))


def second_pass(out: FecFile, plan: Plan, payload: dict[str, Any], ps: Pseudonymizer,
                prefixes: dict[str, list[str]], whitelist: Whitelist):
    """Relit la SORTIE : noms restants, prénoms/noms isolés, noms propres inconnus. Affichage local uniquement."""
    cols = out.fmt.columns
    alertes: list[dict[str, str]] = []
    values: Counter = Counter()
    for r in out.rows():
        for f in TEXT_FIELDS:
            i = cols.get(f)
            if i is not None and r[i].strip():
                values[r[i]] += 1
    # 1. une entité pseudonymisée dont une variante subsiste = défaut grave
    left = 0
    for v, n in values.items():
        left += len(plan.matcher.find(v)) * n
    if left:
        alertes.append({"level": "erreur", "code": "RESTES",
                        "message": f"{left} occurrence(s) d'entités pseudonymisées subsistent dans la sortie : à examiner."})
    # 2. prénoms / noms isolés des personnes pseudonymisées
    tok_count: Counter = Counter()
    for v, n in values.items():
        for t in set(tokens(v)):
            tok_count[t] += n
    prenoms = []
    for e in plan.by_uid.values():
        if e["cat"] not in ("SAL", "ASS"):
            continue
        toks = [t for t in tokens(e["nom"]) if len(t) >= 3 and t not in LEGAL_FORMS and t not in LINK_WORDS
                and t not in STOPWORDS]
        if len(toks) < 2:
            continue
        for t in toks:
            if tok_count.get(t):
                prenoms.append({"mot": t, "occurrences": tok_count[t], "pseudo": e["pseudo"]})
    prenoms.sort(key=lambda x: -x["occurrences"])
    # 3. noms propres inconnus (heuristiques) dans la sortie
    res = detect([out], {"entities": []}, prefixes, whitelist)
    residuels = []
    for c in res.candidates:
        if c.source != "libelle" or c.confiance == "faible" or PSEUDO_RE.match(c.nom.replace(" ", "")):
            continue
        if all(t in {"frn", "cli", "sal", "ass", "grp", "soc", "tie"} or t in STOPWORDS for t in tokens(c.nom)):
            continue
        residuels.append({"texte": c.nom, "occurrences": c.occurrences, "confiance": c.confiance,
                          "exemple": c.exemples[0] if c.exemples else ""})
    residuels.sort(key=lambda x: -x["occurrences"])
    if prenoms:
        alertes.append({"level": "avertissement", "code": "PRENOMS_ISOLES",
                        "message": f"{len(prenoms)} prénom(s) ou nom(s) isolé(s) de personnes pseudonymisées subsistent seuls."})
    if residuels:
        alertes.append({"level": "avertissement", "code": "NOMS_RESIDUELS",
                        "message": f"{len(residuels)} nom(s) propre(s) potentiel(s) non pseudonymisé(s) à examiner."})
    return alertes, residuels[:60], prenoms[:40]
