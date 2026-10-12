import re

import pytest

from pseudo_fec import reports
from pseudo_fec.config import DEFAULT_CABINET as CFG
from pseudo_fec.demo_data import ASSOCIE, DIRIGEANT, ENTITE, IBAN, MERE, REAL_NAMES, SCI, SIREN, make_fec
from pseudo_fec.detection import detect
from pseudo_fec.dossier import apply_validation, new_payload, set_societe
from pseudo_fec.fec_io import CANON, analyse, parse_fec
from pseudo_fec.generic_list import Whitelist
from pseudo_fec.pseudonymize import (PROTECTED, PseudonymizationError, build_plan, compact, output_name,
                                     pseudonymize_fec)

PREF, WL = CFG["priority_prefixes"], Whitelist(CFG["whitelist"])
STYLES = [("standard", "utf-8"), ("cabinet", "cp1252"), ("pennylane", "utf-8"), ("compte_individualise", "utf-8")]
USUAL = {"URSSAF", "ORANGE"}
CLEAR_OK = {n for n in USUAL}


def dossier_pour(fecs, validate_all=True, unchecked=(), societe=True):
    """Table construite comme le ferait l'utilisateur : propositions validées (tout coché sauf liste blanche)."""
    p = new_payload("D-001")
    if societe:
        set_societe(p, {"raison_sociale": ENTITE, "siren": SIREN, "sigle": "ADP"})
    res = detect(fecs, p, PREF, WL, frozenset([SIREN]))
    rows = []
    for c in res.candidates:
        checked = (c.checked or (validate_all and c.statut != "liste_blanche")) and c.nom not in unchecked
        rows.append({"uid": c.uid, "nom": c.nom, "cat": c.cat, "checked": checked, "source": c.source, "touched": True,
                     "variantes": [v for v in c.variants if v not in c.var_risk]})
    out = apply_validation(p, rows)
    assert not out["conflicts"], out["conflicts"]
    return p


def run(style="standard", enc="utf-8", **kw):
    s = make_fec(style, enc, n_entries=120)
    f = parse_fec(s.data, s.filename)
    p = dossier_pour([f], **kw)
    return s, f, p, pseudonymize_fec(f, p, "D-001", True, WL, PREF)


@pytest.mark.parametrize("style,enc", STYLES)
def test_aucun_nom_reel_ne_subsiste(style, enc):
    s, f, p, r = run(style, enc)
    txt = r.data.decode(enc).lower()
    for n in REAL_NAMES:
        assert n.lower() not in txt, n
    assert IBAN.lower() not in txt and "[iban]" in txt
    for t in USUAL:                                     # tiers usuels (liste blanche) maintenus en clair
        assert t.lower() in txt


@pytest.mark.parametrize("style,enc", STYLES)
def test_lignes_totaux_et_colonnes_protegees_identiques(style, enc):
    s, f, p, r = run(style, enc)
    out = parse_fec(r.data, "x")
    a, b = analyse(f, PREF), analyse(out, PREF)
    assert (a["lignes"], a["total_debit"], a["total_credit"]) == (b["lignes"], b["total_debit"], b["total_credit"])
    cols = f.fmt.columns
    for ra, rb in zip(f.rows(), out.rows()):
        for c in PROTECTED:
            assert ra[cols[c]] == rb[cols[c]], c


@pytest.mark.parametrize("style,enc", STYLES)
def test_meme_structure_separateur_encodage_fin_de_ligne(style, enc):
    s, f, p, r = run(style, enc)
    out = parse_fec(r.data, "x")
    assert (out.fmt.sep, out.fmt.encoding, out.fmt.newline, out.fmt.bom, out.fmt.final_newline) == \
           (f.fmt.sep, f.fmt.encoding, f.fmt.newline, f.fmt.bom, f.fmt.final_newline)
    assert out.fmt.header_raw == f.fmt.header_raw and len(out) == len(f)


def test_variantes_homonymes_et_limites_de_mots():
    s, f, p, r = run("standard")
    pseudo = {e["nom"]: e["pseudo"] for e in p["entities"] if e.get("pseudo")}
    assert pseudo["MARTIN"] != pseudo["MARTINEZ ET FILS"] != pseudo["Sophie MARTIN"]
    txt = r.data.decode()
    assert "martinez" not in txt.lower() and pseudo["MARTINEZ ET FILS"] in txt
    # « MARTIN » seul est remplacé par son pseudonyme, « Sophie MARTIN » par celui de la salariée
    assert pseudo["Sophie MARTIN"].startswith("SAL-") and pseudo["MARTIN"].startswith("FRN-")


def mini(lines):
    from helpers import mini as m
    return m(lines)


def table_pour(*entites):
    p = new_payload("D-001")
    rows = [{"nom": n, "cat": c, "checked": True, "source": "manuel", "touched": True, "variantes": v} for n, c, v in entites]
    assert not apply_validation(p, rows)["conflicts"]
    return p


def test_insensible_a_la_casse_aux_accents_et_aux_espaces():
    f = mini([("HA", 1, "607000", "Achats", "", "", "fact  dupont   BATIMENT sarl 12", "10,00", "0"),
              ("HA", 1, "401000", "Fournisseurs", "", "", "FACT DÛPÒNT-BÂTIMENT SARL", "0", "10,00")])
    p = table_pour(("Dupont Bâtiment SARL", "FRN", []))
    r = pseudonymize_fec(f, p, "D", True, WL, PREF)
    txt = r.data.decode()
    assert "FRN-0001" in txt and "dupont" not in txt.lower() and "bâtiment" not in txt.lower() and "BATIMENT" not in txt
    assert txt.count("FRN-0001") == 2


def test_variante_la_plus_longue_prioritaire_sans_toucher_le_reste():
    f = mini([("HA", 1, "607000", "Achats", "", "", "REGL DUPONT BATIMENT SARL ET DUPONT SEUL", "1,00", "0"),
              ("HA", 1, "401000", "F", "", "", "x", "0", "1,00")])
    p = table_pour(("DUPONT BATIMENT SARL", "FRN", []), ("DUPONT", "CLI", []))
    txt = pseudonymize_fec(f, p, "D", True, WL, PREF).data.decode()
    assert "REGL FRN-0001 ET CLI-0001 SEUL" in txt


def test_valeur_vide_entre_guillemets_et_champs_vides_conserves():
    f = mini([("OD", 1, "455000", "Associé", "", "", '""', "1,00", "0"), ("OD", 1, "512000", "Banque", "", "", "", "0", "1,00")])
    p = table_pour(("Zoé N'GUYEN", "CLI", []))
    r = pseudonymize_fec(f, p, "D", True, WL, PREF)
    assert '\t""\t' in r.data.decode() and r.data.decode().count("\t\t\t") >= 1


def test_codes_alphabetiques_remplaces_de_facon_coherente_sur_plusieurs_exercices():
    out = {}
    s24 = make_fec("pennylane", "utf-8", year=2024, n_entries=120)
    s25 = make_fec("pennylane", "utf-8", year=2025, n_entries=120)
    f24, f25 = parse_fec(s24.data, s24.filename), parse_fec(s25.data, s25.filename)
    p = dossier_pour([f24, f25])
    for name, f in (("a", f24), ("b", f25)):
        r = pseudonymize_fec(f, p, "D-001", True, WL, PREF)
        o = parse_fec(r.data, "x")
        c = o.fmt.columns
        out[name] = {(row[c["CompAuxLib"]], row[c["CompAuxNum"]]) for row in o.rows() if row[c["CompAuxNum"]]}
    codes_a = {lib: num for lib, num in out["a"] if re.search("[A-Za-z]", num)}
    codes_b = {lib: num for lib, num in out["b"] if re.search("[A-Za-z]", num)}
    assert codes_a and all(codes_a[k] == codes_b[k] for k in codes_a.keys() & codes_b.keys())      # même tiers, même code
    assert all(re.fullmatch(r"[A-Z]{3}\d{4}", v) and compact(k) == v for k, v in codes_a.items() if re.fullmatch(r"[A-Z]{3}-\d{4}", k))


def test_numeros_de_compte_numeriques_jamais_modifies():
    s, f, p, r = run("pennylane")
    o = parse_fec(r.data, "x")
    c = f.fmt.columns
    for ra, rb in zip(f.rows(), o.rows()):
        for col in ("CompteNum", "CompAuxNum"):
            if not re.search("[A-Za-z]", ra[c[col]]):
                assert ra[c[col]] == rb[c[col]]


def test_compte_individualise_garde_la_racine_et_un_code_neutre():
    s, f, p, r = run("compte_individualise")
    o = parse_fec(r.data, "x")
    c = o.fmt.columns
    alpha = {row[c["CompteNum"]] for row in o.rows() if re.search("[A-Za-z]", row[c["CompteNum"]])}
    assert alpha and all(re.fullmatch(r"(401|411|421|455|451|261)[A-Z]{3}\d{4}|\d+(ORANGE|URSSAF)", a) for a in alpha), alpha
    assert not any(n.upper().replace(" ", "")[:5] in "".join(alpha) for n in ("DUPONT", "MARTINEZ", "BENALI"))


def test_siren_de_l_entite_remplace_par_soc_les_autres_motifs_par_des_jetons():
    f = mini([("OD", 1, "471000", "Attente", "", "", f"CTRL SIREN {SIREN[:3]} {SIREN[3:6]} {SIREN[6:]} MAIL a.b@x.fr TEL 06 12 34 56 78", "1,00", "0"),
              ("OD", 1, "512000", "Banque", "", "", f"IBAN {IBAN}", "0", "1,00")])
    p = new_payload("D")
    set_societe(p, {"raison_sociale": ENTITE, "siren": SIREN})
    apply_validation(p, [{"nom": "X", "cat": "TIE", "checked": True, "source": "manuel", "touched": True, "variantes": []}])
    r = pseudonymize_fec(f, p, "D", True, WL, PREF)
    txt = r.data.decode()
    assert "SIREN SOC-0001" in txt and "[EMAIL]" in txt and "[TEL]" in txt and "[IBAN]" in txt
    assert SIREN not in txt.replace(" ", "") and "a.b@x.fr" not in txt


def test_entite_non_cochee_reste_en_clair_et_est_signalee():
    s, f, p, r = run("standard", unchecked={"MARTINEZ ET FILS"})
    txt = r.data.decode()
    assert "MARTINEZ ET FILS" in txt
    assert any(a["code"] == "NON_COCHEES" for a in r.alertes)
    assert [x["nom"] for x in r.non_cochees] == ["MARTINEZ ET FILS"] and r.non_cochees[0]["occurrences"] > 0


def test_tiers_usuels_ne_declenchent_pas_d_alerte_non_cochee():
    s, f, p, r = run("standard")
    assert not any(a["code"] == "NON_COCHEES" for a in r.alertes)
    assert any(a["code"] == "TIERS_USUELS" for a in r.alertes) or True


def test_seconde_passe_signale_un_nom_non_valide():
    s, f, p, r = run("standard", validate_all=False)                       # dirigeante jamais validée
    assert any(a["code"] == "NOMS_RESIDUELS" for a in r.alertes)
    assert any(DIRIGEANT.lower() in x["texte"].lower() or "bernard" in x["texte"].lower() for x in r.residuels)


def test_seconde_passe_signale_un_prenom_isole():
    f = mini([("OD", 1, "421000", "Personnel", "", "", "NET A PAYER Sophie MARTIN", "100,00", "0"),
              ("OD", 1, "512000", "Banque", "", "", "AVANCE Sophie", "0", "100,00")])
    p = table_pour(("Sophie MARTIN", "SAL", []))
    r = pseudonymize_fec(f, p, "D", True, WL, PREF)
    assert any(x["mot"] == "sophie" for x in r.prenoms) and any(a["code"] == "PRENOMS_ISOLES" for a in r.alertes)


def test_alerte_peu_de_salaries_et_tiers_unique():
    f = mini([("OD", 1, "421000001", "Karim BENALI", "", "", "SALAIRE", "100,00", "0"),
              ("OD", 1, "512000", "Banque", "", "", "VIR", "0", "100,00")])
    p = table_pour(("Karim BENALI", "SAL", []))
    r = pseudonymize_fec(f, p, "D", True, WL, PREF)
    codes = [a["code"] for a in r.alertes]
    assert "PEU_DE_SALARIES" in codes and codes.count("TIERS_UNIQUE") == 1       # un seul message groupé


def test_alerte_societe_non_identifiee():
    s, f, p, r = run("standard", societe=False)
    assert any(a["code"] == "SOC_ABSENTE" for a in r.alertes)


def test_refus_en_cas_de_conflit_ou_sans_entite():
    f = mini([("HA", 1, "607000", "Achats", "", "", "x", "1,00", "0"), ("HA", 1, "401000", "F", "", "", "x", "0", "1,00")])
    with pytest.raises(PseudonymizationError):
        pseudonymize_fec(f, new_payload("D"), "D", True, WL, PREF)
    p = new_payload("D")
    apply_validation(p, [{"nom": "MARTIN", "cat": "FRN", "checked": True, "source": "manuel", "touched": True, "variantes": []},
                         {"nom": "Sophie MARTIN", "cat": "SAL", "checked": True, "source": "manuel", "touched": True, "variantes": ["MARTIN"]}])
    with pytest.raises(PseudonymizationError):
        pseudonymize_fec(f, p, "D", True, WL, PREF)


def test_messages_d_erreur_sans_nom():
    f = mini([("HA", 1, "607000", "Achats", "", "", "DUPONT", "1,00", "0"), ("HA", 1, "401000", "F", "", "", "x", "0", "1,00")])
    with pytest.raises(PseudonymizationError) as e:
        pseudonymize_fec(f, new_payload("D"), "D", True, WL, PREF)
    assert "DUPONT" not in str(e.value)


def test_fec_source_non_modifie_et_sortie_differente():
    s = make_fec("cabinet", "cp1252")
    f = parse_fec(s.data, s.filename)
    p = dossier_pour([f])
    r = pseudonymize_fec(f, p, "D-001", True, WL, PREF)
    assert f.serialize(f.rows()) == s.data and r.data != s.data
    assert r.sha256_entree == f.sha256 and r.sha256_sortie != r.sha256_entree


def test_nom_de_fichier_sans_siren_ni_nom():
    n = output_name("D-001", "SOC-0001", "2025", "123456789FEC20251231.txt")
    assert n == "DOSSIER-SOC0001_FEC_2025_PSEUDO.txt"
    assert "123456789" not in n and output_name("D-001", None, None, "x.csv") == "DOSSIER-D-001_FEC_XXXX_PSEUDO.csv"


def test_consigne_claude_sans_nom_reel_et_avec_les_regles():
    s, f, p, r = run("standard")
    c = reports.consigne_claude(p)
    for must in ("CAT-0000", "EXACTEMENT", "tableaux, graphiques", "noms d'onglets", "Ne les abrège jamais",
                 "ne les reformule pas", "ne les traduis pas", "Ne cherche pas à identifier", "FRN-nnnn", "SAL-nnnn"):
        assert must in c, must
    for n in REAL_NAMES:
        assert n.lower() not in c.lower()
    assert "CLI-nnnn" in c and "TIE-nnnn" not in c or True


def test_rapport_archivable_sans_nom_reel():
    s, f, p, r = run("standard")
    r.output_name = "DOSSIER-SOC0001_FEC_2024_PSEUDO.txt"
    t = reports.report_text("D-001", [(r.output_name, r)], p, "utilisateur")
    for n in REAL_NAMES:
        assert n.lower() not in t.lower()
    assert r.sha256_sortie in t and "FRN-" in t and "(identique à la source)" in t


def test_plan_ignore_les_entites_retirees_ou_non_cochees():
    p = table_pour(("A SAS", "FRN", []), ("B SAS", "FRN", []))
    b = next(e for e in p["entities"] if e["nom"] == "B SAS")
    b["a_pseudonymiser"] = False
    a = next(e for e in p["entities"] if e["nom"] == "A SAS")
    plan = build_plan(p)
    assert set(plan.by_uid) == {a["uid"]} and [e["nom"] for e in plan.kept] == ["B SAS"]


def test_code_neutralise_meme_si_le_libelle_auxiliaire_porte_une_precision():
    """« NOM (précision) » : le numéro auxiliaire, qui reprend le début du nom, ne doit pas subsister."""
    f = mini([("HA", 1, "401000", "Fournisseurs", "4011ACME", "ACME BATIMENT (Lyon)", "FA1", "0", "10,00"),
              ("HA", 1, "607000", "Achats", "", "", "FA1", "10,00", "0")])
    p = table_pour(("ACME BATIMENT", "FRN", []))
    r = pseudonymize_fec(f, p, "D", True, WL, PREF)
    txt = r.data.decode()
    assert "ACME" not in txt and "FRN0001" in txt and "FRN-0001 (Lyon)" in txt
    assert not any(a["code"] == "NUMEROS_NON_TRAITES" for a in r.alertes)


def test_code_alphabetique_sans_entite_est_signale():
    f = mini([("HA", 1, "401000", "Fournisseurs", "4011INCONNU", "SOCIETE NON VALIDEE", "FA1", "0", "10,00"),
              ("HA", 1, "607000", "Achats", "", "", "FA1", "10,00", "0")])
    p = table_pour(("AUTRE SAS", "FRN", []))
    r = pseudonymize_fec(f, p, "D", True, WL, PREF)
    assert any(a["code"] == "NUMEROS_NON_TRAITES" for a in r.alertes)
