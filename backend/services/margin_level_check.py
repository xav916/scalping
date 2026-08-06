"""Alerte quand le niveau de marge d'un compte réel approche la liquidation.

Pourquoi : le 2026-08-06, le compte Live est descendu à **95,5 % de niveau de
marge** — déjà sous le seuil d'appel de marge — à cause d'une seule position
XAU/USD tenue volontairement sans stop. Rien ne surveillait cette grandeur.

Le risque n'est pas la perte elle-même, qui est un choix assumé : c'est que le
**courtier ferme la position à sa place**, au prix du marché et au moment qu'il
choisit. Cette alerte existe pour que la décision reste celle de Xavier.

Niveau de marge = équité / marge utilisée × 100.
  100 % → appel de marge (plus aucune ouverture possible)
   50 % → liquidation automatique chez IC Markets

Le seuil d'alerte est délibérément **au-dessus** de la liquidation : prévenir à
50 % serait prévenir pendant l'exécution.
"""
from __future__ import annotations

import json
import os

import httpx

# Marge de manœuvre avant la liquidation à 50 %. À 70 %, il reste de la place
# pour agir (fermer, couvrir, alimenter) avant que le courtier ne décide.
DEFAULT_ALERT_LEVEL = 70.0

# Sous ce seuil, il n'y a plus rien à surveiller : aucune position ouverte
# signifie une marge nulle, donc un niveau de marge non défini.
_MARGE_MINIMALE = 0.01


def _bridges() -> list[tuple[str, str, str]]:
    """(libellé, url, clé) des comptes en argent réel uniquement.

    Le compte démo est exclu : une liquidation y est sans conséquence, et
    l'alerter diluerait le signal.
    """
    url = os.getenv("MT5_BRIDGE_LIVE_URL", "")
    key = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "")
    return [("live", url, key)] if url else []


def _seuil() -> float:
    try:
        return float(os.getenv("MARGIN_ALERT_LEVEL_PCT", DEFAULT_ALERT_LEVEL))
    except (TypeError, ValueError):
        return DEFAULT_ALERT_LEVEL


def run() -> dict:
    """Rend l'état de marge de chaque compte réel. Ne lève jamais."""
    seuil = _seuil()
    rapport = {"seuil_alerte_pct": seuil, "comptes": {}, "alerte": False}

    for libelle, url, key in _bridges():
        sous = {"joignable": False, "niveau_marge_pct": None, "alerte": False}
        try:
            r = httpx.get(
                f"{url.rstrip('/')}/account",
                headers={"X-API-Key": key} if key else {},
                timeout=8.0,
            )
            if r.status_code == 200:
                d = r.json()
                sous["joignable"] = True
                sous.update({
                    "solde": d.get("balance"),
                    "equite": d.get("equity"),
                    "marge": d.get("margin"),
                    "marge_libre": d.get("margin_free"),
                    "positions": d.get("positions_count"),
                })
                marge = float(d.get("margin") or 0.0)
                equite = float(d.get("equity") or 0.0)
                # Marge nulle = aucune position : le ratio n'a pas de sens et
                # ne doit surtout pas être lu comme « 0 %, donc critique ».
                if marge > _MARGE_MINIMALE:
                    niveau = 100.0 * equite / marge
                    sous["niveau_marge_pct"] = round(niveau, 1)
                    sous["alerte"] = niveau < seuil
            else:
                sous["erreur"] = f"HTTP {r.status_code}"
        except Exception as e:
            sous["erreur"] = f"{type(e).__name__}: {e}"

        rapport["comptes"][libelle] = sous
        if sous.get("alerte"):
            rapport["alerte"] = True

    return rapport


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))
