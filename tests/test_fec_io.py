from decimal import Decimal

import pytest

from pseudo_fec.config import DEFAULT_CABINET
from pseudo_fec.errors import FecFormatError
from pseudo_fec.fec_io import (CANON, analyse, date_kind, detect_encoding, filename_info,
                               parse_amount, parse_fec)
from synth import SIREN, make_fec

PREF = DEFAULT_CABINET["priority_prefixes"]


@pytest.mark.parametrize("style,enc,bom,sep", [
    ("standard", "utf-8", False, "\t"), ("standard", "utf-8", True, "\t"),
    ("standard", "utf-8", False, "|"), ("cabinet", "cp1252", False, "\t"),
    ("pennylane", "iso-8859-15", False, "\t"), ("pennylane", "utf-8", False, "|"),
])
def test_lecture_controle_et_reecriture_identique(style, enc, bom, sep):
    s = make_fec(style, enc, bom=bom, sep=sep)
    f = parse_fec(s.data, s.filename)
    r = analyse(f, PREF, SIREN)
    assert r["lignes"] == s.n_lines
    assert Decimal(r["total_debit"]) == Decimal(r["total_credit"]) == s.total
    assert r["equilibre"] and not r["bloquant"]
    assert r["siren_controle"] == "concordant"
    assert r["exercice"] == "2024"
    assert f.serialize(f.rows()) == s.data          # même séparateur, encodage, fins de ligne, BOM


def test_particularites_du_format_cabinet():
    s = make_fec("cabinet", "cp1252")
    r = analyse(parse_fec(s.data, s.filename), PREF)
    assert r["formats_dates"]["EcritureDate"] == "JJ/MM/AAAA" and r["formats_dates"]["PieceDate"] == "AAAAMMJJ"
    codes = {i["code"] for i in r["issues"]}
    assert {"ENTETES_VARIANTES", "DATE_HORS_NORME"} <= codes
    assert r["newline"] == "CRLF"


def test_modes_de_tiers_par_classe():
    std = analyse(parse_fec(make_fec("standard").data, "x"), PREF)["classes_tiers"]
    assert std["tiers_commerciaux"]["mode"] == "auxiliaire"
    assert std["personnel"]["mode"] == "compte / libellé"
    penny = analyse(parse_fec(make_fec("pennylane").data, "x"), PREF)["classes_tiers"]
    assert penny["tiers_commerciaux"]["mode"] == "compte / libellé" and penny["tiers_commerciaux"]["comptes"] > 3


def test_montants_formats_reels():
    assert parse_amount("-") == 0 and parse_amount("") == 0
    assert parse_amount("1 234,56") == Decimal("1234.56")
    assert parse_amount("1 234,56") == Decimal("1234.56")
    assert parse_amount("1234.5") == Decimal("1234.5")
    assert parse_amount("1.234,56") == Decimal("1234.56")
    assert parse_amount("-12,5") == Decimal("-12.5")
    assert parse_amount("12abc") is None


def test_formats_de_date():
    assert date_kind("20241231") == "AAAAMMJJ" and date_kind("31/12/2024") == "JJ/MM/AAAA"
    assert date_kind("2024-12-31") == "AAAA-MM-JJ" and date_kind("abc") is None


def test_detection_encodage():
    assert detect_encoding("é".encode("utf-8")) == ("utf-8", False)
    assert detect_encoding(b"\xef\xbb\xbfabc") == ("utf-8", True)
    assert detect_encoding("é".encode("cp1252"))[0] == "cp1252"
    assert detect_encoding("œ".encode("iso-8859-15"))[0] == "iso-8859-15"


def test_siren_du_nom_de_fichier():
    assert filename_info(f"{SIREN}FEC20241231.txt") == (SIREN, "20241231")
    assert filename_info(f"abc-{SIREN}FEC20241231.txt")[0] == SIREN
    assert filename_info("export.txt") == (None, None)


def test_siren_different_bloquant():
    s = make_fec()
    r = analyse(parse_fec(s.data, s.filename), PREF, "123456782")
    assert r["siren_controle"] == "DIFFÉRENT" and r["bloquant"]


def test_colonne_essentielle_manquante():
    s = make_fec()
    lines = s.data.decode().split("\n")
    lines[0] = lines[0].replace("EcritureLib", "Autre")
    with pytest.raises(FecFormatError) as e:
        parse_fec("\n".join(lines).encode())
    assert "EcritureLib" in str(e.value)


def test_message_derreur_sans_donnee():
    with pytest.raises(FecFormatError) as e:
        parse_fec("DUPONT BATIMENT\nMARTINEZ\n".encode())
    assert "DUPONT" not in str(e.value) and "MARTINEZ" not in str(e.value)
    with pytest.raises(FecFormatError):
        parse_fec(b"   \n")


def test_desequilibre_et_ligne_mal_formee():
    s = make_fec()
    lines = s.data.decode().split("\n")
    cells = lines[1].split("\t"); cells[11] = "999999,00"; lines[1] = "\t".join(cells)
    lines[2] = "\t".join(lines[2].split("\t")[:10])
    r = analyse(parse_fec("\n".join(lines).encode()), PREF)
    codes = {i["code"] for i in r["issues"]}
    assert not r["equilibre"] and "DESEQUILIBRE" in codes and "NB_COLONNES" in codes and r["bloquant"]


def test_variantes_dentetes_tolerees():
    s = make_fec()
    text = s.data.decode().replace("EcritureLet", "ecriturelet", 1).replace("Idevise", "Devise", 1)
    r = analyse(parse_fec(text.encode()), PREF)
    assert not r["bloquant"]


def test_lignes_vides_signalees():
    s = make_fec()
    r = analyse(parse_fec(s.data + b"\n\n"), PREF)
    assert any(i["code"] == "LIGNES_VIDES" for i in r["issues"]) and r["lignes"] == s.n_lines


def test_rapport_sans_nom_de_tiers():
    for st, enc in (("standard", "utf-8"), ("cabinet", "cp1252"), ("pennylane", "utf-8")):
        s = make_fec(st, enc)
        blob = repr(analyse(parse_fec(s.data, s.filename), PREF))
        for n in s.names:
            assert n not in blob


def test_18_colonnes_normees():
    assert len(CANON) == 18
