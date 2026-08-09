"""Registre des destinations de trading — source unique de vérité.

⚠️ **Pourquoi ce module existe.** Le 2026-08-04, l'ajout des destinations
Kraken (2026-08-02) a révélé que « brancher une plateforme » exigeait de
modifier au moins cinq endroits indépendants, et que quatre avaient été
oubliés :

===============================  ==========================================
endroit oublié                   conséquence
===============================  ==========================================
``VALID_DESTINATIONS``           une admission scopée sur Kraken devenait
                                 GLOBALE — elle ouvrait toutes les
                                 destinations, Cédric compris
``DESTINATION_LABELS``           un trade Kraken s'affichait « Démo » alors
                                 qu'il engageait de l'argent réel
sondes de santé                  les deux bridges Kraken n'étaient
                                 surveillés par rien
sizing                           ``TRADING_CAPITAL`` global appliqué à un
                                 compte de 103 USD → ordres 20× trop gros,
                                 rejetés par Kraken en ``invalidSize``
===============================  ==========================================

Aucun de ces oublis n'a produit d'erreur : ils ont produit du **silence**,
ou pire, une affirmation fausse. C'est le motif que ce registre supprime.

**Ajouter une plateforme = ajouter une entrée ici**, plus son constructeur
dans ``bridge_destinations``. Tout le reste en découle : libellés Telegram,
portée des admissions, mode de sizing, sonde de santé, notifications.

``test_destinations_registry`` échoue si une destination connue de
``bridge_destinations`` n'est pas déclarée ici — la dérive redevient
impossible sans qu'un test l'annonce.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# Destinations multi-tenant : ``user:<id>``, cf. bridge_destinations
USER_DESTINATION_RE = re.compile(r"^user:\d+$")


@dataclass(frozen=True)
class Destination:
    """Tout ce que le système doit savoir d'une plateforme de trading.

    Attributes
    ----------
    id
        Identifiant technique, celui de ``BridgeConfig.destination_id``.
    badge
        Libellé court, pour l'annotation « Auto-exécuté → … ».
    mode
        Libellé long, pour la ligne broker du message de trade.
    reel
        ``True`` si de l'argent réel est engagé. **Déclaré, jamais déduit** :
        une destination dont on ignore le statut est traitée comme fictive,
        donc silencieuse côté notifications.
    bridge_type
        Aiguille le dispatch vers le bon client : ``mt5``, ``kraken``,
        ``kraken_spot``, ``binance``, ``ibkr``.
    url_env / key_env / key_header
        De quoi sonder ``/health`` sans connaître le bridge à l'avance.
        ``key_header`` diffère selon les familles : MT5 attend
        ``X-API-Key``, les bridges Kraken ``X-Bridge-Key``.
    sizing
        ``global`` : dimensionné sur ``TRADING_CAPITAL`` — le bridge
        reclampe au minimum du broker (cas MT5).
        ``live_balance`` : dimensionné sur le solde réel lu via
        ``/account``. Obligatoire dès que le bridge envoie la quantité
        telle quelle, sans quoi on rejoue l'incident ``invalidSize``.
    asset_classes
        Classes d'actifs que ce broker accepte.
    plateforme
        Préfixe lisible pour les notifications de push (script shell).
    max_correlated_positions
        Nombre maximum de positions constituant un **même pari**. ``0`` ⇒
        illimité.

        Le 2026-08-04, un short BTC et un short ETH étaient ouverts en même
        temps : leurs rendements horaires corrèlent à 0,81, c'était donc un
        seul pari pris deux fois. Réglé par destination car le compte
        principal présente 281 chevauchements de paris identiques sur 568
        trades — l'activer partout changerait massivement un comportement
        en place. Cf. ``correlation_guard``.
    order_cooldown_sec
        Délai minimum entre deux ordres sur un **même symbole**, en secondes.
        ``0`` ⇒ désactivé.

        Le 2026-08-04, six ordres ETH sont partis en vingt-sept minutes sur
        Kraken, dont deux de sens opposés à la même seconde. La déduplication
        existante porte sur le prix d'entrée : un centime d'écart rouvre la
        porte. Réglé par destination car un délai global de quinze minutes
        bloquerait 45 % des ordres de Cédric, dont le rythme mesuré est sain.
    max_notional_leverage
        Notionnel maximal d'une position, en multiple du capital du compte.
        ``None`` ⇒ garde-fou global ``MAX_NOTIONAL_LEVERAGE``.

        Le dimensionnement vise un **risque** constant, pas une taille : le
        notionnel vaut ``risque × entrée / distance du stop``. Un stop serré
        produit donc mécaniquement une position énorme. Le 2026-08-04, un
        ordre de 0,215 ETH — 403 USD de notionnel sur un compte de 103 —
        est parti pour cette seule raison.

        Le plafond se déclare par destination parce que les familles ne se
        comparent pas : le forex MT5 à 0,1 lot atteint naturellement 3,8× et
        ce n'est pas anormal, tandis que 3,9× sur un perpétuel crypto engage
        un actif dont la volatilité est d'un tout autre ordre.
    """

    id: str
    badge: str
    mode: str
    reel: bool
    bridge_type: str
    url_env: str = ""
    key_env: str = ""
    key_header: str = "X-API-Key"
    sizing: str = "global"
    asset_classes: frozenset[str] = field(default_factory=frozenset)
    plateforme: str = ""
    max_notional_leverage: float | None = None
    order_cooldown_sec: int = 0
    max_correlated_positions: int = 0


DESTINATIONS: dict[str, Destination] = {
    d.id: d for d in (
        Destination(
            id="admin_legacy",
            badge="🧪 Demo Pepperstone",
            mode="Pepperstone · Démo",
            reel=False,
            bridge_type="mt5",
            url_env="MT5_BRIDGE_URL",
            key_env="MT5_BRIDGE_API_KEY",
            sizing="global",
            asset_classes=frozenset({"forex", "metal", "energy"}),
            plateforme="MT5 Demo Pepperstone",
        ),
        Destination(
            id="admin_live",
            badge="💰 Live IC Markets",
            mode="IC Markets · LIVE (argent réel)",
            reel=True,
            bridge_type="mt5",
            url_env="MT5_BRIDGE_LIVE_URL",
            key_env="MT5_BRIDGE_LIVE_API_KEY",
            sizing="global",
            asset_classes=frozenset({"forex", "metal", "energy", "equity"}),
            plateforme="MT5 IC Markets",
        ),
        Destination(
            id="admin_kraken",
            badge="🐙 Kraken Futures",
            mode="Kraken Futures · LIVE (argent réel)",
            reel=True,
            bridge_type="kraken",
            url_env="KRAKEN_BRIDGE_URL",
            key_env="KRAKEN_BRIDGE_API_KEY",
            key_header="X-Bridge-Key",
            sizing="live_balance",
            asset_classes=frozenset({"crypto"}),
            max_notional_leverage=2.0,
            order_cooldown_sec=900,
            max_correlated_positions=1,
            plateforme="Kraken Futures",
        ),
        Destination(
            id="admin_kraken_spot",
            badge="🐙 Kraken Spot",
            mode="Kraken Spot · LIVE (argent réel)",
            reel=True,
            bridge_type="kraken_spot",
            url_env="KRAKEN_SPOT_BRIDGE_URL",
            key_env="KRAKEN_SPOT_BRIDGE_API_KEY",
            key_header="X-Bridge-Key",
            sizing="live_balance",
            asset_classes=frozenset({"crypto"}),
            max_notional_leverage=2.0,
            order_cooldown_sec=900,
            max_correlated_positions=1,
            plateforme="Kraken Spot",
        ),
        Destination(
            id="admin_kraken_stocks",
            badge="🐙 Kraken xStocks",
            mode="Kraken xStocks · LIVE (argent réel)",
            reel=True,
            bridge_type="kraken",
            url_env="KRAKEN_STOCKS_BRIDGE_URL",
            key_env="KRAKEN_STOCKS_BRIDGE_API_KEY",
            key_header="X-Bridge-Key",
            sizing="live_balance",
            asset_classes=frozenset({"equity"}),
            max_notional_leverage=2.0,
            order_cooldown_sec=900,
            max_correlated_positions=1,
            plateforme="Kraken xStocks",
        ),
        Destination(
            id="admin_binance",
            badge="🅑 Binance Testnet",
            mode="Binance · Testnet (R&D)",
            reel=False,
            bridge_type="binance",
            url_env="BINANCE_BRIDGE_URL",
            key_env="BINANCE_BRIDGE_API_KEY",
            sizing="live_balance",
            asset_classes=frozenset({"crypto"}),
            plateforme="Binance Futures",
        ),
    )
}

# Destinations multi-tenant : une seule entrée, l'id porte le numéro.
USER_DESTINATION = Destination(
    id="user:N",
    badge="👤 Compte Premium",
    mode="Premium · Démo",
    reel=False,
    bridge_type="mt5",
    sizing="global",
    plateforme="MT5 Premium",
)


def get(destination_id: str | None) -> Destination | None:
    """Déclaration d'une destination, ou ``None`` si elle est inconnue.

    Une destination inconnue renvoie ``None`` plutôt qu'un objet par
    défaut : les appelants doivent décider explicitement quoi faire, et
    le défaut sûr est toujours « se taire ».
    """
    if not destination_id:
        return None
    if USER_DESTINATION_RE.match(destination_id):
        return USER_DESTINATION
    return DESTINATIONS.get(destination_id)


def is_known(destination_id: str | None) -> bool:
    return get(destination_id) is not None


def is_real_money(destination_id: str | None) -> bool:
    """Inconnue ⇒ fictive ⇒ silencieuse. Ne jamais supposer sur l'argent."""
    d = get(destination_id)
    return bool(d and d.reel)


def ids() -> frozenset[str]:
    """Identifiants admin déclarés (hors ``user:N``, dynamique)."""
    return frozenset(DESTINATIONS)


# Classes d'actifs qui cotent en continu. La grille de séance de
# ``session_service`` décrit les fenêtres de volume du FOREX (Sydney, Tokyo,
# London, New York) : elle ne dit rien d'un marché sans séance.
CLASSES_CONTINUES = frozenset({"crypto"})


def cote_en_continu(destination_id: str | None) -> bool:
    """La destination ne liste que des instruments cotant 24/7.

    **Dérivé d'``asset_classes``, jamais déclaré à part.** C'est le point :
    fermer cette porte ne devait rien ajouter à la liste des choses à ne pas
    oublier en branchant un instrument.

    Pourquoi la destination et non le symbole. Jusqu'au 2026-08-09, savoir
    si un instrument cotait 24/7 passait par ``asset_class_for``, donc par
    une liste de préfixes codée en dur **plus** ``ASSET_CLASS_OVERRIDES`` du
    ``.env``. Un instrument Kraken ajouté sans cette déclaration retombait en
    « forex », recevait un multiplicateur de séance de 0,0 le week-end, et
    son risque tombait à zéro : ordre jamais envoyé, motif de rejet faux, et
    échec visible **uniquement** le week-end.

    Or coter en continu est une propriété du **lieu de cotation**. Un
    perpétuel listé sur Kraken Futures cote 24/7 quel que soit son nom, et
    le registre le sait déjà.

    Inconnue, multi-classe ou sans déclaration ⇒ ``False`` : le défaut sûr
    reste de garder la grille.
    """
    d = get(destination_id)
    if d is None or not d.asset_classes:
        return False
    return d.asset_classes <= CLASSES_CONTINUES


def bridge_types_with_live_balance() -> frozenset[str]:
    """Types de bridge dont le sizing doit lire le solde réel."""
    return frozenset(d.bridge_type for d in DESTINATIONS.values()
                     if d.sizing == "live_balance")


def as_json() -> str:
    """Dump consommable par les scripts shell (santé, notifications).

    Évite qu'un script bash reconstruise sa propre table de destinations —
    c'est ainsi que ``notify-new-*-pushes.sh`` s'était dupliqué en quatre
    fichiers, chacun avec sa copie des libellés.
    """
    out: dict[str, Any] = {}
    for d in DESTINATIONS.values():
        out[d.id] = {
            "badge": d.badge, "mode": d.mode, "reel": d.reel,
            "bridge_type": d.bridge_type, "url_env": d.url_env,
            "key_env": d.key_env, "key_header": d.key_header,
            "sizing": d.sizing, "plateforme": d.plateforme,
            "max_notional_leverage": d.max_notional_leverage,
            "order_cooldown_sec": d.order_cooldown_sec,
            "max_correlated_positions": d.max_correlated_positions,
            "asset_classes": sorted(d.asset_classes),
        }
    return json.dumps(out, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    print(as_json())
