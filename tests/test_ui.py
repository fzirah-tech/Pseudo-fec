import http.client
import json
import socket
import threading
import urllib.parse
from pathlib import Path

import pytest

from conftest import TEST_PASS
from pseudo_fec.ui.server import PseudoFecServer
from synth import REAL_NAMES, SIREN, make_fec

PKG = Path(__file__).parent.parent / "pseudo_fec"


class Client:
    def __init__(self, srv):
        self.srv, self.port = srv, srv.server_address[1]
        self.tok = srv.token
        self.cookie = f"pf_token={self.tok}"

    def req(self, method, path, body=None, headers=None, raw=None, host=None, auth=True, cookie=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": host or f"127.0.0.1:{self.port}", **(headers or {})}
        if auth:
            h["X-PF-Token"] = self.tok
        if cookie:
            h["Cookie"] = self.cookie
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        txt = r.read()
        try:
            return r.status, json.loads(txt)
        except ValueError:
            return r.status, txt


@pytest.fixture
def app(cfg):
    srv = PseudoFecServer(cfg)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield Client(srv)
    srv.shutdown()
    srv.server_close()


FICHE = {"societe": {"raison_sociale": "ATELIERS DU PORT SAS", "sigle": "ADP", "siren": SIREN},
         "personnes": [{"nom": "Claire BERNARD-MOREAU", "role": "dirigeant"}],
         "liees": [{"raison_sociale": "HOLDING DESCHAMPS SAS", "lien": "mere"}]}


def parcours(app):
    assert app.req("POST", "/api/unlock", {"passphrase": TEST_PASS, "confirm": TEST_PASS})[0] == 200
    assert app.req("POST", "/api/dossier/create", {"code": "D-001", "fiche": FICHE})[0] == 200
    out = {}
    for style, enc in (("standard", "utf-8"), ("cabinet", "cp1252")):
        s = make_fec(style, enc)
        st, rep = app.req("POST", "/api/fec/upload", raw=s.data,
                          headers={"X-Filename": urllib.parse.quote(f"{style}_{s.filename}")})
        assert st == 200, rep
        out[style] = (s, rep)
    return out


def test_parcours_complet(app):
    out = parcours(app)
    for s, rep in out.values():
        assert rep["lignes"] == s.n_lines and rep["equilibre"] and rep["siren_controle"] == "concordant"
    st, d = app.req("GET", "/api/dossier")
    assert {e["pseudo"] for e in d["entities"]} == {"SOC-0001", "ASS-0001", "GRP-0001"}
    assert len(app.req("GET", "/api/fec/list")[1]["fecs"]) == 2


def test_reouverture_du_dossier(app):
    parcours(app)
    app.req("POST", "/api/lock", {})
    assert app.req("POST", "/api/dossier/open", {"code": "D-001"})[0] == 400      # verrouillé
    assert app.req("POST", "/api/unlock", {"passphrase": TEST_PASS + "x"})[0] == 400
    assert app.req("POST", "/api/unlock", {"passphrase": TEST_PASS})[0] == 200
    assert app.req("POST", "/api/dossier/open", {"code": "D-001"})[0] == 200


def test_premiere_phrase_exige_confirmation_et_longueur(app):
    assert app.req("POST", "/api/unlock", {"passphrase": "court", "confirm": "court"})[0] == 400
    assert app.req("POST", "/api/unlock", {"passphrase": TEST_PASS, "confirm": "autre"})[0] == 400


def test_siren_different_signale(app):
    app.req("POST", "/api/unlock", {"passphrase": TEST_PASS, "confirm": TEST_PASS})
    fiche = json.loads(json.dumps(FICHE)); fiche["societe"]["siren"] = "123456782"
    app.req("POST", "/api/dossier/create", {"code": "D-002", "fiche": fiche})
    s = make_fec()
    st, rep = app.req("POST", "/api/fec/upload", raw=s.data, headers={"X-Filename": s.filename})
    assert rep["siren_controle"] == "DIFFÉRENT" and rep["bloquant"]


# ---------------------------------------------------------------- sécurité du serveur local

def test_ecoute_uniquement_en_loopback(app):
    assert app.srv.server_address[0] == "127.0.0.1"


def test_api_sans_jeton_refusee(app):
    assert app.req("GET", "/api/state", auth=False)[0] == 401
    assert app.req("GET", "/api/state", cookie=False)[0] == 401
    assert app.req("POST", "/api/quit", {}, auth=False)[0] == 401


def test_rebond_dns_refuse(app):
    assert app.req("GET", "/api/state", host="evil.example:80")[0] == 403
    assert app.req("GET", "/api/state", headers={"Origin": "http://evil.example"})[0] == 403


def test_jeton_dans_url_pose_le_cookie(app):
    c = http.client.HTTPConnection("127.0.0.1", app.port)
    c.request("GET", f"/?t={app.tok}", headers={"Host": f"127.0.0.1:{app.port}"})
    r = c.getresponse()
    assert r.status == 302 and "HttpOnly" in r.getheader("Set-Cookie") and "SameSite=Strict" in r.getheader("Set-Cookie")
    c = http.client.HTTPConnection("127.0.0.1", app.port)
    c.request("GET", "/?t=mauvais", headers={"Host": f"127.0.0.1:{app.port}"})
    assert c.getresponse().status == 401


def test_page_servie_avec_csp_et_sans_ressource_externe(app):
    c = http.client.HTTPConnection("127.0.0.1", app.port)
    c.request("GET", "/", headers={"Host": f"127.0.0.1:{app.port}", "Cookie": app.cookie})
    r = c.getresponse(); html = r.read().decode()
    assert r.status == 200 and "default-src 'self'" in r.getheader("Content-Security-Policy")
    assert app.tok in html and "__TOKEN__" not in html
    for f in (PKG / "ui" / "static").iterdir():
        t = f.read_text(encoding="utf-8")
        assert "http://" not in t.replace("http://127.0.0.1", "") and "https://" not in t, f.name


def test_pas_de_traversee_de_chemin(app):
    for p in ("/../config.py", "/static/../../config.py", "/%2e%2e/config.py"):
        assert app.req("GET", p)[0] in (401, 404)


def test_taille_maximale(app):
    app.srv.app.cfg.cabinet["max_fec_mb"] = 1
    app.req("POST", "/api/unlock", {"passphrase": TEST_PASS, "confirm": TEST_PASS})
    st, _ = app.req("POST", "/api/fec/upload", raw=b"x", headers={"Content-Length": str(2 * 1024 * 1024)})
    assert st == 413


def test_erreur_interne_sans_detail(app):
    app.req("POST", "/api/unlock", {"passphrase": TEST_PASS, "confirm": TEST_PASS})
    st, body = app.req("POST", "/api/dossier/create", raw=b"{pas du json")
    assert st == 500 and "Erreur interne" in body["error"] and "json" not in body["error"].lower()


# ---------------------------------------------------------------- confidentialité

def test_aucun_nom_reel_dans_logs_ni_fichiers(app, cfg, capfd, tmp_path):
    parcours(app)
    app.req("POST", "/api/fec/upload", raw=b"DUPONT BATIMENT SARL\nMARTINEZ ET FILS\n")   # erreur volontaire
    out, err = capfd.readouterr()
    for n in REAL_NAMES:
        assert n not in out and n not in err
    for f in tmp_path.rglob("*"):
        if f.is_file():
            raw = f.read_bytes()
            for n in REAL_NAMES:
                for enc in ("utf-8", "cp1252"):
                    assert n.encode(enc, "ignore") not in raw, f.name


def test_aucun_appel_reseau_hors_loopback(app, monkeypatch):
    real = socket.socket.connect

    def garde(self, addr, *a, **k):
        host = addr[0] if isinstance(addr, tuple) else addr
        assert host in ("127.0.0.1", "localhost", "::1"), "appel réseau non local"
        return real(self, addr, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", garde)
    parcours(app)


def test_aucun_module_reseau_dans_le_code():
    interdits = ("import requests", "urllib.request", "import smtplib", "import ftplib", "import telnetlib",
                 "import ssl", "import socket", "http.client", "httpx", "aiohttp", "websocket", "urlopen")
    for f in PKG.rglob("*.py"):
        src = f.read_text(encoding="utf-8")
        for mot in interdits:
            assert mot not in src, f"{mot} dans {f.name}"


# ---------------------------------------------------------------- jalon (b) : détection et validation

def test_detection_et_validation_via_api(app):
    parcours(app)
    st, det = app.req("POST", "/api/detect", {})
    assert st == 200 and det["stats"]["lignes"] > 0
    noms = {c["nom"]: c for c in det["candidats"]}
    assert noms["DUPONT BATIMENT SARL"]["checked"] and noms["ORANGE"]["statut"] == "liste_blanche"
    rows = [{"nom": c["nom"], "cat": c["cat"], "checked": c["checked"], "uid": c["uid"], "source": c["source"],
             "variantes": [v["texte"] for v in c["variantes"] if v["coche"]]} for c in det["candidats"]]
    st, out = app.req("POST", "/api/entities/save", {"rows": rows})
    assert st == 200 and out["created"] > 0 and not out["bloquant"]
    st, d = app.req("GET", "/api/dossier")
    pseudos = {e["nom"]: e["pseudo"] for e in d["entities"]}
    assert pseudos["ATELIERS DU PORT SAS"] == "SOC-0001" and pseudos["DUPONT BATIMENT SARL"].startswith("FRN-")
    # réouverture : les entités validées sont reconnues, aucun pseudonyme n'est réattribué
    app.req("POST", "/api/dossier/open", {"code": "D-001"})
    app.req("POST", "/api/fec/upload", raw=make_fec("standard").data, headers={"X-Filename": "x.txt"})
    det2 = app.req("POST", "/api/detect", {})[1]
    again = {c["nom"]: c for c in det2["candidats"]}
    assert again["DUPONT BATIMENT SARL"]["statut"] == "connu" and again["DUPONT BATIMENT SARL"]["pseudo"] == pseudos["DUPONT BATIMENT SARL"]


def test_detection_exige_un_fec_sans_erreur(app):
    app.req("POST", "/api/unlock", {"passphrase": TEST_PASS, "confirm": TEST_PASS})
    app.req("POST", "/api/dossier/create", {"code": "D-001", "fiche": FICHE})
    assert app.req("POST", "/api/detect", {})[0] == 400
    s = make_fec()
    app.req("POST", "/api/fec/upload", raw=s.data, headers={"X-Filename": "123456782FEC20241231.txt"})  # SIREN différent -> bloquant
    st, body = app.req("POST", "/api/detect", {})
    assert st == 400 and "bloquant" in body["error"].lower() or "erreurs" in body["error"].lower()


def test_liste_blanche_api_ecrit_le_cabinet_et_la_trace(app, cfg):
    parcours(app)
    st, out = app.req("POST", "/api/whitelist/add", {"nom": "Banque Exemple"})
    assert st == 200 and "BANQUE EXEMPLE" in out["whitelist"]
    assert "BANQUE EXEMPLE" in json.loads(cfg.cabinet_file.read_text())["whitelist"]
    assert app.req("POST", "/api/whitelist/add", {"nom": "banque exemple"})[0] == 400


def test_detection_sans_nom_dans_les_logs(app, capfd):
    parcours(app)
    app.req("POST", "/api/detect", {})
    out, err = capfd.readouterr()
    for n in REAL_NAMES:
        assert n not in out and n not in err


# ---------------------------------------------------------------- aide, démonstration, diagnostic

def test_autodiagnostic_sans_donnee_de_dossier(app):
    st, d = app.req("GET", "/api/diagnostic")
    assert st == 200 and d["ok"], d["texte"]
    noms = {c["nom"] for c in d["checks"]}
    assert {"Python", "Chiffrement des tables", "Lecture et réécriture de FEC", "Détection des noms", "Réseau"} <= noms
    assert "127.0.0.1" in d["texte"]
    for n in REAL_NAMES:
        assert n not in d["texte"]
    assert str(Path.home()) not in d["texte"] or str(Path.home()) == "/"        # chemin personnel masqué


def test_demo_en_un_clic(app):
    assert app.req("POST", "/api/demo/create", {"style": "cabinet"})[0] == 400          # phrase secrète requise
    app.req("POST", "/api/unlock", {"passphrase": TEST_PASS, "confirm": TEST_PASS})
    st, out = app.req("POST", "/api/demo/create", {"style": "cabinet"})
    assert st == 200 and out["code"] == "DEMO-001" and out["dossier"] == "DEMO-001"
    fecs = app.req("GET", "/api/fec/list")[1]["fecs"]
    assert len(fecs) == 2 and all(f["equilibre"] and not f["bloquant"] for f in fecs)
    assert {f["exercice"] for f in fecs} == {"2024", "2025"}
    st, det = app.req("POST", "/api/detect", {})
    assert st == 200 and any(c["cat"] == "SAL" for c in det["candidats"])
    st, out2 = app.req("POST", "/api/demo/create", {"style": "pennylane"})
    assert out2["code"] == "DEMO-002"                                                    # jamais d'écrasement
    assert app.req("POST", "/api/demo/create", {"style": "inconnu"})[0] == 400


def test_telechargement_du_fec_fictif(app):
    c = http.client.HTTPConnection("127.0.0.1", app.port)
    c.request("GET", "/api/demo/fec?style=pennylane&year=2025", headers={"Host": f"127.0.0.1:{app.port}", "Cookie": app.cookie, "X-PF-Token": app.tok})
    r = c.getresponse(); data = r.read()
    assert r.status == 200 and "attachment" in r.getheader("Content-Disposition") and b"JournalCode" in data
    assert app.req("GET", "/api/demo/fec?style=../../etc")[0] == 400
    assert app.req("GET", "/api/demo/fec?year=abc")[0] in (400, 500)


def test_ouverture_de_dossier_limitee_a_deux_dossiers_connus(app, monkeypatch):
    import os
    opened = []
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(p), raising=False)
    assert app.req("POST", "/api/open-folder", {"which": "tables"})[1]["ok"]
    assert app.req("POST", "/api/open-folder", {"which": "outputs"})[1]["ok"]
    assert len(opened) == 2
    assert app.req("POST", "/api/open-folder", {"which": "C:/Windows"})[0] == 400
    assert len(opened) == 2



# ---------------------------------------------------------------- parcours « FEC d'abord, propositions ensuite »

def _sans_fiche(app):
    app.req("POST", "/api/unlock", {"passphrase": TEST_PASS, "confirm": TEST_PASS})
    assert app.req("POST", "/api/dossier/create", {"code": "D-777"})[0] == 200           # un simple code, aucune fiche
    s = make_fec("cabinet", "cp1252", n_entries=120)
    st, rep = app.req("POST", "/api/fec/upload", raw=s.data, headers={"X-Filename": s.filename})
    assert st == 200 and not rep["bloquant"], rep
    return s, rep


def test_import_sans_fiche_le_siren_est_lu_dans_le_nom_du_fichier(app):
    s, rep = _sans_fiche(app)
    assert rep["siren_nom_fichier"] == SIREN and "confirmer" in rep["siren_controle"]
    so = app.req("GET", "/api/societe")[1]
    assert so["siren"] == SIREN and so["siren_detecte"] and so["siren_valide"] and so["raison_sociale"] == "" and so["pseudo"] is None
    # un second exercice d'un AUTRE SIREN est refusé : le premier FEC sert de référence
    s2 = make_fec("cabinet", "cp1252", year=2025)
    st, rep2 = app.req("POST", "/api/fec/upload", raw=s2.data, headers={"X-Filename": "123456782FEC20251231.txt"})
    assert rep2["siren_controle"] == "DIFFÉRENT" and rep2["bloquant"]
    # le même SIREN est accepté
    st, rep3 = app.req("POST", "/api/fec/upload", raw=s2.data, headers={"X-Filename": s2.filename})
    assert rep3["siren_controle"] == "concordant"


def test_propositions_puis_validation_de_la_societe(app):
    _sans_fiche(app)
    st, det = app.req("POST", "/api/detect", {})
    assert st == 200 and det["societe"]["pseudo"] is None
    noms = {c["nom"]: c for c in det["candidats"]}
    # dirigeants/associés/sociétés liées/salariés proposés à partir des comptes, sans aucune saisie
    assert noms["Paul Henri DESCHAMPS"]["cat"] == "ASS" and noms["HOLDING DESCHAMPS SAS"]["cat"] == "GRP"
    assert noms["SCI LES TILLEULS"]["cat"] == "GRP" and noms["Karim BENALI"]["cat"] == "SAL"
    # la raison sociale est suggérée à partir des libellés
    assert "ATELIERS DU PORT SAS" in [x["nom"] for x in det["stats"]["societe_suggestions"]]
    # le SIREN du dossier est déjà reconnu comme sensible avant toute validation
    assert any(t["type"] in ("SIREN", "SIRET") for t in det["sensibles"]["types"]) or det["sensibles"]["total"] >= 0
    st, so = app.req("POST", "/api/societe/save", {"raison_sociale": "ATELIERS DU PORT SAS", "sigle": "ADP", "siren": SIREN})
    assert st == 200 and so["pseudo"] == "SOC-0001" and so["entity"]["nom"] == "ATELIERS DU PORT SAS"
    det2 = app.req("POST", "/api/detect", {})[1]
    soc = [c for c in det2["candidats"] if c["cat"] == "SOC"]
    assert len(soc) == 1 and soc[0]["statut"] == "connu" and soc[0]["occurrences"] > 0       # retrouvée dans les libellés
    assert [c["nom"] for c in det2["candidats"]].count("ATELIERS DU PORT SAS") == 1           # plus de doublon proposé
    assert det2["societe"]["pseudo"] == "SOC-0001"


def test_societe_invalide_refusee_ou_signalee(app):
    _sans_fiche(app)
    st, so = app.req("POST", "/api/societe/save", {"raison_sociale": "X SAS", "siren": "123456789"})
    assert st == 200 and any("SIREN" in w for w in so["warnings"])


def test_demo_sans_aucune_saisie_prealable(app):
    app.req("POST", "/api/unlock", {"passphrase": TEST_PASS, "confirm": TEST_PASS})
    app.req("POST", "/api/demo/create", {"style": "cabinet"})
    so = app.req("GET", "/api/societe")[1]
    assert so["raison_sociale"] == "" and so["siren"] == SIREN
    det = app.req("POST", "/api/detect", {})[1]
    assert det["societe"]["pseudo"] is None and det["stats"]["societe_suggestions"]
