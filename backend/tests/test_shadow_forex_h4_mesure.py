"""Mesure des stops forex en H4 (ajout 2026-08-07).

Raison d'être : la porte de coût refuse tout stop sous 0,33 % du prix. En
5 minutes le forex est à 0,021-0,036 % — **rien ne passe, sur aucune paire**.
En H4, 100 % des setups XAU/XAG/WTI passent. Le forex H4 est le seul candidat
que le capital disponible puisse porter (~90-270 EUR contre 4 117 EUR pour
l'or). Mais ses stops H4 n'ont jamais été mesurés : ils étaient projetés par
un rapport ×8,1 tiré de deux ancres contradictoires, et les projections
tombent à cheval sur le seuil.

⚠️ Ces tests verrouillent ce qui pourrait faire dérailler la mesure :
  - une paire absente de `WATCHED_PAIRS` (aucune bougie ⇒ aucun setup) ;
  - un `system_id` en collision avec un système existant (la contrainte
    UNIQUE (system_id, bar_timestamp) écraserait des mesures) ;
  - un jeu de motifs sans intersection avec la whitelist MT5 (on mesurerait
    des setups qui ne seraient jamais dispatchés) ;
  - un `risk_pct` plus agressif que le plus prudent de la configuration,
    alors qu'aucun backtest ne le justifie.
"""
import pytest

from backend.services.shadow_v2_core_long import (
    FOREX_MEASURE_PATTERNS,
    SHADOW_CONFIG,
)

FOREX_H4 = [
    "EUR/JPY", "GBP/JPY", "EUR/GBP", "USD/JPY", "AUD/USD",
    "USD/CAD", "GBP/USD", "EUR/USD", "USD/CHF",
]

# Whitelist de motifs du bridge MT5 en prod (MT5_BRIDGE_ALLOWED_PATTERNS).
WHITELIST_MT5 = {"range_bounce_up", "range_bounce_down"}


def test_les_9_paires_sont_configurees_en_h4():
    for pair in FOREX_H4:
        assert pair in SHADOW_CONFIG, f"{pair} absente de SHADOW_CONFIG"
        assert SHADOW_CONFIG[pair]["tf"] == "4h", f"{pair} n'est pas en H4"


def test_les_paires_sont_dans_le_defaut_watched_pairs():
    """Sans bougies, pas de setup : la mesure ne produirait rien, en silence.

    On vérifie le **défaut du code**, pas `settings.WATCHED_PAIRS` : cette
    dernière est surchargée par l'environnement, et un poste de dev
    (`WATCHED_PAIRS=EUR/USD,XAU/USD`) ferait échouer le test sans qu'aucun
    déploiement ne soit en cause. Lecture par AST — pas de correspondance de
    chaîne, donc un renommage ou une reformulation ne peut pas rendre le test
    vert à tort.

    ⚠️ Ce test ne remplace PAS la vérification en production : il garantit
    qu'un déploiement neuf sera cohérent, pas que celui en cours l'est.
    """
    import ast
    from pathlib import Path

    src = Path("config/settings.py").resolve()
    if not src.exists():  # exécution hors racine du dépôt
        src = Path(__file__).resolve().parents[2] / "config" / "settings.py"
    arbre = ast.parse(src.read_text(encoding="utf-8"))

    defaut = None
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Assign):
            continue
        cibles = [t.id for t in noeud.targets if isinstance(t, ast.Name)]
        if "WATCHED_PAIRS" not in cibles:
            continue
        # WATCHED_PAIRS = os.getenv("WATCHED_PAIRS", "<defaut>").split(",")
        for sous in ast.walk(noeud.value):
            if (isinstance(sous, ast.Call)
                    and getattr(sous.func, "attr", None) == "getenv"
                    and len(sous.args) == 2):
                defaut = ast.literal_eval(sous.args[1])
        break

    assert defaut, "défaut de WATCHED_PAIRS introuvable dans config/settings.py"
    paires = [p.strip() for p in defaut.split(",")]
    manquantes = [p for p in FOREX_H4 if p not in paires]
    assert not manquantes, (
        f"{manquantes} hors du défaut WATCHED_PAIRS : le scheduler ne "
        f"fournirait aucune bougie H1, donc aucun setup H4 — et l'absence de "
        f"mesure serait indiscernable d'un stop trop serré."
    )


def test_les_system_id_sont_uniques():
    """La contrainte UNIQUE (system_id, bar_timestamp) écraserait des lignes."""
    ids = [c["system_id"] for c in SHADOW_CONFIG.values()]
    doublons = {i for i in ids if ids.count(i) > 1}
    assert not doublons, f"system_id en collision : {doublons}"


def test_les_motifs_mesures_croisent_la_whitelist_mt5():
    """Sinon on mesurerait des setups que le bridge n'aurait jamais dispatchés."""
    commun = FOREX_MEASURE_PATTERNS & WHITELIST_MT5
    assert commun, (
        f"aucun motif commun entre la mesure {sorted(FOREX_MEASURE_PATTERNS)} "
        f"et la whitelist MT5 {sorted(WHITELIST_MT5)}"
    )


def test_le_risque_est_le_plus_prudent_de_la_configuration():
    """Aucun backtest n'existe : on ne peut pas être plus agressif que le reste."""
    plus_prudent = min(c["risk_pct"] for c in SHADOW_CONFIG.values())
    for pair in FOREX_H4:
        assert SHADOW_CONFIG[pair]["risk_pct"] == plus_prudent, (
            f"{pair} risque {SHADOW_CONFIG[pair]['risk_pct']} alors que le plus "
            f"prudent de la config est {plus_prudent}, et rien ne le justifie"
        )


def test_les_systemes_existants_ne_sont_pas_touches():
    """Non-régression : l'ajout ne doit rien redéfinir."""
    attendus = {
        "XAU/USD": "V2_CORE_LONG_XAUUSD_4H",
        "XAG/USD": "V2_CORE_LONG_XAGUSD_4H",
        "WTI/USD": "V2_WTI_OPTIMAL_WTIUSD_4H",
        "ETH/USD": "V2_CORE_LONG_ETHUSD_1D",
        "BTC/USD": "V2_CORE_LONG_BTCUSD_1D",
        "XLI": "V2_TIGHT_LONG_XLI_1D",
        "XLK": "V2_WTI_OPTIMAL_XLK_1D",
    }
    for pair, sid in attendus.items():
        assert SHADOW_CONFIG[pair]["system_id"] == sid


def test_shadow_pairs_expose_les_nouvelles_paires():
    """`SHADOW_PAIRS` pilote l'outputsize H1 du scheduler (200 au lieu de 50)."""
    from backend.services.shadow_v2_core_long import SHADOW_PAIRS

    for pair in FOREX_H4:
        assert pair in SHADOW_PAIRS, (
            f"{pair} absente de SHADOW_PAIRS : le scheduler ne demanderait que "
            f"50 bougies H1, insuffisant pour agréger un historique H4."
        )
