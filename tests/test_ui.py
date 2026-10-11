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
