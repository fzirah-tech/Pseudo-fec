"""Table de correspondance chiffrée : une table par dossier client.

Disposition d'un dossier (dans ``tables_root``) :
    <code>/keyring.json      clés enveloppées (aucune donnée réelle)
    <code>/table.enc         dernière révision, chiffrée
    <code>/versions/NNNNNN.enc   historique : une copie par révision

Les tables sont enrichies, jamais régénérées ; restaurer une version crée une
NOUVELLE révision (l'historique n'est jamais réécrit).
Le verrouillage multi-utilisateurs est ajouté au jalon (h).
"""

from __future__ import annotations

import json
import os
import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import crypto
from .errors import PassphraseError, TableError

CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,31}$")
CANARY_SCOPE = "__cabinet__"
CANARY_FILE = "cabinet.canary"


def check_code(code: str) -> str:
    if not CODE_RE.match(code or ""):
        raise TableError("Code dossier invalide (3 à 32 caractères : lettres, chiffres, - et _).")
    return code


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


# --- Contrôle de la phrase secrète du cabinet (évite une faute de frappe silencieuse) ---

def canary_exists(root: Path) -> bool:
    return (root / CANARY_FILE).exists()


def canary_create(root: Path, passphrase: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    keyring, dek = crypto.create_keyring(CANARY_SCOPE, passphrase)
    blob = crypto.encrypt_blob(dek, b"ok", CANARY_SCOPE)
    _atomic_write(root / CANARY_FILE, json.dumps({"keyring": keyring, "blob": blob.hex()}).encode())


def canary_verify(root: Path, passphrase: str) -> None:
    try:
        d = json.loads((root / CANARY_FILE).read_text(encoding="utf-8"))
        dek = crypto.unlock_keyring(d["keyring"], passphrase)
        crypto.decrypt_blob(dek, bytes.fromhex(d["blob"]), CANARY_SCOPE)
    except PassphraseError:
        raise
    except (OSError, ValueError, KeyError):
        raise TableError("Fichier de contrôle de la phrase secrète illisible.") from None


def list_dossiers(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "keyring.json").is_file())


@dataclass
class VersionInfo:
    rev: int
    size: int
    mtime: float


class TableStore:
    def __init__(self, root: Path, code: str, dek: bytes, payload: dict[str, Any]):
        self.root, self.code = root, code
        self._dek = dek
        self.payload = payload

    @property
    def dir(self) -> Path:
        return self.root / self.code

    # -- création / ouverture --
    @classmethod
    def create(cls, root: Path, code: str, passphrase: str, payload: dict[str, Any],
               kdf: dict[str, int] | None = None) -> "TableStore":
        check_code(code)
        d = root / code
        if (d / "keyring.json").exists():
            raise TableError("Un dossier portant ce code existe déjà.")
        (d / "versions").mkdir(parents=True, exist_ok=True)
        keyring, dek = crypto.create_keyring(code, passphrase, kdf)
        _atomic_write(d / "keyring.json", json.dumps(keyring, indent=1).encode())
        store = cls(root, code, dek, payload)
        store.save()
        return store

    @classmethod
    def open(cls, root: Path, code: str, passphrase: str) -> "TableStore":
        check_code(code)
        d = root / code
        try:
            keyring = json.loads((d / "keyring.json").read_text(encoding="utf-8"))
            blob = (d / "table.enc").read_bytes()
        except (OSError, ValueError):
            raise TableError("Dossier introuvable ou illisible.") from None
        dek = crypto.unlock_keyring(keyring, passphrase)
        return cls(root, code, dek, cls._decode(dek, code, blob))

    # -- (dé)sérialisation --
    @staticmethod
    def _decode(dek: bytes, code: str, blob: bytes) -> dict[str, Any]:
        try:
            return json.loads(zlib.decompress(crypto.decrypt_blob(dek, blob, code)).decode("utf-8"))
        except (zlib.error, ValueError):
            raise TableError("Contenu de table illisible.") from None

    def _encode(self) -> bytes:
        raw = json.dumps(self.payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return crypto.encrypt_blob(self._dek, zlib.compress(raw, 6), self.code)

    # -- enregistrement versionné --
    def save(self, keep: int = 50) -> int:
        rev = int(self.payload.get("_rev", 0)) + 1
        self.payload["_rev"] = rev
        blob = self._encode()
        (self.dir / "versions").mkdir(exist_ok=True)
        _atomic_write(self.dir / "versions" / f"{rev:06d}.enc", blob)
        _atomic_write(self.dir / "table.enc", blob)
        self._prune(keep)
        return rev

    def _prune(self, keep: int) -> None:
        files = sorted((self.dir / "versions").glob("*.enc"))
        for f in files[:-keep] if keep > 0 else []:
            f.unlink()

    def versions(self) -> list[VersionInfo]:
        out = []
        for f in sorted((self.dir / "versions").glob("*.enc")):
            st = f.stat()
            out.append(VersionInfo(int(f.stem), st.st_size, st.st_mtime))
        return out

    def restore(self, rev: int, keep: int = 50) -> int:
        f = self.dir / "versions" / f"{rev:06d}.enc"
        if not f.exists():
            raise TableError("Version introuvable.")
        restored = self._decode(self._dek, self.code, f.read_bytes())
        restored["_rev"] = self.payload.get("_rev", 0)
        restored["_restored_from"] = rev
        self.payload = restored
        return self.save(keep)

    # -- phrases secrètes --
    def change_passphrase(self, old: str, new: str, slot_id: str = "main") -> None:
        kr_path = self.dir / "keyring.json"
        keyring = json.loads(kr_path.read_text(encoding="utf-8"))
        crypto.unlock_keyring(keyring, old)  # vérifie l'ancienne
        crypto.add_slot(keyring, self._dek, new, slot_id)
        _atomic_write(kr_path, json.dumps(keyring, indent=1).encode())
