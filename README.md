# Pseudo-FEC

Outil **local et hors ligne** de cabinet : pseudonymise les FEC avant analyse dans Claude, puis
ré-identifie les restitutions. Interface HTML servie sur `127.0.0.1` par l'application elle-même.

**État : jalon (c)** — import et contrôle du FEC, détection et validation des noms, **pseudonymisation du FEC**
(rapport, seconde passe de contrôle, consigne Claude).
Prochains jalons : (d) texte libre,
(e–g) ré-identification DOCX/XLSX/PPTX, (h) verrouillage et audit, (i) packaging Windows.

## Dossier portable prêt à copier (recommandé pour le pilote)

`python scripts/build_portable.py` construit `dist/Pseudo-FEC-<version>-windows-portable.zip` : Python 3.13 officiel
(NuGet, Python Software Foundation) + composants Windows épinglés + application. **Rien à installer, aucune connexion
Internet.** `python scripts/verify_portable.py <zip> --smoke` le contrôle (structure, exécutables Windows AMD64, imports
résolus, aucun fichier sensible, démarrage et auto-diagnostic de l'application extraite). L'exécution sous Windows
elle-même n'est pas testable depuis Linux : à valider sur un poste réel. Le guide embarqué est `DEMARRER.html`.

## Lancer depuis le dépôt (développement)

1. Installer **Python 3.13** une fois (« Add python.exe to PATH » coché, sans droit administrateur).
2. Décompresser le dossier (ZIP débloqué : clic droit → Propriétés → Débloquer).
3. **Double-cliquer sur `Lancer-Pseudo-FEC.bat`**. Première fois : préparation automatique (1 à 3 min, Internet
   pour télécharger les composants). Ensuite : lancement immédiat, outil hors ligne.
4. Le navigateur s'ouvre ; bouton **« Aide et test »** : démo sur données fictives, auto-diagnostic copiable,
   ouverture des dossiers de tables et de sorties.

Guide illustré pas à pas : `DEMARRER.html` (à ouvrir par double-clic).
Installation hors ligne : déposer un dossier `wheels` de composants à côté de `bootstrap.py`.
Une page web ne peut pas démarrer un programme (sécurité du navigateur) : c'est le fichier `.bat` qui lance l'outil.

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

## Parcours : le FEC d'abord, les propositions ensuite

1. **Nouveau dossier** : un simple code neutre (aucun nom de client).
2. **Import du FEC** (un par exercice) : contrôles d'intégrité ; le SIREN est lu dans le nom du fichier (norme A47 A-1) et
   sert de référence : un exercice portant un autre SIREN est refusé.
3. **Noms à valider** : l'outil propose la société (raison sociale suggérée à partir des libellés, SIREN prérempli),
   ses dirigeants et associés, ses sociétés liées, ses clients, fournisseurs et salariés ; l'utilisateur valide.
   La fiche société reste disponible, **facultative**, pour ajouter à l'avance ce que le FEC ne révèle pas.

## Pseudonymisation du FEC (jalon c)

Un NOUVEAU fichier par exercice dans `…/sorties/<code>/PSEUDO/` (`DOSSIER-SOC0001_FEC_2025_PSEUDO.txt` : ni SIREN ni nom ;
jamais d'écrasement : `_v2`, `_v3`…), même structure, séparateur, encodage et fin de ligne. Jamais modifiés : montants, dates,
codes journaux, numéros d'écritures, lettrage, numéros de compte numériques. Un `CompAuxNum` / `CompteNum` qui reprend un nom
reçoit un code neutre cohérent (`FRN0007`, ou `401FRN0007`). **Contrôles bloquants** : lignes et totaux débit/crédit identiques
à la source, colonnes protégées inchangées. **Seconde passe** sur la sortie : noms propres restants, prénoms/noms isolés des
personnes pseudonymisées, entités non cochées, alertes de risque résiduel (salariés peu nombreux, tiers unique sur un compte).
Livrés aussi : `CONSIGNE-CLAUDE.txt` à coller avec le FEC et `RAPPORT-PSEUDONYMISATION.txt` (sans aucun nom réel).
La liste des noms résiduels n'est affichée qu'à l'écran, en local.

## Contextes sensibles et parties identifiantes

Les libellés de **paie**, de **provisions** et de **comptes courants / groupe** citent souvent un nom de façon partielle
(nom de famille seul, prénom seul, composant d'un nom hyphéné, partie d'une raison sociale). Le contexte est déterminé par
l'ÉCRITURE entière (journal + numéro) à partir des comptes (paramétrables dans `cabinet.json`, clé `contexts`) : le virement de
salaire côté banque est donc en contexte de paie.

- **Synthèse à valider** (écran « Noms à valider ») : par type d'écriture, noms relevés / validés / à examiner, libellés les
  plus fréquents, « Voir » et « Tout valider » par contexte.
- **Parties identifiantes** : pour chaque nom, ses parties (nom de famille, prénom, composants hyphénés ; pour une société, la
  partie distinctive d'une raison sociale longue). Portée au choix : « contextes sensibles » (défaut pour les personnes) ou « partout »
  (défaut pour la partie distinctive d'une société liée, sauf mot courant, trop court ou partagé).
- **Sociétés liées** : un nom à raison sociale porté par les comptes 451, 455-458, 467 ou 26x est proposé comme « Société liée ».
  Pour chaque partie distinctive (DURAND), l'outil propose aussi les **formes tronquées** : dernière lettre omise (DURAN) et
  première lettre omise (URAND), avec leur nombre d'occurrences dans le FEC. Les notes de frais de salariés en 425 ou 467 restent
  couvertes (la partie « contextes » d'un salarié s'applique aussi en contexte compte courant).
- **Homonymes** : en contexte de paie le salarié l'emporte sur un fournisseur homonyme ; à priorité égale (holding / associé
  « DESCHAMPS ») c'est un conflit bloquant à **arbitrer** (attribuer à une entité ou laisser en clair).
- Un mot isolé relevé en paie, provision ou compte courant et non reconnu est proposé (non coché) : validez-le dans la synthèse.

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
