"""La commande Telegram `/trade` : ce qu'elle accepte et ce qu'elle refuse.

Demandé par Xavier le 2026-10-10, option **A**.

## ⛔ Pourquoi l'analyse de la commande est une fonction PURE testée ici

Le reste du moniteur (`mt5-bridge-monitor/bridge_monitor.py`) parle à Telegram
et à Docker : il n'est pas testable sans réseau. Mais la partie qui peut être
FAUSSE — lire « /trade », en extraire une paire, refuser le reste — est du
calcul pur. Elle est donc isolée dans `parse_commande_trade`, et c'est elle
qu'on éprouve.

⚠️ Un `/trade` mal lu sur de l'argent réel, c'est soit un cycle qui ne part
pas (il croit que tu n'as rien demandé), soit un cycle sur la mauvaise paire.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SRC = (Path(__file__).resolve().parents[2] / "mt5-bridge-monitor"
        / "bridge_monitor.py")


@pytest.fixture(scope="module")
def M():
    """⚠️ Le moniteur lit `os.environ["BRIDGE_VPS_URL"]` a l'import. On ne
    l'importe donc PAS : on extrait la fonction pure de sa source.

    🔑 C'est moins elegant qu'un import, mais un import qui exige six variables
    d'environnement ferait de ce test un test d'environnement.
    """
    src = _SRC.read_text(encoding="utf-8")
    # ⚠️ On part des CONSTANTES, pas du `def` : extraire la seule fonction
    # laissait `_TRADE_SENS` non defini, et le test tombait sur une
    # `NameError` qui ne disait rien du comportement.
    debut = src.index("_TRADE_OR = {")
    fin = src.index("\ndef declencher_analyse_or(", debut)
    ns: dict = {}
    exec(compile(src[debut:fin], str(_SRC), "exec"), ns)  # noqa: S102
    assert "parse_commande_trade" in ns, "l'extraction a rate la fonction"
    return ns


# ─────────────────────────────────────────────────────────────────────────
# 1. Ce qu'elle accepte
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texte", [
    "/trade",
    "/trade ",
    "/TRADE",
    "/trade@mon_bot",
    "  /trade  ",
])
def test_un_trade_NU_vise_l_or_par_defaut(M, texte):
    """🔑 L'or est la seule paire ouverte au réel : `/trade` tout court doit
    marcher, sinon la commande est pénible à taper sur un téléphone."""
    assert M["parse_commande_trade"](texte) == "XAU/USD"


@pytest.mark.parametrize("texte,attendu", [
    ("/trade XAUUSD", "XAU/USD"),
    ("/trade xau/usd", "XAU/USD"),
    ("/trade or", "XAU/USD"),
    ("/trade gold", "XAU/USD"),
])
def test_les_noms_de_l_or_sont_RECONNUS(M, texte, attendu):
    assert M["parse_commande_trade"](texte) == attendu


# ─────────────────────────────────────────────────────────────────────────
# 2. ⛔ Ce qu'elle refuse
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texte", [
    "/status",
    "/start",
    "trade",                 # sans la barre
    "je voudrais un trade",
    "",
    "   ",
    "/trades",               # pluriel : une AUTRE commande possible demain
    "/tradeur",
])
def test_ce_qui_n_est_PAS_la_commande_est_refuse(M, texte):
    """⛔ `/trades` et `/tradeur` doivent être refusés : accepter tout ce qui
    COMMENCE par `/trade` volerait le nom de commandes futures."""
    assert M["parse_commande_trade"](texte) is None


def test_un_SENS_demande_est_refuse_AVEC_un_motif(M):
    """⛔ LE POINT QUI COMPTE. Xavier avait demandé `/trade buy`. La mesure du
    2026-10-10 a écarté la direction : indiscernable du hasard sur 5 jours
    (n=59, aucune p sous 0,27). Et l'entrée des signaux externes est barrée de
    l'argent réel par conception.

    ⇒ `/trade buy` ne doit PAS être silencieusement traité comme `/trade` : ça
    lui ferait croire que son sens a été pris en compte. On refuse, et on
    explique.
    """
    r = M["parse_commande_trade"]("/trade buy")
    assert r is None or isinstance(r, str) and r.startswith("REFUS:"), r
    if isinstance(r, str) and r.startswith("REFUS:"):
        assert "sens" in r.lower() or "direction" in r.lower(), r


@pytest.mark.parametrize("texte", ["/trade buy", "/trade sell",
                                   "/trade achat", "/trade vente"])
def test_les_quatre_formes_de_SENS_sont_refusees_de_la_meme_facon(M, texte):
    r = M["parse_commande_trade"](texte)
    assert isinstance(r, str) and r.startswith("REFUS:"), (texte, r)


def test_une_AUTRE_paire_est_refusee(M):
    """⚠️ L'or est la seule paire en liste blanche au réel
    (`MT5_BRIDGE_LIVE_WHITELIST_PAIRS=XAU/USD`). Accepter `/trade EURUSD`
    produirait un cycle qui ne peut rien faire, et un silence inexplicable."""
    r = M["parse_commande_trade"]("/trade EURUSD")
    assert r is None or (isinstance(r, str) and r.startswith("REFUS:")), r
