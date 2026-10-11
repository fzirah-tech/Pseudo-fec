import json

from pseudo_fec.config import Config


def test_prefs_surchargent_seulement_les_emplacements(tmp_path):
    cab = tmp_path / "cabinet.json"
    cab.write_text(json.dumps({"tables_root": "/partage/tables", "whitelist": ["X"]}))
    pf = tmp_path / "prefs.json"
    pf.write_text(json.dumps({"tables_root": "/local/tables", "whitelist": ["PIRATE"]}))
    c = Config.load(cab, pf)
    assert str(c.tables_root).replace("\\", "/") == "/local/tables"
    assert c.cabinet["whitelist"] == ["X"]          # la liste blanche reste celle du cabinet


def test_valeurs_par_defaut(tmp_path):
    c = Config.load(tmp_path / "absent.json", tmp_path / "absent2.json")
    assert "401" in c.all_priority_prefixes() and "URSSAF" in c.cabinet["whitelist"]
    assert c.cabinet["max_fec_mb"] == 200


def test_ecriture_prefs(tmp_path):
    c = Config.load(tmp_path / "a.json", tmp_path / "p.json")
    c.set_pref("last_dossier", "D-001")
    assert json.loads((tmp_path / "p.json").read_text())["last_dossier"] == "D-001"
