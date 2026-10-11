import pytest

from pseudo_fec import crypto
from pseudo_fec.errors import PassphraseError, TableError


def test_roundtrip_et_aucun_clair():
    kr, dek = crypto.create_keyring("D-001", "secret un peu long")
    blob = crypto.encrypt_blob(dek, "DUPONT BATIMENT".encode(), "D-001")
    assert b"DUPONT" not in blob
    assert crypto.decrypt_blob(crypto.unlock_keyring(kr, "secret un peu long"), blob, "D-001") == b"DUPONT BATIMENT"


def test_mauvaise_phrase():
    kr, _ = crypto.create_keyring("D-001", "bonne phrase")
    with pytest.raises(PassphraseError):
        crypto.unlock_keyring(kr, "mauvaise phrase")


def test_alteration_detectee():
    _, dek = crypto.create_keyring("D-001", "x" * 12)
    blob = bytearray(crypto.encrypt_blob(dek, b"contenu", "D-001"))
    blob[-1] ^= 1
    with pytest.raises(TableError):
        crypto.decrypt_blob(dek, bytes(blob), "D-001")


def test_table_non_transposable_vers_un_autre_dossier():
    _, dek = crypto.create_keyring("D-001", "x" * 12)
    blob = crypto.encrypt_blob(dek, b"contenu", "D-001")
    with pytest.raises(TableError):
        crypto.decrypt_blob(dek, blob, "D-002")


def test_changement_de_phrase_sans_rechiffrer():
    kr, dek = crypto.create_keyring("D-001", "ancienne phrase")
    blob = crypto.encrypt_blob(dek, b"abc", "D-001")
    crypto.add_slot(kr, dek, "nouvelle phrase", "main")
    assert crypto.decrypt_blob(crypto.unlock_keyring(kr, "nouvelle phrase"), blob, "D-001") == b"abc"
    with pytest.raises(PassphraseError):
        crypto.unlock_keyring(kr, "ancienne phrase")


def test_phrase_de_secours_en_plus():
    kr, dek = crypto.create_keyring("D-001", "phrase principale")
    crypto.add_slot(kr, dek, "phrase de secours", "secours")
    assert crypto.unlock_keyring(kr, "phrase de secours") == dek
    assert crypto.unlock_keyring(kr, "phrase principale") == dek


def test_normalisation_unicode_de_la_phrase():
    kr, dek = crypto.create_keyring("D-001", "é-phrase-longue")  # é précomposé
    assert crypto.unlock_keyring(kr, "é-phrase-longue") == dek  # e + accent combinant


def test_parametres_kdf_par_defaut_robustes():
    assert crypto.KDF_DEFAULT["n"] >= 2**10  # en test ; la valeur réelle est contrôlée ci-dessous


def test_valeur_reelle_kdf():
    import importlib
    real = importlib.import_module("pseudo_fec.crypto")
    # le monkeypatch autouse masque la valeur : on relit la source
    src = open(real.__file__, encoding="utf-8").read()
    assert '"n": 2**17' in src
