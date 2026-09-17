---
name: dossier-pennylane
description: Consultation orale d'un dossier comptable dans PennyLane : soldes, compte de résultat, bilan, factures fournisseurs, transactions bancaires, journaux. Se déclenche sur « où en est le dossier X », « donne-moi le résultat de », « combien on a facturé », « les factures fournisseurs de ». Lecture seule. Pour une analyse financière approfondie, enchaîner avec le skill analyse-financiere ; pour la révision des comptes, avec revision-comptable.
---

# Consultation d'un dossier PennyLane

## Contrainte absolue : lecture seule

Le connecteur PennyLane disponible n'expose que des opérations de consultation.
Aucune création, modification ou validation d'écriture, de facture ou de
paiement n'est possible. Si l'utilisateur demande une action d'écriture, le
dire clairement au lieu de contourner ou de simuler.

## Séquence d'accès

1. Générer un UUID aléatoire au premier appel et le réutiliser comme
   `conversation_id` sur **tous** les appels PennyLane suivants de la
   conversation. Ne jamais en changer en cours de route.
2. `get_context` **sans** `company_id` pour découvrir les sociétés accessibles
   et les portefeuilles clients.
3. Identifier le dossier visé. Si l'utilisateur l'a nommé à l'oral, passer par
   les alias du référentiel des dossiers. **Si deux dossiers peuvent
   correspondre, demander — ne jamais choisir.**
4. `get_context` avec le `company_id` retenu : exercices, comptes bancaires,
   contexte de travail.
5. Avant d'afficher des écritures ou des documents comptables, lire la
   ressource `pennylane://guides/ledger-display`. Avant de filtrer ou paginer
   une liste, lire `pennylane://guides/filtering`.

## Restitution orale

- Annoncer le dossier avant le premier chiffre : « sur Techno Diffusion… ».
- Trois chiffres maximum à l'oral. Le détail vient sur demande.
- Chaque chiffre est accompagné de sa source et de sa période : « résultat au
  31/12/2025, compte de résultat PennyLane ».
- Sur le bilan actif, `amount` est le net ; `gross_amount` et
  `depreciation_amount` sont disponibles séparément. Seul le net se réconcilie
  avec le total et avec le passif — ne jamais additionner un poste avec ses
  sous-postes.

## Fiabilité

- Si l'exercice n'est pas clôturé, le préciser systématiquement : les chiffres
  d'un exercice en cours ne sont pas des chiffres définitifs.
- Ne jamais extrapoler un chiffre manquant, ni reconstituer un solde par
  différence sans le dire.
- Si une donnée paraît incohérente (solde débiteur sur un compte fournisseur,
  écart bilan/résultat), le signaler au lieu de le lisser.
- Ne jamais recouper deux dossiers clients sans demande explicite.
