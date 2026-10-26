# Pré-inscription — la cause des 36,6 % de TIMEOUT forex

**Date** : 2026-10-26 · **Écrit AVANT toute requête de mesure.**

## Le fait à expliquer

Le rattrapage (palier 2) a résolu 2 819 setups non-crypto. Répartition :

| | n | part |
|---|---|---|
| `SL` | 1 345 | 47,7 % |
| `TIMEOUT` | 1 031 | **36,6 %** |
| `TP1` | 443 | 15,7 % |

Le palier 1 (crypto, 18 986 setups) n'a que **1,5 %** de `TIMEOUT` (276).
Facteur **24**. Fenêtre identique dans les deux cas : `timeout_hours = 96`
pour `1h` et `4h`.

⛔ **J'ai déjà avancé une explication FAUSSE** : « les ETF ne cotent que
6,5 h/jour ». Réfutée par la donnée — les plus forts taux sont du forex pur
(USD/CAD 42 %, GBP/USD 37 %).

## Ce que la lecture du code apporte (avant mesure)

`simulate_trade_forward` a **deux branches de `TIMEOUT` distinctes** :

```python
    # Timeout : close au dernier prix connu
    if last_candle:
        return ("TIMEOUT", last_candle.timestamp, last_candle.close)
    # Pas de candle dans la fenêtre (weekend ?) → pas de trade
    return ("TIMEOUT", entry_time, setup.entry_price)
```

Ces deux branches **sont** mes deux hypothèses, et elles sont séparables dans
la donnée déjà écrite :

- **H1 — trou de donnée** : aucune bougie après l'entrée.
  Signature : `exit_at == bar_timestamp` et `exit_price == entry_price`.
- **H2 — objectifs hors de portée** : des bougies existaient, le prix n'a
  simplement atteint ni TP ni SL en 96 h.
  Signature : `exit_at > bar_timestamp`.

## Prédictions, dites d'avance

1. **La majorité des `TIMEOUT` forex est la branche SANS AUCUNE BOUGIE**
   (`exit_at == bar_timestamp`) : **> 50 %**.
2. Ces lignes auront `exit_price == entry_price` **exactement**, et un
   `pnl_pct_net` égal au seul coût (≈ −0,02 %), donc |pnl| < 0,05 % pour
   **> 95 %** d'entre elles.
3. Leur `bar_timestamp` sera concentré en **fin de semaine** (vendredi soir →
   dimanche) : la part vendredi+samedi+dimanche dépassera **50 %**, contre
   ~43 % attendus si les jours étaient uniformes sur 7 — et surtout nettement
   plus que la part de ces jours dans les setups NON-TIMEOUT.
4. **Contrôle crypto** : la part de la branche sans bougie parmi les 276
   `TIMEOUT` crypto sera **< 20 %** (Binance cote 7 jours sur 7).
5. Pour les `TIMEOUT` forex de la branche H2 (avec bougies), le `mfe_pct`
   restera **inférieur à la distance requise jusqu'au TP** dans **> 80 %** des
   cas — c'est-à-dire : le prix n'a vraiment pas voyagé assez loin.

## Barre de décision

- Si **P1 et P4** passent ⇒ la cause dominante est le **trou de donnée**
  (H1), pas une propriété du forex. Conséquence : ces `TIMEOUT` ne sont pas
  des trades, ce sont des **non-mesures**, et il faudra les distinguer dans
  toute statistique — comme `resolved_backfill` le fait déjà pour la source.
- Si **P1 échoue et P5 passe** ⇒ la cause est **H2**, les objectifs sont hors
  de portée de la volatilité forex en 96 h. Conséquence : c'est une
  information sur le réglage TP/SL, pas un artefact.
- Si **P1 et P5 échouent toutes deux** ⇒ je n'ai pas compris, et je le dirai
  sans proposer de troisième explication construite après coup.

⚠️ **Ce que ce banc ne peut PAS dire** : rien sur la rentabilité. Il explique
une répartition d'issues sur de la donnée rattrapée, pas un edge.
