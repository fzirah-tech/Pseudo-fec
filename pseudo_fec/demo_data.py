"""Générateur de FEC SYNTHÉTIQUES (aucune donnée réelle : toutes les entités sont fictives).

Utilisé par les tests ET par le mode démonstration de l'application.

Styles :
- "standard"  : norme A47 A-1 (dates AAAAMMJJ, tiers en comptes auxiliaires) ;
- "cabinet"   : reproduit les particularités observées sur un export réel
                (CRLF, 8 bits, en-têtes « ␣Debit␣ », EcritureDate JJ/MM/AAAA,
                montants « 1 234,56 », « - » pour zéro, salariés en 421 individualisés) ;
- "pennylane" : reproduit un export Pennylane réel (UTF-8 sans BOM, LF, dates AAAAMMJJ,
                un seul 401/411 général, tiers en CompAuxNum/CompAuxLib, CompAuxNum
                incrustant le nom, valeur "" littérale dans EcritureLib) ;
- "compte_individualise" : tiers individualisés en compte général (ex. 401DUPBAT),
                CompteLib = nom, sans auxiliaire (cas à gérer selon le logiciel).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import Decimal

from pseudo_fec.fec_io import CANON

SIREN = "732829320"  # Luhn valide, fictif

ENTITE = "ATELIERS DU PORT SAS"
SIGLE = "ADP"
DIRIGEANT = "Claire BERNARD-MOREAU"
ASSOCIE = "Paul Henri DESCHAMPS"
MERE = "HOLDING DESCHAMPS SAS"
SCI = "SCI LES TILLEULS"
FOURNISSEURS = [("DUPONT BATIMENT SARL", "DUPBAT"), ("MARTINEZ ET FILS", "MARTIN"),
                ("MARTIN", "MARTI2"), ("Boulangerie ROSE", "ROSE"),
                ("ÉTABLISSEMENTS LEFÈVRE-DUBOIS", "LEFDUB"), ("ORANGE", "ORANGE"), ("URSSAF", "URSSAF")]
CLIENTS = [("Société DURAND & ASSOCIÉS", "DURAND"), ("Mme Zoé N'GUYEN", "NGUYEN"), ("ŒUVRES DU SUD SARL", "OEUVRE")]
SALARIES = ["Karim BENALI", "Sophie MARTIN", "Jean-Pierre LEFEBVRE", "Aïcha BOUSSAC-NEVEU"]
SALARIE_HORS_COMPTES = "Bruno VASSEUR"      # n'apparaît que dans des libellés de paie (aucun compte individualisé)
IBAN = "FR7630006000011234567890189"

REAL_NAMES = [ENTITE, DIRIGEANT, ASSOCIE, MERE, SCI, *[f[0] for f in FOURNISSEURS if f[0] not in ("ORANGE", "URSSAF")],
              *[c[0] for c in CLIENTS], *SALARIES, SALARIE_HORS_COMPTES]


@dataclass
class Synth:
    data: bytes
    filename: str
    style: str
    year: int
    n_lines: int
    total: Decimal
    names: list[str] = field(default_factory=lambda: list(REAL_NAMES))


def _amt(v: Decimal, style: str, thousands: bool) -> str:
    if style == "cabinet":
        if v == 0:
            return "-"
        s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
        return s
    return f"{v:.2f}".replace(".", ",")


def make_fec(style: str = "standard", encoding: str = "utf-8", year: int = 2024, seed: int = 7,
             bom: bool = False, sep: str = "\t", n_entries: int = 60,
             tva_suffix: bool = False) -> Synth:
    rnd = random.Random(seed + year)
    cabinet = style == "cabinet"
    penny = style == "compte_individualise"
    pl = style == "pennylane"
    lines: list[list[str]] = []
    num = [0]
    i_cur = [0]

    def date(m: int, d: int) -> tuple[str, str]:
        ymd = f"{year}{m:02d}{d:02d}"
        return (f"{d:02d}/{m:02d}/{year}" if cabinet else ymd), ymd

    def add(journal: str, jlib: str, m: int, d: int, cpt: str, cptlib: str, aux: str, auxlib: str,
            piece: str, lib: str, debit: Decimal, credit: Decimal, let: str = "") -> None:
        ed, pd = date(m, d)
        lines.append([journal, jlib, str(num[0]), ed, cpt, cptlib, aux, auxlib, piece, pd, lib,
                      _amt(debit, style, True), _amt(credit, style, True), let, "", pd, "", ""])

    def tiers(prefix: str, name: str, code: str) -> tuple[str, str, str, str]:
        if penny:
            return f"{prefix}{code}", name, "", ""
        if pl:
            aux = f"{prefix}{code}" if i_cur[0] % 2 else str(rnd.randint(10000, 99999))
            return prefix, "Fournisseurs" if prefix == "401" else "Clients", aux, name
        if cabinet:
            return f"{prefix}000000", "Fournisseurs" if prefix == "401" else "Clients", f"{rnd.randint(1, 99)}{code}", name
        return f"{prefix}000", "Fournisseurs" if prefix == "401" else "Clients", ("F" if prefix == "401" else "C") + code, name

    for i in range(n_entries):
        num[0] += 1
        i_cur[0] = i
        m, d = 1 + i % 12, 1 + (i * 3) % 27
        kind = i % 6
        ht = Decimal(rnd.randint(100, 9000)) + Decimal(rnd.randint(0, 99)) / 100
        tva = (ht * Decimal("0.2")).quantize(Decimal("0.01"))
        ttc = ht + tva
        if kind in (0, 1):  # achat
            nm, code = FOURNISSEURS[i % len(FOURNISSEURS)]
            c, cl, a, al = tiers("401", nm, code)
            lib = f"FACT 2024-{i:03d} {nm}" if i % 2 else f"{nm} fact {i}"
            add("ACH", "Achats", m, d, "607000", "Achats de marchandises", "", "", f"FA{i:04d}", lib, ht, Decimal(0))
            add("ACH", "Achats", m, d, "445660", "TVA déductible", "", "", f"FA{i:04d}", lib, tva, Decimal(0))
            add("ACH", "Achats", m, d, c, cl, a, al, f"FA{i:04d}", lib, Decimal(0), ttc, "AA")
        elif kind == 2:  # vente
            nm, code = CLIENTS[i % len(CLIENTS)]
            c, cl, a, al = tiers("411", nm, code)
            lib = f"Facture client {nm}"
            add("VEN", "Ventes", m, d, c, cl, a, al, f"FV{i:04d}", lib, ttc, Decimal(0))
            add("VEN", "Ventes", m, d, "706000", "Prestations de services", "", "", f"FV{i:04d}", lib, Decimal(0), ht)
            add("VEN", "Ventes", m, d, "445710", "TVA collectée", "", "", f"FV{i:04d}", lib, Decimal(0), tva)
        elif kind == 3:  # paie
            sal = SALARIES[(i // 6) % len(SALARIES)]
            net = ht
            if cabinet or penny:
                cpt, cl = (f"421{SALARIES.index(sal) + 1:06d}" if cabinet else f"421{sal.split()[-1][:5].upper()}"), sal
            else:
                cpt, cl = "421000", "Personnel - rémunérations dues"
            lib = f"SALAIRE {m:02d}/{year} {sal}" if i % 2 else f"Paie {sal}"
            add("OD", "Opérations diverses", m, 28, "641000", "Rémunérations du personnel", "", "", f"PAIE{m:02d}", lib, net, Decimal(0))
            add("OD", "Opérations diverses", m, 28, cpt, cl, "", "", f"PAIE{m:02d}", lib, Decimal(0), net)
        elif kind == 4:  # opérations avec groupe / associé
            lib = rnd.choice([f"REFACT {ENTITE}", f"PRET {SCI}", f"CCA {ASSOCIE}", f"Intérêts {DIRIGEANT}",
                              f"Avance {MERE}", f"Remb. ADP {SIGLE}"])
            add("OD", "Opérations diverses", m, d, "455000" if not (cabinet or penny) else "455000",
                f"Associé - {ASSOCIE}", "", "", f"OD{i:04d}", lib, ht, Decimal(0))
            add("OD", "Opérations diverses", m, d, "451000", f"Groupe - {MERE}", "", "", f"OD{i:04d}", lib, Decimal(0), ht)
            if i % 12 == 4:
                add("OD", "Opérations diverses", m, d, "261000", f"Titres {SCI}", "", "", f"OD{i:04d}", lib, ht, Decimal(0))
                add("OD", "Opérations diverses", m, d, "512000", "Banque", "", "", f"OD{i:04d}", lib, Decimal(0), ht)
        elif i % 12 == 11:  # paiement de salaire par virement (NOM Prénom)
            sal = SALARIES[(i // 12) % len(SALARIES)]
            first, last = sal.split()[0], sal.split()[-1]
            cpt, cl = ((f"421{SALARIES.index(sal) + 1:06d}", sal) if cabinet else
                       (f"421{last[:5].upper()}", sal) if penny else ("421000", "Personnel - rémunérations dues"))
            lib = f"VIR SALAIRE {last} {first}"
            add("BQ", "Banque", m, d, cpt, cl, "", "", f"BQ{i:04d}", lib, ht, Decimal(0))
            add("BQ", "Banque", m, d, "512000", "Banque", "", "", f"BQ{i:04d}", lib, Decimal(0), ht)
        else:  # banque avec IBAN
            nm, code = FOURNISSEURS[(i + 1) % len(FOURNISSEURS)]
            c, cl, a, al = tiers("401", nm, code)
            lib = f"VIR SEPA {nm} IBAN {IBAN} REF {i:05d}"
            add("BQ", "Banque", m, d, c, cl, a, al, f"BQ{i:04d}", lib, ttc, Decimal(0), "AA")
            add("BQ", "Banque", m, d, "512000", "Banque", "", "", f"BQ{i:04d}", lib, Decimal(0), ttc)

    def sal_account(sal: str) -> tuple[str, str]:
        if cabinet:
            return f"421{SALARIES.index(sal) + 1:06d}", sal
        if penny:
            return f"421{sal.split()[-1][:5].upper()}", sal
        return "421000", "Personnel - rémunérations dues"

    # --- écritures « sensibles » : paie, provisions, comptes courants. Les libellés ne citent souvent qu'UN mot du nom
    for j in range(24):
        num[0] += 1
        m, d = 1 + j % 12, 2 + (j * 5) % 25
        amt = Decimal(rnd.randint(100, 5000)) + Decimal(rnd.randint(0, 99)) / 100
        sal = SALARIES[j % len(SALARIES)]
        first, last = sal.split()[0], sal.split()[-1]
        kind = j % 6
        if kind in (0, 1):                        # paie : nom de famille seul, ou prénom seul
            lib = f"SALAIRES {m:02d}/{year} {last}" if kind == 0 else f"ACOMPTE {first}"
            c, cl = sal_account(sal)
            add("OD", "Opérations diverses", m, d, "641000", "Rémunérations du personnel", "", "", f"PAIE{j:02d}", lib, amt, Decimal(0))
            add("OD", "Opérations diverses", m, d, c, cl, "", "", f"PAIE{j:02d}", lib, Decimal(0), amt)
        elif kind == 2:                           # paie : salarié sans compte individualisé
            lib = f"NET A PAYER {SALARIE_HORS_COMPTES.split()[-1]}"
            add("OD", "Opérations diverses", m, d, "641000", "Rémunérations du personnel", "", "", f"PAIE{j:02d}", lib, amt, Decimal(0))
            add("OD", "Opérations diverses", m, d, "421000", "Personnel - rémunérations dues", "", "", f"PAIE{j:02d}", lib, Decimal(0), amt)
        elif kind == 3:                           # provisions
            lib = rnd.choice([f"PROVISION CONGES PAYES {last}", "PROV LITIGE TILLEULS", "DEPRECIATION CREANCE DURAND"])
            add("OD", "Opérations diverses", m, d, "681500", "Dotations aux provisions", "", "", f"PRV{j:02d}", lib, amt, Decimal(0))
            add("OD", "Opérations diverses", m, d, "151000", "Provisions pour risques", "", "", f"PRV{j:02d}", lib, Decimal(0), amt)
        elif kind == 4:                           # compte courant : nom partiel de l'associé / de la société liée
            lib = rnd.choice(["CCA DESCHAMPS", "REMB CCA TILLEULS", "AVANCE DESCHAMPS"])
            add("OD", "Opérations diverses", m, d, "455000", f"Associé - {ASSOCIE}", "", "", f"CC{j:02d}", lib, amt, Decimal(0))
            add("OD", "Opérations diverses", m, d, "512000", "Banque", "", "", f"CC{j:02d}", lib, Decimal(0), amt)
        else:                                     # virement de salaire : nom de famille seul (écriture de paie côté 421)
            lib = f"VIR {last}"
            c, cl = sal_account(sal)
            add("BQ", "Banque", m, d, c, cl, "", "", f"BQ{j:02d}S", lib, amt, Decimal(0))
            add("BQ", "Banque", m, d, "512000", "Banque", "", "", f"BQ{j:02d}S", lib, Decimal(0), amt)

    if tva_suffix:  # variante Pennylane « avec suffixes de TVA » : comptes de 12 chiffres, taux dans CompteLib
        for r in lines:
            if r[4][:3] in ("607", "706", "445", "625") and len(r[4]) == 6:
                r[4] += "002000"
                r[5] += " 20%"
    if pl:
        for r in lines:
            if r[0] == "OD" and int(r[2]) % 2 == 1 and r[4][:3] in ("455", "451", "261"):
                r[10] = '""'
    header = list(CANON)
    if cabinet:
        header[header.index("Debit")], header[header.index("Credit")] = " Debit ", " Credit "
    nl = "\r\n" if cabinet else "\n"
    text = nl.join(sep.join(r) for r in [header, *lines]) + nl
    data = text.encode(encoding)
    if bom:
        data = b"\xef\xbb\xbf" + data
    total = sum((Decimal(r[11].replace(" ", "").replace("-", "0").replace(",", ".")) for r in lines), Decimal(0))
    return Synth(data, f"{SIREN}FEC{year}1231.txt", style, year, len(lines), total)


DEMO_FICHE = {
    "societe": {"raison_sociale": ENTITE, "sigle": SIGLE, "nom_commercial": "", "siren": SIREN, "variantes": ["Ateliers du Port"], "sirets": []},
    "personnes": [{"nom": DIRIGEANT, "role": "dirigeant"}, {"nom": ASSOCIE, "role": "associe"}],
    "liees": [{"raison_sociale": MERE, "lien": "mere"}, {"raison_sociale": SCI, "lien": "sci"}],
}
DEMO_STYLES = {"cabinet": ("cp1252", "Style cabinet (CRLF, 8 bits, dates JJ/MM/AAAA, salariés en 421)"),
               "pennylane": ("utf-8", "Style Pennylane (UTF-8, tiers en auxiliaire)"),
               "standard": ("utf-8", "Style norme A47 A-1 (AAAAMMJJ)"),
               "compte_individualise": ("utf-8", "Tiers individualisés en compte général")}
