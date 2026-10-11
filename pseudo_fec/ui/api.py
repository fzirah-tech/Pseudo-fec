"""Logique applicative de l'interface (indépendante du transport HTTP)."""

from __future__ import annotations

import json
import threading
import urllib.parse
from typing import Any

from .. import __version__, mapping
from ..config import Config
from ..dossier import LIENS, ROLES, apply_fiche, new_payload
from ..errors import DossierError, PseudoFecError, TableError
from ..fec_io import analyse, parse_fec, FecFile

MIN_PASSPHRASE = 12


class AppState:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.lock = threading.RLock()
        self.passphrase: str | None = None
        self.store: mapping.TableStore | None = None
        self.fecs: dict[str, tuple[FecFile, dict[str, Any]]] = {}

    def close(self) -> None:
        with self.lock:
            self.passphrase = None
            self.store = None
            self.fecs.clear()

    # ------------------------------------------------------------ routage
    def handle(self, method: str, path: str, body: bytes, headers: Any) -> dict[str, Any]:
        with self.lock:
            data = json.loads(body) if body and path != "/api/fec/upload" else {}
            routes = {
                ("GET", "/api/ping"): lambda: {"ok": True},
                ("GET", "/api/state"): self.state,
                ("POST", "/api/unlock"): lambda: self.unlock(data),
                ("POST", "/api/lock"): self.do_lock,
                ("GET", "/api/dossiers"): lambda: {"dossiers": mapping.list_dossiers(self.cfg.tables_root)},
                ("POST", "/api/dossier/create"): lambda: self.create_dossier(data),
                ("POST", "/api/dossier/open"): lambda: self.open_dossier(data),
                ("GET", "/api/dossier"): self.get_dossier,
                ("POST", "/api/dossier/fiche"): lambda: self.save_fiche(data),
                ("POST", "/api/fec/upload"): lambda: self.upload_fec(body, headers),
                ("GET", "/api/fec/list"): self.list_fecs,
                ("POST", "/api/fec/remove"): lambda: self.remove_fec(data),
                ("POST", "/api/quit"): lambda: {"_quit": True},
            }
            fn = routes.get((method, path))
            if fn is None:
                raise PseudoFecError("Requête inconnue.")
            return fn()

    # ------------------------------------------------------------ état
    def state(self) -> dict[str, Any]:
        root = self.cfg.tables_root
        return {
            "version": __version__,
            "unlocked": self.passphrase is not None,
            "canary": mapping.canary_exists(root),
            "dossier": self.store.code if self.store else None,
            "tables_root": str(root), "outputs_root": str(self.cfg.outputs_root),
            "max_fec_mb": self.cfg.get("max_fec_mb"),
            "liens": LIENS, "roles": ROLES,
        }

    def _need_pass(self) -> str:
        if self.passphrase is None:
            raise PseudoFecError("Saisissez d'abord la phrase secrète du cabinet.")
        return self.passphrase

    def unlock(self, d: dict[str, Any]) -> dict[str, Any]:
        phrase = str(d.get("passphrase", ""))
        root = self.cfg.tables_root
        if mapping.canary_exists(root):
            mapping.canary_verify(root, phrase)
        else:
            if len(phrase) < MIN_PASSPHRASE:
                raise PseudoFecError(f"Phrase secrète trop courte (minimum {MIN_PASSPHRASE} caractères).")
            if phrase != str(d.get("confirm", "")):
                raise PseudoFecError("La confirmation ne correspond pas à la phrase secrète.")
            mapping.canary_create(root, phrase)
        self.passphrase = phrase
        return self.state()

    def do_lock(self) -> dict[str, Any]:
        self.close()
        return self.state()

    # ------------------------------------------------------------ dossier
    def create_dossier(self, d: dict[str, Any]) -> dict[str, Any]:
        phrase = self._need_pass()
        code = str(d.get("code", "")).strip()
        payload = new_payload(code)
        warns = apply_fiche(payload, d.get("fiche", {}))
        self.fecs.clear()
        self.store = mapping.TableStore.create(self.cfg.tables_root, code, phrase, payload)
        self.cfg.set_pref("last_dossier", code)
        return {**self.get_dossier(), "warnings": warns}

    def open_dossier(self, d: dict[str, Any]) -> dict[str, Any]:
        phrase = self._need_pass()
        code = str(d.get("code", "")).strip()
        self.fecs.clear()
        self.store = mapping.TableStore.open(self.cfg.tables_root, code, phrase)
        self.cfg.set_pref("last_dossier", code)
        return self.get_dossier()

    def _store(self) -> mapping.TableStore:
        if self.store is None:
            raise DossierError("Aucun dossier ouvert.")
        return self.store

    def get_dossier(self) -> dict[str, Any]:
        s = self._store()
        p = s.payload
        return {"code": s.code, "fiche": p["fiche"],
                "entities": [{k: e[k] for k in ("pseudo", "cat", "nom", "retired")} for e in p["entities"]]}

    def save_fiche(self, d: dict[str, Any]) -> dict[str, Any]:
        s = self._store()
        warns = apply_fiche(s.payload, d.get("fiche", {}))
        s.save(int(self.cfg.get("versions_keep") or 50))
        return {**self.get_dossier(), "warnings": warns}

    # ------------------------------------------------------------ FEC
    def upload_fec(self, body: bytes, headers: Any) -> dict[str, Any]:
        s = self._store()
        name = urllib.parse.unquote(headers.get("X-Filename", "") or "fec.txt")
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        fec = parse_fec(body, name)
        rep = analyse(fec, self.cfg.priority_prefixes, s.payload["fiche"]["societe"]["siren"])
        self.fecs[name] = (fec, rep)
        return rep

    def list_fecs(self) -> dict[str, Any]:
        return {"fecs": [rep for _, rep in self.fecs.values()]}

    def remove_fec(self, d: dict[str, Any]) -> dict[str, Any]:
        self.fecs.pop(str(d.get("filename", "")), None)
        return self.list_fecs()
