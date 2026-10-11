from pseudo_fec.textmatch import NameMatcher, fold_text, name_key


def spans(m, text):
    return [(text[a:b], k) for a, b, k in m.find(text)]


def test_limites_de_mots():
    m = NameMatcher([("MARTIN", "m"), ("MARTINEZ ET FILS", "mz")])
    assert spans(m, "FACT MARTINEZ ET FILS 12") == [("MARTINEZ ET FILS", "mz")]
    assert spans(m, "MARTINEZ seul") == []
    assert spans(m, "amartin") == [] and spans(m, "martini") == []
    assert spans(m, "vir martin ok") == [("martin", "m")]


def test_casse_accents_espaces_multiples():
    m = NameMatcher([("Dupont Bâtiment", "db")])
    for t in ("DUPONT BATIMENT", "dupont   batiment", "Dupont-Bâtiment", "DUPONT\tBATIMENT"):
        assert spans(m, t) == [(t, "db")], t


def test_variante_la_plus_longue_prioritaire():
    m = NameMatcher([("DUPONT", "d"), ("DUPONT BATIMENT SARL", "db")])
    assert spans(m, "REGL DUPONT BATIMENT SARL FACT") == [("DUPONT BATIMENT SARL", "db")]
    assert spans(m, "REGL DUPONT SEUL") == [("DUPONT", "d")]


def test_positions_conservees_apres_normalisation():
    for s in ("Œuvre É à ç", "ÉTABLISSEMENTS LEFÈVRE-DUBOIS", "straße"):
        assert len(fold_text(s)) == len(s)


def test_ligature_et_apostrophe():
    m = NameMatcher([("ŒUVRES DU SUD", "o"), ("N'Guyen", "n")])
    assert spans(m, "OEUVRES DU SUD") == [("OEUVRES DU SUD", "o")]
    assert spans(m, "ŒUVRES DU SUD") == [("ŒUVRES DU SUD", "o")]
    assert [k for _, k in spans(m, "paie N'GUYEN et n guyen")] == ["n", "n"]


def test_remplacement_ne_touche_que_le_nom():
    m = NameMatcher([("Karim BENALI", "KB")])
    out, n = m.replace("SALAIRE 01/2024  karim   benali (net)", lambda k, s: f"<{k}>")
    assert out == "SALAIRE 01/2024  <KB> (net)" and n == 1


def test_conflit_meme_texte_deux_entites():
    m = NameMatcher([("MARTIN", "a"), ("Martin", "b")])
    assert list(m.conflicts.values()) == [["a", "b"]]


def test_name_key_ignore_forme_juridique_et_ordre():
    assert name_key("SARL DUPONT") == name_key("DUPONT SARL") == name_key("Dupont")
    assert name_key("Karim BENALI") == name_key("BENALI Karim")
    assert name_key("MARTIN") != name_key("MARTINEZ ET FILS")
