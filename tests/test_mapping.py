import json

import pytest

from conftest import TEST_PASS
from pseudo_fec import mapping
from pseudo_fec.errors import PassphraseError, TableError


def _payload():
    return {"entities": [{"nom": "DUPONT BATIMENT SARL", "pseudo": "FRN-0001"}], "counters": {"FRN": 1}}


def test_creation_ouverture(tmp_path):
    mapping.TableStore.create(tmp_path, "D-001", TEST_PASS, _payload())
    s = mapping.TableStore.open(tmp_path, "D-001", TEST_PASS)
    assert s.payload["entities"][0]["nom"] == "DUPONT BATIMENT SARL"


def test_aucun_nom_reel_sur_disque(tmp_path):
    s = mapping.TableStore.create(tmp_path, "D-001", TEST_PASS, _payload())
    s.payload["entities"].append({"nom": "Karim BENALI"})
    s.save()
    for f in tmp_path.rglob("*"):
        if f.is_file():
            raw = f.read_bytes()
            assert b"DUPONT" not in raw and b"BENALI" not in raw, f.name


def test_mauvaise_phrase_refusee(tmp_path):
    mapping.TableStore.create(tmp_path, "D-001", TEST_PASS, _payload())
    with pytest.raises(PassphraseError):
        mapping.TableStore.open(tmp_path, "D-001", "autre phrase")


def test_versions_et_restauration(tmp_path):
    s = mapping.TableStore.create(tmp_path, "D-001", TEST_PASS, _payload())
    s.payload["entities"].append({"nom": "AJOUT", "pseudo": "FRN-0002"})
    s.save()
    assert [v.rev for v in s.versions()] == [1, 2]
    s.restore(1)
    assert len(s.payload["entities"]) == 1
    assert [v.rev for v in s.versions()] == [1, 2, 3]  # l'historique n'est jamais réécrit
    assert mapping.TableStore.open(tmp_path, "D-001", TEST_PASS).payload["_restored_from"] == 1


def test_purge_des_versions(tmp_path):
    s = mapping.TableStore.create(tmp_path, "D-001", TEST_PASS, _payload())
    for _ in range(5):
        s.save(keep=3)
    assert len(s.versions()) == 3


def test_table_alteree_detectee(tmp_path):
    mapping.TableStore.create(tmp_path, "D-001", TEST_PASS, _payload())
    f = tmp_path / "D-001" / "table.enc"
    b = bytearray(f.read_bytes()); b[20] ^= 1; f.write_bytes(bytes(b))
    with pytest.raises(TableError):
        mapping.TableStore.open(tmp_path, "D-001", TEST_PASS)


def test_tables_non_echangeables_entre_dossiers(tmp_path):
    mapping.TableStore.create(tmp_path, "D-001", TEST_PASS, _payload())
    mapping.TableStore.create(tmp_path, "D-002", TEST_PASS, _payload())
    (tmp_path / "D-002" / "table.enc").write_bytes((tmp_path / "D-001" / "table.enc").read_bytes())
    with pytest.raises(TableError):
        mapping.TableStore.open(tmp_path, "D-002", TEST_PASS)


def test_code_dossier_invalide(tmp_path):
    for bad in ("", "a", "../x", "D 001", "x" * 40):
        with pytest.raises(TableError):
            mapping.TableStore.create(tmp_path, bad, TEST_PASS, _payload())


def test_doublon_refuse(tmp_path):
    mapping.TableStore.create(tmp_path, "D-001", TEST_PASS, _payload())
    with pytest.raises(TableError):
        mapping.TableStore.create(tmp_path, "D-001", TEST_PASS, _payload())


def test_pas_de_fichier_temporaire_residuel(tmp_path):
    s = mapping.TableStore.create(tmp_path, "D-001", TEST_PASS, _payload())
    s.save()
    assert not [f for f in tmp_path.rglob("*") if ".tmp" in f.name]


def test_canary_detecte_une_faute_de_frappe(tmp_path):
    mapping.canary_create(tmp_path, TEST_PASS)
    mapping.canary_verify(tmp_path, TEST_PASS)
    with pytest.raises(PassphraseError):
        mapping.canary_verify(tmp_path, TEST_PASS + "x")


def test_changement_de_phrase_dossier(tmp_path):
    s = mapping.TableStore.create(tmp_path, "D-001", TEST_PASS, _payload())
    s.change_passphrase(TEST_PASS, "nouvelle phrase de test")
    assert mapping.TableStore.open(tmp_path, "D-001", "nouvelle phrase de test").payload["counters"]["FRN"] == 1
    assert json.loads((tmp_path / "D-001" / "keyring.json").read_text())["slots"][0]["id"] == "main"
