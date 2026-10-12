"""Vocabulaire comptable courant : mots qui ne sont PAS des noms propres.

Liste volontairement compacte et incomplète : la détection complète ce
vocabulaire avec celui du fichier lui-même (libellés de comptes et de journaux).
Les propositions restent soumises à validation de l'utilisateur.
"""

# mots génériques des libellés de comptes (à retirer autour d'un nom : « Associé - X »)
GENERIC_ACCOUNT_WORDS = set("""
fournisseur fournisseurs client clients personnel remunerations remuneration dues du des de la le les et
associe associes associee compte comptes courant courants groupe societe societes sociale
titres participations participation pret prets emprunt emprunts
debiteur debiteurs crediteur crediteurs divers diverses divers avances avance acompte acomptes
salarie salaries salaire salaires charges produits sociaux social organismes organisme
caisse tva collectee deductible debit credit sur biens services
creances dettes factures facture non parvenues recevoir payer emettre emises
""".split())

# vocabulaire des libellés d'écritures (abréviations bancaires et comptables incluses)
STOPWORDS = set("""
fact facture factures fa fac avoir av vir virement virements prlv prelevement prelevements sepa cb carte cheque chq chèque
remise remises rglt reglt reglement reglements paiement paiements pmt pay encaissement decaissement
salaire salaires paie paye bulletin acompte avance net brut cotisation cotisations charge charges
conges cp rtt indemnite indemnites frais note notes km deplacement mission
tva ht ttc taux regul regularisation reprise report ouverture solde soldes cloture
loyer loyers assurance assurances honoraires honoraire abonnement abonnements licence licences
achat achats vente ventes prestation prestations marchandises matieres matiere fournitures fourniture
interets interet agios commission commissions frais bancaires
mois janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre
janv fev avr juil sept oct nov dec trimestre semestre annee exercice
ref reference numero num no nr facturation paiement acompte solde echeance
compte comptes courant associe associes societe groupe refacturation refact refac
pret prets remboursement remb emprunt echeance echeances capital
de du des la le les un une et ou sur sous en au aux par pour chez dans avec sans
sepa ecriture ecritures opération operation operations diverses divers od an anouveau nouveau
impot impots taxe taxes cfe cvae tvs ir is urssaf dgfip sie
paiement carte retrait depot versement dépôt virt recu recue reçu
iban bic swift mandat rum ics bancaire banque agence siege code client fournisseur
mme mr mlle monsieur madame
frn cli sal ass grp soc tie siret siren nir email tel
""".split())

SALARY_WORDS = set("""
salaire salaires paie paye bulletin acompte avance net remuneration indemnite indemnites conges
note frais notes rtt cp prime primes
""".split())
PAYROLL_PREFIXES = {"421", "422", "425", "427", "428", "641", "645", "431", "437"}
