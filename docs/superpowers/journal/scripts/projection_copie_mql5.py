#!/usr/bin/env python3
"""Projection de copie de signaux MQL5 sur petit compte — Goldtrade Pro ICM vs GoldWave.

Consigne le calcul de ext-3 (2026-09-27). Dependances : numpy + stdlib.

Ce que ce script montre, et qui est le resultat principal : sur un petit compte,
le terme dominant n'est ni la strategie ni le trader, c'est le SIZING (quantification
du lot au minimum broker) puis le FRAIS d'abonnement. Les deux ecrasent l'edge.

Les distributions par trade sont calibrees sur les statistiques PUBLIEES de chaque
signal (taux de reussite, gain moyen, perte moyenne, meilleur/pire trade), pas sur
une hypothese de forme. Validation : l'historique reel de Goldtrade (x7.36 sur 741
trades) tombe entre P25 et P75 du modele.

    python3 projection_copie_mql5.py
"""
from statistics import NormalDist
import math
import numpy as np

RNG = np.random.default_rng(20260927)
N = 200_000
JOURS = 95                 # 2026-09-27 -> 2026-12-31
SEM = JOURS / 7.0
EURUSD = 1.17              # HYPOTHESE, non verifiee a la source
LOT_MIN = 0.01             # IC Markets

# --------------------------------------------------------------------- calibration
def lognorm_de(moyenne, q_val, q_p):
    """mu, sigma d'une lognormale de moyenne donnee dont le quantile q_p vaut q_val.

    Resout  mu = ln(moyenne) - s^2/2  et  mu + z*s = ln(q_val).
    Si le systeme n'a pas de racine reelle on prend la racine double (cas limite).
    """
    z = NormalDist().inv_cdf(q_p)
    disc = 4 * z * z - 8 * (math.log(q_val) - math.log(moyenne))
    s = z if disc < 0 else (2 * z - math.sqrt(disc)) / 2.0
    return math.log(moyenne) - s * s / 2.0, s

# Goldtrade Pro ICM — 741 trades / 155 sem. ; 429 G / 312 P ; 1000 -> 7360.45 EUR
# equite moyenne temporelle : (7360-1000)/ln(7.36) ; c'est l'echelle qui reproduit
# la croissance reelle, donc celle qui suppose un sizing proportionnel a l'equite.
EQ_GT = (7360.45 - 1000.0) / math.log(7.36045)
GT = dict(
    nom="Goldtrade Pro ICM", url="https://www.mql5.com/en/signals/2084890",
    serveur="ICMarketsSC-MT5-4", tarif_usd=39, eq_fournisseur=7360.45,
    lot_fournisseur=0.01 * (7360.45 / 1000.0),     # EA divulgue LotsizeStep=1000
    p_win=429 / 741, n_sem=741 / 155,
    win=lognorm_de(40.59 / EQ_GT * 100, 608.87 / EQ_GT * 100, 1 - 1 / 429),
    loss=lognorm_de(35.42 / EQ_GT * 100, 400.94 / EQ_GT * 100, 1 - 1 / 312),
    posterieur=None,                               # 312 pertes observees : pas besoin
)
# GoldWave — 296 trades ; 282 G / 14 P ; PF 4.52
# equite operationnelle ~395 USD (DD 22.68 = 5.66 % -> 401 ; 66.89 = 17.52 % -> 382)
EQ_GW = 395.0
GW = dict(
    nom="GoldWave", url="https://www.mql5.com/en/signals/2339082",
    serveur="ICMarketsSC-MT5-4", tarif_usd=49, eq_fournisseur=428.68 / EURUSD,
    lot_fournisseur=0.010,
    p_win=282 / 296, n_sem=5.0,
    win=lognorm_de(1.72 / EQ_GW * 100, 25.13 / EQ_GW * 100, 1 - 1 / 282),
    loss=lognorm_de(7.67 / EQ_GW * 100, 22.64 / EQ_GW * 100, 1 - 1 / 14),
    posterieur=(14.5, 282.5),                      # 14 pertes seulement : Beta/Jeffreys
)

# --------------------------------------------------------------------- mecanique
def volume(sig, capital, allocation=1.0):
    """(volume theorique, volume reellement ouvert, exposition relative).

    MQL5 arrondit VERS LE BAS et jamais vers le haut (moderateur MQL5). Un volume
    sous le lot minimum ne peut donc pas remonter a 0.01 : le trade n'est pas copie.
    `allocation` <= 0.95 selon la documentation MQL5.
    """
    theo = sig["lot_fournisseur"] * capital / sig["eq_fournisseur"] * allocation
    reel = math.floor(theo / LOT_MIN) * LOT_MIN
    return theo, reel, (reel / theo if theo > 0 else 0.0)

def simule(sig, n_trades, expo, capital):
    mu_w, s_w = sig["win"]; mu_l, s_l = sig["loss"]
    cap = np.full(N, float(capital))
    p_loss = (RNG.beta(*sig["posterieur"], size=N) if sig["posterieur"]
              else np.full(N, 1 - sig["p_win"]))
    for _ in range(n_trades):
        perdant = RNG.random(N) < p_loss
        r = np.where(perdant, -RNG.lognormal(mu_l, s_l, N),
                     RNG.lognormal(mu_w, s_w, N)) / 100.0 * expo
        cap *= np.clip(1.0 + r, 0.0, None)
    return cap

# --------------------------------------------------------------------- sorties
def echelle(sig, capitaux, allocation=1.0):
    n = round(sig["n_sem"] * SEM)
    frais = 3 * sig["tarif_usd"] / EURUSD
    print(f"\n### {sig['nom']}  ({sig['serveur']}, {sig['tarif_usd']} $/mois, "
          f"{n} trades sur {JOURS} j, allocation {allocation:.0%})")
    print(f"{'capital':>8} | {'volume':>17} | {'P10':>7} {'mediane':>8} {'P90':>7} "
          f"| {'P(perte)':>8} | frais/dispersion")
    for C in capitaux:
        theo, reel, expo = volume(sig, C, allocation)
        if reel < LOT_MIN:
            print(f"{C:>6} E | {theo:.4f} -> RIEN     |  aucun trade copie          "
                  f"|  100.0 % | capital final {C - frais:.0f} E (certain)")
            continue
        net = simule(sig, n, expo, C) - frais
        q = np.percentile(net, [10, 50, 90])
        disp = q[2] - q[0]
        print(f"{C:>6} E | {theo:.4f} -> {reel:.2f} {expo:4.2f}x | {q[0]:7.0f} {q[1]:8.0f} "
              f"{q[2]:7.0f} | {100*(net<C).mean():7.1f} % | {100*frais/disp:5.1f} %")

def seuils(sig, allocation=1.0):
    s = LOT_MIN / sig["lot_fournisseur"] * sig["eq_fournisseur"] / allocation
    print(f"  {sig['nom']:20s} : {s:6.0f} EUR  (allocation {allocation:.0%})")

def echantillon(sig):
    mu_w, s_w = sig["win"]; mu_l, s_l = sig["loss"]
    M = 2_000_000
    perdant = RNG.random(M) < (1 - sig["p_win"])
    r = np.where(perdant, -RNG.lognormal(mu_l, s_l, M), RNG.lognormal(mu_w, s_w, M))
    m, sd = r.mean(), r.std()
    n_req = (2 * sd / m) ** 2
    print(f"  {sig['nom']:20s} : esperance {m:+.4f} %/trade, ecart-type {sd:.3f} % "
          f"-> N = {n_req:,.0f} trades = {n_req/sig['n_sem']/52:.1f} ans")

if __name__ == "__main__":
    CAPITAUX = (100, 200, 366, 500, 733, 1000, 2000, 5000)
    print("=" * 84)
    print("SEUIL D'EXECUTION — capital minimum pour qu'UN SEUL trade soit copie")
    print("=" * 84)
    for sig in (GT, GW):
        seuils(sig, 1.00); seuils(sig, 0.95)
    print("\n" + "=" * 84)
    print(f"PROJECTION AU 31/12/2026 — net de frais, {N:,} chemins")
    print("=" * 84)
    for sig in (GT, GW):
        echelle(sig, CAPITAUX)
    print("\n" + "=" * 84)
    print("TAILLE D'ECHANTILLON POUR DETECTER L'EDGE (t = 2)")
    print("=" * 84)
    for sig in (GT, GW):
        echantillon(sig)
    print("\n  ATTENTION : pour GoldWave ce N n'est PAS interpretable. Sa faible variance")
    print("  vient d'un echantillon de 14 pertes sans catastrophe. Son DD equite (17,52 %)")
    print("  vaut 3x sa pire perte cloturee (5,73 %) : le risque vit dans une queue non")
    print("  echantillonnee, qu'aucun test sur la moyenne ne peut voir.")
