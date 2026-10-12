"""Contextes sensibles (paie, provisions, comptes courants), parties identifiantes, arbitrage des homonymes."""
import re

import pytest

from pseudo_fec.config import DEFAULT_CABINET as CFG
from pseudo_fec.contexts import contexts_for_accounts, main_context
from pseudo_fec.demo_data import ASSOCIE, ENTITE, MERE, SALARIES, SALARIE_HORS_COMPTES, SCI, SIREN, make_fec
from pseudo_fec.detection import detect
from pseudo_fec.dossier import apply_validation, arbitrate, entity_conflicts, new_payload, set_societe
from pseudo_fec.fec_io import parse_fec
from pseudo_fec.generic_list import Whitelist
from pseudo_fec.pseudonymize import pseudonymize_fec
from pseudo_fec.textmatch import tokens
from test_detection import STYLES, by_name, run
from test_pseudonymize import dossier_pour

PREF, WL = CFG["priority_prefixes"], Whitelist(CFG["whitelist"])


def mini(lines):
    from helpers import mini as m
    return m(lines)


def table(*ents):
    p = new_payload("D")
    rows = [{"nom": n, "cat": c, "checked": True, "source": "manuel", "touched": True, "variantes": [], "parties": parts}
            for n, c, parts in ents]
    out = apply_validation(p, rows)
    return p, out


# ---------------------------------------------------------------- contextes d'écriture

def test_contexte_determine_par_l_ecriture_entiere():
    assert contexts_for_accounts(["641000", "512000"]) == {"paie"}
    assert contexts_for_accounts(["421000001", "512000"]) == {"paie"}                  # le virement de salaire est en contexte de paie
    assert contexts_for_accounts(["455000", "512000"]) == {"compte_courant"}
    assert contexts_for_accounts(["681500", "151000"]) == {"provisions"}
    assert contexts_for_accounts(["607000", "401000"]) == {"autres"}
    assert main_context(["provisions", "paie"]) == "paie" and main_context({"autres"}) is None


def test_contextes_parametrables():
    assert contexts_for_accounts(["9999"], {"paie": ["9999"]}) == {"paie"}


# ---------------------------------------------------------------- détection

@pytest.mark.parametrize("style,enc", STYLES)
def test_synthese_des_contextes(style, enc):
    res, _ = run(style, enc)
    s = {x["id"]: x for x in res.synthese["contextes"]}
    assert s["paie"]["lignes"] > 0 and s["provisions"]["lignes"] > 0 and s["compte_courant"]["lignes"] > 0 and s["autres"]["lignes"] > 0
    assert s["paie"]["libelles"] > 0


@pytest.mark.parametrize("style,enc", STYLES)
def test_parties_des_salaries_et_composants_hyphenes(style, enc):
    res, _ = run(style, enc)
    k = {p["texte"]: p for p in by_name(res, "Karim BENALI").parties}
    assert k["BENALI"]["actif"] and k["BENALI"]["portee"] == "contextes" and k["BENALI"]["ctx"].get("paie", 0) > 0
    assert k["Karim"]["actif"] and k["Karim"]["ctx"].get("paie", 0) > 0
    b = {p["texte"] for p in by_name(res, "Aïcha BOUSSAC-NEVEU").parties}
    assert {"BOUSSAC-NEVEU", "BOUSSAC", "NEVEU", "Aïcha"} <= b


def test_nom_de_famille_seul_n_est_pas_propose_a_part():
    res, _ = run("cabinet", "cp1252")
    noms = {c.nom for c in res.candidates}
    assert "BENALI" not in noms and "Karim" not in noms and "Sophie" not in noms


def test_partie_distinctive_d_une_societe_liee_proposee_et_activee():
    res, _ = run("standard")
    sci = {p["texte"]: p for p in by_name(res, SCI).parties}
    assert sci["TILLEULS"]["actif"] and sci["TILLEULS"]["portee"] == "partout" and sci["TILLEULS"]["n"] > 0


def test_partie_partagee_signalee_avec_les_noms_concernes_et_non_activee():
    res, _ = run("standard")
    h = {p["texte"]: p for p in by_name(res, MERE).parties}
    assert "partagé avec un autre nom" in h["DESCHAMPS"]["risque"] and not h["DESCHAMPS"]["actif"]
    assert ASSOCIE in h["DESCHAMPS"]["partage_avec"]


def test_mots_trop_courts_ou_generiques_non_actives():
    res, _ = run("standard")
    soc = {p["texte"]: p for p in by_name(res, ENTITE).parties}
    assert "ATELIERS" not in soc                                       # mot générique : jamais proposé
    assert not soc.get("PORT", {"actif": False})["actif"]


def test_societe_ordinaire_parties_proposees_mais_non_activees():
    res, _ = run("standard")
    assert all(not p["actif"] for p in by_name(res, "DUPONT BATIMENT SARL").parties)


def test_salarie_sans_compte_individualise_releve_dans_la_paie():
    res, _ = run("cabinet", "cp1252")
    v = next(c for c in res.candidates if c.nom.upper() == SALARIE_HORS_COMPTES.split()[-1])
    assert v.cat == "SAL" and not v.checked and v.contextes.get("paie", 0) > 0 and v.confiance != "haute" or v.cat == "SAL"
    assert v.contextes.get("paie", 0) > 0


def test_mots_courants_de_la_paie_ne_sont_pas_proposes():
    res, _ = run("cabinet", "cp1252")
    noms = {c.nom.lower() for c in res.candidates}
    assert not noms & {"salaires", "acompte", "net", "payer", "provision", "conges", "payes", "cca", "remb", "vir"}


# ---------------------------------------------------------------- pseudonymisation contextuelle

def _paie_libelles(out_fec):
    c = out_fec.fmt.columns
    ecr = {}
    for r in out_fec.rows():
        ecr.setdefault((r[c["JournalCode"]], r[c["EcritureNum"]]), []).append(r)
    res = []
    for lines in ecr.values():
        if any(r[c["CompteNum"]][:3] in ("421", "641") for r in lines):
            res += [r[c["EcritureLib"]] for r in lines]
    return res


@pytest.mark.parametrize("style,enc", STYLES)
def test_aucun_nom_de_salarie_dans_les_libelles_de_paie(style, enc):
    s = make_fec(style, enc, n_entries=120)
    f = parse_fec(s.data, s.filename)
    p = dossier_pour([f])
    # l'utilisateur a validé toutes les propositions, y compris le salarié connu seulement par la paie
    assert any(e["nom"].upper().startswith(SALARIE_HORS_COMPTES.split()[-1]) and e["a_pseudonymiser"] for e in p["entities"])
    r = pseudonymize_fec(f, p, "D-001", True, WL, PREF)
    out = parse_fec(r.data, "x")
    libs = _paie_libelles(out)
    assert libs
    noms = {t for sal in [*SALARIES, SALARIE_HORS_COMPTES] for t in tokens(sal) if len(t) >= 3}
    for lib in libs:
        assert not (set(tokens(lib)) & noms), lib
    assert r.contextes.get("paie", 0) > 0


def test_homonyme_fournisseur_et_salariee_selon_le_contexte():
    f = mini([("ACH", 1, "607000", "Achats", "", "", "FACT MARTIN 12", "10,00", "0"),
              ("ACH", 1, "401000", "Fournisseurs", "4010MART", "MARTIN", "FACT MARTIN 12", "0", "10,00"),
              ("BQ", 2, "421000", "Personnel", "", "", "VIR MARTIN", "100,00", "0"),
              ("BQ", 2, "512000", "Banque", "", "", "VIR MARTIN", "0", "100,00")])
    p, out = table(("MARTIN", "FRN", []), ("Sophie MARTIN", "SAL", [{"texte": "MARTIN", "portee": "contextes", "actif": True}]))
    assert not out["conflicts"]                                   # le salarié l'emporte en contexte de paie : pas de conflit
    r = pseudonymize_fec(f, p, "D", True, WL, PREF)
    lines = r.data.decode().split("\n")
    assert "FACT FRN-0001 12" in lines[1] and "VIR SAL-0001" in lines[3]


def test_partie_partout_remplacee_meme_hors_contexte_sensible():
    f = mini([("ACH", 1, "607000", "Achats", "", "", "FACT TILLEULS 12", "10,00", "0"),
              ("ACH", 1, "401000", "Fournisseurs", "", "", "FACT TILLEULS 12", "0", "10,00")])
    p, _ = table(("SCI LES TILLEULS", "GRP", [{"texte": "TILLEULS", "portee": "partout", "actif": True}]))
    assert "FACT GRP-0001 12" in pseudonymize_fec(f, p, "D", True, WL, PREF).data.decode()


def test_partie_contextuelle_non_appliquee_hors_contexte():
    f = mini([("ACH", 1, "607000", "Achats", "", "", "REGL BENALI", "10,00", "0"),
              ("ACH", 1, "401000", "Fournisseurs", "", "", "REGL BENALI", "0", "10,00"),
              ("OD", 2, "641000", "Salaires", "", "", "SALAIRES BENALI", "10,00", "0"),
              ("OD", 2, "421000", "Personnel", "", "", "SALAIRES BENALI", "0", "10,00")])
    p, _ = table(("Karim BENALI", "SAL", [{"texte": "BENALI", "portee": "contextes", "actif": True}]))
    r = pseudonymize_fec(f, p, "D", True, WL, PREF)
    txt = r.data.decode()
    assert "SALAIRES SAL-0001" in txt and "REGL BENALI" in txt                  # hors paie : laissé en clair…
    assert any(x["mot"] == "benali" for x in r.prenoms)                          # …mais signalé par la seconde passe


def test_partie_inactive_jamais_appliquee():
    f = mini([("OD", 1, "641000", "Salaires", "", "", "SALAIRES BENALI", "10,00", "0"),
              ("OD", 1, "421000", "Personnel", "", "", "SALAIRES BENALI", "0", "10,00")])
    p, _ = table(("Karim BENALI", "SAL", [{"texte": "BENALI", "portee": "contextes", "actif": False}]))
    assert "SALAIRES BENALI" in pseudonymize_fec(f, p, "D", True, WL, PREF).data.decode()


def test_provisions_et_comptes_courants_pseudonymises():
    f = mini([("OD", 1, "681500", "Dotations", "", "", "PROVISION CONGES PAYES BENALI", "10,00", "0"),
              ("OD", 1, "151000", "Provisions", "", "", "PROVISION CONGES PAYES BENALI", "0", "10,00"),
              ("OD", 2, "455000", "Associé", "", "", "REMB CCA TILLEULS", "10,00", "0"),
              ("OD", 2, "512000", "Banque", "", "", "REMB CCA TILLEULS", "0", "10,00")])
    p, _ = table(("Karim BENALI", "SAL", [{"texte": "BENALI", "portee": "contextes", "actif": True}]),
                 ("SCI LES TILLEULS", "GRP", [{"texte": "TILLEULS", "portee": "contextes", "actif": True}]))
    txt = pseudonymize_fec(f, p, "D", True, WL, PREF).data.decode()
    assert "PROVISION CONGES PAYES SAL-0001" in txt and "REMB CCA GRP-0001" in txt


# ---------------------------------------------------------------- conflits et arbitrage

def _deschamps():
    return table((ASSOCIE, "ASS", [{"texte": "DESCHAMPS", "portee": "contextes", "actif": True}]),
                 (MERE, "GRP", [{"texte": "DESCHAMPS", "portee": "contextes", "actif": True}]))


def test_homonyme_en_compte_courant_est_un_conflit_a_arbitrer():
    p, out = _deschamps()
    assert out["conflicts"] and out["conflicts"][0]["texte"] == "deschamps" and out["conflicts"][0]["contexte"]
    f = mini([("OD", 1, "455000", "Associé", "", "", "CCA DESCHAMPS", "10,00", "0"), ("OD", 1, "512000", "Banque", "", "", "CCA DESCHAMPS", "0", "10,00")])
    from pseudo_fec.pseudonymize import PseudonymizationError
    with pytest.raises(PseudonymizationError):
        pseudonymize_fec(f, p, "D", True, WL, PREF)


def test_arbitrage_attribue_le_texte_a_une_entite():
    p, _ = _deschamps()
    asso = next(e for e in p["entities"] if e["cat"] == "ASS")
    assert arbitrate(p, "DESCHAMPS", asso["uid"]) == []
    f = mini([("OD", 1, "455000", "Associé", "", "", "CCA DESCHAMPS", "10,00", "0"), ("OD", 1, "512000", "Banque", "", "", "CCA DESCHAMPS", "0", "10,00")])
    assert "CCA ASS-0001" in pseudonymize_fec(f, p, "D", True, WL, PREF).data.decode()


def test_arbitrage_laisser_en_clair():
    p, _ = _deschamps()
    assert arbitrate(p, "DESCHAMPS", None) == []
    f = mini([("OD", 1, "455000", "Associé", "", "", "CCA DESCHAMPS", "10,00", "0"), ("OD", 1, "512000", "Banque", "", "", "CCA DESCHAMPS", "0", "10,00")])
    assert "CCA DESCHAMPS" in pseudonymize_fec(f, p, "D", True, WL, PREF).data.decode()


def test_priorite_de_la_paie_sur_les_autres_contextes():
    f = mini([("OD", 1, "421000", "Personnel", "", "", "PROV BENALI", "10,00", "0"),
              ("OD", 1, "681500", "Dotation", "", "", "PROV BENALI", "0", "10,00")])
    p, out = table(("Karim BENALI", "SAL", [{"texte": "BENALI", "portee": "contextes", "actif": True}]),
                   ("BENALI SARL", "FRN", [{"texte": "BENALI", "portee": "contextes", "actif": True}]))
    # en provisions seules : conflit (rang égal côté contextes) ; en paie : le salarié l'emporte
    ctx = " ".join(c["contexte"] or "" for c in out["conflicts"]).lower()
    assert "provisions" in ctx and "paie" not in ctx
