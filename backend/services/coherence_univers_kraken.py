"""Les trois listes qui définissent l'univers Kraken doivent s'accorder.

Posé le 2026-09-06, après deux défauts nés de leur divergence dans la même
journée :

```
SHADOW_CONFIG (code)              -> produit les SIGNAUX
WATCHED_PAIRS_ADMIN_KRAKEN (.env) -> autorise le ROUTAGE
live_whitelist_symbols (bridge)   -> autorise l'EXÉCUTION
```

Le matin, une portée construite depuis le mauvais univers a **coupé 11 paires**
que Kraken tradait. Le soir, **six paires** ouvertes dans la portée et la
whitelist ne pouvaient produire **aucun signal**, absentes de la liste du code.

🔑 **Une porte ouverte sur une pièce vide se voit moins qu'une porte fermée.**
Pas d'erreur, pas de refus — juste une absence de trades qu'on met sur le
compte du marché. La divergence est donc INVISIBLE tant que personne ne la
compare : c'est ce que fait ce module.

Le premier trou a été fermé en dérivant la configuration de la portée
(`_completer_depuis_la_portee_kraken`). **Il reste le dernier maillon** : une
paire routable dont le symbole manque à la whitelist du bridge produira des
signaux refusés à l'exécution.

⚠️ Les deux sens de divergence n'ont pas la même gravité, et on ne les traite
pas pareil :

  - **routable mais pas exécutable** ⇒ du travail jeté à chaque signal. On
    ALERTE ;
  - **exécutable mais pas routable** ⇒ une autorisation qui ne sert pas. C'est
    l'état normal après un retrait (`ETHFI` le 06/09). On le RAPPORTE, sans
    alerter — sinon l'alerte devient du bruit qu'on apprend à ignorer.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)


def _whitelist_du_bridge() -> set[str] | None:
    """Symboles autorisés par le bridge. ``None`` si injoignable.

    ⛔ Jamais un ensemble vide en repli : « je n'ai pas pu lire » et « rien
    n'est autorisé » mèneraient à des conclusions opposées.
    """
    url = os.environ.get("KRAKEN_BRIDGE_URL", "")
    cle = os.environ.get("KRAKEN_BRIDGE_API_KEY", "")
    if not url:
        return None
    try:
        req = urllib.request.Request(url.rstrip("/") + "/health",
                                     headers={"X-Bridge-Key": cle})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        symboles = d.get("live_whitelist_symbols")
        if symboles is None:
            return None
        return {str(s).upper() for s in symboles}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"coherence_univers_kraken: /health injoignable : {e}")
        return None


def verifier() -> dict:
    """Compare les trois listes. Ne modifie RIEN — c'est une observation.

    Rend ``{"lisible", "portee", "sans_config", "sans_whitelist",
    "whitelist_en_trop", "alerte"}``.
    """
    from config.settings import WATCHED_PAIRS_PAR_DESTINATION as portees
    from backend.services.shadow_v2_core_long import SHADOW_CONFIG
    from backend.services import kraken_funding_scoring as kfs

    portee = sorted((portees or {}).get("admin_kraken") or ())
    rapport: dict = {
        "lisible": False,
        "portee": portee,
        "sans_config": sorted(p for p in portee if p not in SHADOW_CONFIG),
        "sans_whitelist": [],
        "whitelist_en_trop": [],
        "alerte": False,
    }

    liste = _whitelist_du_bridge()
    if liste is None:
        # ⛔ Bridge injoignable : on ne peut RIEN conclure sur la whitelist.
        # Le dire vaut mieux que rendre une liste vide qui ferait croire à une
        # divergence totale.
        rapport["alerte"] = bool(rapport["sans_config"])
        return rapport

    rapport["lisible"] = True
    attendus: dict[str, str] = {}
    for paire in portee:
        sym = kfs.symbole_pour(paire)
        if not sym:
            # Pas de symbole Kraken dérivable : la paire ne peut pas s'exécuter.
            rapport["sans_whitelist"].append(f"{paire} (symbole indérivable)")
            continue
        attendus[sym.upper()] = paire
        if sym.upper() not in liste:
            rapport["sans_whitelist"].append(f"{paire} → {sym}")

    rapport["whitelist_en_trop"] = sorted(liste - set(attendus))
    # ⚠️ Seul le sens DANGEREUX alerte. Le surplus de whitelist est l'état
    # normal après un retrait de portée.
    rapport["alerte"] = bool(rapport["sans_config"] or rapport["sans_whitelist"])
    return rapport


def texte(rapport: dict) -> tuple[str, str]:
    """`(titre, corps)` lisibles pour Telegram."""
    if not rapport.get("alerte"):
        titre = "✅ Univers Kraken cohérent"
        corps = (f"{len(rapport['portee'])} paires en portée, toutes "
                 "configurables et exécutables.")
        if not rapport.get("lisible"):
            corps += "\n⚠️ Whitelist du bridge NON LUE — vérification partielle."
        if rapport.get("whitelist_en_trop"):
            corps += ("\n\nAutorisés chez le courtier mais hors portée "
                      "(sans effet) :\n• " + "\n• ".join(rapport["whitelist_en_trop"]))
        return titre, corps

    lignes = []
    if rapport["sans_config"]:
        lignes.append("⛔ ROUTABLES MAIS SANS SIGNAL POSSIBLE — une porte "
                      "ouverte sur une pièce vide :\n• "
                      + "\n• ".join(rapport["sans_config"]))
    if rapport["sans_whitelist"]:
        lignes.append("⛔ ROUTABLES MAIS PAS AUTORISÉES CHEZ LE COURTIER — "
                      "leurs signaux seront refusés à l'exécution :\n• "
                      + "\n• ".join(rapport["sans_whitelist"]))
    if not rapport.get("lisible"):
        lignes.append("⚠️ Whitelist du bridge non lue : vérification partielle.")
    return "🚨 Univers Kraken INCOHÉRENT", "\n\n".join(lignes)


def run() -> int:
    rapport = verifier()
    titre, corps = texte(rapport)
    print(json.dumps(rapport, ensure_ascii=False, indent=1))
    print()
    print(titre)
    print(corps)
    return 1 if rapport.get("alerte") else 0


if __name__ == "__main__":
    raise SystemExit(run())
