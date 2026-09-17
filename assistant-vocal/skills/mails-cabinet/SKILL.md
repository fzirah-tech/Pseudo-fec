---
name: mails-cabinet
description: Tri et traitement des mails d'un cabinet d'expertise comptable (Gmail ou Outlook) : classement par dossier client et par nature, détection des demandes de pièces et des relances, préparation de brouillons de réponse. Se déclenche sur « trie mes mails », « qu'est-ce qu'on m'a envoyé », « prépare une réponse à », « réponds à ce client ». Ne pas utiliser pour le brief quotidien global (skill brief-cabinet).
---

# Gestion des mails du cabinet

## Classement

Cinq catégories, dans cet ordre de priorité :

1. **Client — action attendue** : demande, question, pièce transmise,
   validation à obtenir. C'est la seule catégorie qui justifie un brouillon.
2. **Administratif et déclaratif** : DGFiP, URSSAF, net-entreprises, greffe,
   OGA, ordre professionnel. Souvent porteur d'une échéance → proposer une
   tâche plutôt qu'une réponse.
3. **Banque et financier** : relevés, avis, demandes de justificatifs.
4. **Fournisseurs et interne cabinet**.
5. **Veille et newsletters** : ne jamais remonter spontanément.

Rattacher chaque mail à un dossier via le domaine de l'expéditeur, en
s'appuyant sur le référentiel des dossiers s'il est disponible. Si le
rattachement est incertain, le dire au lieu de trancher.

## Préparation des réponses

- Créer un **brouillon** (`create_draft` / `outlook_create_draft`). Ne jamais
  envoyer : l'envoi à un client est une action à fort impact, soumise à
  validation explicite.
- Pour la rédaction elle-même, appliquer la charte rédactionnelle du cabinet
  (skill `style-cabinet-humanise`) : français naturel, ton de professionnel
  qui connaît son client, pas de formules creuses.
- Ne jamais engager le cabinet sur un délai, un chiffre ou une position
  technique qui n'a pas été validé. En cas de question technique dans le mail,
  préparer la réponse en laissant le point en suspens et le signaler à l'oral.

## Détections utiles

- **Demande de pièce** (« pouvez-vous nous transmettre… ») → proposer la
  création d'une tâche Todoist rattachée au dossier.
- **Relance** (deuxième message sans réponse sur le même fil) → à remonter en
  priorité, c'est un signal de dégradation de la relation client.
- **Échéance mentionnée** → proposer une tâche avec la date reprise du mail,
  jamais une date devinée.

## Actions autorisées sans validation

Classer, étiqueter, archiver, créer un brouillon, créer une tâche associée.

## Actions soumises à validation

Envoyer, transférer, répondre directement, supprimer, ou toute action sur un
mail rattaché à un dossier que l'utilisateur n'a pas nommé dans sa demande.
