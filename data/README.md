# Dictionnaire des données

Données **entièrement fictives**, générées par `generate_dataset.py` pour un projet de forecasting avec Prophet.
Le contexte reprend le fonctionnement type d'un tiers-archiveur, mais l'entreprise, les clients, les volumes et les effectifs sont fictifs.

Les CSV ne sont pas versionnés : on les régénère en quelques secondes depuis la racine du projet.

```
python generate_dataset.py            # écrit les CSV dans ./data (seed 42, résultat reproductible)
python generate_dataset.py --seed 7   # autre tirage
```

## Ce qui est simulé

5 sites, environ 500 clients, du 01/01/2021 au 30/10/2026, au jour près.

Chaque client a un stock de boîtes et un comportement qui dépend de son segment (banque, santé, notariat…) :
il verse de nouvelles boîtes, en consulte, en fait détruire quand les durées de conservation expirent, et parfois part.
Chaque mouvement est converti en minutes d'archiviste grâce à un temps standard par boîte.
La cible du forecast est la somme de ces heures par site et par jour ouvré.

Ce qui rend la série intéressante à modéliser :

| Effet | Comment il est simulé |
|---|---|
| Hebdomadaire | Lundi chargé (demandes accumulées le week-end), vendredi plus calme |
| Annuel | Creux d'août et de fin décembre ; pics de consultations au S1 pour banque/assurance, mars-mai pour avocats/EC, automne pour les collectivités |
| Fériés et ponts | Aucune activité les jours fériés, activité réduite de 35 % les jours de pont |
| Campagnes de destruction | Concentrées de janvier à avril |
| Reprises de fonds | 5 gros clients entrants (12 000 à 42 000 boîtes chacun) + arrivées de clients moyens |
| Départ client | Un grand compte part en 2025 : restitution de 20 000 boîtes |
| Pics imprévus | Contrôles fiscaux, audits, contentieux : consultations ×3 à ×7 pendant 2 à 4 semaines sur un client |
| Tendance | Consultations physiques en baisse de 3 %/an ; part servie en numérisation qui passe de 8 % à 30 % |

## Tables (modèle en étoile)

| Fichier | Grain | Contenu |
|---|---|---|
| `fact_mouvement.csv` | jour × client × type | nb de boîtes et minutes standard |
| `fact_charge_jour.csv` | jour × site | heures par type, heures requises, ETP, heures disponibles, taux de charge |
| `fact_stock_mensuel.csv` | fin de mois × client | stock de boîtes en rayon |
| `prophet_charge_site.csv` | jour ouvré × site | `ds`, `y` = heures requises, prêt pour Prophet |
| `dim_date.csv` | jour | fériés, ponts, périodes de congés, jour ouvré |
| `dim_site.csv` | site | ville, région, capacité, agrément SIAF |
| `dim_client.csv` | client | segment, taille, dates de contrat, taux de comportement |
| `dim_type_mouvement.csv` | type | libellé, minutes par boîte |
| `dim_evenement.csv` | événement | reprises, arrivées, départs, pics ; colonne `connu_a_lavance` |

`connu_a_lavance = True` : événements qu'une exploitation connaît en avance (contrat signé, fin de contrat).
Ils peuvent servir de régresseurs ou de « holidays » dans Prophet. Les pics imprévus (`False`) ne doivent pas
être utilisés comme variables explicatives : ce serait de la fuite d'information.

## Hypothèses à challenger

Les temps standards sont les hypothèses les plus fortes. Ils sont tous dans `TYPES_MOUVEMENT`, en haut de `generate_dataset.py` :

| Mouvement | Minutes / boîte |
|---|---|
| Versement (contrôle, étiquetage, saisie, mise en rayon) | 5 |
| Consultation (recherche, sortie, préparation) | 9 |
| Retour de consultation | 5 |
| Numérisation à la demande | 12 |
| Destruction | 2,5 |
| Restitution | 3 |

S'y ajoutent 3,5 h fixes par site et par jour ouvré (inventaires, réception, administratif), et un aléa de productivité de ±6 %.

Taux annuels moyens de consultation (4 à 12 % du stock selon le segment), de versement et de destruction :
voir `PROFIL_SEGMENT`. L'effectif de chaque site est dimensionné chaque année sur la charge moyenne de l'année
précédente, ce qui crée volontairement des périodes de sous-effectif pendant les reprises de fonds.

## Ordres de grandeur

Les volumes ont été calés sur des repères publics du secteur, puis arrondis :
- un grand tiers-archiveur français compte quelques dizaines de sites de conservation et plusieurs milliers de clients ;
- un site régional conserve de l'ordre de 150 000 à 400 000 boîtes ;
- les demandes de consultation sont généralement servies sous 24 à 48 h ;
- ratios type : environ 7,5 % du stock consulté par an, environ 8 % versé (blog d'éditeur de logiciel, source commerciale à prendre avec prudence).

Les noms de villes servent uniquement d'ancrage géographique : les sites, leurs stocks et leurs clients sont inventés.
