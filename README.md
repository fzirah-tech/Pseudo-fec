# pseudo-fec — Pseudonymisation LOCALE de fichiers FEC

Outil **100 % local et hors-ligne** pour pseudonymiser les identités d'un
**Fichier des Écritures Comptables (FEC)**, afin de pouvoir l'analyser dans un
environnement cloud (p. ex. Claude Cowork) **sans exposer les noms réels**, puis
**ré-identifier en local** les livrables produits (Word, Excel, texte).

> ⚠️ **Aucun appel réseau.** L'outil n'importe ni `requests`, ni `urllib`, ni
> `socket`, ni aucun client HTTP, et n'envoie aucune télémétrie. Il fonctionne
> entièrement hors-ligne sur Windows ou macOS.

## Principe

- **Pseudonymiser le QUI** : noms de tiers, libellés et codes auxiliaires
  identifiants.
- **Préserver le QUOI / COMBIEN / QUAND** : montants, dates, numéros de compte
  PCG, journaux, lettrage — indispensables pour que l'analyse reste valable
  (cut-off, contrôle de TVA, balance âgée, détection d'anomalies).
- **Cohérence** : une même entité réelle reçoit **toujours le même pseudonyme**,
  partout et **de façon persistante entre exécutions** d'un même dossier.

## Format des pseudonymes

`§<TYPE><NNNN>§` — par exemple `§CLI0001§`, `§FRN0007§`, `§SAL0003§`.

| Type | Tiers | Comptes |
|------|-------|---------|
| `CLI` | Clients | 41x |
| `FRN` | Fournisseurs | 40x |
| `SAL` | Salariés / paie | 42x |
| `TIE` | Autres tiers | 455, 467, … |

- Le délimiteur `§` est très rare en comptabilité, visuellement repérable, et
  permet un *find/replace* exact et non ambigu.
- Option `--ascii` : repli `~<TYPE><NNNN>~` si `§` pose un problème d'encodage.
- Dans un `CompteNum` concaténé, la racine du compte collectif est conservée :
  `411DUPON` → `411CLI0001`.

## Installation

```bash
pip install -r requirements.txt
# ou, pour disposer de la commande `pseudo-fec` :
pip install -e .
```

Dépendances : `openpyxl`, `python-docx` (et `pandas` uniquement si vous lisez un
FEC au format `.xlsx`). Python 3.11+.

## Utilisation

On peut invoquer l'outil via `pseudo-fec …` (après `pip install -e .`) ou via
`python -m pseudo_fec …`.

### 1. Pseudonymiser un FEC

```bash
pseudo-fec pseudonymize \
    --in FEC.txt --out FEC_pseudo.txt \
    --dossier ACME --exercice 2024 \
    [--include-pieceref] [--ascii] [--map mapping.csv]
```

- Le FEC d'entrée peut être un texte séparé par `|` (séparateur, encodage et
  format des montants/dates **autodétectés et préservés**) ou un `.xlsx`
  (feuille « FEC »).
- La **clé de correspondance** est écrite en `.csv` **et** `.json` dans
  `./_local_mapping/` (sauf chemin `--map` explicite).
- `--include-pieceref` masque complètement les n° de pièce (désactivé par
  défaut : un n° de pièce n'est pas nominatif et reste utile à l'échantillonnage).

### 2. Ré-identifier un livrable

```bash
pseudo-fec reidentify --in rapport.docx --map mapping.csv --out rapport_reid.docx
pseudo-fec reidentify --in tableau.xlsx --map mapping.csv --out tableau_reid.xlsx
```

Formats pris en charge : `.docx`, `.xlsx`, `.txt`, `.md`, `.csv`.
Pour Word, les *runs* adjacents de même mise en forme sont fusionnés avant
remplacement (un pseudonyme peut être scindé entre plusieurs *runs*). Les
formules Excel ne sont pas altérées.

### 3. Vérifier l'absence de fuite

```bash
pseudo-fec verify --in FEC_pseudo.txt --map mapping.csv
```

- Signale toute **valeur réelle résiduelle** (nom ou code auxiliaire
  alphabétique) → **code de sortie ≠ 0**.
- Liste les **mots à capitale initiale hors dictionnaire** (noms potentiels non
  masqués, à revoir manuellement) → avis, sans effet sur le code de sortie.

### 4. Exporter une table de correspondance (find/replace manuel)

```bash
pseudo-fec export-findreplace --map mapping.csv --out correspondance.xlsx
```

Table à 2 colonnes `pseudo → valeur_reelle`, utile pour un remplacement manuel
dans Word/Excel.

## Flux de travail recommandé

1. `pseudonymize` votre FEC → obtenez `FEC_pseudo.txt` + le mapping (local).
2. `verify` le FEC pseudonymisé (corrigez toute fuite éventuelle).
3. Envoyez **uniquement** `FEC_pseudo.txt` dans le cloud pour analyse.
4. Récupérez les livrables (Word/Excel) et `reidentify`-les localement.

## Sécurité du mapping

Le fichier de correspondance contient les **noms réels** : c'est l'élément
sensible. Il est écrit dans `./_local_mapping/`, **exclu du suivi Git**
(`.gitignore`) et **ne doit JAMAIS être transmis dans le cloud** ni synchronisé.

## Tests

```bash
python -m pytest tests/ -q
```

Les tests couvrent : round-trip Word/Excel, cohérence des pseudonymes,
préservation des montants/dates/comptes, anti-fuite, `CompteNum` concaténé,
idempotence et persistance incrémentale du mapping.

## Arborescence

```
pseudo_fec/
├── pseudo_fec/
│   ├── cli.py            # interface en ligne de commande (4 commandes)
│   ├── pseudonymize.py   # I/O FEC + détection/réécriture des tiers
│   ├── reidentify.py     # remplacement pseudo→réel (docx/xlsx/txt)
│   ├── mapping.py        # clé de correspondance (CSV+JSON, incrémental)
│   ├── replacer.py       # remplacement multi-termes
│   └── verify.py         # contrôle anti-fuite
├── tests/
├── _local_mapping/       # mappings — NE PAS synchroniser
├── logs/
├── README.md
└── requirements.txt
```
