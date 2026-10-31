"""Un `MetaTrader5` de remplacement, pour que les tests des garde-fous de
risque TOURNENT sur Linux — et non pour qu'ils y soient ignorés.

## Le défaut corrigé (audit IT-1, ÉLEVÉ)

Cinq fichiers de tests chargent `mt5-bridge/bridge.py`, qui fait
`import MetaTrader5 as mt5` à son premier niveau. Hors Windows, le module
n'existe pas : la collecte s'interrompt.

> « **Ce sont précisément les tests des garde-fous de risque MT5** — contrôle
> du risque, ajustement à la marge, protection SL/TP, risque engagé. Combiné à
> S-3, cela signifie qu'ils ne sont **vérifiés automatiquement nulle part** :
> ni en CI (inexistante), ni sur une machine Linux, uniquement à la main sur un
> poste Windows. »

🔑 **C'est pour cela qu'un `skipif` ne serait pas une réponse.** Ignorer ces
cinq fichiers sur Linux les laisse exactement là où l'audit les a trouvés :
nulle part. Et un `skipped` se lit comme un `passed` dans un compteur.

## Les valeurs des constantes sont les VRAIES

⛔ Elles ne sont pas inventées. `bridge.py` les **compare** à ce que les tests
fournissent — `p.type == mt5.POSITION_TYPE_BUY`, `r.retcode ==
mt5.TRADE_RETCODE_DONE`. Une constante au mauvais chiffre ferait passer un test
contre une doublure qui ne ressemble pas au vrai, et c'est une famille d'erreur
qui a déjà livré quatre défauts avec 42 tests verts.

Elles ont donc été **lues dans le module installé** (MetaTrader5 5.0.5735) le
2026-10-31. `TIMEFRAME_H1 = 16385` est la preuve qu'il fallait les lire :
personne ne devine cette valeur.

Et `test_doublure_metatrader5.py` les **recompare au vrai module** dès qu'il
est importable — donc sur tout poste Windows. La doublure a ainsi une source
de vérité indépendante d'elle-même.

## Les fonctions LÈVENT, elles ne rendent pas None

Un `None` silencieux ferait passer un test pour la mauvaise raison : le code
appellerait `mt5.positions_get()`, recevrait `None`, conclurait « aucune
position » et son garde-fou ne mordrait pas. Chaque fonction dit donc
explicitement ce qu'il faut faire : doubler `bridge.mt5` dans le test.

⚠️ Cette doublure n'est installée **que si le vrai module est absent** (cf.
`conftest.py`). Sur Windows, les cinq fichiers continuent de tourner contre le
vrai MetaTrader5 : ce fichier ne masque jamais le réel quand le réel existe.
"""
from __future__ import annotations

__version__ = "doublure-de-test (le vrai module est absent de cet hote)"

# ─── Constantes : valeurs LUES dans MetaTrader5 5.0.5735 le 2026-10-31 ────
#
# Elles sont comparees par bridge.py, donc leur valeur porte du sens.
# Toute modification doit passer par test_doublure_metatrader5.py, qui les
# recompare au vrai module quand il est la.

DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_OUT_BY = 3

ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2

ORDER_TIME_GTC = 0

ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1

POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1

TIMEFRAME_H1 = 16385

TRADE_ACTION_DEAL = 1
TRADE_ACTION_SLTP = 6

TRADE_RETCODE_DONE = 10009


# ─── Fonctions : elles LEVENT, pour ne jamais passer pour la mauvaise raison ──

class TerminalAbsent(RuntimeError):
    """Un appel reel a MetaTrader5 a eu lieu sans que le test l'ait double."""


def _refuser(nom: str):
    def _appel(*args, **kwargs):
        raise TerminalAbsent(
            "mt5.%s() a ete appele, mais le vrai MetaTrader5 est absent de cet "
            "hote (Linux). Ce n'est pas un defaut de la doublure : un test qui "
            "a besoin de cet appel doit remplacer `bridge.mt5` par sa propre "
            "doublure, comme le font deja test_mt5_bridge_sltp_protection, "
            "test_bridge_horloge_serveur et test_bridge_risque_engage. "
            "⛔ Ne PAS faire rendre une valeur par defaut a cette fonction : "
            "un `None` silencieux ferait conclure « aucune position » a un "
            "garde-fou, et il ne mordrait pas." % nom)
    _appel.__name__ = nom
    _appel.__qualname__ = nom
    return _appel


account_info = _refuser("account_info")
copy_rates_from_pos = _refuser("copy_rates_from_pos")
copy_rates_range = _refuser("copy_rates_range")
history_deals_get = _refuser("history_deals_get")
history_orders_get = _refuser("history_orders_get")
initialize = _refuser("initialize")
last_error = _refuser("last_error")
order_calc_margin = _refuser("order_calc_margin")
order_check = _refuser("order_check")
order_send = _refuser("order_send")
positions_get = _refuser("positions_get")
positions_total = _refuser("positions_total")
shutdown = _refuser("shutdown")
symbol_info = _refuser("symbol_info")
symbol_info_tick = _refuser("symbol_info_tick")
symbol_select = _refuser("symbol_select")
symbols_get = _refuser("symbols_get")
