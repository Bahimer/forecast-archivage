# Prévision de la charge des archivistes — documentation du projet

Journal de travail : ce qui a été fait, pourquoi, et ce qu'on en a appris.
À mettre à jour à chaque étape.

---

## 1. Contexte et objectif

Un tiers-archiveur conserve les boîtes d'archives de ses clients et traite chaque jour des mouvements :
nouveaux versements, sorties en consultation, retours, destructions, restitutions. Le volume varie beaucoup
selon les clients, la saison et les contrats signés. Les responsables de site dimensionnent leurs équipes
avec peu de visibilité.

**Question posée :** peut-on prévoir, plusieurs semaines à l'avance, le nombre d'heures d'archivistes
nécessaires par site, à partir du comportement historique des clients ?

**Outil retenu :** Prophet (Meta). Il gère nativement plusieurs saisonnalités (semaine, année), les jours
fériés et des régresseurs externes. Il reste aussi lisible quand on doit expliquer le modèle à un métier.

**Pourquoi ce sujet :** la charge d'un centre d'archives varie fortement (reprises de fonds, contrôles chez
les clients, congés d'été), alors que les effectifs sont souvent fixés une fois par an. Le projet mesure ce
qu'un modèle simple et explicable apporte à ce pilotage. La présentation complète est dans le `README.md`.

Le jeu de données est entièrement fictif : l'entreprise, les clients et les volumes sont inventés.

---

## 2. Environnement

| Élément | Version / choix |
|---|---|
| OS | Windows, VS Code |
| Python | 3.13.17 (installation python.org) |
| Environnement | `.venv` dans le dossier projet |
| Paquets principaux | prophet 1.5.0, pandas 3.1.0, numpy 2.5.4, matplotlib 3.11.2, plotly 7.1.0, jupyter |

Installation :

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Le `requirements.txt` du dépôt ne liste que les paquets utilisés directement, avec leurs versions figées.
Attention : sous PowerShell, `pip freeze > requirements.txt` produit un fichier en UTF-16, mal affiché par GitHub.

Point de vigilance : Prophet dépend de Stan (via cmdstanpy), qui pose souvent problème sous Windows.
Ici, la wheel précompilée s'installe sans compilation, et un fit de test a tourné correctement.

---

## 3. Les données

### Pourquoi un dataset simulé

Pas d'accès à des données réelles, et de toute façon pas question d'utiliser des données clients d'un
ancien employeur. Le dataset est donc généré from scratch par `generate_dataset.py`. Ses ordres de grandeur
sont calés sur des informations publiques : taille des sites, nombre de clients, ratios de consultation.
Le détail et les sources sont dans `data/README.md`.

Le seed est fixé (42), donc tout le monde obtient les mêmes données en relançant le script.

### Choix de conception

| Décision | Choix | Raison |
|---|---|---|
| Cible | Heures d'archivistes par site et par jour ouvré | C'est ce qu'un responsable de site planifie. Un nombre de boîtes ne dit rien du temps passé, car une consultation coûte presque deux fois plus qu'un versement. |
| Périmètre | 5 sites, 01/2021 → 10/2026 | Assez de sites pour comparer des profils différents. Près de 6 ans, ce qui permet d'apprendre la saisonnalité annuelle et de garder 2026 en test. |
| Grain | Jour × client × type de mouvement | Permet d'agréger ensuite comme on veut (site, segment, semaine). |
| Format | Modèle en étoile en CSV | Réutilisable tel quel dans Power BI, et proche de ce qu'on trouverait dans un entrepôt réel. |
| Conversion en heures | Temps standard par boîte et par type, + 3,5 h fixes/jour/site, ± 6 % d'aléa | Simple, explicable, facile à ajuster. C'est aussi l'hypothèse la plus fragile du projet. |

### Mécanismes simulés

- **Comportement par segment** (banque, santé, notariat…) : taux annuels de consultation, versement et
  destruction, plus une saisonnalité propre à chaque segment.
- **Calendrier français** : fériés, ponts, creux d'août et de fin d'année, lundi plus chargé.
- **Événements connus à l'avance** : 5 reprises de fonds (12 000 à 42 000 boîtes), 31 arrivées de clients
  de taille moyenne, 1 départ de grand compte (20 000 boîtes restituées).
- **Événements imprévus** : 482 pics de consultation liés à un client (contrôle fiscal, audit, contentieux).
- **Tendances** : consultations physiques en baisse de 3 %/an, numérisation à la demande en hausse.
- **Effectif** : dimensionné chaque année sur la charge moyenne de l'année précédente. C'est volontairement
  naïf, pour pouvoir montrer ensuite ce qu'apporte une prévision.

### Itérations sur le générateur

La première version produisait des journées irréalistes : un lot de 2 400 boîtes traité en une seule journée
donnait 240 h de travail sur un site dimensionné pour 25 h. Corrections apportées :

1. Les lots de versement sont étalés à ~120 boîtes/jour, et les reprises de fonds à ~200 boîtes/jour.
2. Les dates de versement et de destruction sont tirées parmi les jours ouvrés. Avant, toutes les dates
   tombant un week-end étaient reportées au lundi, ce qui gonflait artificiellement l'effet lundi.
3. Les délais de retour de consultation sont comptés en jours ouvrés.
4. Les taux de versement sont réduits de 30 %, car le stock croissait de près de 10 %/an, ce qui est peu
   crédible pour de l'archivage physique.

Un premier test Prophet, sur 2021-2025 avec 2026 en test, confirme que la série est apprenable.
Sur Villeneuve-la-Garenne, l'erreur hebdomadaire (MAPE) passe de 25 % à 13 % quand on ajoute les événements
connus en régresseur. Sur Charleval, ça dégrade : l'explication est en section 5.

---

## 4. Exploration (`notebooks/01_exploration.ipynb`)

Résultats obtenus avec le seed 42.

**Qualité des données.** Aucune clé orpheline, aucun doublon, aucun mouvement un jour non ouvré, aucun
stock négatif. Les valeurs nulles sont toutes attendues : contrats en cours, pics sans volume, taux de charge
les jours fermés.

**Composition de la charge.** Les versements représentent 38 % des heures, les consultations 28,5 %, les
retours 15,7 % et la numérisation 9,2 %. Destructions et restitutions pèsent peu en moyenne, mais elles
arrivent en blocs. La part des demandes servies en numérique passe de 9,7 % en 2021 à 28,2 % en 2026.

**Saisonnalité hebdomadaire.** Le lundi est 3 à 11 % au-dessus de la moyenne de la semaine selon le site,
le vendredi 5 à 9 % en dessous. L'effet existe, mais il reste faible comparé au bruit d'un jour à l'autre.

**Saisonnalité annuelle.** Le creux d'août est marqué (environ −40 % par rapport à un mois moyen), celui de
décembre aussi. Les segments ont des profils nets : avocats et experts-comptables en mars-avril, banques en
début d'année, collectivités en septembre-octobre.

**Fériés et ponts.** L'effet des ponts va de −2 % à −30 % selon le site. Il y a trop peu de ponts par an
pour une estimation stable : Prophet devra probablement les traiter comme un seul effet commun à tous.
Aucun report de charge n'apparaît le lendemain d'un férié.

**Événements.** Pendant un événement connu, la charge moyenne d'un site est multipliée par 1,7 à 2,3.
Ce sont de loin les plus gros mouvements de la série. Sans eux, n'importe quel modèle ratera les pics.

**Capacité.** La règle « effectif = charge moyenne de l'an dernier » crée des déséquilibres visibles.
Lesquin est en surcharge (taux > 110 %) 76 % des jours ouvrés en 2024, pendant une reprise de fonds.
Saint-Priest ne l'est jamais en 2026, parce que son effectif a été calé sur 2025, une année gonflée
par une reprise ponctuelle.

**Clients.** Le stock est très concentré : 10 % des clients détiennent 55 % des boîtes. Un pic d'activité
chez un gros client se voit donc au niveau du site.

> **À compléter avec tes mots :** ce qui t'a surpris, ce qui te paraît crédible ou non par rapport à ce que tu
> as vu sur le terrain, et les hypothèses que tu veux corriger dans le générateur.

---

## 5. Modélisation (`notebooks/02_prophet.ipynb`)

### Protocole

- **Un modèle par site** : les niveaux et les événements diffèrent trop pour un modèle global.
- **Entraînement 2021-2025, test sur 2026** (janvier à octobre). C'est une prévision faite au 1er janvier
  pour toute l'année.
- **Métrique : MAPE hebdomadaire**, c'est-à-dire l'écart moyen en % entre heures prévues et réelles, semaine
  par semaine. On prévoit au jour, mais on juge à la semaine, parce que c'est le pas de planification
  d'un site et que le bruit journalier est élevé.
- **Validation croisée** : 15 dates de coupure tous les 3 mois à partir de 2023, avec un horizon de 8 semaines
  à chaque fois. 8 semaines, c'est le délai pour recruter un intérimaire ou décaler des congés.

### Ce qu'on donne au modèle

| Information | Forme | Justification |
|---|---|---|
| Ponts, semaine entre Noël et le jour de l'an | `holidays` Prophet | Effets calendaires connus. Les jours fériés ne sont pas dans la série puisqu'ils ne sont pas travaillés. |
| Événements connus à l'avance | Régresseur `evt` : centaines de boîtes à traiter par jour, volume de l'événement étalé sur ses jours ouvrés | C'est l'info qu'un planning d'exploitation possède réellement (contrat signé, date de reprise). |
| Pics imprévus (audits, contrôles) | Rien | Inconnus au moment de prévoir : les donner serait de la fuite d'information. |

### Modèles comparés

| Modèle | MAPE test 2026 | MAPE validation croisée |
|---|---|---|
| 0. Baseline « même jour l'an dernier » | 45,9 % | 41,5 % |
| 1. Prophet seul | 54,7 % | 36,2 % |
| 2. Prophet + événements (tendance linéaire) | 19,4 % | 17,8 % |
| **3. Prophet + événements, tendance plate** | **17,2 %** | **16,6 %** |

Moyennes sur les 5 sites. Le détail par site est dans le notebook et dans `outputs/validation_croisee.csv`.

### Ce qu'on en retient

**Les événements connus font presque tout le travail.** Sans eux, Prophet prend une reprise de fonds pour une
tendance et la prolonge. À Saint-Priest, il surestime 2026 de plus de 100 % parce qu'il extrapole la reprise
de 2025. Avec eux, l'erreur est divisée par deux.

**Pourquoi la tendance plate.** En tendance linéaire, Charleval passe de 23 % d'erreur (sans événements) à
31 % (avec). Une fois les arrivées de clients de 2022-2023 expliquées par le régresseur, le modèle place sa
tendance de fond trop haut fin 2025 (environ 31 h/jour pour un niveau réel d'environ 28) et surestime
toute l'année suivante. La tendance plate supprime ce piège. En contrepartie, elle sous-estimera un site
en croissance régulière. La validation croisée la donne meilleure ou à égalité sur 4 sites sur 5 ; seul
Villeneuve-la-Garenne fait un peu mieux en linéaire (14,6 % contre 15,6 %).

**Le modèle retrouve le temps standard.** Le coefficient appris pour le régresseur vaut 7,3 à 9,4 h pour
100 boîtes/jour selon le site. Le générateur utilise 5 min par boîte, soit 8,3 h pour 100 boîtes : le
modèle a donc retrouvé le mécanisme sans qu'on le lui donne.

**L'erreur ne se dégrade pas avec l'horizon.** Elle reste entre 14 et 19 % de la semaine 1 à la semaine 8.
Le modèle s'appuie sur le calendrier et les événements planifiés, pas sur les dernières valeurs observées.

**Ce qui reste raté.** Les pics imprévus des gros clients, et une sous-estimation d'environ 15 % au plus fort
de la reprise de Buc en 2026.

### Pistes non explorées

- Un régresseur « stock en rayon » : un nouveau client augmente durablement les consultations, ce que la
  tendance plate ne capte pas.
- Prévoir chaque type de mouvement séparément (versements planifiés vs consultations aléatoires), puis
  additionner.
- Comparer avec un modèle de gradient boosting (LightGBM) sur des variables calendaires.

> **À compléter avec tes mots :** ta lecture des résultats, ce qui te paraît exploitable ou non pour un
> responsable de site.

### Sorties

- `outputs/previsions_2026.csv` : par site et par jour ouvré de 2026, heures réelles, prévision de la
  baseline, de Prophet seul et du modèle retenu, avec l'intervalle à 80 %.
- `outputs/validation_croisee.csv` : MAPE hebdo par site et par modèle.

---

## 6. Des heures aux effectifs (`notebooks/03_effectifs.ipynb`)

### Conversion

**ETP nécessaires = heures prévues ÷ (capacité d'un ETP × 90 %)**

- Capacité d'un ETP : 7 h par jour ouvré × taux de présence. Le taux vient des hypothèses du générateur :
  92 % en temps normal, 82 % en juillet et décembre, 62 % en août.
- Cible de 90 % : on garde une marge pour les imprévus (audits clients, absences), les inventaires et la
  formation.
- Arrondi au demi-ETP supérieur pour un effectif mensuel.

### Les alertes de surcharge (rétrospectif 2026)

Une semaine est signalée quand les heures prévues dépassent les heures disponibles de l'équipe en place.
En 2026, 46 semaines-site sur 220 ont réellement été en surcharge.

| Alerte dès que la prévision dépasse… | Fiabilité (alertes justes) | Couverture (surcharges vues) |
|---|---|---|
| 100 % des heures dispo | 77 % | 52 % |
| 90 % | 76 % | 57 % |
| 80 % | 45 % | 76 % |
| 70 % | 35 % | 91 % |

Il n'y a pas de bon réglage dans l'absolu. Tout dépend de ce que coûte une fausse alerte (une semaine
d'intérim inutile) par rapport à une surcharge ratée (retards de restitution aux clients). C'est une
décision métier.

### Pilotage actuel vs pilotage par la prévision (janvier-octobre 2026, 5 sites)

- **Actuel** : effectif fixé pour l'année sur la charge moyenne de l'année précédente (+5 %).
- **Par la prévision** : effectif mensuel calculé à partir de la prévision du 1er janvier.

| | Pilotage actuel | Par la prévision | Écart |
|---|---|---|---|
| ETP moyens par site | 6,3 | 5,5 | −0,8 |
| Heures payées | 40 726 | 35 766 | −4 961 (−12 %) |
| Heures de surcharge | 1 008 | 819 | −190 |
| Heures inutilisées | 9 273 | 4 123 | −5 150 |

Charge réelle sur la période : 32 462 h.

Par site, le gain n'est pas uniforme :
- **Buc** : la reprise de 2026 était signée mais absente du calcul d'effectif. On passe de 655 h de surcharge
  à 30 h.
- **Saint-Priest** : l'effectif avait été gonflé par la reprise ponctuelle de 2025. On passe de 5 018 h
  inutilisées à 388 h.
- **Charleval et Lesquin** : un peu plus de surcharge avec la prévision (331 h contre 147, 297 h contre 192),
  parce que le modèle sous-estime légèrement ces sites.
- **Villeneuve-la-Garenne** : plus d'heures inutilisées avec la prévision, à cause de l'arrondi au
  demi-poste et de la cible de 90 %.

Point de prudence : ajuster un effectif chaque mois a un coût que ce calcul ignore (recrutement et
formation d'intérimaires, contraintes contractuelles). Une heure « inutilisée » n'est pas non plus
forcément perdue, puisqu'elle sert aux inventaires et à la formation.

### Plan prévisionnel novembre 2026 → janvier 2027

Modèle réentraîné sur tout l'historique, prévision semaine par semaine et écart en ETP avec l'équipe en
place :
- novembre-décembre calmes partout, avec Saint-Priest en sureffectif d'environ 3,5 postes ;
- en janvier, Villeneuve-la-Garenne repasse au-dessus de sa capacité (+1 à +1,5 ETP), à cause des
  consultations bancaires de début d'année et des campagnes de destruction.

Le notebook contient une liste `EVENEMENTS_A_VENIR` où l'on saisit les reprises signées. Exemple fictif
inclus : 15 000 boîtes à Lesquin de mi-janvier à fin mars 2027, ce qui fait apparaître un besoin de
+3,5 à +4 ETP dès la semaine du 11 janvier.

> **À compléter avec tes mots :** est-il réaliste d'ajuster l'effectif au mois sur un site d'archivage ?
> Qui choisirait le réglage des alertes ? Comment ce plan serait-il diffusé aux responsables de site ?

### Sorties

- `outputs/effectifs_2026_retrospectif.csv` : par site et par semaine, heures réelles et prévues,
  ETP nécessaires et en place.
- `outputs/pilotage_mensuel_2026.csv` : comparaison des deux pilotages, par site et par mois.
- `outputs/plan_effectifs_nov2026_janv2027.csv` : plan prévisionnel, avec et sans scénario, et un statut
  (Renfort à prévoir / OK / Sous-charge).

---

## 7. Limites connues

- Les temps standards par boîte sont des hypothèses, pas des mesures.
- Les ratios de consultation et de versement s'appuient en partie sur une source commerciale (blog d'éditeur).
- Les pics imprévus sont probablement trop nombreux (environ 80 par an sur 5 sites).
- Les retours de consultation sont une conséquence mécanique des sorties : ils sont donc en partie
  prévisibles, ce qui avantage un peu le modèle par rapport à la réalité.
- Les noms de villes servent uniquement d'ancrage géographique : sites, stocks et clients sont inventés.
- Les taux de présence (congés, absences) sont des hypothèses fixes, identiques pour tous les sites.
- Le gain du pilotage par la prévision dépend fortement de la règle de dimensionnement « actuelle », qui est elle-même simulée.
- Les prévisions et les scores sont identiques d'une exécution à l'autre. Seules les bornes des intervalles
  d'incertitude varient de quelques heures, car Prophet les estime par tirage aléatoire.

---

## 8. Arborescence

```
forecast-archivage/
├── .venv/                    # non versionné
├── data/
│   ├── README.md             # dictionnaire des données, hypothèses, sources
│   └── *.csv                 # non versionnés, régénérés par generate_dataset.py
├── notebooks/
│   ├── 01_exploration.ipynb
│   ├── 02_prophet.ipynb
│   └── 03_effectifs.ipynb
├── outputs/                  # prévisions, scores et plans d'effectifs (générés par 02 et 03)
├── docs/img/                 # graphiques exportés pour le README
├── generate_dataset.py
├── README.md                 # présentation du projet (vitrine GitHub)
├── DOCUMENTATION.md          # ce fichier
├── requirements.txt          # dépendances principales, versions figées
└── .gitignore
```

---

## 9. Historique

| Date | Étape |
|---|---|
| 31/10/2026 | Environnement (Python 3.13, venv, Prophet), générateur de données v1, notebook d'exploration |
| 02/11/2026 | Modélisation : baseline, 3 variantes Prophet, validation croisée, choix du modèle (événements + tendance plate) |
| 02/11/2026 | Effectifs : conversion heures → ETP, évaluation des alertes, pilotage actuel vs prévision, plan nov. 2026 – janv. 2027 |
| 02/11/2026 | Mise en forme GitHub : README de présentation, dictionnaire déplacé dans `data/`, `.gitignore`, `requirements.txt` minimal, graphiques dans `docs/img/` |
