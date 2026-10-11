# Pseudo-FEC

Outil **local et hors ligne** de cabinet : pseudonymise les FEC avant analyse dans Claude, puis
ré-identifie les restitutions. Interface HTML servie sur `127.0.0.1` par l'application elle-même.

**État : jalon (b)** — socle, fiche dossier, import et contrôle du FEC, détection et validation des noms.
Prochains jalons : (c) pseudonymisation du FEC, (d) texte libre,
(e–g) ré-identification DOCX/XLSX/PPTX, (h) verrouillage et audit, (i) packaging Windows.

## Essayer sur son poste (avant tout déploiement)

Prérequis : Python 3.11 ou plus sur Windows 11 (aucun droit administrateur : cocher « Add to PATH » / installation « pour moi seul »).

1. Double-clic sur `scripts\installer_dev.bat` (une fois ; seule étape qui télécharge des paquets).
2. Double-clic sur `scripts\lancer.bat` : le navigateur s'ouvre sur l'interface.
3. Première utilisation : saisir deux fois la phrase secrète du cabinet.

Les tables chiffrées sont dans `%LOCALAPPDATA%\PseudoFEC\tables` (modifiable via `prefs.json`).
**La phrase secrète n'est écrite nulle part** ; la perdre rend les tables irrécupérables.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

Les tests n'utilisent que des données synthétiques (`tests/synth.py`) ; ne jamais committer de FEC réel
(`.gitignore` protège `*FEC*.txt`, `*.enc`, etc.).

## Sécurité du jalon (a)

- Serveur sur 127.0.0.1 uniquement ; jeton de session (cookie HttpOnly + en-tête), contrôle `Host`/`Origin`,
  CSP stricte, aucune ressource externe, journal d'accès muet.
- Tables : AES-256-GCM, clé de données par dossier enveloppée par scrypt (n = 2^17) ; plusieurs phrases
  possibles (secours, changement sans rechiffrement) ; une table ne peut pas être transposée dans un autre dossier.
- Messages d'erreur sans aucune donnée issue des fichiers.

## Détection des noms (jalon b)

Les noms candidats viennent, par ordre de fiabilité : de la fiche dossier et de la table, de `CompAuxLib`,
du `CompteLib` des comptes de tiers individualisés (421, 455, 164…), puis des libellés d'écritures
(tiers connus retrouvés avec leurs variantes ; noms propres inconnus proposés par heuristiques).
**Rien n'est appliqué sans validation** : fusions de variantes seulement proposées, propositions peu fiables
non cochées, tiers usuels (liste blanche) maintenus sauf si vous les cochez.
Un même texte rattaché à deux entités (« MARTIN ») est un **conflit bloquant** à résoudre.
Les motifs sensibles (IBAN, SIRET, e-mail, téléphone…) sont signalés ; un SIREN n'est retenu que s'il est celui
d'une entité ou précédé du mot « SIREN » (la clé de Luhn seule laisse passer 1 nombre sur 10).

## Limites connues (jalons a et b)

- La détection **n'offre aucune garantie d'exhaustivité** : un nom écrit sous une forme non proposée (prénom seul,
  faute de frappe, abréviation) reste en clair ; la seconde passe de contrôle sur la sortie (jalon c) le signalera.
- Les propositions issues des libellés sont nombreuses sur les FEC dont le journal de banque contient des noms de
  contreparties : elles demandent une revue humaine (filtres et sélections en masse fournis).
- Fusion « Œ » / « OE » gérée ; autres ligatures rares non testées.

- Pas encore de verrouillage multi-utilisateurs ni de journal d'audit (jalon h) : **un seul utilisateur à la fois** en pilote.
- Détection de l'encodage 8 bits (cp1252 / ISO-8859-15) heuristique ; la réécriture à l'identique est vérifiée à l'import.
- Les FEC de test « Pennylane » reproduisent la structure d'un export Pennylane réel (vérifié sur un échantillon) ; le style « compte individualisé » reste à valider sur un cas réel.
- Fichier jusqu'à 200 Mo : téléversé en mémoire (prévoir ~3 à 4 fois la taille en RAM).
- Interface testée avec Chromium sous Linux ; à valider sur Edge / Windows 11.
- Build Windows (PyInstaller), signature et contrôle de version : jalon (i), à exécuter sur un poste Windows.
