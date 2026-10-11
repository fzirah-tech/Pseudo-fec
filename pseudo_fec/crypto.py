"""Chiffrement des tables : AES-256-GCM, clé dérivée par scrypt.

Architecture à deux niveaux :
- une clé de données (DEK) aléatoire par dossier chiffre la table ;
- la DEK est « enveloppée » par une clé dérivée de la phrase secrète (scrypt).
  Plusieurs enveloppes (« slots ») sont possibles : changer la phrase secrète
  ou ajouter une phrase de secours ne nécessite pas de rechiffrer la table.

La phrase secrète n'est jamais écrite sur disque.
"""

from __future__ import annotations

import base64
import os
import unicodedata
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .errors import PassphraseError, TableError

MAGIC = b"PFEC1"
KDF_DEFAULT: dict[str, int] = {"n": 2**17, "r": 8, "p": 1}
_NONCE = 12


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _norm(passphrase: str) -> bytes:
    return unicodedata.normalize("NFC", passphrase).encode("utf-8")


def _derive(passphrase: str, salt: bytes, kdf: dict[str, int]) -> bytes:
    return Scrypt(
        salt=salt, length=32, n=kdf["n"], r=kdf["r"], p=kdf["p"]
    ).derive(_norm(passphrase))


def new_dek() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def make_slot(dek: bytes, passphrase: str, scope: str, slot_id: str = "main",
              kdf: dict[str, int] | None = None) -> dict[str, Any]:
    kdf = dict(kdf or KDF_DEFAULT)
    salt = os.urandom(16)
    nonce = os.urandom(_NONCE)
    kek = _derive(passphrase, salt, kdf)
    wrapped = AESGCM(kek).encrypt(nonce, dek, b"PFEC-DEK|" + scope.encode())
    return {"id": slot_id, "kdf": {"name": "scrypt", **kdf, "salt": _b64(salt)},
            "nonce": _b64(nonce), "wrapped": _b64(wrapped)}


def open_slot(slot: dict[str, Any], passphrase: str, scope: str) -> bytes:
    k = slot["kdf"]
    kek = _derive(passphrase, _unb64(k["salt"]), {"n": k["n"], "r": k["r"], "p": k["p"]})
    try:
        return AESGCM(kek).decrypt(_unb64(slot["nonce"]), _unb64(slot["wrapped"]),
                                   b"PFEC-DEK|" + scope.encode())
    except InvalidTag:
        raise PassphraseError("Phrase secrète incorrecte.") from None


def create_keyring(scope: str, passphrase: str,
                   kdf: dict[str, int] | None = None) -> tuple[dict[str, Any], bytes]:
    dek = new_dek()
    return {"v": 1, "scope": scope, "slots": [make_slot(dek, passphrase, scope, "main", kdf)]}, dek


def unlock_keyring(keyring: dict[str, Any], passphrase: str) -> bytes:
    scope = keyring["scope"]
    for slot in keyring["slots"]:
        try:
            return open_slot(slot, passphrase, scope)
        except PassphraseError:
            continue
    raise PassphraseError("Phrase secrète incorrecte.")


def add_slot(keyring: dict[str, Any], dek: bytes, passphrase: str, slot_id: str,
             kdf: dict[str, int] | None = None) -> None:
    keyring["slots"] = [s for s in keyring["slots"] if s["id"] != slot_id]
    keyring["slots"].append(make_slot(dek, passphrase, keyring["scope"], slot_id, kdf))


def encrypt_blob(dek: bytes, plaintext: bytes, scope: str) -> bytes:
    nonce = os.urandom(_NONCE)
    return MAGIC + nonce + AESGCM(dek).encrypt(nonce, plaintext, b"PFEC-TBL|" + scope.encode())


def decrypt_blob(dek: bytes, blob: bytes, scope: str) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + _NONCE + 16:
        raise TableError("Fichier de table illisible ou corrompu.")
    nonce = blob[len(MAGIC):len(MAGIC) + _NONCE]
    try:
        return AESGCM(dek).decrypt(nonce, blob[len(MAGIC) + _NONCE:], b"PFEC-TBL|" + scope.encode())
    except InvalidTag:
        raise TableError("Table corrompue, altérée ou appartenant à un autre dossier.") from None
