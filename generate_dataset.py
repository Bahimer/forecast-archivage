"""
Générateur de dataset simulé — charge de travail des archivistes d'un tiers-archiveur fictif

Toutes les données sont FICTIVES. Les ordres de grandeur s'appuient sur des informations
publiques du secteur (voir data/README.md), mais l'entreprise, les clients et les volumes sont inventés.

Usage :
    python generate_dataset.py                # écrit les CSV dans ./data
    python generate_dataset.py --seed 7       # autre tirage aléatoire
    python generate_dataset.py --out data_v2  # autre dossier de sortie

Dépendances : pandas, numpy, python-dateutil (déjà installées avec Prophet).
"""

import argparse
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dateutil.easter import easter

# ---------------------------------------------------------------------------
# 1. PARAMÈTRES GÉNÉRAUX
# ---------------------------------------------------------------------------
DATE_DEBUT = date(2021, 1, 1)
DATE_FIN = date(2026, 10, 30)

# Sites simulés. Les villes ne servent que d'ancrage géographique ;
# stocks, nombres de clients et capacités sont des hypothèses.
SITES = [
    # id, nom, ville, dept, region, stock_2021 (boîtes), nb_clients, capacite_ml, agree_siaf
    ("S01", "Site IDF Nord", "Villeneuve-la-Garenne", "92", "Île-de-France", 420_000, 130, 60_000, True),
    ("S02", "Site IDF Ouest", "Buc", "78", "Île-de-France", 170_000, 110, 25_000, True),
    ("S03", "Site Provence", "Charleval", "13", "Provence-Alpes-Côte d'Azur", 200_000, 80, 28_000, True),
    ("S04", "Site Hauts-de-France", "Lesquin", "59", "Hauts-de-France", 210_000, 85, 32_000, False),
    ("S05", "Site Rhône", "Saint-Priest", "69", "Auvergne-Rhône-Alpes", 240_000, 95, 35_000, True),
]

# Répartition des segments clients par site (poids relatifs)
SEGMENTS = ["Banque", "Assurance", "Santé", "Collectivité", "Notariat",
            "Avocats & experts-comptables", "Industrie & distribution", "Grand compte"]
MIX_SEGMENTS = {
    "S01": [0.18, 0.10, 0.06, 0.14, 0.06, 0.16, 0.10, 0.20],
    "S02": [0.06, 0.06, 0.04, 0.08, 0.45, 0.20, 0.06, 0.05],
    "S03": [0.08, 0.06, 0.24, 0.24, 0.10, 0.12, 0.12, 0.04],
    "S04": [0.22, 0.10, 0.08, 0.10, 0.06, 0.12, 0.24, 0.08],
    "S05": [0.10, 0.20, 0.10, 0.12, 0.06, 0.12, 0.20, 0.10],
}

# Comportement annuel moyen par segment (part du stock concernée chaque année)
#   consult : boîtes sorties en consultation / stock
#   verse   : boîtes nouvellement versées / stock
#   detruit : boîtes détruites à échéance de DUA / stock
#   p_audit : probabilité annuelle d'un pic de consultations (contrôle, audit, contentieux)
PROFIL_SEGMENT = {
    "Banque":                       dict(consult=0.11, verse=0.08, detruit=0.045, p_audit=0.30),
    "Assurance":                    dict(consult=0.10, verse=0.08, detruit=0.040, p_audit=0.20),
    "Santé":                        dict(consult=0.12, verse=0.07, detruit=0.020, p_audit=0.10),
    "Collectivité":                 dict(consult=0.05, verse=0.06, detruit=0.030, p_audit=0.12),
    "Notariat":                     dict(consult=0.06, verse=0.05, detruit=0.003, p_audit=0.05),
    "Avocats & experts-comptables": dict(consult=0.07, verse=0.09, detruit=0.035, p_audit=0.15),
    "Industrie & distribution":     dict(consult=0.04, verse=0.07, detruit=0.040, p_audit=0.08),
    "Grand compte":                 dict(consult=0.09, verse=0.08, detruit=0.040, p_audit=0.20),
}

# Saisonnalité mensuelle des consultations par segment (multiplicateur, moyenne ~1)
#   Banque/Assurance : audits et clôtures au S1 ; Avocats/EC : saison fiscale mars-mai ;
#   Collectivités : contrôles CRC et préparation budgétaire à l'automne.
SAISON_CONSULT = {
    "Banque":                       [1.20, 1.25, 1.20, 1.10, 1.05, 1.00, 0.90, 0.55, 0.95, 1.00, 1.00, 0.80],
    "Assurance":                    [1.10, 1.15, 1.15, 1.10, 1.05, 1.00, 0.90, 0.60, 1.00, 1.05, 1.05, 0.85],
    "Santé":                        [1.05, 1.05, 1.05, 1.00, 1.00, 1.00, 0.95, 0.80, 1.00, 1.05, 1.05, 0.90],
    "Collectivité":                 [0.90, 1.00, 1.05, 1.00, 1.00, 0.95, 0.85, 0.55, 1.10, 1.25, 1.25, 0.90],
    "Notariat":                     [1.00, 1.05, 1.10, 1.10, 1.05, 1.05, 0.95, 0.55, 1.00, 1.05, 1.05, 0.95],
    "Avocats & experts-comptables": [1.00, 1.10, 1.30, 1.35, 1.25, 1.00, 0.80, 0.45, 0.90, 0.95, 0.95, 0.85],
    "Industrie & distribution":     [1.05, 1.05, 1.05, 1.00, 1.00, 1.00, 0.90, 0.65, 1.00, 1.05, 1.05, 0.90],
    "Grand compte":                 [1.10, 1.15, 1.15, 1.05, 1.00, 1.00, 0.90, 0.60, 1.00, 1.05, 1.05, 0.85],
}

# Répartition dans l'année des versements et des campagnes de destruction
MOIS_VERSEMENT = np.array([0.12, 0.10, 0.09, 0.08, 0.08, 0.10, 0.10, 0.03, 0.10, 0.08, 0.07, 0.05])
MOIS_DESTRUCTION = np.array([0.20, 0.20, 0.18, 0.12, 0.06, 0.05, 0.03, 0.01, 0.05, 0.05, 0.04, 0.01])

# Effet jour de semaine (lundi -> vendredi) : les demandes s'accumulent le week-end
JOUR_SEMAINE = np.array([1.18, 1.05, 1.00, 0.98, 0.79])

# Types de mouvements et temps standard d'un archiviste (minutes par boîte) — hypothèses
TYPES_MOUVEMENT = [
    # code, libellé, minutes_par_boite, description
    ("VER", "Versement", 5.0, "Contrôle bordereau, étiquetage code-barres, saisie, mise en rayon"),
    ("CON", "Consultation (sortie)", 9.0, "Recherche emplacement, extraction, préparation de l'envoi"),
    ("RET", "Retour de consultation", 5.0, "Contrôle, réintégration à l'emplacement"),
    ("NUM", "Numérisation à la demande", 12.0, "Préparation, scan, contrôle qualité et envoi du fichier"),
    ("DES", "Destruction", 2.5, "Extraction, palettisation, bordereau et certificat de destruction"),
    ("RES", "Restitution", 3.0, "Extraction et préparation du transfert en fin de contrat"),
]
MINUTES = {t[0]: t[2] for t in TYPES_MOUVEMENT}

HEURES_FIXES_JOUR = 3.5        # inventaires, réception, administration (par site et jour ouvré)
HEURES_PAR_ETP_JOUR = 7.0
TENDANCE_CONSULT_AN = -0.03    # baisse annuelle des consultations physiques (dématérialisation)
PART_NUM_DEBUT, PART_NUM_FIN = 0.08, 0.30  # part des consultations servies en numérique

# Événements connus à l'avance (contrats signés, fins de contrat) — fictifs
REPRISES = [
    # site, segment, nom_client, début, fin, nb_boites
    ("S03", "Santé", "Centre hospitalier du Val de Durance", date(2022, 9, 5), date(2022, 11, 25), 18_000),
    ("S01", "Collectivité", "Conseil départemental (reprise de fonds)", date(2023, 3, 13), date(2023, 6, 30), 42_000),
    ("S04", "Banque", "Banque régionale du Nord", date(2024, 10, 7), date(2024, 12, 13), 25_000),
    ("S05", "Assurance", "Mutuelle Rhône-Alpes Prévoyance", date(2025, 5, 12), date(2025, 7, 11), 30_000),
    ("S02", "Notariat", "Groupement d'offices notariaux des Yvelines", date(2026, 2, 2), date(2026, 4, 10), 12_000),
]
PERTES = [
    # site, segment, nom_client, début restitution, fin, nb_boites (sorties du stock)
    ("S01", "Grand compte", "Groupe industriel (départ concurrent)", date(2025, 1, 13), date(2025, 2, 28), 20_000),
]

PRENOMS_SOCIETES = ["Arval", "Belcour", "Cerval", "Dumont", "Esterel", "Fontanel", "Garance", "Hautval",
                    "Isard", "Jonquière", "Kerval", "Lavalette", "Marigny", "Norval", "Orsay", "Peyrac",
                    "Quincy", "Rochemaure", "Saulnier", "Tarente", "Valmont", "Verneuil", "Vauclair", "Brionne"]
PREFIXE_SEGMENT = {
    "Banque": "Banque", "Assurance": "Assurances", "Santé": "Clinique", "Collectivité": "Commune de",
    "Notariat": "Office notarial", "Avocats & experts-comptables": "Cabinet",
    "Industrie & distribution": "Société", "Grand compte": "Groupe",
}


# ---------------------------------------------------------------------------
# 2. CALENDRIER
# ---------------------------------------------------------------------------
def jours_feries(annee):
    p = easter(annee)
    return {
        date(annee, 1, 1): "Jour de l'an",
        p + timedelta(days=1): "Lundi de Pâques",
        date(annee, 5, 1): "Fête du travail",
        date(annee, 5, 8): "Victoire 1945",
        p + timedelta(days=39): "Ascension",
        p + timedelta(days=50): "Lundi de Pentecôte",
        date(annee, 7, 14): "Fête nationale",
        date(annee, 8, 15): "Assomption",
        date(annee, 11, 1): "Toussaint",
        date(annee, 11, 11): "Armistice",
        date(annee, 12, 25): "Noël",
    }


def construire_calendrier():
    jours = pd.date_range(DATE_DEBUT, DATE_FIN, freq="D")
    feries = {}
    for a in range(DATE_DEBUT.year, DATE_FIN.year + 1):
        feries.update(jours_feries(a))
    cal = pd.DataFrame({"date": jours})
    cal["annee"] = cal.date.dt.year
    cal["mois"] = cal.date.dt.month
    cal["jour_semaine"] = cal.date.dt.dayofweek  # 0 = lundi
    cal["nom_jour"] = cal.jour_semaine.map(dict(enumerate(
        ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"])))
    cal["semaine_iso"] = cal.date.dt.isocalendar().week.astype(int)
    cal["trimestre"] = cal.date.dt.quarter
    cal["jour_ferie"] = cal.date.dt.date.map(feries).fillna("")
    cal["est_ferie"] = cal.jour_ferie != ""
    cal["est_ouvre"] = (cal.jour_semaine < 5) & ~cal.est_ferie
    # Pont : jour ouvré coincé entre un férié et un week-end
    ouvre = cal.est_ouvre.values
    pont = np.zeros(len(cal), dtype=bool)
    for i in range(1, len(cal) - 1):
        if ouvre[i] and (cal.est_ferie.iat[i - 1] and cal.jour_semaine.iat[i + 1] >= 5
                         or cal.est_ferie.iat[i + 1] and cal.jour_semaine.iat[i - 1] >= 5):
            pont[i] = True
    cal["est_pont"] = pont
    jj = cal.date.dt.day
    cal["periode_conges"] = np.select(
        [cal.mois == 8, (cal.mois == 7) & (jj >= 14), (cal.mois == 12) & (jj >= 23), (cal.mois == 1) & (jj <= 2)],
        ["Été", "Été", "Fin d'année", "Fin d'année"], default="")
    return cal


def facteur_activite(cal):
    """Multiplicateur d'activité des demandes clients (0 les jours non ouvrés)."""
    f = np.where(cal.est_ouvre, JOUR_SEMAINE[np.minimum(cal.jour_semaine, 4)], 0.0)
    jj = cal.date.dt.day.values
    m = cal.mois.values
    f = f * np.where(cal.est_pont, 0.65, 1.0)
    f = f * np.where((m == 12) & (jj >= 23), 0.55, 1.0)
    f = f * np.where((m == 7) & (jj >= 14), 0.85, 1.0)
    return f


def jours_ouvres_entre(cal, debut, fin):
    d = cal[(cal.date >= pd.Timestamp(debut)) & (cal.date <= pd.Timestamp(fin)) & cal.est_ouvre]
    return d.index.values


# ---------------------------------------------------------------------------
# 3. CLIENTS
# ---------------------------------------------------------------------------
def nom_client(rng, segment, deja):
    while True:
        n = f"{PREFIXE_SEGMENT[segment]} {rng.choice(PRENOMS_SOCIETES)}"
        if segment in ("Avocats & experts-comptables", "Notariat"):
            n += f" & {rng.choice(PRENOMS_SOCIETES)}"
        n += f" {rng.integers(10, 99)}" if n in deja else ""
        if n not in deja:
            deja.add(n)
            return n


def construire_clients(rng):
    lignes, noms = [], set()
    cid = 1
    for site_id, _, _, _, _, stock, n_cli, _, _ in SITES:
        # Stock très concentré : quelques gros clients, beaucoup de petits (loi log-normale)
        poids = rng.lognormal(0, 1.4, n_cli)
        stocks = np.maximum(30, (poids / poids.sum() * stock)).round().astype(int)
        segs = rng.choice(SEGMENTS, size=n_cli, p=np.array(MIX_SEGMENTS[site_id]) / sum(MIX_SEGMENTS[site_id]))
        for s, seg in zip(stocks, segs):
            # 80 % des clients sont déjà là au 01/01/2021, les autres arrivent en cours de période
            if rng.random() < 0.80:
                debut = date(int(rng.integers(2003, 2021)), int(rng.integers(1, 13)), 1)
                stock_init = int(s)
            else:
                debut = DATE_DEBUT + timedelta(days=int(rng.integers(30, (DATE_FIN - DATE_DEBUT).days - 60)))
                stock_init = 0
            fin = None
            if rng.random() < 0.10:  # ~10 % de départs sur la période
                fin = max(debut, DATE_DEBUT) + timedelta(days=int(rng.integers(180, 1900)))
                fin = fin if fin < DATE_FIN else None
            prof = PROFIL_SEGMENT[seg]
            lignes.append(dict(
                client_id=f"C{cid:04d}", nom_client=nom_client(rng, seg, noms), segment=seg, site_id=site_id,
                date_debut_contrat=debut, date_fin_contrat=fin,
                stock_cible_boites=int(s), stock_initial_boites=stock_init,
                taux_consultation=round(prof["consult"] * rng.lognormal(0, 0.35), 4),
                taux_versement=round(prof["verse"] * 0.7 * rng.lognormal(0, 0.30), 4),
                taux_destruction=round(prof["detruit"] * rng.lognormal(0, 0.30), 4),
                type_client="Récurrent", evenement_id=None))
            cid += 1

    for i, (site, seg, nom, d1, d2, n) in enumerate(REPRISES, 1):
        prof = PROFIL_SEGMENT[seg]
        lignes.append(dict(
            client_id=f"C{cid:04d}", nom_client=nom, segment=seg, site_id=site,
            date_debut_contrat=d1, date_fin_contrat=None, stock_cible_boites=n, stock_initial_boites=0,
            taux_consultation=prof["consult"], taux_versement=prof["verse"] * 0.6,
            taux_destruction=prof["detruit"], type_client="Reprise de fonds", evenement_id=f"EV-REP-{i:02d}"))
        cid += 1

    clients = pd.DataFrame(lignes)
    # Les pertes portent sur un gros client existant du site concerné
    for i, (site, seg, nom, d1, d2, n) in enumerate(PERTES, 1):
        idx = clients[(clients.site_id == site) & (clients.type_client == "Récurrent")
                      & (clients.stock_initial_boites > 0)].stock_initial_boites.idxmax()
        clients.loc[idx, ["nom_client", "segment", "date_fin_contrat", "stock_cible_boites",
                          "stock_initial_boites", "type_client", "evenement_id"]] = \
            [nom, seg, d2, n, n, "Départ (restitution)", f"EV-PER-{i:02d}"]
        clients.loc[idx, "date_debut_contrat"] = date(2009, 4, 1)
    clients["taille_client"] = pd.cut(clients.stock_cible_boites, [0, 500, 3000, 15000, 10**9],
                                      labels=["TPE/PME", "ETI", "Grand compte", "Très grand compte"])
    return clients


# ---------------------------------------------------------------------------
# 4. SIMULATION JOUR PAR JOUR
# ---------------------------------------------------------------------------
def repartir(total, n_jours, rng):
    """Répartit un total de boîtes sur n jours avec un peu d'irrégularité."""
    if n_jours <= 0 or total <= 0:
        return np.zeros(max(n_jours, 0), dtype=int)
    p = rng.dirichlet(np.full(n_jours, 8.0))
    return rng.multinomial(int(total), p)


def simuler(rng, cal, clients):
    n_j, n_c = len(cal), len(clients)
    act = facteur_activite(cal)
    mois = cal.mois.values
    annee_frac = ((cal.date - pd.Timestamp(DATE_DEBUT)).dt.days / 365.25).values
    ouvres = np.where(cal.est_ouvre.values)[0]
    idx_date = {d.date(): i for i, d in enumerate(cal.date)}

    def idx_ouvre_apres(d):
        i = idx_date.get(d, 0 if d < DATE_DEBUT else n_j - 1)
        pos = np.searchsorted(ouvres, i)
        return ouvres[min(pos, len(ouvres) - 1)]

    ouvres_par_mois = {}
    for i in ouvres:
        d = cal.date.iat[i]
        ouvres_par_mois.setdefault((d.year, d.month), []).append(i)

    def pos_ouvre_aleatoire(a, m):
        """Position (dans `ouvres`) d'un jour ouvré tiré au hasard dans le mois, ou None."""
        liste = ouvres_par_mois.get((a, m))
        if not liste:
            return None
        return int(np.searchsorted(ouvres, rng.choice(liste)))

    # Matrices planifiées (jour x client) : versements, destructions, restitutions
    VER = np.zeros((n_j, n_c), dtype=np.int32)
    DES = np.zeros((n_j, n_c), dtype=np.int32)
    RES = np.zeros((n_j, n_c), dtype=np.int32)
    AUDIT = np.ones((n_j, n_c), dtype=np.float32)
    evenements = []

    debut_idx = np.array([idx_date.get(d, 0) if d >= DATE_DEBUT else 0 for d in clients.date_debut_contrat])
    fin_idx = np.array([idx_date[d] if (d is not None and not pd.isna(d)) else n_j for d in clients.date_fin_contrat])

    annees = range(DATE_DEBUT.year, DATE_FIN.year + 1)
    for c, cl in clients.iterrows():
        k = clients.index.get_loc(c)
        prof = PROFIL_SEGMENT[cl.segment]

        # --- Arrivée d'un nouveau client : versement initial étalé sur quelques semaines
        if cl.stock_initial_boites == 0 and cl.type_client == "Récurrent":
            d0 = idx_ouvre_apres(cl.date_debut_contrat)
            # Reprise du fonds au rythme de ~200 boîtes/jour (camions + indexation)
            jours = ouvres[(ouvres >= d0)][: max(1, math.ceil(cl.stock_cible_boites / 200))]
            VER[jours, k] += repartir(cl.stock_cible_boites, len(jours), rng)
            if cl.stock_cible_boites >= 3000:  # assez gros pour être planifié par l'exploitation
                evenements.append(dict(
                    evenement_id=f"EV-NEW-{k:04d}", type_evenement="Arrivée nouveau client",
                    site_id=cl.site_id, client_id=cl.client_id,
                    date_debut=cal.date.iat[jours[0]].date(), date_fin=cal.date.iat[jours[-1]].date(),
                    nb_boites=int(cl.stock_cible_boites), connu_a_lavance=True,
                    description=f"Reprise du fonds initial de {cl.nom_client}"))

        # --- Reprises de fonds (gros clients entrants, connues à l'avance)
        if cl.type_client == "Reprise de fonds":
            r = REPRISES[int(cl.evenement_id[-2:]) - 1]
            jours = jours_ouvres_entre(cal, r[3], r[4])
            VER[jours, k] += repartir(cl.stock_cible_boites, len(jours), rng)
            evenements.append(dict(evenement_id=cl.evenement_id, type_evenement="Reprise de fonds",
                                   site_id=cl.site_id, client_id=cl.client_id, date_debut=r[3], date_fin=r[4],
                                   nb_boites=r[5], connu_a_lavance=True,
                                   description=f"Prise en charge du fonds de {cl.nom_client}"))

        # --- Versements récurrents (lots livrés par camion, traités sur 1 à 3 jours)
        for a in annees:
            vol = cl.stock_cible_boites * cl.taux_versement
            if vol < 5:
                continue
            nb_lots = int(np.clip(rng.poisson(max(1.0, cl.stock_cible_boites / 2500)), 1, 12))
            for _ in range(nb_lots):
                m = int(rng.choice(12, p=MOIS_VERSEMENT)) + 1
                pos = pos_ouvre_aleatoire(a, m)
                if pos is None:
                    continue
                taille = int(vol / nb_lots * rng.lognormal(0, 0.45))
                # Un lot est traité au fil de l'eau : ~120 boîtes/jour max sur ce client
                jours = ouvres[pos: pos + int(np.clip(math.ceil(taille / 120), 1, 20))]
                VER[jours, k] += repartir(taille, len(jours), rng)

        # --- Campagnes de destruction (DUA échues, surtout en début d'année)
        for a in annees:
            if rng.random() > 0.85 or cl.taux_destruction < 0.005:
                continue
            m = int(rng.choice(12, p=MOIS_DESTRUCTION)) + 1
            pos = pos_ouvre_aleatoire(a, m)
            if pos is None:
                continue
            taille = int(cl.stock_cible_boites * cl.taux_destruction / 0.85 * rng.lognormal(0, 0.35))
            if taille < 10:
                continue
            jours = ouvres[pos: pos + int(np.clip(math.ceil(taille / 300), 1, 15))]
            DES[jours, k] += repartir(taille, len(jours), rng)

        # --- Pics de consultation imprévus (contrôle fiscal, audit, contentieux)
        for a in annees:
            if rng.random() < prof["p_audit"]:
                pos = pos_ouvre_aleatoire(a, int(rng.integers(1, 13)))
                if pos is None:
                    continue
                duree = int(rng.integers(8, 21))
                jours = ouvres[pos: pos + duree]
                mult = float(rng.uniform(3, 7))
                AUDIT[jours, k] *= mult
                motif = rng.choice(["Contrôle fiscal", "Audit réglementaire", "Contentieux / prud'hommes",
                                    "Due diligence"])
                evenements.append(dict(evenement_id=f"EV-AUD-{len(evenements)+1:04d}",
                                       type_evenement="Pic de consultations", site_id=cl.site_id,
                                       client_id=cl.client_id, date_debut=cal.date.iat[jours[0]].date(),
                                       date_fin=cal.date.iat[jours[-1]].date(), nb_boites=None,
                                       connu_a_lavance=False,
                                       description=f"{motif} — consultations x{mult:.1f}"))

    # --- Départs de clients : restitution du stock restant (calculé pendant la simulation)
    depart_planifie = {}
    for k in range(n_c):
        if fin_idx[k] < n_j:
            ev = clients.evenement_id.iat[k]
            if isinstance(ev, str) and ev.startswith("EV-PER"):
                p = PERTES[int(ev[-2:]) - 1]
                jours = jours_ouvres_entre(cal, p[3], p[4])
                evenements.append(dict(evenement_id=ev, type_evenement="Départ client (restitution)",
                                       site_id=clients.site_id.iat[k], client_id=clients.client_id.iat[k],
                                       date_debut=p[3], date_fin=p[4], nb_boites=p[5], connu_a_lavance=True,
                                       description=f"Restitution du fonds de {clients.nom_client.iat[k]}"))
            else:
                pos = np.searchsorted(ouvres, fin_idx[k])
                jours = ouvres[max(0, pos - 15): pos]
            depart_planifie[k] = jours

    # --- Boucle jour par jour (consultations, retours, numérisation, stocks)
    stock = clients.stock_initial_boites.values.astype(float)
    taux_c = clients.taux_consultation.values
    seg_idx = clients.segment.map({s: i for i, s in enumerate(SEGMENTS)}).values
    saison = np.array([SAISON_CONSULT[s] for s in SEGMENTS])  # (segments, 12)

    CON = np.zeros((n_j, n_c), dtype=np.int32)
    NUM = np.zeros((n_j, n_c), dtype=np.int32)
    RET = np.zeros((n_j + 80, n_c), dtype=np.int32)
    STOCK_FIN_MOIS = []
    gamma_shape = 1.6  # sur-dispersion des demandes (une demande = souvent plusieurs boîtes)

    for j in range(n_j):
        actif = (j >= debut_idx) & (j < fin_idx)
        if act[j] > 0:
            tend = (1 + TENDANCE_CONSULT_AN) ** annee_frac[j]
            lam = stock * taux_c / 252 * act[j] * saison[seg_idx, mois[j] - 1] * AUDIT[j] * tend
            lam = np.where(actif, lam, 0.0)
            lam = rng.gamma(gamma_shape, lam / gamma_shape) if lam.sum() > 0 else lam
            demandes = rng.poisson(lam)
            demandes = np.minimum(demandes, np.maximum(stock, 0).astype(int))
            part_num = PART_NUM_DEBUT + (PART_NUM_FIN - PART_NUM_DEBUT) * annee_frac[j] / annee_frac[-1]
            num = rng.binomial(demandes, part_num)
            CON[j] = demandes - num
            NUM[j] = num
            # Retours physiques : 1 à 8 semaines plus tard, en jours ouvrés
            pos_j = np.searchsorted(ouvres, j)
            for k in np.nonzero(CON[j])[0]:
                lag = int(rng.choice([4, 8, 12, 16, 22, 30], p=[0.15, 0.25, 0.25, 0.15, 0.12, 0.08]))
                cible = ouvres[pos_j + lag] if pos_j + lag < len(ouvres) else n_j
                RET[cible, k] += CON[j, k]

        for k, jours in depart_planifie.items():
            if len(jours) and j == jours[0]:
                RES[jours, k] = repartir(max(int(stock[k]), 0), len(jours), rng)

        stock = stock + VER[j] - DES[j] - RES[j] - CON[j] + RET[j]
        stock = np.maximum(stock, 0)
        DES[j] = np.minimum(DES[j], np.maximum(stock + DES[j], 0).astype(int))

        dj = cal.date.iat[j]
        if (dj + pd.Timedelta(days=1)).month != dj.month or j == n_j - 1:
            STOCK_FIN_MOIS.append(pd.DataFrame({
                "date_fin_mois": dj.date(), "client_id": clients.client_id.values,
                "site_id": clients.site_id.values, "stock_boites": stock.round().astype(int)}))

    # Les retours tombés un jour non ouvré sont reportés au jour ouvré suivant
    RET = RET[:n_j]
    for j in range(n_j):
        if act[j] == 0 and RET[j].any():
            nxt = ouvres[np.searchsorted(ouvres, j)] if np.searchsorted(ouvres, j) < len(ouvres) else None
            if nxt is not None:
                RET[nxt] += RET[j]
            RET[j] = 0

    return dict(VER=VER, CON=CON, RET=RET, NUM=NUM, DES=DES, RES=RES), evenements, STOCK_FIN_MOIS


# ---------------------------------------------------------------------------
# 5. MISE EN FORME DES TABLES
# ---------------------------------------------------------------------------
def table_mouvements(mats, cal, clients):
    morceaux = []
    for code, M in mats.items():
        j, k = np.nonzero(M)
        if len(j) == 0:
            continue
        morceaux.append(pd.DataFrame({
            "date": cal.date.values[j], "site_id": clients.site_id.values[k],
            "client_id": clients.client_id.values[k], "type_mouvement": code,
            "nb_boites": M[j, k]}))
    f = pd.concat(morceaux, ignore_index=True)
    f["minutes_standard"] = (f.nb_boites * f.type_mouvement.map(MINUTES)).round(1)
    f = f.sort_values(["date", "site_id", "client_id", "type_mouvement"]).reset_index(drop=True)
    f.insert(0, "mouvement_id", np.arange(1, len(f) + 1))
    return f


def table_charge(rng, mouv, cal):
    piv = (mouv.groupby(["date", "site_id", "type_mouvement"]).minutes_standard.sum()
           .unstack(fill_value=0) / 60)
    piv.columns = [f"heures_{c.lower()}" for c in piv.columns]
    grille = pd.MultiIndex.from_product([cal.date, [s[0] for s in SITES]], names=["date", "site_id"])
    ch = piv.reindex(grille, fill_value=0).reset_index()
    ch = ch.merge(cal[["date", "est_ouvre", "mois", "annee"]], on="date")
    cols_h = [c for c in ch.columns if c.startswith("heures_")]
    brut = ch[cols_h].sum(axis=1) + np.where(ch.est_ouvre, HEURES_FIXES_JOUR, 0)
    # Écart de productivité réel (aléas, boîtes difficiles à trouver, nouvelles recrues…)
    ch["heures_requises"] = (brut * rng.normal(1, 0.06, len(ch)).clip(0.8, 1.25)).round(2)
    ch.loc[~ch.est_ouvre, "heures_requises"] = 0.0

    # Effectif : dimensionné chaque année sur la charge moyenne de l'année précédente (+5 %)
    moy = ch[ch.est_ouvre].groupby(["site_id", "annee"]).heures_requises.mean().unstack()
    etp = {}
    for s in moy.index:
        for a in moy.columns:
            ref = moy.loc[s, a - 1] if (a - 1) in moy.columns else moy.loc[s, a]
            etp[(s, a)] = math.ceil(ref * 1.05 / (HEURES_PAR_ETP_JOUR * 0.88) * 2) / 2
    ch["etp_archivistes"] = [etp[(s, a)] for s, a in zip(ch.site_id, ch.annee)]
    presence = np.where(ch.mois == 8, 0.62, np.where(ch.mois.isin([7, 12]), 0.82, 0.92))
    ch["heures_disponibles"] = np.where(ch.est_ouvre, ch.etp_archivistes * HEURES_PAR_ETP_JOUR * presence, 0).round(2)
    ch["taux_charge"] = np.where(ch.heures_disponibles > 0,
                                 (ch.heures_requises / ch.heures_disponibles).round(3), np.nan)
    ordre = ["date", "site_id", "heures_ver", "heures_con", "heures_ret", "heures_num", "heures_des",
             "heures_res", "heures_requises", "etp_archivistes", "heures_disponibles", "taux_charge"]
    for c in ordre:
        if c not in ch.columns:
            ch[c] = 0.0
    ch[cols_h] = ch[cols_h].round(2)
    ren = {"heures_ver": "heures_versement", "heures_con": "heures_consultation", "heures_ret": "heures_retour",
           "heures_num": "heures_numerisation", "heures_des": "heures_destruction", "heures_res": "heures_restitution"}
    return ch[ordre].rename(columns=ren)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    cal = construire_calendrier()
    clients = construire_clients(rng)
    mats, evenements, stocks = simuler(rng, cal, clients)
    mouv = table_mouvements(mats, cal, clients)
    charge = table_charge(rng, mouv, cal)

    dim_site = pd.DataFrame(SITES, columns=["site_id", "nom_site", "ville", "departement", "region",
                                            "stock_reference_boites", "nb_clients_simules", "capacite_ml",
                                            "agree_siaf"])
    dim_type = pd.DataFrame(TYPES_MOUVEMENT, columns=["type_mouvement", "libelle", "minutes_par_boite",
                                                      "description"])
    dim_date = cal.drop(columns=[])
    dim_client = clients[["client_id", "nom_client", "segment", "taille_client", "type_client", "site_id",
                          "date_debut_contrat", "date_fin_contrat", "stock_cible_boites",
                          "taux_consultation", "taux_versement", "taux_destruction", "evenement_id"]]
    dim_evt = pd.DataFrame(evenements).sort_values(["date_debut", "evenement_id"])
    stock_mensuel = pd.concat(stocks, ignore_index=True)
    stock_mensuel = stock_mensuel[stock_mensuel.client_id.isin(mouv.client_id.unique())]

    # Série prête pour Prophet : ds / y par site (jours ouvrés uniquement)
    prophet = charge.merge(cal[["date", "est_ouvre"]], on="date")
    prophet = prophet[prophet.est_ouvre][["date", "site_id", "heures_requises"]] \
        .rename(columns={"date": "ds", "heures_requises": "y"})

    fichiers = {
        "dim_date.csv": dim_date, "dim_site.csv": dim_site, "dim_client.csv": dim_client,
        "dim_type_mouvement.csv": dim_type, "dim_evenement.csv": dim_evt,
        "fact_mouvement.csv": mouv, "fact_charge_jour.csv": charge,
        "fact_stock_mensuel.csv": stock_mensuel, "prophet_charge_site.csv": prophet,
    }
    for nom, df in fichiers.items():
        df.to_csv(out / nom, index=False, encoding="utf-8", sep=",", date_format="%Y-%m-%d")
        print(f"{nom:28s} {len(df):>9,} lignes")


if __name__ == "__main__":
    main()
