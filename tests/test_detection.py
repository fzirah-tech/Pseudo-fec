import pytest

from pseudo_fec import redact
from pseudo_fec.config import DEFAULT_CABINET as CFG
from pseudo_fec.detection import detect
from pseudo_fec.dossier import apply_fiche, new_payload
from pseudo_fec.fec_io import CANON, parse_fec
from pseudo_fec.generic_list import Whitelist
from synth import SIREN, make_fec

PREF, WL = CFG["priority_prefixes"], Whitelist(CFG["whitelist"])
FICHE = {"societe": {"raison_sociale": "ATELIERS DU PORT SAS", "sigle": "ADP", "siren": SIREN},
         "personnes": [{"nom": "Claire BERNARD-MOREAU", "role": "dirigeant"},
                       {"nom": "Paul Henri DESCHAMPS", "role": "associe"}],
         "liees": [{"raison_sociale": "HOLDING DESCHAMPS SAS", "lien": "mere"},
                   {"raison_sociale": "SCI LES TILLEULS", "lien": "sci"}]}
STYLES = [("standard", "utf-8"), ("cabinet", "cp1252"), ("pennylane", "utf-8"), ("compte_individualise", "utf-8")]


def run(style="standard", enc="utf-8", fiche=True, **kw):
    s = make_fec(style, enc, n_entries=120, **kw)
    p = new_payload("D-001")
    if fiche:
        apply_fiche(p, FICHE)
    return detect([parse_fec(s.data, s.filename)], p, PREF, WL), p


def by_name(res, nom):
    return next(c for c in res.candidates if c.nom == nom)


@pytest.mark.parametrize("style,enc", STYLES)
def test_tiers_commerciaux_proposes_et_coches(style, enc):
    res, _ = run(style, enc)
    for nom in ("DUPONT BATIMENT SARL", "MARTINEZ ET FILS", "Boulangerie ROSE", "MARTIN"):
        c = by_name(res, nom)
        assert c.checked and c.statut == "nouveau" and c.cat == "FRN", nom
    assert by_name(res, "ŒUVRES DU SUD SARL").cat == "CLI"


@pytest.mark.parametrize("style,enc", STYLES)
def test_liste_blanche_non_cochee(style, enc):
    res, _ = run(style, enc)
    c = by_name(res, "ORANGE")
    assert c.statut == "liste_blanche" and not c.checked and c.liste_blanche == "ORANGE"


@pytest.mark.parametrize("style,enc", STYLES)
def test_salaries_detectes_dans_comptes_et_libelles(style, enc):
    res, _ = run(style, enc)
    sal = {c.nom for c in res.candidates if c.cat == "SAL" and c.checked}
    assert {"Karim BENALI", "Jean-Pierre LEFEBVRE"} <= sal
    assert any("MARTIN" in n and "Sophie" in n for n in sal)       # homonyme du fournisseur MARTIN


def test_salarie_homonyme_de_fournisseur_propose_en_entier():
    res, _ = run("standard")
    noms = {c.nom for c in res.candidates}
    assert "Sophie MARTIN" in noms and "MARTIN Sophie" in noms and "MARTIN" in noms
    # pas de candidat « Sophie » seul : le prénom ne doit pas rester en clair
    assert "Sophie" not in noms
    assert any("Recoupement" in n for n in by_name(res, "MARTIN").notes)


def test_variantes_d_ordre_proposees_en_fusion_jamais_appliquees():
    res, _ = run("standard")
    a, b = by_name(res, "Karim BENALI"), by_name(res, "BENALI Karim")
    assert b.key in a.merge_with and a.key in b.merge_with
    assert a.uid is None and b.uid is None          # rien n'est fusionné sans validation
    assert not by_name(res, "MARTIN").merge_with     # MARTIN != MARTINEZ ET FILS


def test_fiche_reconnue_dans_les_libelles_avec_sigle():
    res, _ = run("standard")
    soc = next(c for c in res.candidates if c.cat == "SOC")
    assert soc.pseudo == "SOC-0001" and soc.champs["EcritureLib"] > 0
    assert "ADP" in soc.variants and soc.statut == "connu" and soc.checked


def test_sans_fiche_aucune_entite_soc():
    res, _ = run("standard", fiche=False)
    assert not any(c.cat == "SOC" for c in res.candidates)


def test_iban_signale_et_pas_pris_pour_un_nom():
    res, _ = run("standard")
    assert {t["type"] for t in res.sensibles["types"]} >= {"IBAN"}
    assert not any(c.nom.upper() in ("IBAN", "FR", "REF") for c in res.candidates)
    assert "FR7630006000011234567890189" not in repr(res.sensibles)          # exemple masqué


def test_incrustation_du_nom_dans_les_numeros():
    assert run("pennylane")[0].incrustations["CompAuxNum"] > 0
    assert run("compte_individualise")[0].incrustations["CompteNum"] > 0
    assert run("standard")[0].incrustations["CompteNum"] == 0


def test_siren_aleatoire_ignore_siren_entite_signale():
    assert redact.scan("REF 732829320", frozenset()) == []                    # Luhn valide mais sans contexte
    assert [h.kind for h in redact.scan("REF 732829320", frozenset({"732829320"}))] == ["SIREN"]
    assert [h.kind for h in redact.scan("SIREN 732 829 320")] == ["SIREN"]
    assert redact.scan("N° 123456789") == []


def test_aucune_ligne_ni_champ_modifie_par_la_detection():
    s = make_fec("cabinet", "cp1252")
    f = parse_fec(s.data, s.filename)
    detect([f], new_payload("D-001"), PREF, WL)
    assert f.serialize(f.rows()) == s.data


def _mini(lines):
    head = "\t".join(CANON)
    rows = []
    for i, (j, num, cpt, cptl, aux, auxl, lib, d, c) in enumerate(lines):
        rows.append("\t".join([j, j, str(num), "20240131", cpt, cptl, aux, auxl, f"P{i}", "20240131", lib, d, c, "", "", "20240131", "", ""]))
    return parse_fec(("\n".join([head, *rows]) + "\n").encode(), "x")


def test_variante_de_contexte_d_ecriture():
    f = _mini([("HA", 1, "401000", "Fournisseurs", "ACMEBAT", "ACME BATIMENT ET TRAVAUX SAS", "FA1 ACME BATIMENT - FA1", "0", "120,00"),
               ("HA", 1, "607000", "Achats", "", "", "FA1 ACME BATIMENT - FA1", "120,00", "0")])
    res = detect([f], new_payload("D"), PREF, WL)
    c = by_name(res, "ACME BATIMENT ET TRAVAUX SAS")
    assert c.var_origin.get("ACME BATIMENT") == "contexte"
    assert not any(x.source == "libelle" for x in res.candidates)             # pas de doublon proposé


def test_variantes_de_personne_proposees_avec_comptage():
    f = _mini([("OD", 1, "421000001", "Karim BENALI", "", "", "NET A PAYER BENALI K.", "0", "100,00"),
               ("OD", 1, "641000", "Salaires", "", "", "NET A PAYER BENALI K.", "100,00", "0"),
               ("BQ", 2, "421000001", "Karim BENALI", "", "", "VIR K. BENALI", "100,00", "0"),
               ("BQ", 2, "512000", "Banque", "", "", "VIR K. BENALI", "0", "100,00")])
    res = detect([f], new_payload("D"), PREF, WL)
    c = by_name(res, "Karim BENALI")
    v = {x["texte"]: x for x in c.variantes_proposees}
    assert v["BENALI K."]["n"] >= 1 and v["K. BENALI"]["n"] >= 1 and not v["K. BENALI"]["risque"]
    assert c.checked and c.cat == "SAL"


def test_conflit_de_variantes_detecte():
    p = new_payload("D")
    apply_fiche(p, {"societe": {"raison_sociale": "A SAS", "variantes": ["TOTO"]}, "personnes": [{"nom": "Toto", "role": "associe"}]})
    res = detect([_mini([("HA", 1, "607000", "Achats", "", "", "x", "1,00", "0"), ("HA", 1, "401000", "F", "", "", "x", "0", "1,00")])], p, PREF, WL)
    assert res.conflits and res.conflits[0]["texte"] == "toto"


def test_resultat_sans_fuite_dans_les_statistiques():
    res, _ = run("standard")
    blob = repr(res.stats) + repr(res.incrustations)
    assert "BENALI" not in blob and "DUPONT" not in blob


def test_repli_sans_rapidfuzz():
    from pseudo_fec.detection import _similarity_fallback as sim
    assert sim("etablissements lefevre dubois", "etablissement lefevre dubois") >= 93     # faute de frappe : fusion proposée
    assert sim("dupont batiment", "martinez fils") < 70
    assert sim("benali karim", "karim benali") == 100                                      # ordre des mots indifférent
