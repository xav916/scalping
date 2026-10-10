"""La commande `/trade` : ce qu'elle accepte, ce qu'elle refuse, où elle vit.

Demandée par Xavier le 2026-10-10.

## ⛔ TROIS TENTATIVES, TROIS DÉFAUTS — et c'est pour ça que ce fichier existe

1. **Mauvais bot.** Câblé sur `TRADES_TELEGRAM_BOT_TOKEN`, qui s'appelle
   « KRAKEN Trades ». L'or du réel vit sur « IC MARKETS Trades », soit
   `SALES_*`. `canaux_telegram.py` documentait déjà ce piège de nommage, et
   précisait que la confusion « s'est déjà produite ».
2. **Markdown cassé.** Les codes de refus sont en snake_case et Telegram lit
   un `_` comme une italique ouverte → `400 Can't find end of the entity`.
   Le message était construit, l'envoi rejeté, Xavier ne recevait **rien**.
3. **`getUpdates` IMPOSSIBLE.** Le bot IC MARKETS porte déjà un webhook, et
   Telegram répond `409 Conflict: can't use getUpdates while webhook is
   active`. L'écouteur ne pouvait **rien** recevoir.

⇒ La commande vit maintenant dans le **radar**, là où le webhook livre les
messages. L'analyse est une **fonction pure** : c'est elle qu'on éprouve ici.

🔑 **Trois réponses distinctes**, et les confondre laisse Xavier sans réponse —
ce qui est exactement ce qui s'est produit trois fois :

```
(None, None)          ce n'est pas la commande        -> on ignore
(None, "motif")       c'est elle, mais on refuse      -> on EXPLIQUE
("XAU/USD", None)     on declenche
```
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture()
def D():
    from backend.services import declencheur_manuel as mod
    return importlib.reload(mod)


# ─────────────────────────────────────────────────────────────────────────
# 1. Ce qu'elle accepte
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texte", [
    "/trade", "/trade ", "/TRADE", "/trade@mon_bot", "  /trade  ", "trade",
])
def test_un_trade_NU_vise_l_or(D, texte):
    """🔑 L'or est la seule paire ouverte au réel : `/trade` tout court doit
    marcher, sinon la commande est pénible à taper sur un téléphone."""
    assert D.parse_commande(texte) == ("XAU/USD", None)


@pytest.mark.parametrize("texte", [
    "/trade XAUUSD", "/trade xau/usd", "/trade or", "/trade GOLD",
])
def test_les_noms_de_l_or_sont_RECONNUS(D, texte):
    assert D.parse_commande(texte)[0] == "XAU/USD"


# ─────────────────────────────────────────────────────────────────────────
# 2. ⛔ Ce qui n'est PAS la commande : on ignore, on ne refuse pas
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texte", [
    "/status", "/start", "recap", "/risque", "gele",
    "je voudrais un trade", "", "   ", "/trades", "/tradeur",
])
def test_ce_qui_n_est_PAS_la_commande_est_IGNORE(D, texte):
    """⛔ `/trades` et `/tradeur` : accepter tout ce qui COMMENCE par `/trade`
    volerait le nom de commandes futures. Et `recap`/`risque`/`gele` sont des
    commandes EXISTANTES du même webhook : les capter les casserait."""
    assert D.parse_commande(texte) == (None, None)


# ─────────────────────────────────────────────────────────────────────────
# 3. ⛔ Ce qu'elle refuse, AVEC un motif
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texte", ["/trade buy", "/trade sell",
                                   "/trade achat", "/trade vente",
                                   "/trade long", "/trade short"])
def test_un_SENS_est_refuse_AVEC_son_motif(D, texte):
    """⛔ LE POINT QUI COMPTE. Xavier avait demandé `/trade buy`. La mesure du
    2026-10-10 l'a écarté : direction indiscernable du hasard sur 5 jours
    (n=59, aucune p sous 0,27). Le traiter en silence comme `/trade` lui
    ferait croire que son sens a été pris en compte."""
    cible, refus = D.parse_commande(texte)

    assert cible is None
    assert refus and "sens" in refus.lower()
    assert "0,27" in refus or "hasard" in refus


def test_une_AUTRE_paire_est_refusee_AVEC_son_motif(D):
    """⚠️ L'or est la seule paire en liste blanche au réel. Un cycle sur
    EUR/USD ne pourrait rien faire, et le silence serait inexplicable."""
    cible, refus = D.parse_commande("/trade EURUSD")

    assert cible is None
    assert refus and "EURUSD" in refus and "XAU/USD" in refus


def test_les_refus_ne_portent_AUCUN_caractere_Markdown(D):
    """⛔ DÉFAUT N°2. Un `_` ou un `*` dans un refus ferait echouer l'envoi en
    400, et Xavier ne recevrait rien — le refus serait donc MUET."""
    for texte in ("/trade buy", "/trade EURUSD"):
        _c, refus = D.parse_commande(texte)
        assert "_" not in refus, (texte, refus)
        assert "*" not in refus, (texte, refus)


# ─────────────────────────────────────────────────────────────────────────
# 4. ⛔ Elle est BRANCHÉE dans le webhook, et nulle part ailleurs
# ─────────────────────────────────────────────────────────────────────────

def test_elle_est_branchee_dans_le_WEBHOOK_sales():
    """⛔ DÉFAUT N°3. Le bot IC MARKETS porte un webhook : `getUpdates` rend
    409 et ne recevra JAMAIS rien. La commande doit être traitée là où
    Telegram livre."""
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8")
    debut = src.index('@app.post("/api/telegram/sales-webhook")')
    fin = src.index("\n@app.", debut + 10)
    bloc = src[debut:fin]

    assert "parse_commande" in bloc, "la commande n'est pas branchee"
    assert "diagnostic_or" in bloc, "le webhook ne rend pas le diagnostic"
    assert "parse_mode=None" in bloc, (
        "l'envoi repasserait en Markdown, et retomberait en 400")


def test_le_moniteur_n_a_PLUS_de_code_pour_cette_commande():
    """⚠️ Du code mort que personne n'appelle dérive en silence. Rien n'est
    laissé « au cas où » dans le moniteur."""
    src = (Path(__file__).resolve().parents[2] / "mt5-bridge-monitor"
           / "bridge_monitor.py").read_text(encoding="utf-8")

    for mort in ("parse_commande_trade", "declencher_analyse_or",
                 "formater_diagnostic", "TRADES_BOT_TOKEN"):
        assert mort not in src, "%s est encore dans le moniteur" % mort
