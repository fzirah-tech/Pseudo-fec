# Assistant vocal complet — DAF externalisé / cabinet comptable

> ⚠️ **Ce dossier est indépendant de `pseudo_fec/`.** Contrairement à
> l'outil de pseudonymisation FEC de ce dépôt, l'assistant décrit ici est
> **connecté en permanence à des services tiers** (messagerie, tâches,
> PennyLane). La garantie « 100 % hors-ligne » du dépôt racine ne s'applique
> **pas** à ce dossier — voir le README racine.

## Objectif

Assistant vocal (mobile + poste de travail à terme) permettant à un expert
comptable / DAF externalisé de piloter en langage naturel :
- la gestion des mails (tri, résumé, préparation de réponses) ;
- la gestion des tâches (suivi des dossiers en cours, échéances) ;
- la consultation des dossiers comptables (PennyLane) ;
- la production de reporting Excel.

## Statut

**v0.1 — pilote testable, sans développement.** L'assistant repose
uniquement sur des skills et un bloc de préférences, exécutés par Claude via
les connecteurs existants. Aucun code à déployer. Les phases 2 et 3 restent
à faire.

> 🔓 **Ce dépôt est PUBLIC.** N'y versionnez jamais de noms de clients,
> d'identifiants de sociétés PennyLane ni d'adresses réelles. Le référentiel
> rempli (`referentiel-dossiers.yaml`) est exclu du suivi Git ; seul
> l'exemple fictif est versionné.

## Contenu

| Fichier | Rôle |
|---|---|
| `preferences-claude.md` | Comportement transverse (mode vocal, politique d'autonomie, confidentialité). À coller dans les préférences Claude. |
| `referentiel-dossiers.exemple.yaml` | Lien entre ce que vous dites à l'oral et les identifiants de chaque outil. À copier et remplir localement. |
| `skills/brief-cabinet/` | Brief quotidien : retards, échéances, mails en attente. |
| `skills/mails-cabinet/` | Tri des mails et préparation des brouillons de réponse. |
| `skills/dossier-pennylane/` | Consultation d'un dossier comptable, en lecture seule. |

Le reporting Excel ne fait pas l'objet d'un skill dédié : il s'appuie sur vos
skills existants `excel-reporting-avance` et `xlsx`, que l'assistant enchaîne
avec les données consultées.

## Mise en service

1. Coller le contenu de `preferences-claude.md` dans **Réglages →
   Préférences personnelles** sur claude.ai.
2. Copier `referentiel-dossiers.exemple.yaml` en `referentiel-dossiers.yaml`,
   le remplir avec vos dossiers réels, et le joindre à un Projet Claude dédié
   (il reste local, hors Git).
3. Charger les trois dossiers de `skills/` dans **Réglages → Capacités →
   Skills**.
4. Vérifier que les connecteurs Gmail ou Outlook, Todoist et PennyLane sont
   actifs sur le compte.
5. Tester en vocal depuis l'app mobile, dans cet ordre : « fais-moi le
   brief », puis « trie mes mails », puis « où en est le dossier X ».

## Ce qu'il faut observer pendant le test

Le pilote sert à décider si la phase 3 vaut l'investissement. Trois points à
surveiller sur deux à trois semaines d'usage réel :

- La reconnaissance vocale tient-elle sur les noms de dossiers et le
  vocabulaire métier, ou passez-vous votre temps à corriger ?
- La politique d'autonomie est-elle au bon niveau, ou demande-t-elle
  validation trop souvent (friction) ou pas assez (inconfort) ?
- Le gain de temps est-il réel sur le brief et le tri des mails, ou
  reprenez-vous la main de toute façon ?

## Connecteurs envisagés

| Connecteur | Usage prévu | État constaté |
|---|---|---|
| Gmail / Outlook (ms365) | Lecture, tri, brouillons, envoi | Lecture + écriture disponibles |
| Google Drive / SharePoint | Fichiers Excel, pièces jointes | Lecture + écriture disponibles |
| Todoist | Tâches et échéances | Lecture + écriture disponibles |
| PennyLane | Consultation des dossiers comptables | **Lecture seule constatée** — aucun outil de création/modification d'écriture, de facture ou de paiement identifié à ce jour |

**Conséquence directe** : « prendre la main sur les dossiers comptables »
au sens *actions* (passer une écriture, valider un paiement) n'est pas
possible aujourd'hui avec ce connecteur. Seule la consultation l'est, sauf
évolution du connecteur PennyLane à vérifier auprès de l'éditeur.

## Politique d'autonomie retenue

- **Actions à faible risque et réversibles** (classer un mail, créer une
  tâche, générer un brouillon) : exécutées directement.
- **Actions à fort impact** (envoi d'un mail à un client, toute écriture
  comptable si le connecteur venait à l'autoriser, modification d'un
  livrable Excel officiel) : validation humaine systématique avant
  exécution.

Cette politique doit être révisée avant toute mise en production réelle,
en particulier sur le cloisonnement des dossiers clients (secret
professionnel) et la traçabilité des actions.

## Feuille de route

1. **Pilote sans développement** — *livré (v0.1)*. Skills et préférences
   réutilisables pour les cas d'usage ci-dessus, testables via l'app mobile
   Claude en mode vocal, sans code à déployer.
2. **Gouvernance** — cloisonnement des dossiers clients, traçabilité des
   actions, revue de la politique d'autonomie ci-dessus avant extension.
3. **Compagnon poste de travail** — capture vocale continue côté poste de
   travail. Projet de développement à part entière (stack à définir), à ne
   lancer qu'une fois le pilote validé.

## Points d'incertitude non résolus

- Confidentialité des données comptables transitant par une couche vocale
  tierce (reconnaissance vocale / synthèse) : conformité RGPD et secret
  professionnel à valider avant la phase 3, en fonction des fournisseurs
  retenus.
- Portée réelle du connecteur PennyLane en écriture : à confirmer auprès de
  l'éditeur avant de promettre une quelconque prise de main automatisée sur
  les dossiers comptables.
