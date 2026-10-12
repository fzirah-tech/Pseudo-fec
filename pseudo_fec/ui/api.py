"""Logique applicative de l'interface (indépendante du transport HTTP)."""

from __future__ import annotations

import json
import threading
import urllib.parse
from typing import Any

from .. import __version__, mapping
import getpass
import os
import datetime as dt
from pathlib import Path

from .. import diagnostic
from ..config import Config
from ..demo_data import DEMO_STYLES, make_fec
from ..dossier import LIENS, ROLES, apply_fiche, apply_validation, entity_conflicts, new_payload, set_societe, luhn_ok
from ..fec_io import filename_info
from ..pseudonymize import output_name, pseudonymize_fec
from ..reports import consigne_claude, report_text
from ..detection import CATS, detect
from ..generic_list import Whitelist, add_entry
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
        self.detection: dict[str, Any] | None = None
        self.listen: tuple[str, int] | None = None

    def close(self) -> None:
        with self.lock:
            self.passphrase = None
            self.store = None
            self.fecs.clear()
            self.detection = None

    # ------------------------------------------------------------ routage
    def handle(self, method: str, path: str, body: bytes, headers: Any, query: dict[str, list[str]] | None = None) -> dict[str, Any]:
        query = query or {}
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
                ("POST", "/api/detect"): self.run_detection,
                ("GET", "/api/societe"): self.societe_state,
                ("POST", "/api/societe/save"): lambda: self.save_societe(data),
                ("POST", "/api/entities/save"): lambda: self.save_entities(data),
                ("POST", "/api/whitelist/add"): lambda: self.whitelist_add(data),
                ("GET", "/api/diagnostic"): self.diagnostic,
                ("POST", "/api/demo/create"): lambda: self.demo_create(data),
                ("GET", "/api/demo/fec"): lambda: self.demo_fec(query),
                ("POST", "/api/open-folder"): lambda: self.open_folder(data),
                ("GET", "/api/pseudo/status"): self.pseudo_status,
                ("POST", "/api/pseudo/run"): lambda: self.pseudo_run(data),
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
            "liens": LIENS, "roles": ROLES, "categories": CATS, "n_fec": len(self.fecs),
            "n_a_pseudonymiser": sum(1 for e in self.store.payload["entities"] if e.get("a_pseudonymiser") and not e.get("retired")) if self.store else 0,
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
        warns = apply_fiche(payload, d["fiche"]) if d.get("fiche") else []     # fiche facultative : complétée après l'import du FEC
        self.fecs.clear()
        self.detection = None
        self.store = mapping.TableStore.create(self.cfg.tables_root, code, phrase, payload)
        self.cfg.set_pref("last_dossier", code)
        return {**self.get_dossier(), "warnings": warns}

    def open_dossier(self, d: dict[str, Any]) -> dict[str, Any]:
        phrase = self._need_pass()
        code = str(d.get("code", "")).strip()
        self.fecs.clear()
        self.detection = None
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
        rep = analyse(fec, self.cfg.priority_prefixes, self.reference_siren())
        self.fecs[name] = (fec, rep)
        self.detection = None
        return rep

    def detected_sirens(self) -> list[str]:
        """SIREN lus dans les noms de fichiers FEC importés (norme A47 A-1 : SIRENFECAAAAMMJJ)."""
        found = []
        for _, rep in self.fecs.values():
            sn = rep.get("siren_nom_fichier")
            if sn and sn not in found:
                found.append(sn)
        return found

    def reference_siren(self) -> str:
        """SIREN du dossier : celui de la fiche s'il est renseigné, sinon celui du premier FEC importé."""
        fiche = self._store().payload["fiche"]["societe"]["siren"]
        if fiche:
            return fiche
        det = self.detected_sirens()
        return det[0] if det else ""

    def societe_state(self) -> dict[str, Any]:
        s = self._store()
        soc = s.payload["fiche"]["societe"]
        det = self.detected_sirens()
        siren = soc["siren"] or (det[0] if det else "")
        return {"raison_sociale": soc["raison_sociale"], "sigle": soc["sigle"], "nom_commercial": soc["nom_commercial"],
                "variantes": soc["variantes"], "siren": siren, "siren_detecte": bool(det) and not soc["siren"],
                "siren_valide": bool(siren) and len(siren) == 9 and luhn_ok(siren),
                "pseudo": next((e["pseudo"] for e in s.payload["entities"] if e["cat"] == "SOC"), None)}

    def save_societe(self, d: dict[str, Any]) -> dict[str, Any]:
        s = self._store()
        warns = set_societe(s.payload, {
            "raison_sociale": str(d.get("raison_sociale", "")), "sigle": str(d.get("sigle", "")),
            "nom_commercial": str(d.get("nom_commercial", "")), "variantes": d.get("variantes", []),
            "siren": str(d.get("siren", ""))})
        s.save(int(self.cfg.get("versions_keep") or 50))
        self.detection = None
        soc = next((e for e in s.payload["entities"] if e["cat"] == "SOC" and not e.get("retired")), None)
        return {**self.societe_state(), "warnings": warns,
                "entity": {k: soc[k] for k in ("uid", "nom", "variantes")} if soc else None}

    def list_fecs(self) -> dict[str, Any]:
        return {"fecs": [rep for _, rep in self.fecs.values()]}

    def remove_fec(self, d: dict[str, Any]) -> dict[str, Any]:
        self.fecs.pop(str(d.get("filename", "")), None)
        self.detection = None
        return self.list_fecs()

    # ------------------------------------------------------------ noms candidats
    def run_detection(self) -> dict[str, Any]:
        s = self._store()
        if not self.fecs:
            raise PseudoFecError("Importez d'abord au moins un FEC.")
        if any(rep["bloquant"] for _, rep in self.fecs.values()):
            raise PseudoFecError("Un FEC présente des erreurs bloquantes : corrigez-les avant la détection.")
        res = detect([f for f, _ in self.fecs.values()], s.payload, self.cfg.priority_prefixes,
                     Whitelist(self.cfg.cabinet.get("whitelist", [])), frozenset(self.detected_sirens()))
        self.detection = res.as_dict()
        return {**self.detection, "conflits_table": entity_conflicts(s.payload), "societe": self.societe_state()}

    def save_entities(self, d: dict[str, Any]) -> dict[str, Any]:
        s = self._store()
        out = apply_validation(s.payload, d.get("rows", []))
        s.save(int(self.cfg.get("versions_keep") or 50))
        return out

    def whitelist_add(self, d: dict[str, Any]) -> dict[str, Any]:
        s = self._store()
        trace = add_entry(self.cfg, str(d.get("nom", "")), s.code)
        s.payload.setdefault("whitelist_log", []).append(trace)
        s.save(int(self.cfg.get("versions_keep") or 50))
        return {"ok": True, "whitelist": self.cfg.cabinet["whitelist"]}

    # ------------------------------------------------------------ aide, démonstration, diagnostic
    def diagnostic(self) -> dict[str, Any]:
        checks = diagnostic.run_checks(self.cfg, self.listen)
        return {"checks": checks, "texte": diagnostic.as_text(checks), "ok": all(c["ok"] for c in checks)}

    def demo_fec(self, query: dict[str, list[str]]) -> dict[str, Any]:
        style = (query.get("style") or ["cabinet"])[0]
        if style not in DEMO_STYLES:
            raise PseudoFecError("Style inconnu.")
        year = int((query.get("year") or ["2024"])[0])
        if not 2000 <= year <= 2100:
            raise PseudoFecError("Année invalide.")
        s = make_fec(style, DEMO_STYLES[style][0], year=year)
        return {"_download": {"name": f"DEMO-FEC-{style}-{year}.txt", "ctype": "text/plain", "data": s.data}}

    def demo_create(self, d: dict[str, Any]) -> dict[str, Any]:
        """Crée un dossier de démonstration (données fictives) avec deux exercices déjà importés."""
        phrase = self._need_pass()
        style = str(d.get("style", "cabinet"))
        if style not in DEMO_STYLES:
            raise PseudoFecError("Style inconnu.")
        existing = set(mapping.list_dossiers(self.cfg.tables_root))
        n = 1
        while f"DEMO-{n:03d}" in existing:
            n += 1
        code = f"DEMO-{n:03d}"
        payload = new_payload(code)                     # comme en usage réel : aucune saisie préalable
        self.store = mapping.TableStore.create(self.cfg.tables_root, code, phrase, payload)
        self.fecs.clear()
        self.detection = None
        for year in (2024, 2025):
            s = make_fec(style, DEMO_STYLES[style][0], year=year, n_entries=120)
            name = f"DEMO-{style}-{s.filename}"
            fec = parse_fec(s.data, name)
            self.fecs[name] = (fec, analyse(fec, self.cfg.priority_prefixes, self.reference_siren()))
        return {**self.state(), "code": code}

    def open_folder(self, d: dict[str, Any]) -> dict[str, Any]:
        which = d.get("which")
        paths = {"tables": self.cfg.tables_root, "outputs": self.cfg.outputs_root}
        if self.store:
            paths["pseudo"] = self.cfg.outputs_root / self.store.code / "PSEUDO"
        path = paths.get(which)
        if path is None:
            raise PseudoFecError("Dossier inconnu.")
        path.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows : ouvre l'Explorateur
            return {"ok": True, "message": "Dossier ouvert dans l'Explorateur."}
        return {"ok": False, "message": "Ouverture automatique disponible sous Windows : " + diagnostic.mask(path)}

    # ------------------------------------------------------------ pseudonymisation (jalon c)
    def pseudo_dir(self) -> Path:
        return self.cfg.outputs_root / self._store().code / "PSEUDO"

    def pseudo_status(self) -> dict[str, Any]:
        s = self._store()
        p = s.payload
        conflicts = entity_conflicts(p)
        n_ent = sum(1 for e in p["entities"] if e.get("a_pseudonymiser") and not e.get("retired"))
        soc = self.societe_state()
        blocks, notes = [], []
        if not self.fecs:
            blocks.append("Aucun FEC importé : retournez à l'étape « Import du FEC ».")
        if any(rep["bloquant"] for _, rep in self.fecs.values()):
            blocks.append("Un FEC présente des erreurs bloquantes.")
        if n_ent == 0:
            blocks.append("Aucune entité à pseudonymiser : validez d'abord les noms et cliquez sur « Enregistrer les décisions ».")
        if conflicts:
            blocks.append("Des conflits de variantes subsistent (même texte rattaché à deux entités) : résolvez-les à l'étape « Noms à valider ».")
        if not soc["pseudo"]:
            notes.append("La société n'est pas identifiée : sa raison sociale ne sera pas remplacée.")
        if 0 < n_ent <= (1 if soc["pseudo"] else 0):
            notes.append("Seule la société est validée : les clients, fournisseurs, salariés et associés resteront en clair. "
                         "Validez-les à l'étape « Noms à valider ».")
        return {"pret": not blocks, "blocages": blocks, "notes": notes, "n_entites": n_ent, "n_fec": len(self.fecs),
                "exercices": [rep.get("exercice") for _, rep in self.fecs.values()], "conflits": conflicts,
                "dossier_sortie": diagnostic.mask(self.pseudo_dir())}

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        n = 2
        while True:
            cand = path.with_name(f"{path.stem}_v{n}{path.suffix}")
            if not cand.exists():
                return cand
            n += 1

    @staticmethod
    def _write_new(path: Path, data: bytes) -> None:
        tmp = path.with_name(path.name + ".part")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def pseudo_run(self, d: dict[str, Any]) -> dict[str, Any]:
        s = self._store()
        st = self.pseudo_status()
        if not st["pret"]:
            raise PseudoFecError(st["blocages"][0])
        p = s.payload
        out_dir = self.pseudo_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        wl = Whitelist(self.cfg.cabinet.get("whitelist", []))
        soc = next((e["pseudo"] for e in p["entities"] if e["cat"] == "SOC" and e.get("pseudo") and not e.get("retired")), None)
        nom_of = {e["pseudo"]: e["nom"] for e in p["entities"] if e.get("pseudo")}
        cat_of = {e["pseudo"]: e["cat"] for e in p["entities"] if e.get("pseudo")}
        results, produced, files = [], [], []
        for name, (fec, rep) in self.fecs.items():
            r = pseudonymize_fec(fec, p, s.code, bool(d.get("replace_codes", True)), wl, self.cfg.priority_prefixes)
            path = self._unique_path(out_dir / output_name(s.code, soc, rep.get("exercice"), name))
            self._write_new(path, r.data)
            r.output_name = path.name
            produced.append((path.name, r))
            files.append(path.name)
            p["fec"].append({"date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                             "utilisateur": getpass.getuser(), "sortie": path.name, "sha256_entree": r.sha256_entree,
                             "sha256_sortie": r.sha256_sortie, "lignes": r.lignes, "remplacements": sum(r.remplacements.values())})
            results.append({
                "fichier": path.name, "lignes": r.lignes, "total_debit": r.total_debit, "total_credit": r.total_credit,
                "remplacements": [{"pseudo": k, "cat": cat_of.get(k, "?"), "nom": nom_of.get(k, ""), "n": n} for k, n in r.remplacements.items()],
                "sensibles": r.sensibles, "champs": r.champs, "codes": r.codes_remplaces, "non_cochees": r.non_cochees,
                "alertes": r.alertes, "residuels": r.residuels, "prenoms": r.prenoms})
        consigne = consigne_claude(p)
        for fname, text in (("CONSIGNE-CLAUDE.txt", consigne), ("RAPPORT-PSEUDONYMISATION.txt", report_text(s.code, produced, p, getpass.getuser()))):
            path = self._unique_path(out_dir / fname)
            self._write_new(path, text.encode("utf-8"))
            files.append(path.name)
        s.save(int(self.cfg.get("versions_keep") or 50))
        return {"resultats": results, "consigne": consigne, "dossier_sortie": diagnostic.mask(out_dir), "fichiers": files}
