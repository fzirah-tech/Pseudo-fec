import json

import pytest

from conftest import TEST_PASS
from pseudo_fec import mapping
from pseudo_fec.config import Config
from pseudo_fec.dossier import apply_fiche, apply_validation, new_payload
from pseudo_fec.errors import PseudoFecError
from pseudo_fec.generic_list import add_entry


def payload():
    p = new_payload("D-001")
    apply_fiche(p, {"societe": {"raison_sociale": "ATELIERS DU PORT SAS"}, "personnes": [], "liees": []})
    return p


def ent(p, nom):
    return next(e for e in p["entities"] if e["nom"] == nom)


def row(nom, cat="FRN", checked=True, **kw):
    return {"nom": nom, "cat": cat, "checked": checked, "source": "aux", "variantes": [], **kw}


def test_pseudonymes_attribues_aux_seules_entites_cochees_puis_stables():
    p = payload()
    apply_validation(p, [row("DUPONT BATIMENT SARL"), row("MARTINEZ ET FILS", checked=False), row("Zoé N'GUYEN", "CLI")])
    assert ent(p, "DUPONT BATIMENT SARL")["pseudo"] == "FRN-0001"
    assert ent(p, "MARTINEZ ET FILS")["pseudo"] is None and not ent(p, "MARTINEZ ET FILS")["a_pseudonymiser"]
    assert ent(p, "Zoé N'GUYEN")["pseudo"] == "CLI-0001"
    apply_validation(p, [row("DUPONT BATIMENT SARL"), row("MARTINEZ ET FILS"), row("AUTRE", "FRN")])
    assert ent(p, "DUPONT BATIMENT SARL")["pseudo"] == "FRN-0001"            # inchangé
    assert ent(p, "MARTINEZ ET FILS")["pseudo"] == "FRN-0002"                # attribué quand coché
    assert ent(p, "AUTRE")["pseudo"] == "FRN-0003"


def test_pas_de_collision_de_prefixe():
    p = payload()
    apply_validation(p, [row(f"TIERS {i:03d}") for i in range(12)])
    pseudos = [e["pseudo"] for e in p["entities"] if e["cat"] == "FRN"]
    assert "FRN-0001" in pseudos and "FRN-0012" in pseudos and len(set(pseudos)) == 12
    assert all(len(x) == 8 for x in pseudos)                                  # CAT-0000 : largeur fixe


def test_categorie_verrouillee_apres_attribution():
    p = payload()
    apply_validation(p, [row("DUPONT")])
    out = apply_validation(p, [row("DUPONT", cat="CLI")])
    assert ent(p, "DUPONT")["cat"] == "FRN" and ent(p, "DUPONT")["pseudo"] == "FRN-0001"
    assert out["warnings"]


def test_categorie_modifiable_avant_attribution():
    p = payload()
    apply_validation(p, [row("DUPONT", checked=False)])
    apply_validation(p, [row("DUPONT", cat="CLI", checked=True)])
    assert ent(p, "DUPONT")["pseudo"] == "CLI-0001"


def test_proposition_heuristique_ignoree_non_memorisee():
    p = payload()
    apply_validation(p, [{"nom": "Frais Divers", "cat": "TIE", "checked": False, "source": "libelle", "variantes": []}])
    assert not any(e["nom"] == "Frais Divers" for e in p["entities"])
    apply_validation(p, [{"nom": "Frais Divers", "cat": "TIE", "checked": False, "touched": True, "source": "libelle", "variantes": []}])
    assert ent(p, "Frais Divers")["a_pseudonymiser"] is False


def test_fusion_garde_le_pseudonyme_de_l_absorbe():
    p = payload()
    apply_validation(p, [row("Karim BENALI", "SAL"), row("BENALI Karim", "SAL")])
    a, b = ent(p, "Karim BENALI"), ent(p, "BENALI Karim")
    apply_validation(p, [row("Karim BENALI", "SAL", uid=a["uid"], variantes=["BENALI Karim"], absorbed_uids=[b["uid"]])])
    assert b["retired"] and b["alias_of"] == a["uid"] and b["pseudo"] == "SAL-0002"   # ancien pseudonyme conservé
    assert "BENALI Karim" in a["variantes"] and not b["a_pseudonymiser"]


def test_conflit_bloquant():
    p = payload()
    out = apply_validation(p, [row("MARTIN"), row("Sophie MARTIN", "SAL", variantes=["MARTIN"])])
    assert out["bloquant"] and out["conflicts"][0]["texte"] == "martin"
    # résolution : on décoche la variante ambiguë
    s = ent(p, "Sophie MARTIN")
    out = apply_validation(p, [row("Sophie MARTIN", "SAL", uid=s["uid"], variantes=[])])
    assert not out["bloquant"]


def test_societe_non_creable_par_validation():
    p = payload()
    apply_validation(p, [row("AUTRE SOC", "SOC")])
    assert not any(e["nom"] == "AUTRE SOC" for e in p["entities"])


def test_entite_fiche_conserve_son_nom_et_gagne_des_variantes():
    p = payload()
    soc = ent(p, "ATELIERS DU PORT SAS")
    apply_validation(p, [row("ATELIERS DU PORT SAS", "SOC", uid=soc["uid"], source="fiche", variantes=["Ateliers Port"])])
    assert ent(p, "ATELIERS DU PORT SAS")["pseudo"] == "SOC-0001" and "Ateliers Port" in soc["variantes"]


def test_table_chiffree_apres_validation(tmp_path):
    p = payload()
    apply_validation(p, [row("DUPONT BATIMENT SARL")])
    mapping.TableStore.create(tmp_path, "D-001", TEST_PASS, p)
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert b"DUPONT" not in f.read_bytes()


def test_liste_blanche_ajout_trace_et_unique(tmp_path):
    cfg = Config.load(tmp_path / "cabinet.json", tmp_path / "p.json")
    t = add_entry(cfg, "nouvelle banque  locale", "D-001")
    assert t["action"] == "ajout_liste_blanche" and t["nom"] == "NOUVELLE BANQUE LOCALE" and t["dossier"] == "D-001" and t["utilisateur"]
    assert "NOUVELLE BANQUE LOCALE" in json.loads((tmp_path / "cabinet.json").read_text())["whitelist"]
    with pytest.raises(PseudoFecError):
        add_entry(cfg, "Nouvelle Banque Locale", "D-001")
    with pytest.raises(PseudoFecError):
        add_entry(cfg, "   ", "D-001")


def test_liste_blanche_correspondances():
    from pseudo_fec.generic_list import Whitelist
    w = Whitelist(["URSSAF", "ORANGE", "FREE", "SOCIETE GENERALE"])
    assert w.matches("URSSAF PROVENCE") and w.matches("Orange SA") and w.matches("FREE")
    assert not w.matches("FREE SOLUTIONS DUPONT") and not w.matches("DUPONT")      # entrée courte : exacte seulement
    assert w.matches("Société Générale Marseille")
