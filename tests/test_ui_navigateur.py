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
            # jalon (b) : détection des noms, fusion proposée, enregistrement
            pg.click("text=Passer à la détection des noms")
            pg.wait_for_selector(".nrow", timeout=20000)
            assert pg.locator(".nrow").count() >= 8
            assert "à pseudonymiser" in pg.locator("#stat").inner_text()
            assert "false" not in pg.locator("main").inner_text()
            pg.click("text=Appliquer tous les regroupements")
            pg.fill("input[type=search]", "benali")
            pw.expect(pg.locator(".nrow")).to_have_count(1)   # « Karim BENALI » et « BENALI Karim » fusionnés
            pg.fill("input[type=search]", "")
            pw.expect(pg.locator(".nrow")).not_to_have_count(1)
            pg.click("text=Enregistrer les décisions")
            pg.wait_for_selector("text=enregistrée(s) dans la table chiffrée", timeout=20000)
            b.close()
    finally:
        srv.shutdown()
    assert erreurs == []


def test_aide_diagnostic_et_demo_en_un_clic(cfg):
    exe = next((c for c in CANDIDATS if Path(c).exists()), None)
    if exe is None:
        pytest.skip("Chromium introuvable")
    srv = PseudoFecServer(cfg)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    erreurs = []
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
            pg = b.new_page()
            pg.on("pageerror", lambda e: erreurs.append(str(e)))
            pg.goto(srv.url)
            pg.wait_for_selector("#pp")
            pg.click("#btn-help")                                               # l'aide est accessible avant la phrase secrète
            pg.wait_for_selector("h1:has-text('Aide et test')")
            pg.click("text=Lancer l'auto-diagnostic")
            pw.expect(pg.locator("text=Tout fonctionne")).to_be_visible(timeout=30000)
            pg.click("#btn-help")                                               # retour
            pg.wait_for_selector("#pp")
            pg.fill("#pp", TEST_PASS); pg.fill("#pp2", TEST_PASS); pg.click("text=Déverrouiller")
            pg.wait_for_selector("h1:has-text('Dossiers')")
            pg.click("#btn-help"); pg.wait_for_selector("h1:has-text('Aide et test')")
            pg.click("text=Lancer la démo >> nth=0")
            pg.wait_for_selector("h1:has-text('Import et contrôle')", timeout=30000)
            pw.expect(pg.locator("text=Contrôles passés")).to_have_count(2, timeout=10000)
            b.close()
    finally:
        srv.shutdown()
    assert erreurs == []
