"""Bot Telegram pour pousser les signaux de scalping sur votre telephone.

Configuration :
- Creer un bot via @BotFather sur Telegram, recuperer le token
- Envoyer un message au bot depuis votre compte Telegram
- Recuperer votre chat_id via https://api.telegram.org/bot<TOKEN>/getUpdates
- Renseigner TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans .env

Le bot envoie uniquement les signaux "strong" par defaut (configurable).
"""

import asyncio
import logging

import httpx

from backend.services import trade_log_service
from backend.services.shadow_v2_core_long import SHADOW_PAIRS as _STAR_PAIRS
from datetime import date

from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_CHATS,
    TELEGRAM_LONG_HORIZON_ENABLED,
    TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE,
    TELEGRAM_SETUP_MIN_CONFIDENCE,
    TELEGRAM_SETUP_VERDICTS,
)

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


# Filtre paires : on ne pousse Telegram QUE pour les "stars" du portefeuille
# Phase 4 (XAU/XAG/WTI/ETH/XLI/XLK). Évite la pollution par les setups des
# 12 autres paires WATCHED_PAIRS (forex/SPX/NDX/BTC) sans edge confirmé.
_STAR_PAIRS_SET: frozenset[str] = frozenset(_STAR_PAIRS)


def is_configured() -> bool:
    """True si au moins un destinataire est configure."""
    return bool(TELEGRAM_BOT_TOKEN and (TELEGRAM_CHATS or TELEGRAM_CHAT_ID))


def _destinataires() -> list[tuple[str, str]]:
    """Retourne la liste (user, chat_id) a qui envoyer (config env legacy).

    Si TELEGRAM_CHATS est defini : un (user, chat_id) par user configure.
    Sinon fallback sur TELEGRAM_CHAT_ID (broadcast a 1 destinataire anonymous).
    """
    if TELEGRAM_CHATS:
        return list(TELEGRAM_CHATS.items())
    if TELEGRAM_CHAT_ID:
        return [("__any__", TELEGRAM_CHAT_ID)]
    return []


def _per_user_chat_ids_for_setup(setup) -> list[tuple[str, str]]:
    """Liste des (email, chat_id) des users DB qui doivent recevoir ce setup.

    Filtre par les prefs personnelles du user :
    - watched_pairs : le pair du setup doit y être
    - min_confidence : confidence_score doit ≥ seuil
    Chantier 2026-06-14 : feature notifs perso par client.
    """
    try:
        from backend.services import users_service
        candidates = users_service.list_users_with_telegram()
    except Exception as e:
        logger.warning(f"_per_user_chat_ids_for_setup: list users failed: {e}")
        return []
    pair = getattr(setup, "pair", None)
    conf = getattr(setup, "confidence_score", None) or 0.0
    out = []
    for u in candidates:
        if pair and pair not in u.get("watched_pairs", []):
            continue
        if conf < u.get("min_confidence", 70.0):
            continue
        out.append((u["email"], u["chat_id"]))
    return out


async def send_test_to_chat_id(chat_id: str, display_name: str) -> tuple[bool, str]:
    """Envoie un message test à un chat_id pour valider la liaison Telegram.

    Utilisé par l'endpoint POST /api/user/telegram/link au moment où le user
    clique "Connecter". Retourne (True, "") si OK, (False, err_msg) si échec.
    """
    if not (TELEGRAM_BOT_TOKEN and chat_id):
        return False, "Telegram bot non configuré côté serveur"
    msg = (
        f"✅ *Connexion réussie !*\n\n"
        f"Tu es maintenant connecté à Scalping Radar en tant que *{display_name}*.\n\n"
        f"Tu recevras ici tes signaux personnalisés selon tes paires sélectionnées "
        f"et ton niveau de confiance choisis dans /v2/settings.\n\n"
        f"Pour te déconnecter à tout moment : /v2/settings → section Telegram → Déconnecter."
    )
    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json={
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            })
            if r.status_code == 200:
                return True, ""
            # Parser le message d'erreur Telegram pour aider le user
            try:
                err_json = r.json()
                err_desc = err_json.get("description", r.text[:200])
            except Exception:
                err_desc = r.text[:200]
            return False, f"Telegram a refusé : {err_desc}"
    except Exception as e:
        return False, f"Erreur réseau : {e}"


async def send_text(text: str, parse_mode: str = "Markdown") -> None:
    """Envoie un texte libre a tous les destinataires (alertes systeme)."""
    if not is_configured():
        return
    destinataires = _destinataires()
    if not destinataires:
        return
    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    for user, chat_id in destinataires:
        if user != "__any__" and trade_log_service.silent_mode_active_for_user(user):
            continue
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json={
                    "chat_id": chat_id, "text": text, "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                })
        except Exception as e:
            logger.warning(f"Erreur Telegram text {user}: {e}")


async def send_infra_text(text: str, parse_mode: str = "HTML") -> bool:
    """Envoie un texte vers le canal infra dédié (@xav_scalping_infra_bot).

    Sépare les alertes système (rafales rejections, monitoring infra,
    routine alerts) du canal user-facing qui est réservé aux signaux de
    trading. Lit INFRA_TELEGRAM_BOT_TOKEN + INFRA_TELEGRAM_CHAT_ID depuis
    config.settings — si non configuré, no-op silencieux + log.

    parse_mode HTML par défaut depuis 2026-05-13 : Markdown legacy Telegram
    cassait dès qu'un message contenait un underscore non échappé (ex:
    reason_code "MIN_RR_BELOW_THRESHOLD" → 88 HTTP 400 sur 96h observés).
    HTML est plus strict côté tags mais ignore complètement les caractères
    _ * ` [ qui sont littéraux. Tout caller passant parse_mode="Markdown"
    bascule silencieusement en plain (pas de parse_mode) pour éviter la
    régression — il faut passer explicitement "HTML" pour formater.

    Retourne True si envoyé, False sinon.
    """
    from config.settings import INFRA_TELEGRAM_BOT_TOKEN, INFRA_TELEGRAM_CHAT_ID
    if not INFRA_TELEGRAM_BOT_TOKEN or not INFRA_TELEGRAM_CHAT_ID:
        logger.info("send_infra_text: INFRA_TELEGRAM_* non configure, skip")
        return False
    url = TELEGRAM_API.format(token=INFRA_TELEGRAM_BOT_TOKEN)
    payload: dict = {
        "chat_id": INFRA_TELEGRAM_CHAT_ID,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    if parse_mode == "HTML":
        payload["parse_mode"] = "HTML"
    elif parse_mode == "Markdown" or parse_mode == "MarkdownV2":
        # Legacy callers — on les laisse passer mais sans parse_mode pour
        # éviter de re-déclencher le bug d'underscore. Le contenu sera
        # affiché en clair (les * et _ resteront visibles).
        logger.info(
            "send_infra_text: parse_mode=%s deprecated, envoi en plain text",
            parse_mode,
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
        if r.status_code != 200:
            logger.warning(f"send_infra_text: HTTP {r.status_code} {r.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.warning(f"send_infra_text: erreur {e}")
        return False


async def send_sales_text(text: str, parse_mode: str = "HTML") -> bool:
    """Envoie un texte vers le canal business/sales dédié.

    Sépare les notifs commerciales (nouveau client payant, upgrade, churn)
    du bruit infra et des signaux user. Lit SALES_TELEGRAM_BOT_TOKEN +
    SALES_TELEGRAM_CHAT_ID — si non configuré, no-op silencieux. Même
    contrat que send_infra_text (HTML par défaut, fallback plain pour
    Markdown legacy).

    Retourne True si envoyé, False sinon.
    """
    from config.settings import SALES_TELEGRAM_BOT_TOKEN, SALES_TELEGRAM_CHAT_ID
    if not SALES_TELEGRAM_BOT_TOKEN or not SALES_TELEGRAM_CHAT_ID:
        logger.info("send_sales_text: SALES_TELEGRAM_* non configure, skip")
        return False
    url = TELEGRAM_API.format(token=SALES_TELEGRAM_BOT_TOKEN)
    payload: dict = {
        "chat_id": SALES_TELEGRAM_CHAT_ID,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    if parse_mode == "HTML":
        payload["parse_mode"] = "HTML"
    elif parse_mode == "Markdown" or parse_mode == "MarkdownV2":
        logger.info(
            "send_sales_text: parse_mode=%s deprecated, envoi en plain text",
            parse_mode,
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
        if r.status_code != 200:
            logger.warning(f"send_sales_text: HTTP {r.status_code} {r.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.warning(f"send_sales_text: erreur {e}")
        return False


async def send_info_text(text: str, parse_mode: str = "HTML") -> bool:
    """Envoie sur « Scalping Radar Info » — le bot `@xav_scalping_radar_bot`.

    Porte les observations qui n'ouvrent **aucune** position : aujourd'hui les
    setups long-horizon 4h/1d. Elles partaient sur le bot sales, où elles se
    mêlaient aux digests, à l'état des marchés et au récap quotidien.

    ⚠️ **Envoi au seul `TELEGRAM_CHAT_ID`, jamais en diffusion.** Le bot radar
    sert aussi les clients via `send_text`, qui boucle sur `TELEGRAM_CHATS` :
    passer par là ferait partir ces observations chez Cédric et les futurs
    Premium le jour où ils y seront inscrits. `TELEGRAM_CHATS` est vide
    aujourd'hui, donc rien ne le révélerait avant que ce ne soit trop tard.

    ⚠️ Repli sur le canal sales si le bot radar n'est pas configuré : c'est le
    comportement d'avant le 2026-08-19, donc rien n'est perdu.

    Retourne True si envoyé, False sinon.
    """
    from config.settings import TELEGRAM_BOT_TOKEN as _TOK
    from config.settings import TELEGRAM_CHAT_ID as _CHAT
    if not _TOK or not _CHAT:
        logger.info(
            "send_info_text: bot radar non configure — repli sur le canal sales"
        )
        return await send_sales_text(text, parse_mode=parse_mode)
    url = TELEGRAM_API.format(token=_TOK)
    payload: dict = {
        "chat_id": _CHAT,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    if parse_mode == "HTML":
        payload["parse_mode"] = "HTML"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
        if r.status_code != 200:
            logger.warning(f"send_info_text: HTTP {r.status_code} {r.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.warning(f"send_info_text: erreur {e}")
        return False


async def send_long_horizon_setup(setup) -> bool:
    """Annonce un setup 4h / 1d sur le canal « Info », hors gate global.

    Ce canal est **indépendant** du réglage qui autorise les alertes setup
    temps-réel : il vaut chaîne vide en production, ce qui les éteint toutes,
    et le rallumer produirait ~2000 messages/jour. Le flux long-horizon, lui,
    en pèse quelques-uns.

    Rend `True` si un message est parti. Best-effort : jamais d'exception
    propagée — le shadow log ne doit pas dépendre de Telegram.
    """
    try:
        if not TELEGRAM_LONG_HORIZON_ENABLED:
            return False

        from backend.services.horizon import is_long as _is_long

        if not _is_long(getattr(setup, "horizon", None)):
            return False
        score = getattr(setup, "confidence_score", None) or 0
        if score < TELEGRAM_LONG_HORIZON_MIN_CONFIDENCE:
            return False

        import html as _html

        def _e(v) -> str:
            return _html.escape(str(v), quote=False)

        direction = getattr(getattr(setup, "direction", None), "value", "")
        lignes = [
            f"<b>Horizon {_e(setup.horizon)} — {_e(setup.pair)}</b>",
            f"{_e(str(direction).upper())} · confiance {score:.0f}/100"
            f" · verdict {_e(getattr(setup, 'verdict_action', '') or 'n/a')}",
            f"Entrée {setup.entry_price:.4f} · SL {setup.stop_loss:.4f}"
            f" · TP1 {setup.take_profit_1:.4f}",
            f"<i>{_e(getattr(setup, 'shadow_system_id', '') or '')}</i>",
            "",
            "Observation seule — aucune position n'est ouverte.",
        ]
        # « Scalping Radar Info » depuis le 2026-08-19 : ces annonces n'ouvrent
        # aucune position, elles n'ont donc rien à faire au milieu des digests
        # et du récap du bot sales.
        return bool(await send_info_text("\n".join(lignes), parse_mode="HTML"))
    except Exception as e:
        logger.warning(f"send_long_horizon_setup a échoué: {e}")
        return False


# ─── Trade setups (potentiels) — chemin distinct des signaux ────────────────
#
# Motivation : un "signal" ne part sur Telegram qu'à partir de strength=strong
# par défaut. Les setups haute confiance avec verdict TAKE méritent d'être
# poussés même sans signal "strong" formel. Sinon le user ne voit les
# opportunités que dans l'UI web.
#
# Dedup : on ne re-pousse pas le même (pair, direction, entry arrondi) dans
# la journée. Reset à minuit (clé date incluse dans le set).

_sent_setups_today: set[tuple[str, str, str, str]] = set()


def _setup_dedup_key(setup) -> tuple[str, str, str, str]:
    """Clé de dédup stable : (date_iso, pair, direction, entry arrondi)."""
    # entry arrondi à 5 décimales pour tolérer des micro-variations entre cycles.
    entry_rounded = f"{setup.entry_price:.5f}"
    return (
        date.today().isoformat(),
        setup.pair,
        setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction),
        entry_rounded,
    )


def _cleanup_old_dedup_keys() -> None:
    """Purge les entrées d'hier. Appelée à chaque push : coût négligeable."""
    today = date.today().isoformat()
    # on crée une nouvelle set avec seulement les entrées du jour
    for key in list(_sent_setups_today):
        if key[0] != today:
            _sent_setups_today.discard(key)


def _should_push_setup(setup) -> bool:
    """Filtre : (pair, direction) éligible Telegram + verdict dans la liste
    autorisée + score au-dessus du seuil.

    Éligibilité Telegram = state in (TELEGRAM, AUTO_EXEC, PAUSED) via
    pair_admission_controller. Fallback sur _STAR_PAIRS_SET hardcodé si
    controller indisponible ou si (pair, direction) jamais vue.
    """
    setup_direction = getattr(setup, "direction", None)
    if hasattr(setup_direction, "value"):
        setup_direction = setup_direction.value
    try:
        from backend.services import pair_admission_controller
        if pair_admission_controller.has_explicit_state(setup.pair, setup_direction):
            if not pair_admission_controller.is_telegram_eligible(setup.pair, setup_direction):
                return False
        else:
            if setup.pair not in _STAR_PAIRS_SET:
                return False
    except Exception:
        if setup.pair not in _STAR_PAIRS_SET:
            return False
    if not setup.verdict_action:
        return False
    if setup.verdict_action.upper() not in TELEGRAM_SETUP_VERDICTS:
        return False
    score = getattr(setup, "confidence_score", None) or 0
    if score < TELEGRAM_SETUP_MIN_CONFIDENCE:
        return False
    return True


_PAIR_FR_LABEL: dict[str, str] = {
    "XAU/USD": "Or",
    "XAG/USD": "Argent",
    "WTI/USD": "Pétrole WTI",
    "ETH/USD": "Ethereum",
    "BTC/USD": "Bitcoin",
    # 6 cryptos promues AUTO_EXEC le 2026-06-13 (cf. project_manual_crypto_promotion_2026_06_13)
    # → ajout 2026-06-16 pour uniformiser les notifs Telegram trade_opened / close.
    "SOL/USD": "Solana",
    "ADA/USD": "Cardano",
    "XRP/USD": "Ripple",
    "LTC/USD": "Litecoin",
    "BCH/USD": "Bitcoin Cash",
    "DOT/USD": "Polkadot",
    # Autres paires watched (forex majors + équités) — labels lisibles pour
    # cohérence en cas de push futur.
    "EUR/USD": "Euro / Dollar",
    "GBP/USD": "Livre / Dollar",
    "USD/JPY": "Dollar / Yen",
    "EUR/GBP": "Euro / Livre",
    "USD/CHF": "Dollar / Franc Suisse",
    "AUD/USD": "Dollar Australien",
    "USD/CAD": "Dollar / Dollar Canadien",
    "EUR/JPY": "Euro / Yen",
    "GBP/JPY": "Livre / Yen",
    "SPX": "S&P 500",
    "NDX": "Nasdaq 100",
}

_PATTERN_EXPLAIN_FR: dict[str, str] = {
    "momentum_up": "fort élan haussier — la dernière bougie absorbe la pression vendeuse et accélère vers le haut",
    "momentum_down": "fort élan baissier — la dernière bougie casse la dynamique acheteuse",
    "engulfing_bullish": "bougie englobante haussière — un retournement net après une phase baissière",
    "engulfing_bearish": "bougie englobante baissière — un retournement net après une phase haussière",
    "breakout_up": "cassure de résistance — le prix franchit un plafond technique avec volume",
    "breakout_down": "cassure de support — le prix casse un plancher technique avec volume",
    "range_bounce_up": "rebond sur support — le prix repart d'un plancher dans un range établi",
    "range_bounce_down": "rejet sur résistance — le prix échoue à casser un plafond dans un range",
    "pin_bar_up": "pin bar haussière — rejet visible du bas, signal de retournement court terme",
    "pin_bar_down": "pin bar baissière — rejet visible du haut, signal de retournement court terme",
    "poc_return_up": "retour au prix d'équilibre en tendance haussière — le marché revient sur la zone où il a passé le plus de temps avant de repartir vers le haut",
    "poc_return_down": "retour au prix d'équilibre en tendance baissière — le marché revient sur la zone où il a passé le plus de temps avant de repartir vers le bas",
    # Ajoutés le 2026-08-04 : sans libellé, le repli affichait la valeur brute
    # `mean_reversion_up`, dont les underscores cassaient le Markdown et
    # faisaient perdre TOUT le message.
    "mean_reversion_up": "retour à la moyenne haussier — le prix s'est trop éloigné vers le bas et revient",
    "mean_reversion_down": "retour à la moyenne baissier — le prix s'est trop éloigné vers le haut et revient",
}


# Labels lisibles pour chaque destination admin connue. Utilisé pour annoter
# le badge "Auto-exécuté" du push Telegram avec les brokers réels touchés.
# Cf. project_live_icmarkets_active_2026_06_12.
# Libellés dérivés du registre des destinations : une seule déclaration
# par plateforme, ici comme ailleurs.
from backend.services import destinations_registry as _registry

# Libellés des destinations, source UNIQUE pour tous les messages Telegram.
#
# ⚠️ Cette table ne listait que `admin_legacy` et `admin_live` — 2 destinations
# sur 7 — et une seconde liste en `if/elif` vivait sa vie plus bas dans le
# fichier. Un trade parti chez Kraken s'affichait donc sous un identifiant
# technique, ou pire sous le libellé générique « Démo » alors qu'il engageait
# de l'argent réel.
#
# Même famille de péremption que `VALID_DESTINATIONS` (2026-08-04) : une
# constante écrite avant l'ajout des destinations, jamais remise à jour.
# `test_telegram_destination_labels` échoue désormais si une destination
# connue de `bridge_destinations` n'a pas son libellé ici.
#
# `badge` : annotation courte du push de setup ("Auto-exécuté → …")
# `mode`  : ligne broker du message d'ouverture de trade
# `reel`  : True si de l'argent réel est engagé — jamais deviner, déclarer.
DESTINATION_LABELS: dict[str, dict[str, object]] = {
    d.id: {"badge": d.badge, "mode": d.mode, "reel": d.reel}
    for d in _registry.DESTINATIONS.values()
}

_USER_DEST_LABEL = {
    "badge": _registry.USER_DESTINATION.badge,
    "mode": _registry.USER_DESTINATION.mode,
    "reel": _registry.USER_DESTINATION.reel,
}


def destination_label(destination_id: str | None, champ: str = "badge") -> str:
    """Libellé lisible d'une destination. Jamais d'exception, jamais de blanc.

    Une destination inconnue retombe sur son identifiant technique plutôt que
    sur un libellé générique : mieux vaut « admin_truc » que « Démo » sur un
    ordre en argent réel.
    """
    if not destination_id:
        return "broker non identifié"
    if destination_id.startswith("user:"):
        return str(_USER_DEST_LABEL[champ])
    entree = DESTINATION_LABELS.get(destination_id)
    if entree is None:
        return destination_id
    return str(entree[champ])


# Rétro-compat : ancien nom, utilisé par _describe_admin_destinations.
_ADMIN_DEST_LABELS = {k: v["badge"] for k, v in DESTINATION_LABELS.items()}


# Valeur en EUR par UNITÉ DE PRIX (= la valeur de `risk_pips` dans le système,
# qui est en réalité la distance brute entry−stop, pas des pips au sens classique)
# pour 0.01 lot (volume minimum). Approximations specs broker standards 2026-06
# + EUR/USD ~1.10 + USD/JPY ~150. Utilisé pour estimer risque/gain € user-facing
# dans les messages Telegram. Volatile, approximation.
#
# Pour Demo (max_lot 0.10) : multiplier mentalement par 10.
# Pour Live IC Markets (max_lot 0.02) : multiplier par 2.
#
# Forex : le système stocke risk_pips = abs(entry-stop) arrondi à 2 décimales.
# Pour les majors quote USD (pip = 0.0001), un SL typique de 10-30 pips = 0.001
# à 0.003 → arrondi à 0.00, le champ est inexploitable. On skip forex pour ne
# pas afficher €0.00 trompeur.
_PIP_VALUE_AT_001_LOT_EUR: dict[str, float] = {
    # Metals (1 lot = 100 oz pour XAU, 5000 oz pour XAG)
    "XAU/USD": 0.90,   # 1 unité prix × 100 × 0.01 = $1 ≈ €0.90
    "XAG/USD": 45.0,   # 1 unité prix × 5000 × 0.01 = $50 ≈ €45
    # Energy (1 lot = 1000 barrels)
    "WTI/USD": 9.0,    # 1 unité prix × 1000 × 0.01 = $10 ≈ €9
    # Crypto (1 lot = 1 unité de la crypto ; pip_value uniforme par convention
    # broker = 1 tick × 0.01 lot × $1/unit ≈ €0.009). Ajout 2026-06-16 des 6
    # cryptos promues 13/06 pour uniformiser notifs Telegram trade_opened/close.
    "ETH/USD": 0.009,
    "BTC/USD": 0.009,
    "SOL/USD": 0.009,
    "ADA/USD": 0.009,
    "XRP/USD": 0.009,
    "LTC/USD": 0.009,
    "BCH/USD": 0.009,
    "DOT/USD": 0.009,
    # Forex : NON mappé volontairement (risk_pips arrondi à 0.00 → affichage
    # €0.00 trompeur). À reactiver quand on aura un pipeline qui conserve la
    # précision (e.g. risk_money directement en EUR).
}


# Margin (= "argent engagé" pour ouvrir la position) estimée en EUR par 0.01 lot.
# Approximations basées sur leverages ESMA retail UE (forex 1:30, métaux 1:20,
# énergie 1:10, crypto 1:2) + prix typiques 2026-06 + USD→EUR ~0.90.
# Pour Demo (max_lot 0.10) ≈ ×10. Pour Live (max_lot 0.02) ≈ ×2.
_MARGIN_AT_001_LOT_EUR: dict[str, float] = {
    # Forex majors (1:30 leverage) — 0.01 lot = 1000 base ÷ 30 ≈ €33
    "EUR/USD": 33.0,
    "GBP/USD": 39.0,
    "AUD/USD": 22.0,
    "NZD/USD": 20.0,
    "USD/JPY": 33.0,
    "EUR/JPY": 33.0,
    "GBP/JPY": 38.0,
    # Metals (1:20 leverage)
    "XAU/USD": 190.0,  # 1 oz × $4200 ÷ 20 ≈ $210 ≈ €190
    "XAG/USD": 113.0,  # 50 oz × $50 ÷ 20 ≈ $125 ≈ €113
    # Energy (1:10 leverage)
    "WTI/USD": 67.0,   # 10 barrels × $75 ÷ 10 ≈ $75 ≈ €67
    # Crypto (1:2 leverage retail EU)
    "ETH/USD": 8.0,    # 0.01 ETH × $1700 ÷ 2 ≈ $8.50 ≈ €7.65
    "BTC/USD": 450.0,  # 0.01 BTC × $100000 ÷ 2 ≈ €450 (probable NO_MONEY sur €300 cap)
    # 6 altcoins promues 2026-06-13 (ajout 2026-06-16). Prix ~mi-juin 2026.
    "SOL/USD": 0.30,   # 0.01 × $67 ÷ 2 ≈ €0.30
    "BCH/USD": 1.00,   # 0.01 × $220 ÷ 2 ≈ €1.00
    "LTC/USD": 0.20,   # 0.01 × $45 ÷ 2 ≈ €0.20
    "ADA/USD": 0.01,   # 0.01 × $0.17 ÷ 2 — trop petit pour affichage utile
    "XRP/USD": 0.01,   # 0.01 × $1.14 ÷ 2 — idem
    "DOT/USD": 0.01,   # 0.01 × $1.0 ÷ 2 — idem
}



def destination_is_real_money(destination_id: str | None) -> bool:
    """True si cette destination engage de l'argent réel.

    Déclaré dans ``DESTINATION_LABELS``, jamais déduit : une destination
    inconnue est traitée comme fictive, donc silencieuse. Mieux vaut rater
    une notification que crier au loup sur du Demo.
    """
    if not destination_id:
        return False
    if destination_id.startswith("user:"):
        return bool(_USER_DEST_LABEL.get("reel"))
    entree = DESTINATION_LABELS.get(destination_id)
    return bool(entree and entree.get("reel"))


def destination_for_ticket(ticket) -> str | None:
    """Retrouve la destination d'un trade à partir de son ticket.

    ``personal_trades`` ne porte pas de ``destination_id`` : le chemin de
    clôture ignore donc chez quel broker le trade a eu lieu. On le résout
    depuis ``mt5_pushes``, dont la réponse du bridge contient le ticket.

    Exact plutôt qu'heuristique — deviner d'après le format du numéro de
    ticket serait fragile, et c'est de l'argent réel.
    """
    if not ticket:
        return None
    try:
        import sqlite3
        from backend.services.trade_log_service import _DB_PATH
        with sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True, timeout=5) as c:
            row = c.execute(
                "SELECT destination_id FROM mt5_pushes "
                " WHERE bridge_response LIKE ? ORDER BY id DESC LIMIT 1",
                (f"%{ticket}%",),
            ).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.debug(f"destination_for_ticket({ticket}): {e}")
        return None

def _executing_destinations(setup) -> list:
    """Destinations admin qui exécuteront effectivement ce setup.

    Source unique pour l'annotation broker ET le bloc monétaire — les deux
    doivent parler du même trade.
    """
    try:
        from backend.services import bridge_destinations
        from backend.services.mt5_bridge import _cost_rejection
        from config.settings import asset_class_for, MT5_BRIDGE_ALLOWED_PATTERNS

        score = float(getattr(setup, "confidence_score", 0) or 0)
        pair = getattr(setup, "pair", None)
        if not pair:
            return []
        try:
            aclass = asset_class_for(pair)
        except Exception:
            aclass = None
        out = []
        for dest in bridge_destinations.resolve_destinations(setup):
            if dest.user_id is not None or not dest.auto_exec_enabled:
                continue
            if score < dest.min_confidence:
                continue
            if aclass and aclass not in dest.allowed_asset_classes:
                continue
            motifs = getattr(dest, "allowed_patterns", None)
            if motifs is None:
                motifs = MT5_BRIDGE_ALLOWED_PATTERNS
            if motifs and _pattern_of(setup) not in motifs:
                continue
            if _cost_rejection(setup, dest):
                continue
            out.append(dest)
        return out
    except Exception:
        return []


def _pattern_of(setup) -> str | None:
    try:
        det = getattr(setup, "pattern", None)
        if det is None:
            return None
        pv = getattr(det, "pattern", det)
        v = pv.value if hasattr(pv, "value") else str(pv)
        return v.lower() if v else None
    except Exception:
        return None


def _amounts_from_sizing(setup, dest) -> dict | None:
    """Montants réels pour une destination qui dimensionne sur son solde.

    ⚠️ La table `_PIP_VALUE_AT_001_LOT_EUR` est calibrée pour du CFD MT5 en
    lot 0,01. Appliquée à Kraken, elle annonçait « ~€8 engagés, −€0,08 de
    risque » sur ETH — des chiffres sans rapport, assortis d'une mention
    « Demo ×0,10 lot · Live IC Markets 0,02 lot » qui n'a aucun sens là-bas.

    Sur ces bridges, `risk_money` **est** le risque réel dans la devise du
    compte : le gain se déduit du R:R, sans table intermédiaire.

    ``None`` si le solde n'est pas connu — mieux vaut pas de bloc qu'un
    bloc faux.
    """
    try:
        from backend.services import sizing
        sz = sizing.compute_risk_money(setup, dest)
        risque = float(sz.get("risk_money") or 0)
        if risque <= 0:
            return None
        rr1 = float(getattr(setup, "risk_reward_1", 0) or 0)
        rr2 = float(getattr(setup, "risk_reward_2", 0) or 0)
        return {
            "margin": None,
            "risk": risque,
            "reward_1": risque * rr1 if rr1 > 0 else None,
            "reward_2": risque * rr2 if rr2 > 0 else None,
            "devise": "USD",
            "capital": sz.get("capital"),
        }
    except Exception:
        return None


def _estimate_eur_amounts(setup) -> dict | None:
    """Retourne dict {margin, risk, reward_1, reward_2} en EUR estimé pour 0.01 lot.

    - ``margin`` : "argent engagé" pour ouvrir la position (= notional ÷ leverage).
      None si la pair n'a pas de mapping margin (le bloc est rendu sans cette ligne).
    - ``risk`` / ``reward_*`` : pertes/gains potentiels si SL/TP touchés.

    None retourné globalement si la pair n'a pas de mapping pip_value ou si
    risk_pips manquant. Best-effort, approximation.
    """
    pair = getattr(setup, "pair", "")
    risk_pips = float(getattr(setup, "risk_pips", 0) or 0)
    reward_pips_1 = float(getattr(setup, "reward_pips_1", 0) or 0)
    reward_pips_2 = float(getattr(setup, "reward_pips_2", 0) or 0)
    pip_eur = _PIP_VALUE_AT_001_LOT_EUR.get(pair)
    if not pip_eur or risk_pips <= 0:
        return None
    return {
        "margin": _MARGIN_AT_001_LOT_EUR.get(pair),  # None si non mappé
        "risk": pip_eur * risk_pips,
        "reward_1": pip_eur * reward_pips_1,
        "reward_2": pip_eur * reward_pips_2 if reward_pips_2 > 0 else None,
    }


def _describe_admin_destinations(setup) -> list[str]:
    """Libellés lisibles des destinations qui exécuteront ce setup.

    S'appuie sur ``_executing_destinations`` : le bloc monétaire et
    l'annotation broker doivent décrire le même trade.
    """
    return [destination_label(d.destination_id, "badge")
            for d in _executing_destinations(setup)]


def _format_setup(setup) -> str:
    """Format Telegram pédagogique : vulgarise l'analyse pour le user-facing.

    Structure :
    1. Header (pair label FR, direction, score, heure Paris)
    2. Lecture du radar (pattern explained + verdict_summary si dispo)
    3. Plan de trade (entry/SL/TP1/TP2 avec gain/perte concrets)
    4. Comment lire ce R:R (explication chiffrée)
    5. Forces validant le setup (verdict_reasons)
    6. Vigilances (verdict_warnings)
    7. Validité

    Vise les Premium qui veulent comprendre POURQUOI le radar émet, pas
    juste recevoir des chiffres bruts.
    """
    from datetime import datetime, timezone, timedelta

    verdict_icon = {"TAKE": "✅", "WAIT": "⏳", "SKIP": "⛔"}.get(
        setup.verdict_action or "", "📊"
    )
    dir_value = (
        setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    )
    dir_label = "ACHAT 🟢" if dir_value == "buy" else "VENTE 🔴"
    score = getattr(setup, "confidence_score", 0) or 0

    paris_now = datetime.now(timezone.utc) + timedelta(hours=2)
    time_str = paris_now.strftime("%H:%M")

    pair_label = _PAIR_FR_LABEL.get(setup.pair, setup.pair)

    # Pattern explanation
    pattern_obj = getattr(setup, "pattern", None)
    pattern_value = ""
    if pattern_obj is not None:
        ptype = getattr(pattern_obj, "pattern", None)
        pattern_value = ptype.value if hasattr(ptype, "value") else str(ptype or "")
    # md_safe sur le repli : un pattern ajouté à l'enum sans libellé FR ici
    # afficherait sa valeur brute (`range_bounce_up`), dont les underscores
    # casseraient le message entier.
    pattern_explain = _PATTERN_EXPLAIN_FR.get(
        pattern_value, md_safe(pattern_value) or "signal technique détecté"
    )

    risk = float(getattr(setup, "risk_pips", 0) or 0)
    reward_1 = float(getattr(setup, "reward_pips_1", 0) or 0)
    reward_2 = float(getattr(setup, "reward_pips_2", 0) or 0)
    rr1 = float(getattr(setup, "risk_reward_1", 0) or 0)
    rr2 = float(getattr(setup, "risk_reward_2", 0) or 0)

    # Statut d'exécution PAC : distingue clairement "trade auto-exécuté chez
    # ton broker" vs "signal info uniquement (paire en surveillance/PAUSED)".
    # Évite la confusion vécue le 2026-06-09 où un signal GBP/USD buy avec
    # verdict TAKE et summary "passez l'ordre" arrivait alors que la paire
    # était PAUSED depuis 6 jours et que le bridge n'exécutait rien.
    pac_auto = None
    pac_state = None
    try:
        from backend.services import pair_admission_controller as _pac
        if _pac.has_explicit_state(setup.pair, dir_value):
            pac_state = _pac.get_current_state(setup.pair, dir_value)
            pac_auto = (pac_state == "AUTO_EXEC")
        else:
            # Fallback legacy stars : si pair dans _STAR_PAIRS_SET, considère auto
            pac_auto = setup.pair in _STAR_PAIRS_SET
            pac_state = "AUTO_EXEC (legacy)" if pac_auto else "non-éligible"
    except Exception:
        pac_auto = None  # PAC indisponible → on n'affiche pas de badge

    if pac_auto is True:
        # Liste les destinations admin qui recevront ce setup (Demo, Live, ...).
        # Filtré sur confidence + asset class pour matcher ce que mt5_bridge
        # routera effectivement. Cf. project_live_icmarkets_active_2026_06_12
        # depuis 2026-06-12 : Demo Pepperstone + Live IC Markets en parallèle.
        dest_labels = _describe_admin_destinations(setup)
        if dest_labels:
            exec_badge = f"🤖 *Auto-exécuté* → {' + '.join(dest_labels)}"
        else:
            # Fallback legacy si resolve_destinations n'a rien retourné
            # (filtres en amont, edge case).
            exec_badge = "🤖 *Auto-exécuté* — ordre envoyé chez ton broker."
    elif pac_auto is False:
        exec_badge = (
            f"👁 *Signal info uniquement* — paire en `{pac_state}`, "
            f"**pas d'auto-exécution**. À placer manuellement si tu veux."
        )
    else:
        exec_badge = None

    lines = [
        f"{verdict_icon} *{pair_label}* ({setup.pair}) — {dir_label}",
        f"Score *{score:.0f}/100* · {time_str} Paris",
    ]
    if exec_badge:
        lines.append(exec_badge)
    lines.extend([
        "",
        "🧭 *Lecture du radar*",
        f"Pattern détecté : *{pattern_explain}*.",
    ])

    verdict_summary = getattr(setup, "verdict_summary", None)
    if verdict_summary:
        # Texte libre du moteur de scoring, interpolé dans une entité italique
        lines.append(f"_{md_safe(verdict_summary)}_")

    lines.extend([
        "",
        "💰 *Plan de trade*",
        f"Entrée  `{setup.entry_price:.5f}`",
        f"Stop    `{setup.stop_loss:.5f}`  _(perte si invalidé : {risk:.1f} pts)_",
        f"TP1     `{setup.take_profit_1:.5f}`  _(+{reward_1:.1f} pts, soit {rr1:.1f}× la perte)_",
        f"TP2     `{setup.take_profit_2:.5f}`  _(+{reward_2:.1f} pts, soit {rr2:.1f}× la perte)_",
    ])

    if rr1 > 0:
        lines.extend([
            "",
            "📊 *Comment lire ce trade*",
            f"Tu risques *{risk:.1f} pts* pour viser *+{reward_1:.1f} pts* (R:R {rr1:.1f}). "
            f"Avec ce ratio, le trade devient gagnant si tu touches TP1 plus de "
            f"{int(round(100/(1+rr1)))}% du temps.",
        ])

    # Conversion EUR estimée (lot baseline 0.01 = volume minimum). Pour Demo
    # (max_lot 0.10) multiplier mentalement par 10, pour Live IC Markets
    # (max_lot 0.02) multiplier par 2. Approximation : EUR/USD ~1.10 + specs
    # broker standards. Cf. _PIP_VALUE_AT_001_LOT_EUR.
    # Montants : deux régimes selon la destination qui exécute.
    #  - bridges à solde interrogeable (Kraken, Binance) : `risk_money` EST
    #    le risque réel, on l'affiche tel quel
    #  - bridges MT5 : estimation par table de pips au lot minimum
    # Mélanger les deux donnait des chiffres faux sur crypto — cf.
    # `_amounts_from_sizing`.
    from backend.services import sizing as _sizing
    _dest_live = next(
        (d for d in _executing_destinations(setup)
         if getattr(d, "bridge_type", "mt5") in _sizing.LIVE_BALANCE_BRIDGE_TYPES),
        None,
    )
    if _dest_live is not None:
        montants = _amounts_from_sizing(setup, _dest_live)
        if montants is not None:
            devise = montants["devise"]
            bloc = ["", f"💵 *Montants réels ({devise})*"]
            bloc.append(
                f"Risque max    : *−{montants['risk']:.2f} {devise}* si SL touché"
            )
            if montants.get("reward_1"):
                ligne = f"Gain TP1      : *+{montants['reward_1']:.2f} {devise}*"
                if montants.get("reward_2"):
                    ligne += f"  ·  TP2 : *+{montants['reward_2']:.2f} {devise}*"
                bloc.append(ligne)
            if montants.get("capital"):
                bloc.append(
                    f"_Dimensionné sur le solde réel du compte "
                    f"({montants['capital']:.2f} {devise})._"
                )
            lines.extend(bloc)
    else:
        eur = _estimate_eur_amounts(setup)
        if eur is not None:
            eur_lines = ["", "💵 *En euros (estimation, lot 0.01)*"]
            if eur.get("margin") is not None:
                eur_lines.append(f"Argent engagé : *~€{eur['margin']:.0f}* (margin requise)")
            eur_lines.extend([
                f"Risque max    : *−€{eur['risk']:.2f}* si SL touché",
                f"Gain TP1      : *+€{eur['reward_1']:.2f}*"
                + (f"  ·  TP2 : *+€{eur['reward_2']:.2f}*" if eur.get("reward_2") else ""),
                "_Demo (×0.10 lot) ≈ ×10  ·  Live IC Markets (0.02 lot) ≈ ×2_",
            ])
            lines.extend(eur_lines)

    reasons = getattr(setup, "verdict_reasons", None) or []
    warnings = getattr(setup, "verdict_warnings", None) or []
    if reasons:
        lines.append("")
        lines.append("✅ *Pourquoi entrer*")
        for r in reasons[:3]:
            lines.append(f"• {r}")
    if warnings:
        lines.append("")
        lines.append("⚠️ *Vigilance*")
        for w in warnings[:3]:
            lines.append(f"• {w}")

    validity = getattr(setup, "validity_minutes", None)
    if validity:
        lines.append("")
        lines.append(f"⏱ *Validité* {validity} min — passé ce délai, le marché aura bougé, recalculer ou attendre le prochain signal.")

    return "\n".join(lines)


async def _send_setup_to(chat_id: str, setup, who: str) -> None:
    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": chat_id,
        "text": _format_setup(setup),
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.warning(f"Telegram setup erreur {response.status_code} pour {who}: {response.text[:200]}")
            else:
                logger.info(
                    f"Setup Telegram envoye a {who} pour {setup.pair} "
                    f"({setup.verdict_action} {getattr(setup, 'confidence_score', 0):.0f})"
                )
    except Exception as e:
        logger.warning(f"Erreur envoi setup Telegram {who}: {e}")


async def send_setup(setup) -> None:
    """Push un trade_setup unique sur Telegram si verdict + seuil + dedup OK."""
    if not is_configured() or not _should_push_setup(setup):
        return
    key = _setup_dedup_key(setup)
    _cleanup_old_dedup_keys()
    if key in _sent_setups_today:
        return
    _sent_setups_today.add(key)

    # Envoi legacy (Xavier env TELEGRAM_CHATS / TELEGRAM_CHAT_ID)
    destinataires = _destinataires()
    for user, chat_id in destinataires:
        if user != "__any__" and trade_log_service.silent_mode_active_for_user(user):
            logger.info(f"Mode silencieux actif pour {user}, setup {setup.pair} skip")
            continue
        await _send_setup_to(chat_id, setup, who=user)

    # Envoi per-user DB (chantier 2026-06-14) : chaque user Premium qui a
    # connecté son Telegram reçoit UNIQUEMENT les setups qui matchent ses
    # watched_pairs + min_confidence. Filtrage déjà appliqué dans
    # _per_user_chat_ids_for_setup. Aucune intervention env.
    per_user = _per_user_chat_ids_for_setup(setup)
    for email, chat_id in per_user:
        await _send_setup_to(chat_id, setup, who=f"db:{email}")


async def send_setups(setups: list) -> None:
    """Push plusieurs trade_setups en parallèle. Dedup + filtres s'appliquent."""
    if not is_configured() or not setups:
        return
    await asyncio.gather(*(send_setup(s) for s in setups), return_exceptions=True)


# ─── Notifications de fermeture (TP/SL/TIMEOUT/MANUAL) ──────────────────────
# Pendant logique : send_setup pousse à l'OUVERTURE d'un setup détecté.
# send_close pousse à la FERMETURE d'un trade auto-exec (mt5_ticket connu).
# Dédup ticket-based : un trade ne notifie qu'une fois sa clôture.

# Clés de dédup sous forme de CHAÎNE : un ticket MT5 est un entier, mais une
# référence d'ordre Kraken est un UUID. `int(ticket)` levait donc une
# ValueError sur toute clôture Kraken — avalée plus haut, elle aurait fait
# disparaître la notification exactement là où on venait de la brancher.
_notified_closes: set[str] = set()


def _mfe_mae(bougies: list, entry: float, risque: float, achat: bool,
             point: float = 0.0) -> dict | None:
    """Meilleur et pire point atteints, en unités de risque.

    ⚠️ **L'inversion vente est le seul endroit où une erreur serait
    silencieuse** : sur une vente, le « meilleur » point est le plus BAS, et
    prendre le plus haut rendrait un MFE négatif qu'on lirait comme « jamais
    passé au vert ». D'où un test dédié plutôt qu'une relecture.

    ⛔ **Le spread ne se paie que d'un côté.** Les bougies MT5 sont en BID.
    Sur un ACHAT l'entrée enregistrée est déjà le fill à l'ask et la sortie se
    fait au bid : les extrêmes sont directement les bons, en retirer un spread
    facturerait le coût deux fois. Sur une VENTE on entre au bid mais on
    **rachète à l'ask** : le point réellement atteignable est `bas + spread`.

    Le spread retenu est celui de la bougie de l'EXTRÊME, pas une moyenne —
    une moyenne lisserait justement le pic qui compte. Mesuré le 2026-08-25 :
    médiane 1 % du risque, mais **29 % dans la queue**, et c'est exactement au
    moment de ces pics que les stops se font toucher.
    """
    valides = [b for b in bougies
               if b.get("h") is not None and b.get("l") is not None]
    if not valides or risque <= 0:
        return None

    def _spread(b) -> float:
        return float(b.get("s") or 0) * float(point or 0)

    if achat:
        haut = max(valides, key=lambda b: float(b["h"]))
        bas = min(valides, key=lambda b: float(b["l"]))
        mfe = (float(haut["h"]) - entry) / risque
        mae = (float(bas["l"]) - entry) / risque
    else:
        bas = min(valides, key=lambda b: float(b["l"]))
        haut = max(valides, key=lambda b: float(b["h"]))
        mfe = (entry - (float(bas["l"]) + _spread(bas))) / risque
        mae = (entry - (float(haut["h"]) + _spread(haut))) / risque
    return {"mfe_R": round(mfe, 2), "mae_R": round(mae, 2)}


def _parcours_en_R(trade: dict, destination_id: str | None) -> dict | None:
    """MFE / MAE du trade, en unités de risque, lus sur le CHEMIN réel du prix.

    ⛔ Sans le chemin, on ne sait pas distinguer une **perte franche** d'un
    **gain rendu** — et « aurait-on pu anticiper » n'a aucune réponse.
    `personal_trades` ne porte ni MFE ni MAE ; la seule source est `/rates` du
    courtier, qui rend les bougies M1 de la vie de la position.

    ⚠️ Le R est **interne à ce trade** (distance entrée↔stop d'origine) : on
    compare la position à elle-même, jamais deux populations entre elles.
    Cf. [[feedback_r_unit_trap]].

    ⚠️ **Rend `None` dès que quoi que ce soit manque.** Un bridge muet ne
    produit pas un zéro : le bloc disparaît du message plutôt que d'annoncer
    « 0,00 R », qui se lirait comme une mesure.
    """
    import json
    import os
    from datetime import datetime, timezone

    try:
        entry = float(trade.get("entry_price") or 0)
        sl = float(trade.get("stop_loss") or 0)
        risque = abs(entry - sl)
        if entry <= 0 or sl <= 0 or risque <= 0:
            return None
        achat = (trade.get("direction") or "").lower().startswith("b")

        def _t(v):
            d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

        debut, fin = _t(trade["created_at"]), _t(trade["closed_at"])

        from backend.services.destinations_registry import DESTINATIONS
        d = DESTINATIONS.get(destination_id or "")
        if d is None or d.bridge_type != "mt5":
            return None
        url = os.environ.get(d.url_env or "", "")
        if not url:
            return None
        entetes = {d.key_header: os.environ.get(d.key_env or "", "")}

        import urllib.parse
        import urllib.request

        symbole = _symbole_courtier(trade.get("pair"), destination_id)
        # ⛔ Le bridge coupe a MAX_BOUGIES et le DIT (`tronque`). Ignorer ce
        # drapeau mesurerait le DEBUT du trade en presentant le resultat comme
        # s'il portait sur toute sa vie — 3 trades sur 35 (positions crypto
        # tenues 40 jours). On remonte donc le pas jusqu'a couvrir la fenetre.
        #
        # ⚠️ Un pas plus large ne degrade PAS le MFE : le maximum des hauts
        # reste le maximum. Il ne degraderait que l'ORDRE intra-bougie — or
        # cet ordre ne se pose sur aucun trade mesure (0 bougie ambigue sur 35).
        for pas in ("M1", "M5", "M15", "H1"):
            q = urllib.parse.urlencode({
                "pair": symbole, "timeframe": pas,
                "from": debut.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": fin.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            rq = urllib.request.Request(f"{url.rstrip('/')}/rates?{q}",
                                        headers=entetes)
            # ⚠️ Court, et dans un `try` total : cet appel entre dans le flux de
            # clôture. Il n'a jamais le droit de retarder ni de casser la notif.
            with urllib.request.urlopen(rq, timeout=5) as r:
                charge = json.load(r) or {}
            if charge.get("tronque"):
                continue
            bougies = charge.get("bougies") or []
            if not bougies:
                return None
            r = _mfe_mae(bougies, entry, risque, achat,
                         point=charge.get("point") or 0.0)
            if r is not None:
                r["pas"] = pas
            return r
        # Aucun pas ne couvre la fenetre : mieux vaut pas de mesure qu'une
        # mesure partielle presentee comme entiere.
        return None
    except Exception as e:  # pragma: no cover - garde-fou du flux trade
        logger.debug(f"_parcours_en_R indisponible : {e}")
        return None


def _symbole_courtier(pair: str | None, destination_id: str | None) -> str:
    """Nom du symbole chez CE courtier. `WTI/USD` vaut `SpotCrude` chez l'un et
    `XTIUSD` chez l'autre ; le repli retire simplement la barre oblique."""
    defaut = (pair or "").replace("/", "")
    try:
        from backend.services import bridge_destinations as _bd
        for cfg in _bd.admin_destinations():
            if cfg.destination_id == destination_id and cfg.symbol_map:
                return cfg.symbol_map.get(pair, defaut)
    except Exception as e:  # pragma: no cover - garde-fou
        logger.debug(f"_symbole_courtier repli : {e}")
    return defaut


def _etat_du_stop(trade: dict) -> tuple[str, bool]:
    """Rend (phrase, risque_annule). Décrit ce que le stop a fait, ou se tait.

    ⛔ **Trois cas, pas deux.** Un stop remonté AU-DELÀ de l'entrée met le
    risque de la position à zéro : elle ne peut plus perdre. Si elle se ferme
    là, ce n'est pas une perte, c'est un trade **neutralisé avant d'avoir
    payé** — le coût exact que la gestion de sortie est soupçonnée d'infliger
    (−0,329 R sur l'or). Le ranger avec les stops ordinaires effacerait ce
    qu'on cherche à mesurer. Cf. [[project_edge_gestion_sorties_2026_08_11]].

    ⚠️ **Silence si le niveau vivant n'a pas été capturé.** Avant le
    2026-08-25 il n'existait pas, et le niveau d'origine s'est révélé faux
    dans 44 % des cas : affirmer « le stop n'avait pas bougé » sur cette base
    serait une devinette.
    """
    vif = trade.get("sl_at_close")
    origine = trade.get("stop_loss")
    if not trade.get("niveaux_source") or vif is None or not origine:
        return "", False
    entry = float(trade.get("entry_price") or 0)
    achat = (trade.get("direction") or "").lower().startswith("b")
    decimales = _decimales(trade.get("pair"))
    if abs(float(vif) - float(origine)) < 10 ** -(decimales + 1):
        return "le stop n'avait pas bougé depuis l'ouverture", False
    niveau = f"{float(vif):.{decimales}f}".replace(".", ",")
    au_dela = (float(vif) > entry) if achat else (float(vif) < entry)
    if au_dela and entry:
        # ⚠️ `*gras*` et non `**gras**` : le fil trades part en Markdown
        # LEGACY, où la double étoile ne se ferme pas.
        # Cf. [[feedback_telegram_legacy_markdown_bold]].
        return (f"le stop avait été remonté à {niveau}, *au-delà de "
                f"l'entrée* — la position était déjà neutralisée, sans risque "
                f"restant"), True
    return (f"le stop avait été déplacé à {niveau} : c'est le mécanisme qui a "
            f"fermé, pas le marché"), False


def _decimales(pair: str | None) -> int:
    return 2 if any(k in (pair or "") for k in (
        "XAU", "XAG", "BTC", "ETH", "SOL", "LTC", "BCH", "DOT", "ADA",
        "XRP", "WTI")) else 5


def _frais_de_portage(ticket) -> float | None:
    """Swap + commission + frais réellement facturés, lus chez le COURTIER.

    ⛔ Pourquoi ça compte. Une position tenue plusieurs nuits paie un coût de
    portage qui n'a rien d'anormal — mais qui creuse la perte au-delà du risque
    annoncé. Constaté le 25/08 : EUR/GBP tenu 4j19h, −4,64 € contre −3,30 €
    prévus. Annoncer « glissement ou trou de cotation » aurait fait chercher un
    défaut inexistant.

    `personal_trades` ne porte pas ces frais ; `broker_close_snapshots` si,
    depuis qu'on fige les réponses du courtier. Rend `None` si la ligne n'y est
    pas — auquel cas on ne conclut rien plutôt que de supposer zéro.
    """
    if not ticket:
        return None
    try:
        # ⚠️ Importé DANS la fonction, comme ailleurs dans ce module : le
        # `except` ci-dessous transformerait un `NameError` en « donnée
        # indisponible », exactement le piège qui a masqué `json` deux heures
        # plus tôt. Un test exécute cette fonction pour de vrai.
        import sqlite3

        from backend.services.trade_log_service import _DB_PATH
        with sqlite3.connect(str(_DB_PATH)) as c:
            r = c.execute(
                "SELECT COALESCE(swap,0) + COALESCE(commission,0) + "
                "COALESCE(fee,0) FROM broker_close_snapshots WHERE ticket=?",
                (int(ticket),)).fetchone()
        return float(r[0]) if r and r[0] is not None else None
    except Exception as e:  # pragma: no cover - garde-fou
        logger.debug(f"_frais_de_portage indisponible : {e}")
        return None


def _risque_annonce(trade: dict, destination_id: str | None):
    """Ce que l'ouverture avait annoncé, pour pouvoir comparer au réalisé."""
    from backend.services import destinations_registry as _reg, risk_eur
    d = _reg.get(destination_id)
    try:
        return risk_eur.calculer(
            pair=trade.get("pair") or "",
            entry=float(trade.get("entry_price") or 0),
            sl=float(trade.get("stop_loss") or 0),
            tp=float(trade.get("take_profit") or 0),
            volume=float(trade.get("size_lot") or 0),
            bridge_type=(d.bridge_type if d else "mt5"),
            eur_usd=risk_eur.taux_eur_usd(),
        )
    except Exception as e:  # pragma: no cover - garde-fou
        logger.debug(f"_risque_annonce indisponible : {e}")
        return None


def _format_close(trade: dict, destination_id: str | None = None) -> str:
    """Format vulgarisé fermeture : 'résultat + impact sur ton solde'.

    Réécrit 2026-06-13 pour parler au lambda.
    """
    from datetime import datetime, timezone, timedelta

    pair = trade.get("pair") or "?"
    pair_label = _PAIR_FR_LABEL.get(pair, pair)
    direction = (trade.get("direction") or "").lower()
    verb_open = "Acheté" if direction == "buy" else "Vendu"
    dir_mot = "ACHAT" if direction == "buy" else "VENTE"
    verb_close = "revendu" if direction == "buy" else "racheté"
    entry = float(trade.get("entry_price") or 0)
    exit_price = float(trade.get("exit_price") or 0)
    pnl = float(trade.get("pnl") or 0)
    close_reason = (trade.get("close_reason") or "UNKNOWN").upper()
    ticket = trade.get("mt5_ticket") or "—"

    # Header + impact compte
    if close_reason in ("TP1", "TP2"):
        outcome_icon = "✅"
        outcome_word = "Trade GAGNÉ"
        impact = "ton solde a augmenté"
        explain = "Objectif de gain atteint comme prévu."
    elif close_reason == "SL":
        outcome_icon = "❌"
        outcome_word = "Trade PERDU"
        impact = "ton solde a baissé"
        explain = "Le marché s'est retourné, le stop de sécurité a coupé la perte."
    elif close_reason == "TIMEOUT":
        outcome_icon = "⏱"
        outcome_word = "Trade clos au temps"
        impact = "ni gain ni perte significatifs"
        explain = "Le marché n'a pas bougé assez. Position libérée pour faire place à d'autres signaux."
    elif close_reason == "TRAILING_SL":
        outcome_icon = "📈"
        outcome_word = "Gain sécurisé par le stop suiveur"
        impact = "ton solde a augmenté"
        explain = (
            "Le marché est allé dans ton sens sans atteindre l'objectif. Le stop "
            "a suivi le prix pour verrouiller le gain, puis le marché s'est "
            "retourné : le stop a fermé en bénéfice."
        )
    elif close_reason == "BREAKEVEN":
        outcome_icon = "⚖️"
        outcome_word = "Trade clos à zéro"
        impact = "ni gain ni perte"
        explain = (
            "Le trade avait assez progressé pour ramener le stop au prix d'entrée. "
            "Le marché est revenu le chercher : sortie sans perte."
        )
    elif close_reason == "STOP_OUT":
        # ⚠️ Ce n'est PAS un stop-loss : c'est le courtier qui a liquidé faute
        # de marge. La sortie n'a pas été choisie. Cf. position or 08-10.
        outcome_icon = "🚨"
        outcome_word = "Position LIQUIDÉE par le courtier"
        impact = "ton solde a baissé"
        explain = (
            "Le compte n'avait plus assez de marge : le courtier a fermé la "
            "position de force, à son prix, pas au tien. Ce n'est pas ton stop "
            "qui a agi — il faut recharger le compte ou réduire l'exposition."
        )
    elif close_reason == "EXPERT":
        # Fermé par notre propre automatisation : /kill, prise partielle,
        # coupe-circuit. La cause EST établie — ne pas la ranger avec les
        # sorties inexpliquées.
        outcome_icon = "🤖"
        outcome_word = "Trade fermé par le radar"
        impact = ""
        explain = (
            "Ce n'est ni le stop ni l'objectif : c'est le système qui a décidé "
            "de sortir (prise partielle, mise en pause ou coupe-circuit)."
        )
    elif close_reason == "MANUAL":
        outcome_icon = "👋"
        outcome_word = "Trade fermé à la main"
        impact = "fermé manuellement"
        explain = "La position a été clôturée depuis MT5 — le radar n'a pas pris la décision."
    else:
        # ⚠️ Ne JAMAIS inventer une cause ici. Jusqu'au 2026-08-10, une sortie
        # non reconnue était annoncée comme « fermée à la main » : 215 sorties
        # du stop suiveur ont ainsi été attribuées à Xavier.
        outcome_icon = "🔚"
        outcome_word = "Trade fermé"
        impact = ""
        explain = "Cause de sortie non établie — à vérifier dans l'historique MT5."

    # Durée
    duration_str = "—"
    try:
        ca = trade.get("created_at")
        cb = trade.get("closed_at")
        if ca and cb:
            t0 = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(str(cb).replace("Z", "+00:00"))
            delta = t1 - t0
            mins = int(delta.total_seconds() / 60)
            if mins < 60:
                duration_str = f"{mins} min"
            elif mins < 24 * 60:
                duration_str = f"{mins // 60}h{mins % 60:02d}"
            else:
                duration_str = f"{mins // (24*60)}j{(mins % (24*60)) // 60}h"
    except Exception:
        pass

    pnl_sign = "+" if pnl >= 0 else "−"
    # Prix au format FR
    decimals = 2 if any(k in pair for k in ("XAU", "XAG", "BTC", "ETH", "SOL", "LTC", "BCH", "DOT", "ADA", "XRP", "WTI")) else 5
    entry_str = f"{entry:.{decimals}f}".replace(".", ",")
    exit_str = f"{exit_price:.{decimals}f}".replace(".", ",")

    # Pas de .capitalize() : il transformerait « TP1 » en « Tp1 ».
    sortie = {"TP1": "Objectif TP1 atteint", "TP2": "Objectif TP2 atteint",
              "SL": "Stop de sécurité touché", "TIMEOUT": "Clôturé au temps",
              "TRAILING_SL": "Stop suiveur déclenché", "BREAKEVEN": "Ramené à zéro",
              "STOP_OUT": "Liquidé par le courtier", "INDETERMINE": "Cause non établie",
              "EXPERT": "Fermé par le radar",
              "MANUAL": "Fermé à la main"}.get(close_reason, "Sortie inconnue")
    broker = destination_label(destination_id, "mode") if destination_id else None
    pnl_fr = f"{abs(pnl):.2f}".replace(".", ",")
    titre = f"{outcome_icon} *{pnl_sign}{pnl_fr} €* · {dir_mot} {pair_label}"
    if broker:
        titre += f" · {broker}"
    lines = [titre]

    # ── Ligne miroir. L'ouverture annonce « Risque −X € → Objectif +Y € » ;
    # la clôture répond sur la même ligne, pour que les deux messages se
    # lisent ensemble dans le fil.
    perte = pnl < 0
    montants = _risque_annonce(trade, destination_id)
    prevu = None
    if montants:
        prevu = montants["risque_eur"] if perte else montants["gain_eur"]
    if prevu is not None:
        prevu_fr = f"{abs(prevu):.2f}".replace(".", ",")
        lines.append(f"Prévu *{'−' if perte else '+'}{prevu_fr} €*  →  "
                     f"Réalisé *{pnl_sign}{pnl_fr} €*")
    lines.append("")

    # ── Le plan et son issue, même grammaire que l'ouverture.
    detail = [f"Entrée {entry_str} → {exit_str}"]
    if trade.get("size_lot"):
        detail.append(f"{trade.get('size_lot')} lot".replace(".", ","))
    detail.append(duration_str)
    # ⚠️ R = pnl / risque en EUROS, jamais déduit du prix de sortie : une
    # position fermée en deux fois n'a pas un prix de sortie unique, et le
    # reliquat seul sous-estime précisément les trades bien gérés.
    # Cf. [[project_edge_gestion_sorties_2026_08_11]].
    if montants and montants.get("risque_eur"):
        # Le vrai signe moins, comme sur les montants en euros juste au-dessus :
        # le trait d'union se lit plus court et casse l'alignement visuel.
        detail.append(f"{pnl / montants['risque_eur']:+.2f} R"
                      .replace(".", ",").replace("-", "−"))
    lines.append(" · ".join(detail))
    lines.append("")

    # ── 🔎 Pourquoi c'est fermé
    phrase_stop, _annule = _etat_du_stop(trade)
    pourquoi = [f"• {sortie}" + (f" — {phrase_stop}" if phrase_stop else "")]
    # `explain` décrit le marché ; il contredirait la phrase du stop quand
    # c'est le mécanisme qui a fermé. On ne garde qu'une seule explication.
    if not phrase_stop or "n'avait pas bougé" in phrase_stop:
        pourquoi.append(f"• {explain}")

    parcours = _parcours_en_R(trade, destination_id)
    if parcours is not None:
        mfe = parcours.get("mfe_R")
        if mfe is not None:
            mfe_fr = f"{mfe:+.2f}".replace(".", ",")
            if mfe >= 0.25 and perte:
                pourquoi.append(
                    f"• Le trade est monté à {mfe_fr} R avant de se retourner "
                    f"— c'est un gain rendu, pas une entrée ratée")
            elif mfe >= 0.25:
                # ⚠️ Pas de « avant de se retourner » sur un gain : un TP
                # atteint ne s'est pas retourné, il a touché sa cible. Le point
                # haut y mesure ce qui restait sur la table, pas un échec.
                pourquoi.append(f"• Au plus haut : {mfe_fr} R")
            elif perte:
                pourquoi.append(
                    f"• Il n'est jamais passé au vert (au mieux {mfe_fr} R) : "
                    f"l'entrée était contre le marché dès le départ")
    lines.append("🔎 *Pourquoi c'est fermé ?*")
    lines.extend(pourquoi)
    lines.append("")

    # ── 🎯 Anticipable ? — sur les pertes seulement.
    #
    # ⛔ CE BLOC NE DOIT RIEN INVENTER. Le contrôle aléatoire a mesuré
    # Δ = +0,004 R sur 29 000 trades : il n'y a pas d'edge à la sélection
    # d'entrée, et le score est anti-prédictif dans la bande 60-65. Écrire
    # « le score était bas, on aurait pu se méfier » fabriquerait une
    # causalité rétrospective. La réponse honnête est le plus souvent
    # « non, et c'est mesuré ».
    # Cf. [[project_controle_aleatoire_verdict_2026_08_05]] ·
    #     [[feedback_v1_score_anti_predictive_60_65]]
    if perte:
        juge = []
        if montants and montants.get("risque_eur"):
            annonce = f"{montants['risque_eur']:.2f}".replace(".", ",")
            depassement = abs(pnl) - montants["risque_eur"]
            if depassement <= montants["risque_eur"] * 0.15:
                juge.append(f"• Perte conforme au risque annoncé (−{annonce} € "
                            f"prévu) — c'est le risque assumé à l'entrée")
            else:
                # ⚠️ Le coût de portage EXPLIQUE souvent le dépassement sur une
                # position tenue plusieurs nuits. Le présenter comme un
                # glissement ferait chercher un défaut qui n'existe pas — mais
                # il ne doit pas devenir l'excuse universelle : on ne l'invoque
                # que s'il couvre vraiment l'écart.
                frais = _frais_de_portage(trade.get("mt5_ticket"))
                if frais is not None and abs(frais) >= depassement * 0.6:
                    frais_fr = f"{abs(frais):.2f}".replace(".", ",")
                    juge.append(f"• Perte au-delà des −{annonce} € prévus, mais "
                                f"expliquée : {frais_fr} € de frais de portage "
                                f"(swap) sur la durée — rien d'anormal")
                else:
                    juge.append(f"• ⚠️ Perte *au-delà* du risque annoncé "
                                f"(−{annonce} € prévu) : glissement ou trou de "
                                f"cotation, ça mérite un coup d'œil")
        conf = trade.get("signal_confidence")
        if conf is not None:
            juge.append(f"• Score IA {float(conf):.0f}/100 — mesuré *sans "
                        f"pouvoir prédictif*, n'en tirer aucun signal")
        if juge:
            lines.append("🎯 *Anticipable ?*")
            lines.extend(juge)
            lines.append("")

    lines.append(f"`#{ticket}`")
    return "\n".join(lines)


def _canal_trade(destination_id: str | None) -> tuple[str, list]:
    """Rend ``(jeton_bot, destinataires)`` pour une notification de trade.

    ⛔ Cette fonction portait sa PROPRE table — la troisième du dépôt :

        admin_live          -> TRADES_TELEGRAM_BOT_TOKEN
        toute autre         -> TELEGRAM_BOT_TOKEN

    Or `TRADES_*` est le bot nommé « KRAKEN Trades » et `TELEGRAM_*` le bot
    « DEMO Trades ». Les ouvertures du compte réel IC Markets partaient donc
    dans le fil Kraken, et celles de Kraken dans le fil démo. Le canal vient
    désormais de `canaux_telegram`, seul module qui sache faire d'un compte un
    fil.

    ⚠️ Un seul destinataire, jamais `_destinataires()` : ce dernier boucle sur
    `TELEGRAM_CHATS` pour servir les clients. Y envoyer les trades d'un de nos
    comptes les leur ferait parvenir le jour où ils y seraient inscrits — et
    `TELEGRAM_CHATS` étant vide aujourd'hui, rien ne le révélerait avant qu'il
    ne soit trop tard. Cette garde valait pour le seul fil du compte réel ;
    elle vaut désormais pour tous.

    ⚠️ Repli sur le fil infra si le fil du compte n'est pas gréé — jamais sur
    les destinataires clients, et jamais sur un autre fil de compte, qui
    attribuerait le trade au mauvais compte.
    """
    from backend.services import canaux_telegram as ct

    canal = ct.canal_pour(destination_id)
    jeton, chat = ct.jeton_et_chat(canal)
    if jeton and chat:
        # `__any__` et non un pseudo-utilisateur : évite la recherche de mode
        # silencieux, qui n'a pas de sens pour un fil d'administration.
        return jeton, [("__any__", chat)]

    jeton, chat = ct.jeton_et_chat("infra")
    if jeton and chat:
        logger.warning(
            "_canal_trade: fil %s non gréé pour %s — repli sur infra",
            canal, destination_id)
        return jeton, [("__any__", chat)]

    logger.error("_canal_trade: aucun fil gréé, même infra — %s", destination_id)
    return TELEGRAM_BOT_TOKEN, []


async def send_close(trade: dict) -> None:
    """Push une notification de fermeture sur le canal user-facing.

    Filtre : pair stars-only + LIVE_EXTRA_PAIRS (forex majors autorisés pour
    le Live IC Markets depuis 2026-06-12). Avant cette date, forex EUR/USD,
    GBP/USD, USD/JPY etaient skipped car non-stars → user ne voyait jamais
    la cloture de ses trades Live forex.

    Dedup en mémoire par mt5_ticket — reset au reboot (peu grave, pire cas
    re-notif au redémarrage si un trade vient de fermer).
    """
    pair = trade.get("pair")
    ticket = trade.get("mt5_ticket")
    cle = str(ticket) if ticket else None
    if cle and cle in _notified_closes:
        return
    if cle:
        _notified_closes.add(cle)

    # Argent réel uniquement, comme à l'ouverture. `personal_trades` ne porte
    # pas la destination : on la résout depuis `mt5_pushes` via le ticket.
    dest_close = destination_for_ticket(ticket)
    if not destination_is_real_money(dest_close):
        logger.debug(f"send_close: ticket {ticket} ({dest_close}) hors argent réel — skip")
        return

    text = _format_close(trade, dest_close)

    # ⚠️ Un miroir vers le canal sales existait ici (2026-08-02) : chaque
    # clôture partait DEUX fois, sur deux canaux, dans le même format. Il
    # servait à contourner le filtre stars pour les paires non-stars — un
    # contournement devenu inutile depuis que l'argent réel court-circuite ce
    # filtre juste en dessous. Supprimé le 2026-08-04 : une clôture est un
    # évènement de trade, elle appartient au seul canal des trades. Le canal
    # sales porte le récap, pas le flux.

    # Canal des trades : filtre stars pour les customers, argent réel exempté.
    if not is_configured():
        return
    try:
        from config.settings import MT5_BRIDGE_LIVE_EXTRA_PAIRS as _live_extras
    except Exception:
        _live_extras = frozenset()
    # Le filtre stars protège les notifications user-facing des customers.
    # Il ne doit PAS s'appliquer à de l'argent réel : l'ouverture est notifiée
    # pour toute destination réelle, la clôture était filtrée aux stars. On
    # recevait donc « trade ouvert BTC » sans jamais « trade fermé BTC », alors
    # que c'est la clôture qui porte le résultat. Constaté le 2026-08-04 sur
    # une perte réelle Kraken.
    allowed_pairs = _STAR_PAIRS_SET | _live_extras
    if pair not in allowed_pairs and not destination_is_real_money(dest_close):
        return
    jeton, destinataires = _canal_trade(dest_close)
    if not destinataires:
        return
    url = TELEGRAM_API.format(token=jeton)
    for user, chat_id in destinataires:
        if user != "__any__" and trade_log_service.silent_mode_active_for_user(user):
            continue
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                })
                if response.status_code != 200:
                    logger.warning(f"Telegram close erreur {response.status_code} pour {user}: {response.text[:200]}")
                else:
                    logger.info(f"Close Telegram envoye a {user} pour {pair} ticket={ticket}")
        except Exception as e:
            logger.warning(f"Erreur envoi close Telegram {user}: {e}")


# ─── Refonte notifs user (2026-06-10) ────────────────────────────────
# Suite à la demande user du 2026-06-10 minuit : virer les push setup
# verbeux (TELEGRAM_SETUP_VERDICTS="" en .env coupe send_setup) et envoyer
# uniquement des notifs actionnables :
#   - send_trade_opened : confirme un fill broker réussi
#   - send_close       : (déjà existant) confirme une clôture
#   - send_veto_alert  : 1er match d'une règle veto dans la journée
#   - send_pac_transition_user : changement d'état AUTO_EXEC/PAUSED/etc.
#   - send_daily_recap : récap 23h59 Paris (PnL + scope + transitions + vetos)

# Dedup en mémoire pour la notif veto : 1 push max par (date, rule_id, pair)
_veto_notified_today: set[tuple[str, str, str]] = set()


# Pattern → texte vulgarisé (1 phrase courte, < 110 chars pour rentrer en mobile).
# Indexé par string PatternType.value pour pouvoir être appelé à la close
# (le dict trade ne contient qu'une string signal_pattern, pas l'enum).
_PATTERN_FR_SHORT: dict[str, str] = {
    "breakout_up": "Cassure de résistance — accélération haussière probable.",
    "breakout_down": "Cassure de support — accélération baissière probable.",
    "momentum_up": "Élan acheteur (plusieurs bougies vertes successives).",
    "momentum_down": "Élan vendeur (plusieurs bougies rouges successives).",
    "range_bounce_up": "Rebond sur support — entrée bas dans une zone d'achat.",
    "range_bounce_down": "Rejet sur résistance — entrée haut dans une zone de vente.",
    "mean_reversion_up": "Retour à la moyenne — prix trop bas, rebond attendu.",
    "mean_reversion_down": "Retour à la moyenne — prix trop haut, baisse attendue.",
    "engulfing_bullish": "Englobante haussière — retournement à la hausse probable.",
    "engulfing_bearish": "Englobante baissière — retournement à la baisse probable.",
    "pin_bar_up": "Pin bar haussière — rejet violent du prix bas.",
    "pin_bar_down": "Pin bar baissière — rejet violent du prix haut.",
}


def _build_trade_justification(pattern_value, confidence_score, pair: str | None = None) -> list[str]:
    """Retourne 0-4 lignes vulgarisées expliquant pourquoi le radar a pris ce trade.

    Args:
        pattern_value: string PatternType.value (ex: "breakout_up") ou None
        confidence_score: score IA 0-100 ou None
        pair: ex "BTC/USD" — active la ligne sentiment crypto si pair crypto

    Renvoie une liste de lignes Markdown prête à splice dans le message.
    Liste vide si rien d'exploitable (silencieux, pas de bruit user).
    """
    lines: list[str] = []
    pat_text = None
    if pattern_value:
        key = str(pattern_value).lower()
        pat_text = _PATTERN_FR_SHORT.get(key)
    if not pat_text and confidence_score is None:
        return lines
    lines.append("📊 *Pourquoi ce trade ?*")
    if pat_text:
        lines.append(f"• {pat_text}")
    if confidence_score is not None:
        try:
            score = float(confidence_score)
        except (TypeError, ValueError):
            score = None
        if score is not None:
            if score >= 75:
                qual = "signal fort"
            elif score >= 65:
                qual = "signal correct"
            else:
                qual = "signal limite"
            lines.append(f"• Score IA : *{score:.0f}/100* ({qual})")
    # Climat de marché tiré du VIX (indice du stress des marchés US, proxy
    # cross-asset). Silencieux si data non disponible ou périmée.
    try:
        from backend.services import vix_service as _vix
        d = _vix.get_current()
        if d.get("available") and d.get("is_fresh"):
            v = float(d["value"])
            if v < 15:
                climate = "calme (peu de stress)"
            elif v < 25:
                climate = "normal"
            elif v < 35:
                climate = "tendu (stress modéré)"
            else:
                climate = "panique"
            lines.append(f"• Climat de marché : *{climate}* (VIX {v:.1f})")
    except Exception:
        pass
    # Sentiment crypto (alternative.me F&G) — pertinent uniquement BTC/ETH/altcoins.
    # Silencieux si pair non crypto ou cache périmé (>2 jours).
    if pair:
        try:
            from backend.services import crypto_fear_greed_service as _cfg
            feats = _cfg.get_features(pair)
            if feats.get("cfg_available"):
                v = float(feats.get("cfg_value") or 0)
                if v < 25:
                    label = "peur extrême (souvent fond de marché)"
                elif v < 50:
                    label = "peur"
                elif v < 75:
                    label = "optimisme"
                else:
                    label = "euphorie (souvent top de marché)"
                lines.append(f"• Sentiment crypto : *{label}* (F&G {v:.0f}/100)")
        except Exception:
            pass
    return lines


def _montants_du_trade(setup, volume: float, destination_id: str | None):
    """Risque et gain en euros pour le volume réellement envoyé au broker.

    Retourne ``None`` si le calcul est indéterminable — auquel cas le bloc
    monétaire est omis. Un montant faux serait pire qu'un montant absent :
    il serait lu comme vrai.
    """
    from backend.services import destinations_registry as _reg, risk_eur

    d = _reg.get(destination_id)
    try:
        return risk_eur.calculer(
            pair=getattr(setup, "pair", ""),
            entry=float(getattr(setup, "entry_price", 0) or 0),
            sl=float(getattr(setup, "stop_loss", 0) or 0),
            tp=float(getattr(setup, "take_profit_1", 0) or 0),
            volume=float(volume or 0),
            bridge_type=(d.bridge_type if d else "mt5"),
            eur_usd=risk_eur.taux_eur_usd(),
        )
    except Exception as e:  # pragma: no cover - garde-fou
        logger.debug(f"_montants_du_trade indisponible : {e}")
        return None


def _unite_de_volume(setup, destination_id: str | None) -> str:
    """Unité dans laquelle le volume est exprimé, selon le broker.

    MT5 raisonne en lots ; les exchanges crypto envoient une quantité dans
    l'actif de base. Écrire « 0,0023 lot » pour 0,0023 BTC était faux, et
    faux d'un facteur qui dépend du contrat.
    """
    from backend.services import destinations_registry as _reg
    d = _reg.get(destination_id)
    if d is None or d.bridge_type == "mt5":
        return "lot"
    base = str(getattr(setup, "pair", "") or "").split("/")[0].strip().upper()
    return base or "unité"


def _format_trade_opened(
    setup, ticket: int | str, fill_price: float, volume: float,
    mode: str, destination_id: str | None = None,
) -> str:
    """Format vulgarisé : 'qu'est-ce qui se passe, combien je gagne/perds, pourquoi'.

    Réécrit 2026-06-13 pour parler au lambda (cf. memo
    feedback_telegram_messages_vulgarized_2026_06_13).

    2026-06-18 fix : "LIVE (argent réel)" ne dépend plus du `mode` du
    bridge (toujours "live" en exécution réelle, qu'on tape sur Demo
    Pepperstone ou Live IC Markets), mais du destination_id.

    ⛔ Cette note affirmait « seul `admin_live` = argent réel ». C'est FAUX :
    Kraken en engage aussi. C'est cette croyance qui avait fait afficher
    « Démo » sur des trades Kraken réels. Le libellé vient du registre, via
    `destination_label()` — jamais d'une liste recopiée ici.
    """
    from datetime import datetime, timezone, timedelta
    dir_value = setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction)
    dir_word = "ACHAT" if dir_value == "buy" else "VENTE"
    pair_label = _PAIR_FR_LABEL.get(setup.pair, setup.pair)
    paris_now = datetime.now(timezone.utc) + timedelta(hours=2)
    time_str = paris_now.strftime("%H:%M")
    # Label broker + statut. destination_id discrimine :
    # - admin_live   = IC Markets, argent réel (le seul vrai LIVE)
    # - admin_legacy = Pepperstone, compte Démo
    # - admin_binance = Binance USDⓈ-M testnet (shadow R&D)
    # - user:N        = Premium user (bridge MT5 Démo Pepperstone côté EA)
    # Source unique : DESTINATION_LABELS. L'ancienne chaîne if/elif ne
    # couvrait pas Kraken, dont les trades s'affichaient donc « Démo »
    # alors qu'ils engagent de l'argent réel.
    mode_label = destination_label(destination_id, "mode")

    # Prix au format FR (virgule, 2 décimales pour métaux/crypto, 5 pour forex)
    decimals = 2 if any(k in setup.pair for k in ("XAU", "XAG", "BTC", "ETH", "SOL", "LTC", "BCH", "DOT", "ADA", "XRP", "WTI")) else 5
    fill_str = f"{fill_price:.{decimals}f}".replace(".", ",")

    # Ligne 1 : QUOI. Ligne 2 : COMBIEN. Le reste est du détail consultable.
    # Le broker figure une seule fois, dans le titre — il y était répété trois
    # fois auparavant, et le montant n'arrivait qu'en quatrième position.
    lines = [f"🟢 *{dir_word} {pair_label}* · {mode_label}"]

    # Montants calculés sur le volume RÉELLEMENT exécuté (2026-08-04).
    # Ils venaient d'une table statique « pour 0,01 lot », sans lien avec
    # l'ordre envoyé : deux fois trop petits sur MT5 à 0,02 lot, et sans
    # signification sur Kraken — le premier trade réel annonçait « Risque
    # −0,01 € » pour environ 0,57 € engagés.
    montants = _montants_du_trade(setup, volume, destination_id)
    if montants is not None and montants.get("risque_eur") is not None:
        perte_fr = f"{montants['risque_eur']:.2f}".replace(".", ",")
        gain_fr = f"{montants['gain_eur']:.2f}".replace(".", ",")
        lines.append(f"Risque *−{perte_fr} €*  →  Objectif *+{gain_fr} €*")
    elif montants is not None:
        # ⛔ Sur une paire croisée sans taux connu, la conversion en euros est
        # indécidable. On dit le R:R, qui reste JUSTE — numérateur et
        # dénominateur sont dans la même devise, elle s'annule — plutôt qu'un
        # montant approché qui serait lu comme vrai. C'est ce défaut-là qui
        # annonçait « Risque −909,09 € » pour 5,82 € engagés sur USD/JPY.
        lines.append(
            f"Rapport gain/risque *{montants['rr']:.2f}*  ·  montant en euros "
            f"indisponible ({montants.get('devise_cotation') or '?'})")
    lines.append("")

    # Le plan complet : ces trois valeurs manquaient au message.
    detail = [f"Entrée {fill_str}"]
    if volume:
        unite = _unite_de_volume(setup, destination_id)
        detail.append(f"{volume:g} {unite}".replace(".", ","))
    try:
        sl = float(getattr(setup, "stop_loss", 0) or 0)
        tp = float(getattr(setup, "take_profit_1", 0) or 0)
        if sl:
            detail.append(f"SL {sl:.{decimals}f}".replace(".", ","))
        if tp:
            detail.append(f"TP {tp:.{decimals}f}".replace(".", ","))
    except (TypeError, ValueError):
        pass
    lines.append(" · ".join(detail))
    lines.append("")

    # Justification du trade (pattern + score IA), vulgarisée
    try:
        pat_val = setup.pattern.pattern.value if hasattr(setup.pattern.pattern, "value") else str(setup.pattern.pattern)
    except AttributeError:
        pat_val = None
    just_lines = _build_trade_justification(
        pat_val,
        getattr(setup, "confidence_score", None),
        pair=getattr(setup, "pair", None),
    )
    if just_lines:
        lines.extend(just_lines)
        lines.append("")

    lines.append("ℹ️ Le radar a lancé un ordre auto chez ton broker. Le trade tourne seul jusqu'à toucher son objectif ou son stop.")
    lines.append("")
    # Le broker est déjà dans le titre : le pied porte la référence et l'heure.
    lines.append(f"`#{ticket}` · {time_str}")
    return "\n".join(lines)


async def send_trade_opened(
    setup, ticket: int | str, fill_price: float, volume: float,
    mode: str, destination_id: str | None = None,
) -> None:
    """Push une notif user-facing à la confirmation d'un fill broker.

    Appelée depuis ``mt5_bridge._push_to_destination`` après status 200.
    Le ticket vient de la réponse bridge.
    ``destination_id`` discrimine admin_live (argent réel) du reste.
    Best-effort : toute exception silencieuse, ne casse jamais le flow trade.
    """
    if not is_configured():
        return
    # ⛔ Le démo était EXCLU depuis le 2026-08-04, au motif qu'il « doublait le
    # volume du canal sans rien engager ». C'était vrai quand tout partageait
    # UN SEUL fil. Depuis le découpage par compte du 06/09, le démo a le sien :
    # le motif de l'exclusion a disparu avec la cause.
    #
    # ⚠️ On n'annonce que nos comptes de trading. Un `user:2` ou une
    # destination inconnue atterrirait sur `infra`, où le message se lirait
    # comme un trade de la maison.
    from backend.services.canaux_telegram import est_un_compte_de_trading
    if not est_un_compte_de_trading(destination_id):
        logger.debug(f"send_trade_opened: {destination_id} n'est pas un compte "
                     f"de trading — skip")
        return
    try:
        text = _format_trade_opened(
            setup, ticket, fill_price, volume, mode,
            destination_id=destination_id,
        )
        jeton, destinataires = _canal_trade(destination_id)
        url = TELEGRAM_API.format(token=jeton)
        for user, chat_id in destinataires:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(url, json={
                        "chat_id": chat_id, "text": text,
                        "parse_mode": "Markdown", "disable_web_page_preview": True,
                    })
                    if r.status_code != 200:
                        logger.warning(f"Telegram trade_opened {r.status_code}: {r.text[:200]}")
            except Exception as e:
                logger.warning(f"Erreur envoi trade_opened {user}: {e}")
    except Exception as e:
        logger.warning(f"send_trade_opened error: {e}")


async def send_veto_alert(pair: str, direction: str, rules_matched: list[str], reasons: list[str]) -> None:
    """Push une alerte user au 1er match veto géopolitique du jour pour
    (pair, rule). Dedup en mémoire par (date_iso, rule_id, pair) — évite le
    spam si la même règle déclenche plusieurs cycles.
    """
    if not is_configured() or not rules_matched:
        return
    from datetime import date
    today_iso = date.today().isoformat()
    new_rules = []
    for rule_id in rules_matched:
        key = (today_iso, rule_id, pair)
        if key in _veto_notified_today:
            continue
        _veto_notified_today.add(key)
        new_rules.append(rule_id)
    if not new_rules:
        return
    try:
        # Vulgarisation des noms de règles techniques (2026-06-13)
        _RULE_FR = {
            "FED_HAWKISH": "Fed (banque centrale US) en mode restrictif",
            "GDELT_STRESS": "Climat géopolitique stressé (actualité internationale)",
            "POLYMARKET_RISK": "Marché prédictif signale un risque imminent",
            "TARIFF": "Annonce de hausse de tarifs douaniers",
            "ECB_HAWKISH": "BCE (banque centrale Europe) en mode restrictif",
        }
        import html as _html
        pair_label = _PAIR_FR_LABEL.get(pair, pair)
        rules_friendly = [_RULE_FR.get(r, r) for r in new_rules]
        causes_str = "\n".join(f"• {_html.escape(r)}" for r in rules_friendly[:3])
        # HTML depuis 2026-08-02 : Markdown legacy cassait sur les parenthèses /
        # apostrophes / underscores des règles vulgarisées (HTTP 400 "can't parse
        # entities at byte offset 131/132"). html.escape neutralise <>& variables.
        text = (
            f"🌍 <b>Trades suspendus</b> · {_html.escape(pair_label)} ({_html.escape(pair)})\n"
            f"\n"
            f"⚠️ Le contexte macro est trop tendu pour trader sereinement.\n"
            f"Cause(s) :\n{causes_str}\n"
            f"\n"
            f"ℹ️ Le radar surveille l'actualité économique et géopolitique en continu. "
            f"Si ça devient risqué, il bloque les trades pour te protéger.\n"
            f"\n"
            f"🔁 Reprise auto dès que la situation se calme — rien à faire de ton côté."
        )
        destinataires = _destinataires()
        url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
        for user, chat_id in destinataires:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(url, json={
                        "chat_id": chat_id, "text": text,
                        "parse_mode": "HTML", "disable_web_page_preview": True,
                    })
                    if r.status_code != 200:
                        logger.warning(f"Telegram veto_alert {r.status_code}: {r.text[:200]}")
            except Exception as e:
                logger.warning(f"Erreur envoi veto_alert {user}: {e}")
    except Exception as e:
        logger.warning(f"send_veto_alert error: {e}")


# Caractères actifs du Markdown legacy de Telegram (parse_mode="Markdown").
# Un seul d'entre eux, non apparié, dans un texte libre interpolé à
# l'intérieur d'une entité (`*gras*`, `_italique_`) fait échouer TOUT le
# message avec un 400 « can't parse entities ».
_MD_LEGACY_ACTIFS = {"_": "-", "*": "·", "`": "'", "[": "(", "]": ")"}


def md_safe(text: str | None) -> str:
    """Neutralise les caractères Markdown actifs d'un texte libre.

    ⚠️ **Corrigé le 2026-08-04.** Les raisons de transition d'admission sont
    interpolées dans `_Raison : ...._` — or elles contiennent presque toujours
    un underscore : `pnl_pct`, `_not_admitted`, `auto_demote`,
    `VALID_DESTINATIONS`. Telegram renvoyait alors un 400, l'exception était
    avalée par le `try/except` best-effort, et **la notification utilisateur
    était perdue en silence**.

    Concrètement, le message qui a rétrogradé trois paires equity le
    2026-08-04 (`auto-demote: pnl_pct -103.71`) n'est jamais arrivé.

    On substitue plutôt qu'on échappe : l'échappement par antislash du
    Markdown legacy est notoirement peu fiable à l'intérieur d'une entité.
    """
    if not text:
        return ""
    return "".join(_MD_LEGACY_ACTIFS.get(c, c) for c in str(text))

async def send_pac_transition_user(pair: str, direction: str | None, from_state: str | None, to_state: str, reason: str) -> None:
    """DÉSACTIVÉE (2026-08-04) — les transitions vont au récap quotidien.

    Le moteur d'admission produit ~26 changements d'état par jour, envoyés
    en double sur les canaux user et infra : 52 messages quotidiens sur
    lesquels aucune décision n'est prise dans l'instant.

    L'information n'est pas perdue — `pair_admission_state` garde
    l'historique complet et le récap en donne la synthèse.

    Conservée en no-op documenté plutôt que supprimée : le point d'appel
    resservira si l'on veut un jour notifier les seules transitions vers
    AUTO_EXEC, qui elles engagent de l'argent.
    """
    return

async def send_daily_recap() -> None:
    """Récap 23h59 Paris : PnL du jour + scope auto-exec + transitions du jour + vetos.

    Cron job appelé depuis scheduler.py via CronTrigger(timezone="Europe/Paris",
    hour=23, minute=59). Le récap couvre la fenêtre Paris [00:00 → 23:59] du jour.
    Best-effort : toute erreur SQL → message minimal sans crash.
    """
    if not is_configured():
        return
    try:
        from datetime import datetime, timezone, timedelta
        import sqlite3
        from backend.services.trade_log_service import _DB_PATH

        paris_now = datetime.now(timezone.utc) + timedelta(hours=2)
        today_paris = paris_now.date().isoformat()
        today_label = paris_now.strftime("%d/%m/%Y")

        con = sqlite3.connect(str(_DB_PATH))
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # PnL du jour (Xavier auto)
        pnl_row = cur.execute(
            """SELECT COUNT(*) n, COALESCE(SUM(pnl),0) pnl,
                      SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) wins,
                      SUM(CASE WHEN pnl<0 THEN 1 ELSE 0 END) losses
               FROM personal_trades
               WHERE is_auto=1 AND status='CLOSED'
                 AND DATE(closed_at)=DATE(?)""",
            (today_paris,),
        ).fetchone()

        # Scope auto-exec : la table pair_admission_state est append-only
        # (insert à chaque transition), donc filtrer state='AUTO_EXEC' direct
        # remonte aussi les paires qui ONT ÉTÉ AUTO_EXEC un jour. Il faut
        # joindre sur MAX(id) par (pair, direction) pour avoir l'état courant.
        scope_rows = cur.execute(
            """SELECT pas.pair, pas.direction
               FROM pair_admission_state pas
               JOIN (
                   SELECT pair, direction, MAX(id) AS max_id
                   FROM pair_admission_state
                   GROUP BY pair, direction
               ) t
                 ON pas.pair = t.pair
                AND IFNULL(pas.direction,'') = IFNULL(t.direction,'')
                AND pas.id = t.max_id
               WHERE pas.state = 'AUTO_EXEC' AND pas.direction IS NOT NULL
               ORDER BY pas.pair, pas.direction"""
        ).fetchall()

        # Transitions du jour
        trans_rows = cur.execute(
            """SELECT pair, direction, state, reason
               FROM pair_admission_state
               WHERE DATE(state_since)=DATE(?)
                 AND transitioned_by != 'auto:backfill'
               ORDER BY state_since DESC LIMIT 15""",
            (today_paris,),
        ).fetchall()

        # Vetos du jour
        veto_row = cur.execute(
            """SELECT COUNT(*) n FROM signal_rejections
               WHERE reason_code='geopolitical_veto'
                 AND DATE(created_at)=DATE(?)""",
            (today_paris,),
        ).fetchone()

        con.close()

        # Format
        lines = [f"📊 *Récap du {today_label}*", ""]
        n = pnl_row["n"] or 0
        if n > 0:
            pnl = pnl_row["pnl"] or 0
            wins = pnl_row["wins"] or 0
            losses = pnl_row["losses"] or 0
            emoji = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪")
            lines.append(f"{emoji} *PnL du jour : {pnl:+.2f} $*")
            wr = (100.0 * wins / n) if n > 0 else 0
            lines.append(f"   {n} trades clôturés · {wins} gagnants / {losses} perdants · WR {wr:.0f}%")
        else:
            lines.append("💤 Aucun trade clôturé aujourd'hui.")

        lines.append("")
        lines.append(f"📋 *Scope auto-exec* ({len(scope_rows)} paires actives) :")
        if scope_rows:
            for r in scope_rows[:20]:
                lines.append(f"   • {r['pair']} {r['direction']}")
        else:
            lines.append("   _(aucune paire AUTO_EXEC)_")

        if trans_rows:
            lines.append("")
            lines.append(f"🔄 *Transitions du jour* ({len(trans_rows)})")
            for r in trans_rows[:8]:
                reason_short = (r["reason"] or "")[:60]
                dir_str = r["direction"] or "*"
                lines.append(f"   • {r['pair']} {dir_str} → *{r['state']}* — {reason_short}")
        else:
            lines.append("")
            lines.append("🔄 Pas de transition PAC aujourd'hui.")

        n_veto = veto_row["n"] or 0
        lines.append("")
        if n_veto > 0:
            lines.append(f"🌍 *{n_veto} setup(s) bloqué(s) par veto géopolitique aujourd'hui.*")
        else:
            lines.append("🌍 Aucun veto géopolitique aujourd'hui.")

        await send_text("\n".join(lines))

    except Exception as e:
        logger.warning(f"send_daily_recap error: {e}")
