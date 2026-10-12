import pytest

from pseudo_fec import dossier
from pseudo_fec.errors import DossierError


def _fiche(**kw):
    f = {"societe": {"raison_sociale": "ATELIERS DU PORT SAS", "sigle": "ADP", "nom_commercial": "",
                     "variantes": "Ateliers du Port\nA.D.P.", "siren": "732829320", "sirets": []},
         "personnes": [{"nom": "Claire BERNARD-MOREAU", "role": "dirigeant"},
                       {"nom": "Paul Henri DESCHAMPS", "role": "associe"}],
         "liees": [{"raison_sociale": "HOLDING DESCHAMPS SAS", "lien": "mere"},
                   {"raison_sociale": "SCI LES TILLEULS", "lien": "sci"}]}
    f.update(kw)
    return f


def test_luhn():
    assert dossier.luhn_ok("732829320")
    assert not dossier.luhn_ok("732829321")


def test_pseudonymes_reserves():
    p = dossier.new_payload("D-001")
    dossier.apply_fiche(p, _fiche())
    ps = {e["nom"]: e["pseudo"] for e in p["entities"]}
    assert ps["ATELIERS DU PORT SAS"] == "SOC-0001"
    assert ps["Claire BERNARD-MOREAU"] == "ASS-0001" and ps["Paul Henri DESCHAMPS"] == "ASS-0002"
    assert ps["HOLDING DESCHAMPS SAS"] == "GRP-0001" and ps["SCI LES TILLEULS"] == "GRP-0002"


def test_variantes_et_sigle_rattaches_a_la_societe():
    p = dossier.new_payload("D-001")
    dossier.apply_fiche(p, _fiche())
    soc = next(e for e in p["entities"] if e["pseudo"] == "SOC-0001")
    assert {"ADP", "Ateliers du Port", "A.D.P."} <= set(soc["variantes"])
    assert "732829320" in soc["ids"]


def test_enrichissement_stable_et_sans_reutilisation():
    p = dossier.new_payload("D-001")
    dossier.apply_fiche(p, _fiche())
    avant = {e["uid"]: e["pseudo"] for e in p["entities"]}
    f = dossier.normalize_fiche(p["fiche"])    # la fiche relue contient les uid stables
    f["personnes"].pop(0)                      # on retire le dirigeant
    dossier.apply_fiche(p, f)
    apres = {e["uid"]: e for e in p["entities"]}
    assert all(apres[u]["pseudo"] == ps for u, ps in avant.items())  # pseudonymes inchangés
    assert sum(e["retired"] for e in apres.values()) == 1             # conservé, marqué retiré
    f["personnes"].append({"nom": "Nouvel Associé", "role": "associe"})
    dossier.apply_fiche(p, f)
    assert next(e for e in p["entities"] if e["nom"] == "Nouvel Associé")["pseudo"] == "ASS-0003"


def test_fiche_facultative_et_societe_renseignee_apres_import():
    p = dossier.new_payload("D-001")
    assert dossier.apply_fiche(p, {"societe": {}, "personnes": [], "liees": []}) == []     # aucune saisie préalable
    assert p["entities"] == []
    dossier.apply_validation(p, [{"nom": "Karim BENALI", "cat": "SAL", "checked": True, "source": "compte", "variantes": []}])
    dossier.set_societe(p, {"raison_sociale": "ATELIERS DU PORT SAS", "siren": "732 829 320", "sigle": "ADP"})
    soc = next(e for e in p["entities"] if e["cat"] == "SOC")
    assert soc["pseudo"] == "SOC-0001" and "732829320" in soc["ids"] and "ADP" in soc["variantes"]
    assert next(e for e in p["entities"] if e["nom"] == "Karim BENALI")["pseudo"] == "SAL-0001"   # le reste est conservé
    dossier.set_societe(p, {"sigle": "ATP"})                                                       # mise à jour partielle
    assert next(e for e in p["entities"] if e["cat"] == "SOC")["uid"] == soc["uid"] and "ATP" in soc["variantes"]


def test_avertissement_siren_invalide():
    p = dossier.new_payload("D-001")
    f = _fiche()
    f["societe"]["siren"] = "123456789"
    assert any("SIREN" in w for w in dossier.apply_fiche(p, f))


def test_dedoublonnage_des_variantes():
    f = dossier.normalize_fiche(_fiche())
    f["societe"]["variantes"] = dossier._clean_list(["Port  SAS", "port sas", "PORT sas "])
    assert len(f["societe"]["variantes"]) == 1
