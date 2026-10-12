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
    synth = make_fec("cabinet", "cp1252", n_entries=120)
    f = tmp_path / synth.filename                                 # nom conforme : SIRENFECAAAAMMJJ.txt
    f.write_bytes(synth.data)
    erreurs = []
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
            pg = b.new_page()
            pg.on("pageerror", lambda e: erreurs.append(str(e)))
            pg.on("console", lambda m: m.type == "error" and erreurs.append(m.text))
            pg.goto(srv.url)
            pg.fill("#pp", TEST_PASS); pg.fill("#pp2", TEST_PASS); pg.click("text=Déverrouiller")
            pg.fill("#code", "D2025-001"); pg.click("text=Créer le dossier et importer le FEC")   # aucune fiche à saisir
            pg.wait_for_selector("h1:has-text('Import et contrôle')")
            pg.set_input_files("input[type=file]", [str(f)])
            pg.wait_for_selector("text=Contrôles passés", timeout=20000)
            pg.click("text=Détecter et proposer les noms")
            pg.wait_for_selector(".nrow", timeout=20000)
            assert pg.locator(".nrow").count() >= 8
            pw.expect(pg.locator("text=La société n'est pas encore identifiée")).to_be_visible()
            assert pg.locator("#soc-siren").input_value() == "732829320"                      # SIREN lu dans le nom du fichier
            pg.locator(".chips button").first.click()                                          # proposition de raison sociale
            assert pg.locator("#soc-rs").input_value() != ""
            pg.click("text=Valider la société")
            pw.expect(pg.locator("text=✓ Société")).to_be_visible()
            assert "SOC-0001" in pg.locator("main").inner_text()
            assert "à pseudonymiser" in pg.locator("#stat").inner_text()
            assert "false" not in pg.locator("main").inner_text()
            # synthèse des noms relevés, par type d'écriture
            pw.expect(pg.locator("text=Synthèse des noms relevés, à valider")).to_be_visible()
            for libelle in ("Libellés de paie", "Comptes courants et groupe", "Provisions"):
                pw.expect(pg.locator("td, th", has_text=libelle).first).to_be_visible()
            pg.locator("tr", has_text="Libellés de paie").get_by_text("Voir").click()
            assert pg.locator(".nrow").count() >= 3
            pg.click("text=Appliquer tous les regroupements")
            pg.fill("input[type=search]", "benali")
            pw.expect(pg.locator(".nrow")).to_have_count(1)   # « Karim BENALI » et « BENALI Karim » fusionnés
            pg.locator("summary", has_text="Détails").first.click()
            pw.expect(pg.locator("text=Parties identifiantes du nom").first).to_be_visible()
            pg.fill("input[type=search]", "")
            pw.expect(pg.locator(".nrow")).not_to_have_count(1)
            pg.click("text=Enregistrer les décisions")
            pg.wait_for_selector("text=enregistrée(s) dans la table chiffrée", timeout=20000)
            # jalon (c) : l'étape « Pseudonymisation » est accessible après l'enregistrement
            pw.expect(pg.locator("button.step", has_text="4 · Pseudonymisation")).to_be_enabled()
            pg.click("text=Continuer : pseudonymiser le FEC")
            pg.wait_for_selector("h1:has-text('Pseudonymisation du FEC')")
            pw.expect(pg.locator("#btn-pseudo")).to_be_enabled()
            pg.click("#btn-pseudo")
            pw.expect(pg.locator("text=fichier(s) pseudonymisé(s) dans")).to_be_visible(timeout=30000)
            pw.expect(pg.locator("text=contrôles bloquants passés")).to_be_visible()
            pw.expect(pg.locator("text=Consigne à coller dans Claude")).to_be_visible()
            assert "CAT-0000" in pg.locator("textarea.consigne").input_value()
            assert "false" not in pg.locator("main").inner_text()
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
