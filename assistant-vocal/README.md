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

**Cadrage — aucun code livré à ce stade.** Ce dossier documente la
trajectoire retenue ; le développement effectif (phase 3 notamment) reste à
faire.

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

1. **Pilote sans développement** — formaliser des prompts/skills réutilisables
   pour les 4 cas d'usage ci-dessus, testés via l'app mobile Claude en mode
   vocal, sans écrire de code dans ce dossier.
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
