#!/bin/bash
# BUT: regenere les correlations horaires lues par la porte de correlation
# PERIODE_MIN: 10080
# Lanceur cron de la mesure des correlations forex/metaux.
#
# ⛔ POURQUOI CE CRON EXISTE. Le fichier lu par `correlation_guard` datait du
# 2026-08-23 — dix-sept jours — et n'etait regenere qu'a la main. Or il porte
# XAU/AUD a 0,607 pour un seuil de 0,600 : SEPT MILLIEMES decident, chaque
# jour, si l'or peut etre achete sur les deux comptes MT5.
#
# ⛔ ET POURQUOI IL ECRIT AILLEURS. Le defaut du script vise l'arbre des
# sources, c'est-a-dire DANS L'IMAGE : un fichier ecrit la disparait au premier
# `docker build`. On vise donc `/app/data`, le volume persistant, que
# `correlation_guard` lit EN PRIORITE et relit a chaud toutes les 5 minutes.
# Sans ces deux proprietes, ce cron produirait une mesure morte.
#
# ⚠️ Le bridge du REEL est la source (BRIDGE_ENV par defaut) : ce sont les
# instruments reellement trades, et c'est hors quota Twelve Data.
set -uo pipefail
docker exec \
  -e CORRELATIONS_SORTIE=/app/data/correlations_forex_1h.json \
  ${DRY_RUN:+-e DRY_RUN=1} \
  scalping-radar python /app/scripts/mesurer_correlations_forex.py
