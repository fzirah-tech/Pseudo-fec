---
name: brief-cabinet
description: Brief quotidien d'un cabinet d'expertise comptable, restitué à l'oral. Enchaîne les tâches et échéances du jour (Todoist), les mails à traiter et, si demandé, les alertes sur un dossier PennyLane. Se déclenche sur « fais-moi le brief », « qu'est-ce que j'ai aujourd'hui », « quoi de neuf ce matin », « où j'en suis ». À ne pas utiliser pour un brief matinal générique en artefact HTML (skill morning), ni pour le tri détaillé d'une boîte mail (skill mails-cabinet).
---

# Brief quotidien du cabinet

Restitution **orale**, destinée à être écoutée en marchant ou en voiture. Le
critère de réussite : l'utilisateur sait quoi faire en moins de 90 secondes
d'écoute.

## Ordre d'exécution

Toujours dans cet ordre, car il suit l'urgence réelle d'un cabinet :

1. **Retards** — `find-tasks-by-date` avec `startDate: "today"` et
   `overdueOption: "overdue-only"`. Ce qui a déjà glissé passe avant tout.
2. **Échéances du jour** — mêmes outils, `overdueOption: "exclude-overdue"`.
   Signaler explicitement les échéances déclaratives (CA3, DSN, liasse,
   dépôt des comptes) : leur dépassement a des conséquences pour le client.
3. **Mails en attente de vous** — `search_threads` / `outlook_email_search`
   sur les non-lus. Ne compter que ceux qui appellent une action de votre
   part : ignorer newsletters, veille, accusés de réception.
4. **Alertes dossiers** — uniquement si l'utilisateur le demande ou si une
   échéance du jour porte sur un dossier précis.

## Restitution

- 5 points maximum. Un point = une phrase.
- Annoncer les volumes, pas les listes : « quatre mails clients en attente,
  dont deux sur Techno Diffusion » plutôt que d'énumérer quatre objets.
- Grouper par dossier quand c'est possible : l'utilisateur pense en dossiers,
  pas en outils.
- Terminer par **une à trois actions proposées**, formulées de façon à
  pouvoir répondre « oui » à l'oral. Exemple : « je prépare les brouillons de
  réponse pour Techno Diffusion ? »

## Règles

- Le brief ne fait qu'**observer et proposer**. Aucune action n'est exécutée
  pendant le brief lui-même, même à faible risque : l'utilisateur écoute,
  il ne valide pas encore.
- Si rien d'urgent : le dire en une phrase et s'arrêter. Ne pas meubler.
- Si un outil ne répond pas (connecteur indisponible), le signaler
  explicitement plutôt que de livrer un brief partiel présenté comme complet.
- Utiliser le référentiel des dossiers s'il est disponible dans le projet,
  pour nommer les dossiers comme l'utilisateur les nomme.
