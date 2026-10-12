from pseudo_fec.fec_io import CANON, parse_fec


def mini(lines, sep="\t"):
    """lines : (journal, num, compte, libelle_compte, aux, libelle_aux, libelle, debit, credit)"""
    head = sep.join(CANON)
    rows = []
    for i, (j, num, cpt, cptl, aux, auxl, lib, d, c) in enumerate(lines):
        rows.append(sep.join([j, j, str(num), "20240131", cpt, cptl, aux, auxl, f"P{i}", "20240131", lib, d, c, "", "", "20240131", "", ""]))
    return parse_fec(("\n".join([head, *rows]) + "\n").encode(), "x")
