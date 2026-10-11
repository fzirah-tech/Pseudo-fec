"""Parcours réel dans Chromium (ignoré si Playwright ou le navigateur sont absents)."""
import threading
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

from conftest import TEST_PASS  # noqa: E402
from pseudo_fec.ui.server import PseudoFecServer  # noqa: E402
from synth import make_fec  # noqa: E402

CANDIDATS = ["/opt/pw-browsers/chromium-1194/chrome-linux/chrome", "/opt/pw-browsers/chromium/chrome-linux/chrome"]


def test_parcours_navigateur(cfg, tmp_path):
    exe = next((c for c in CANDIDATS if Path(c).exists()), None)
    if exe is None:
        pytest.skip("Chromium introuvable")
    srv = PseudoFecServer(cfg)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    f = tmp_path / "fec.txt"
    f.write_bytes(make_fec("cabinet", "cp1252").data)
    erreurs = []
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
            pg = b.new_page()
            pg.on("pageerror", lambda e: erreurs.append(str(e)))
            pg.on("console", lambda m: m.type == "error" and erreurs.append(m.text))
            pg.goto(srv.url)
            pg.fill("#pp", TEST_PASS); pg.fill("#pp2", TEST_PASS); pg.click("text=Déverrouiller")
            pg.fill("#code", "D2025-001"); pg.click("text=Créer la fiche dossier")
            pg.wait_for_selector("h1:has-text('Fiche dossier')")      # régression : renvoyait à l'accueil
            pg.locator("input").nth(0).fill("ATELIERS DU PORT SAS")
            pg.click("text=Créer le dossier")
            pg.wait_for_selector("h1:has-text('Import et contrôle')")
            pg.set_input_files("input[type=file]", [str(f)])
            pg.wait_for_selector("text=Contrôles passés", timeout=20000)
            b.close()
    finally:
        srv.shutdown()
    assert erreurs == []
