# Pseudo-FEC

Outil **local et hors ligne** de cabinet : pseudonymise les FEC avant analyse dans Claude, puis
ré-identifie les restitutions. Interface HTML servie sur `127.0.0.1` par l'application elle-même.

**État : jalon (a)** — socle, fiche dossier, import et contrôle du FEC.
Prochains jalons : (b) détection et validation des noms, (c) pseudonymisation du FEC, (d) texte libre,
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

## Limites connues (jalon a)

- Pas encore de verrouillage multi-utilisateurs ni de journal d'audit (jalon h) : **un seul utilisateur à la fois** en pilote.
- Détection de l'encodage 8 bits (cp1252 / ISO-8859-15) heuristique ; la réécriture à l'identique est vérifiée à l'import.
- Le style « Pennylane » des FEC de test est une **hypothèse** : à confirmer sur un export réel.
- Fichier jusqu'à 200 Mo : téléversé en mémoire (prévoir ~3 à 4 fois la taille en RAM).
- Interface testée avec Chromium sous Linux ; à valider sur Edge / Windows 11.
- Build Windows (PyInstaller), signature et contrôle de version : jalon (i), à exécuter sur un poste Windows.
