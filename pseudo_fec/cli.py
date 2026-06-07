"""Interface en ligne de commande de pseudo-fec (100 % local, hors-ligne)."""

from __future__ import annotations

import argparse
import os
import sys

from .mapping import Mapping
from .pseudonymize import Pseudonymizer, read_fec, write_fec
from .reidentify import reidentify_file
from .verify import verify

LOCAL_MAPPING_DIR = "_local_mapping"

WARNING_MAPPING = (
    "\n  ⚠ Le fichier de correspondance contient les NOMS RÉELS.\n"
    "    Conservez-le en local. NE LE TRANSMETTEZ JAMAIS dans le cloud\n"
    "    (dossier {dir}/ à exclure de toute synchronisation)."
)


def _resolve_mapping_path(map_arg, dossier, exercice):
    if map_arg:
        path = map_arg
    else:
        parts = ["mapping"]
        if dossier:
            parts.append(str(dossier))
        if exercice:
            parts.append(str(exercice))
        path = "_".join(parts) + ".csv"
    # Sans répertoire explicite, on place le mapping dans _local_mapping/.
    if not os.path.dirname(path):
        path = os.path.join(LOCAL_MAPPING_DIR, path)
    return path


def cmd_pseudonymize(args) -> int:
    if not os.path.exists(args.input):
        print(f"Erreur : fichier introuvable : {args.input}", file=sys.stderr)
        return 1

    map_path = _resolve_mapping_path(args.map, args.dossier, args.exercice)
    os.makedirs(os.path.dirname(os.path.abspath(map_path)) or ".", exist_ok=True)

    fec = read_fec(args.input)
    mapping = Mapping.load(map_path)  # incrémental : réutilise l'existant.
    if args.dossier:
        mapping.meta["dossier"] = args.dossier
    if args.exercice:
        mapping.meta["exercice"] = args.exercice
    mapping.meta["source_file"] = os.path.basename(args.input)

    pseudo = Pseudonymizer(
        include_pieceref=args.include_pieceref, ascii_mode=args.ascii
    )
    fec_out, mapping = pseudo.run(fec, mapping)

    write_fec(fec_out, args.out)
    mapping.save(map_path)

    by_type = {}
    for e in mapping.entries.values():
        by_type[e.type] = by_type.get(e.type, 0) + 1
    print(f"FEC pseudonymisé        : {args.out}")
    print(f"Mapping (CSV + JSON)    : {map_path}")
    print(f"Tiers / entités         : {len(mapping.entries)}")
    if by_type:
        print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(by_type.items())))
    print(WARNING_MAPPING.format(dir=LOCAL_MAPPING_DIR))
    return 0


def cmd_reidentify(args) -> int:
    if not os.path.exists(args.map):
        print(f"Erreur : mapping introuvable : {args.map}", file=sys.stderr)
        return 1
    if not os.path.exists(args.input):
        print(f"Erreur : fichier introuvable : {args.input}", file=sys.stderr)
        return 1

    mapping = Mapping.load(args.map)
    out_path, n = reidentify_file(args.input, mapping, args.out)
    print(f"Document ré-identifié    : {out_path}  ({n} élément(s) modifié(s))")
    return 0


def cmd_verify(args) -> int:
    if not os.path.exists(args.map):
        print(f"Erreur : mapping introuvable : {args.map}", file=sys.stderr)
        return 1
    if not os.path.exists(args.input):
        print(f"Erreur : fichier introuvable : {args.input}", file=sys.stderr)
        return 1

    mapping = Mapping.load(args.map)
    leaks, suspects = verify(args.input, mapping)

    if leaks:
        print("FUITE DÉTECTÉE — valeurs réelles résiduelles dans le FEC :")
        for lk in leaks:
            print(f"  - {lk['valeur']!r} ({lk['type']}) x{lk['occurrences']}")
    else:
        print("Aucune valeur réelle résiduelle détectée. ✓")

    if suspects:
        print("\nNoms potentiels à revoir manuellement (texte libre) :")
        for s in suspects[:50]:
            print(f"  - {s['mot']} x{s['occurrences']}")
        if len(suspects) > 50:
            print(f"  … et {len(suspects) - 50} autre(s).")

    return 2 if leaks else 0


def cmd_export_findreplace(args) -> int:
    if not os.path.exists(args.map):
        print(f"Erreur : mapping introuvable : {args.map}", file=sys.stderr)
        return 1
    from openpyxl import Workbook

    mapping = Mapping.load(args.map)
    wb = Workbook()
    ws = wb.active
    ws.title = "Correspondance"
    ws.append(["pseudo", "valeur_reelle"])
    for e in mapping.sorted_entries():
        ws.append([e.pseudo, e.valeur_reelle])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    wb.save(args.out)
    print(f"Table de correspondance : {args.out} ({len(mapping.entries)} lignes)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pseudo-fec",
        description="Pseudonymisation et ré-identification LOCALE de fichiers FEC.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("pseudonymize", help="Pseudonymiser un FEC.")
    sp.add_argument("--in", dest="input", required=True, help="FEC source (.txt/.csv/.xlsx).")
    sp.add_argument("--out", required=True, help="FEC pseudonymisé (sortie).")
    sp.add_argument("--map", help="Fichier de mapping (.csv). Défaut : _local_mapping/.")
    sp.add_argument("--dossier", help="Nom du dossier (nommage du mapping).")
    sp.add_argument("--exercice", help="Exercice (nommage du mapping).")
    sp.add_argument(
        "--include-pieceref",
        action="store_true",
        help="Masquer complètement les n° de pièce (désactivé par défaut).",
    )
    sp.add_argument(
        "--ascii",
        action="store_true",
        help="Délimiteur ASCII ~ au lieu de § (repli encodage).",
    )
    sp.set_defaults(func=cmd_pseudonymize)

    sr = sub.add_parser("reidentify", help="Ré-identifier un livrable.")
    sr.add_argument("--in", dest="input", required=True, help="Livrable (.docx/.xlsx/.txt/.md/.csv).")
    sr.add_argument("--map", required=True, help="Fichier de mapping (.csv).")
    sr.add_argument("--out", required=True, help="Fichier de sortie ré-identifié.")
    sr.set_defaults(func=cmd_reidentify)

    sv = sub.add_parser("verify", help="Contrôle anti-fuite d'un FEC pseudonymisé.")
    sv.add_argument("--in", dest="input", required=True, help="FEC pseudonymisé.")
    sv.add_argument("--map", required=True, help="Fichier de mapping (.csv).")
    sv.set_defaults(func=cmd_verify)

    se = sub.add_parser(
        "export-findreplace",
        help="Exporter une table pseudo→réel (.xlsx) pour find/replace manuel.",
    )
    se.add_argument("--map", required=True, help="Fichier de mapping (.csv).")
    se.add_argument("--out", required=True, help="Fichier .xlsx de sortie.")
    se.set_defaults(func=cmd_export_findreplace)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
