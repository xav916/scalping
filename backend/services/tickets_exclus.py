"""La liste des tickets retirés du bulletin — une seule, pour tous les juges.

⛔ **Pourquoi un module et pas trois copies.** Trois modules décident du sort
d'une paire, et `mt5_bridge` les interroge tous :

| juge | ce qu'il décide | porte |
|---|---|---|
| `pair_admission_controller` | l'état d'admission (`AUTO_EXEC`/`TELEGRAM`/…) | `mt5_bridge.py:563` |
| `pair_pnl_regulator` | la pause automatique sur saignement chronique | `mt5_bridge.py:613` |
| `promotion_engine` | la rétrogradation sur drawdown 7 jours | écrit l'état lu par le premier |

Entre le 19/08 et le 25/08/2026, seul le premier consultait la liste. L'or a
été promu en `AUTO_EXEC` sur les deux comptes et n'a pas passé un seul ordre :
176 rejets `pair_auto_paused` par jour, prononcés par le deuxième sur un
échantillon que le premier avait déjà écarté. **Une parade posée sur un chemin
n'est pas posée sur les autres** — la seule façon de le garantir est qu'il n'y
ait qu'un seul endroit à poser.

⛔ Cette liste ne retire rien au risque, au P&L, ni à aucun relevé d'argent.
L'argent a réellement été perdu. Elle retire d'un bulletin qui juge le système
une décision qui n'était pas la sienne.
"""

from __future__ import annotations


def tickets_exclus() -> frozenset[int]:
    """Lue à l'appel, jamais à l'import : un test doit pouvoir la régler, et le
    conteneur doit pouvoir changer sans reconstruction d'image."""
    try:
        from config.settings import PAC_EXCLUDED_TICKETS
        return frozenset(PAC_EXCLUDED_TICKETS)
    except Exception:  # noqa: BLE001 — un réglage illisible ne doit rien casser
        return frozenset()


def filtre_sql(exclus: frozenset[int]) -> str:
    """Fragment SQL écartant les tickets exclus, à coller après un `WHERE`.

    Rend `""` sur une liste vide : sans réglage, aucune requête ne change.

    ⚠️ `CAST(... AS INTEGER)` n'est pas cosmétique. `mt5_ticket` est stocké en
    TEXTE dans `personal_trades` et en ENTIER dans `ea_closed_trades` : sans le
    cast, SQLite compare un texte à un entier sans jamais les trouver égaux, et
    le filtre n'écarte rien **sans lever la moindre erreur**. Même famille de
    défaut que `coalesce(mt5_ticket, 0)`, qui efface l'affinité de la colonne.
    """
    if not exclus:
        return ""
    trous = ",".join("?" * len(exclus))
    return (f" AND (mt5_ticket IS NULL OR "
            f"CAST(mt5_ticket AS INTEGER) NOT IN ({trous}))")
