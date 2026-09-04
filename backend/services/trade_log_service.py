"""Journal des trades personnels du user + mode silencieux journalier.

Distinct du backtest_service (qui track les signaux theoriques du radar).
Ici on enregistre les trades REELLEMENT pris par l'utilisateur, avec
son entry/SL/TP reels et ses notes.

SQLite persistant. Schema simple pour debuter.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, date, timezone
from pathlib import Path

from config.settings import DAILY_LOSS_LIMIT_PCT, TRADING_CAPITAL

logger = logging.getLogger(__name__)

_DB_PATH = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _init_schema() -> None:
    """Crée/migre le schéma SQLite.

    Ordre critique : on crée d'abord les TABLES (sans les INDEX), puis on
    migre les colonnes manquantes sur les bases existantes, et SEULEMENT
    ENSUITE on pose les INDEX (qui référencent ces colonnes).

    Avant ce fix : sur une DB pré-migration (sans colonne `user`), le
    `CREATE INDEX ... ON personal_trades(user)` du executescript plantait
    avec "no such column: user" et empêchait tout le reste de tourner.
    """
    with _conn() as c:
        # 1) Créer les tables si elles n'existent pas (no-op sur DB ancienne)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS personal_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL DEFAULT 'anonymous',
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                size_lot REAL NOT NULL,
                signal_pattern TEXT,
                horizon TEXT,
                source TEXT,
                signal_confidence REAL,
                checklist_passed INTEGER DEFAULT 0,
                notes TEXT,
                status TEXT DEFAULT 'OPEN',
                exit_price REAL,
                pnl REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                closed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_prefs (
                user TEXT PRIMARY KEY,
                silent_mode_manual INTEGER DEFAULT 0,
                updated_at TEXT
            );
        """)

        # 2) Migration : ajouter les colonnes manquantes sur DB pré-migration.
        # SQLite n'accepte pas ADD COLUMN NOT NULL sans DEFAULT, donc on
        # reste sur DEFAULT 'anonymous' (identique au CREATE TABLE).
        cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)").fetchall()]
        if "user" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN user TEXT NOT NULL DEFAULT 'anonymous'")
        if "post_entry_sl" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN post_entry_sl INTEGER DEFAULT 0")
        if "post_entry_tp" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN post_entry_tp INTEGER DEFAULT 0")
        if "post_entry_size" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN post_entry_size INTEGER DEFAULT 0")
        if "post_entry_alarm" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN post_entry_alarm INTEGER DEFAULT 0")
        # Traçabilité auto-exec : lien vers le ticket MT5 + flag 'ordre automatique'
        if "mt5_ticket" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN mt5_ticket INTEGER")
        if "is_auto" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN is_auto INTEGER DEFAULT 0")
        if "context_macro" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN context_macro TEXT")
        # Traçabilité ML-ready : lien vers le signal d'origine, prix
        # d'exécution réel (vs entry théorique), slippage calculé, raison
        # de fermeture. Ces colonnes alimenteront le futur dataset ML.
        if "signal_id" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN signal_id INTEGER")
        if "fill_price" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN fill_price REAL")
        if "slippage_pips" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN slippage_pips REAL")
        # Horizon d'analyse du setup (2026-08-26). Son ABSENCE rendait
        # l'hypothese « le 4 h sur l'or porte un edge » non mesurable : elle
        # n'existait nulle part dans la chaine persistee, ni ici ni dans les
        # 390 676 lignes de `signals`. Elle vit desormais depuis la poussee,
        # rattachee au trade par le ticket.
        if "horizon" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN horizon TEXT")
        # Fournisseur du signal (2026-08-26), `interne` par defaut. Sans
        # elle, la performance d'un bot externe et la notre se melangent
        # dans le meme P&L, sans rattrapage possible.
        if "source" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN source TEXT")
        if "close_reason" not in cols:
            # TP1 | TP2 | SL | MANUAL | TIMEOUT | UNKNOWN — remonte depuis
            # le bridge si disponible, sinon reste NULL.
            c.execute("ALTER TABLE personal_trades ADD COLUMN close_reason TEXT")
        # Destination du trade (2026-08-20). Son ABSENCE melait demo et reel
        # dans le plafond journalier : une perte fictive coupait le trading
        # reel. On la resolvait par sous-requete sur `mt5_pushes` a chaque
        # appel ; la colonne rend la reponse directe et durable.
        # Niveaux SL/TP REELLEMENT portes par la position a sa cloture
        # (2026-08-24). Les colonnes `stop_loss`/`take_profit` gardent ceux de
        # l'ORIGINE ; le systeme les deplace (mise a zero du risque, suiveur,
        # soupape d'equilibre) et Xavier aussi, a la main. Rejeu bougie par
        # bougie sur 36 clotures : 16 (44 %) avaient leur niveau stocke franchi
        # AVANT l'heure reelle de cloture — il n'etait pas celui du courtier.
        # `niveaux_source` distingue une mesure vivante d'une reconstruction
        # partielle. Cf. [[project_analyse_clotures_main_2026_08_24]].
        if "sl_at_close" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN sl_at_close REAL")
        if "tp_at_close" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN tp_at_close REAL")
        if "niveaux_source" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN niveaux_source TEXT")
        if "destination_id" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN destination_id TEXT")
            # Reprise de l'historique, UNE SEULE FOIS — a l'ajout de la
            # colonne, pas a chaque demarrage. `ORDER BY id DESC LIMIT 1`
            # comme `destination_for_ticket` : un ticket peut apparaitre dans
            # plusieurs pushes, on retient le dernier.
            try:
                c.execute("""
                    UPDATE personal_trades SET destination_id = (
                        SELECT p.destination_id FROM mt5_pushes p
                         WHERE p.bridge_response LIKE '%' || personal_trades.mt5_ticket || '%'
                         ORDER BY p.id DESC LIMIT 1)
                     WHERE mt5_ticket IS NOT NULL
                """)
                logger.info(
                    "personal_trades: colonne destination_id ajoutee, "
                    "%d ligne(s) reprises depuis mt5_pushes",
                    c.execute("SELECT COUNT(*) FROM personal_trades "
                              "WHERE destination_id IS NOT NULL").fetchone()[0])
            except Exception as e:  # noqa: BLE001
                # `mt5_pushes` peut ne pas exister sur une base neuve : la
                # colonne reste NULL, et la sous-requete de repli prend le
                # relais. Ne jamais faire echouer l'init du schema pour ca.
                logger.info(f"reprise destination_id impossible ({e})")

        # 3) Poser les INDEX une fois toutes les colonnes présentes
        c.executescript("""
            CREATE INDEX IF NOT EXISTS idx_pt_user ON personal_trades(user);
            CREATE INDEX IF NOT EXISTS idx_pt_status ON personal_trades(status);
            CREATE INDEX IF NOT EXISTS idx_pt_created ON personal_trades(created_at);
            CREATE INDEX IF NOT EXISTS idx_pt_ticket ON personal_trades(mt5_ticket);
            CREATE INDEX IF NOT EXISTS idx_pt_signal ON personal_trades(signal_id);
        """)
        # Unicité (mt5_ticket, direction). C'est ELLE qui donne son effet au
        # `INSERT OR IGNORE` de `mt5_sync._upsert_open_trade` : sans contrainte
        # à violer, `OR IGNORE` n'ignore rien et insère le doublon. Ce garde
        # était écrit depuis le début mais sans prise — 544 doublons accumulés
        # entre avril et juin 2026, purgés le 2026-08-13.
        #
        # La clé porte sur (ticket, sens) et non sur le ticket seul : une
        # position a parfois une patte de clôture (`close-sell`, `close-buy`)
        # qui partage son ticket. `UNIQUE(mt5_ticket)` les rendrait impossibles.
        #
        # ⚠️ Le repli est OBLIGATOIRE : une autre base (autre locataire, clone,
        # sauvegarde ancienne) peut encore contenir des doublons. `_init_schema`
        # est appelé à chaque opération — y laisser remonter l'exception
        # arrêterait le service pour une question d'hygiène. Même principe que
        # la porte d'heure : une contrainte qui ne peut pas se poser se tait.
        try:
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_pt_ticket_dir "
                "  ON personal_trades(mt5_ticket, direction)"
            )
        except sqlite3.IntegrityError:
            logger.warning(
                "personal_trades: doublons (mt5_ticket, direction) presents, "
                "index unique NON pose. Purger avant de compter quoi que ce soit."
            )


def get_manual_silent(user: str) -> bool:
    _init_schema()
    with _conn() as c:
        row = c.execute(
            "SELECT silent_mode_manual FROM user_prefs WHERE user=?", (user,)
        ).fetchone()
        return bool(row["silent_mode_manual"]) if row else False


def set_manual_silent(user: str, active: bool) -> bool:
    _init_schema()
    with _conn() as c:
        c.execute(
            "INSERT INTO user_prefs (user, silent_mode_manual, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user) DO UPDATE SET silent_mode_manual=excluded.silent_mode_manual, "
            "updated_at=excluded.updated_at",
            (user, 1 if active else 0, datetime.now(timezone.utc).isoformat()),
        )
    return active


@contextmanager
def _conn():
    conn = sqlite3.connect(str(_DB_PATH), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _scope_clause(user: str, user_id: int | None) -> tuple[str, tuple]:
    """Chantier 3 SaaS : retourne (SQL fragment, params) pour scoper par user.

    - Si `user_id` est fourni (user DB) : scope par colonne `user_id` (exact,
      isolation multi-tenant garantie).
    - Sinon (user env legacy) : scope par colonne `user` TEXT (back-compat).

    Garde invariable : une seule des deux colonnes est interrogée, évite les
    OR ambigus.
    """
    if user_id is not None:
        return "user_id = ?", (user_id,)
    return "user = ?", (user,)


def list_trades(
    status: str | None = None,
    limit: int = 100,
    user: str = "anonymous",
    user_id: int | None = None,
) -> list[dict]:
    _init_schema()
    scope_sql, scope_params = _scope_clause(user, user_id)
    with _conn() as c:
        if status:
            rows = c.execute(
                f"SELECT * FROM personal_trades WHERE {scope_sql} AND status=? "
                "ORDER BY created_at DESC LIMIT ?",
                (*scope_params, status, limit),
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT * FROM personal_trades WHERE {scope_sql} "
                "ORDER BY created_at DESC LIMIT ?",
                (*scope_params, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def get_trade(
    trade_id: int,
    user: str = "anonymous",
    user_id: int | None = None,
) -> dict | None:
    _init_schema()
    scope_sql, scope_params = _scope_clause(user, user_id)
    with _conn() as c:
        row = c.execute(
            f"SELECT * FROM personal_trades WHERE id=? AND {scope_sql}",
            (trade_id, *scope_params),
        ).fetchone()
        return dict(row) if row else None


def get_daily_status(user: str = "anonymous", user_id: int | None = None) -> dict:
    """Stats du jour pour `user` (ou `user_id` si fourni, préféré).

    Retourne :
    - silent_mode : ON/OFF selon le choix manuel du user (source unique de verite)
    - loss_alert : True si -X% atteint (informatif, non contraignant)
    """
    _init_schema()
    today_iso = date.today().isoformat()
    scope_sql, scope_params = _scope_clause(user, user_id)
    with _conn() as c:
        rows = c.execute(
            f"SELECT pnl, status FROM personal_trades "
            f"WHERE {scope_sql} AND created_at >= ?",
            (*scope_params, today_iso + "T00:00:00"),
        ).fetchall()

    n_total = len(rows)
    n_open = sum(1 for r in rows if r["status"] == "OPEN")
    pnl_today = sum(r["pnl"] or 0 for r in rows if r["status"] == "CLOSED")
    pnl_pct = (pnl_today / TRADING_CAPITAL * 100) if TRADING_CAPITAL > 0 else 0.0
    loss_alert = pnl_pct <= -DAILY_LOSS_LIMIT_PCT
    silent_mode = get_manual_silent(user)

    return {
        "date": today_iso,
        "n_trades_today": n_total,
        "n_open": n_open,
        "n_closed_today": n_total - n_open,
        "pnl_today": round(pnl_today, 2),
        "pnl_pct": round(pnl_pct, 2),
        "silent_mode": silent_mode,
        "loss_alert": loss_alert,
        "daily_loss_limit_pct": DAILY_LOSS_LIMIT_PCT,
        "capital": TRADING_CAPITAL,
    }


def silent_mode_active_for_user(user: str) -> bool:
    """True si CE user a atteint sa limite journaliere."""
    try:
        return get_daily_status(user=user)["silent_mode"]
    except Exception:
        return False


def assurer_colonne_destination(c) -> None:
    """Garantit `personal_trades.destination_id` sur la connexion donnee.

    ⚠️ **L'ecrivain garantit la colonne dont il a besoin**, il ne la suppose
    pas. `personal_trades` est recree a la main dans **68 fichiers de test**
    qui ne passent pas par `_init_schema` — et la meme duplication existe
    partout ou une base est montee autrement. Supposer la colonne fait
    echouer l'INSERT en `no such column`, ce qui, dans un `try/except` mal
    place, deviendrait une perte de trade silencieuse.

    Idempotent, et volontairement minuscule : c'est un filet, pas une
    migration. La migration complete reste dans `_init_schema`.
    """
    cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)")]
    if cols and "destination_id" not in cols:
        c.execute("ALTER TABLE personal_trades ADD COLUMN destination_id TEXT")


def _destinations_reelles() -> frozenset[str]:
    """Identifiants des destinations qui engagent de l'ARGENT REEL.

    Lu dans le registre (`Destination.reel`) plutot que recopie ici : c'est la
    duplication d'une table de ce genre qui avait fait afficher « Demo » sur
    des trades Kraken engageant de l'argent reel.
    """
    try:
        from backend.services.destinations_registry import DESTINATIONS
        return frozenset(k for k, d in DESTINATIONS.items()
                         if getattr(d, "reel", False))
    except Exception:
        return frozenset()


def silent_mode_active_any_user() -> bool:
    """True si AU MOINS UN user a atteint sa limite aujourd'hui.

    ⚠️ **Ne compte que l'argent REEL** (2026-08-20). `personal_trades` ne
    porte pas de `destination_id` : demo et reel s'additionnaient donc sous le
    meme utilisateur, et une perte sur le demo — de l'argent qui n'existe
    pas — coupait le trading reel.

    Mesure sur 30 jours avant correction : le seuil se serait declenche le
    12/08 sur **−101,98 EUR de DEMO**, alors que la seule journee reellement
    mauvaise (05/08, −271,88 EUR de reel) etait noyee dans le meme total.

    La destination se resout depuis `mt5_pushes` via le ticket — **exact
    plutot qu'heuristique**, comme `destination_for_ticket` : deviner d'apres
    le format du numero serait fragile, et c'est de l'argent reel.

    ⚠️ Une destination **non resolue compte comme reelle**. Quand on ne sait
    pas, on protege : l'inverse laisserait un trade inconnu echapper au
    garde-fou.

    ⚠️ Sous-requete correlee et non jointure : un `LEFT JOIN` sur `LIKE`
    pourrait apparier plusieurs pushes pour un meme ticket et **gonfler la
    somme**, donc declencher a tort.
    """
    _init_schema()
    reelles = _destinations_reelles()
    if not reelles:
        # Registre illisible : on ne filtre pas plutot que de tout ignorer.
        # Se taire ici reviendrait a desarmer le garde-fou en silence.
        logger.warning(
            "silent_mode: registre des destinations illisible — "
            "le plafond journalier compte TOUTES les destinations")
        clause = ""
        params: tuple = (date.today().isoformat() + "T00:00:00",)
    else:
        trous = ",".join("?" * len(reelles))
        # La COLONNE d'abord (2026-08-20), la sous-requete seulement en repli
        # pour les lignes anterieures a la migration ou non reprises. Le jour
        # ou toutes les lignes la portent, ce repli devient inerte — mais le
        # retirer trop tot ferait passer d'anciens trades pour inconnus.
        clause = (
            " AND COALESCE(t.destination_id,"
            "   CASE WHEN t.mt5_ticket IS NULL THEN NULL ELSE ("
            "     SELECT p.destination_id FROM mt5_pushes p"
            "      WHERE p.bridge_response LIKE '%' || t.mt5_ticket || '%'"
            "      ORDER BY p.id DESC LIMIT 1) END, '?')"
            f" IN ({trous}, '?')"
        )
        params = (date.today().isoformat() + "T00:00:00",
                  *sorted(reelles))

    with _conn() as c:
        rows = c.execute(
            "SELECT t.user AS user, SUM(t.pnl) AS pnl FROM personal_trades t "
            "WHERE t.status='CLOSED' AND t.created_at >= ?" + clause +
            " GROUP BY t.user",
            params,
        ).fetchall()
    if not rows:
        return False
    limit_usd = -TRADING_CAPITAL * DAILY_LOSS_LIMIT_PCT / 100
    return any((r["pnl"] or 0) <= limit_usd for r in rows)


def _capital_du_plafond(destination_id: str) -> float:
    """Capital à opposer au plafond journalier de CETTE destination.

    Le solde réel du compte quand on le connaît, `TRADING_CAPITAL` sinon.

    ⚠️ Le repli n'est pas un détail : `TRADING_CAPITAL` est une constante
    (650 €) pendant que le compte réel en portait 719,18 le 2026-09-03. Elle
    donne donc le seuil le plus SERRÉ des deux, et c'est le sens prudent —
    ignorer le solde d'un compte ne doit jamais ÉLARGIR son plafond.

    ⛔ Seul un solde réellement résolu (`live` / `destination`) est retenu.
    `sizing.destination_capital` retombe silencieusement sur `TRADING_CAPITAL`
    sous l'étiquette ``global`` : accepter ce repli reviendrait à croire qu'on
    a lu un solde alors qu'on a relu la constante.
    """
    try:
        from backend.services import sizing
        solde = sizing.capital_reel_connu(destination_id)
        if solde and solde > 0:
            return float(solde)
    except Exception as e:  # pragma: no cover - défensif
        logger.debug(f"plafond journalier[{destination_id}]: solde illisible ({e})")
    return TRADING_CAPITAL


def _pnl_du_jour_par_destination() -> list[tuple[str, str, float]]:
    """``(user, destination_resolue, pnl)`` des trades fermés aujourd'hui.

    La destination se résout comme dans `silent_mode_active_any_user` : la
    COLONNE d'abord, la sous-requête `mt5_pushes` seulement en repli pour les
    lignes antérieures à la migration du 2026-08-20. Un trade qu'on ne sait
    rattacher à personne ressort sous ``'?'``.

    ⚠️ Sous-requête corrélée et non jointure : un `LEFT JOIN` sur `LIKE`
    pourrait apparier plusieurs pushes pour un même ticket et **gonfler la
    somme**, donc déclencher le garde-fou à tort.
    """
    _init_schema()
    with _conn() as c:
        rows = c.execute(
            "SELECT t.user AS user,"
            " COALESCE(t.destination_id,"
            "   CASE WHEN t.mt5_ticket IS NULL THEN NULL ELSE ("
            "     SELECT p.destination_id FROM mt5_pushes p"
            "      WHERE p.bridge_response LIKE '%' || t.mt5_ticket || '%'"
            "      ORDER BY p.id DESC LIMIT 1) END, '?') AS dest,"
            " SUM(t.pnl) AS pnl"
            " FROM personal_trades t"
            " WHERE t.status='CLOSED' AND t.created_at >= ?"
            " GROUP BY t.user, dest",
            (date.today().isoformat() + "T00:00:00",),
        ).fetchall()
    return [(r["user"], r["dest"], r["pnl"] or 0.0) for r in rows]


def silent_mode_active_for_destination(destination_id: str | None = None) -> bool:
    """True si CE compte doit être bloqué au titre du plafond journalier.

    ⚠️ Depuis le 2026-09-04, franchir le plafond ne gèle plus automatiquement :
    ça ouvre un **arbitrage** (`plafond_arbitrage`). Le compte est bloqué dès
    le franchissement et le reste jusqu'à ce que Xavier réponde sur Telegram —
    seul un `CONTINUER` enregistré débloque. Le retour de cette fonction reste
    donc « faut-il bloquer », mais ce n'est plus « le plafond est-il franchi ».

    Posé le 2026-09-03. Le 02/09 à 11h35 UTC, un stop sur `XAU/USD` portait le
    cumul du compte réel à −28,45 € contre −19,50 € de plafond : le gel s'est
    appliqué au réel, à la démo **et** à Kraken, qui n'avaient rien perdu.
    3 490 signaux refusés en `kill_switch` jusqu'à minuit.

    C'est le même défaut de portée que `pair_pnl_regulator` avait le 29/08 —
    corrigé alors pour les pauses par paire, jamais pour le plafond journalier.

    La cascade, et pourquoi elle penche du côté prudent :

    - **destination absente** → portée globale d'avant. Les appelants qui ne
      la fournissent pas (`binance_drawdown_breaker`, `promotion_engine`)
      demandent « le système est-il gelé », pas « ce compte l'est-il ».
    - **registre illisible** → portée globale. Sans registre on ne distingue
      plus le réel du fictif ; se taire désarmerait le garde-fou en silence.
    - **destination réelle** → jugée sur ses propres clôtures et son propre
      solde.
    - **destination connue et NON réelle** → jamais gelée. Prolonge le
      correctif du 2026-08-20 : la démo perd de l'argent qui n'existe pas.
    - **destination inconnue du registre** → portée globale. Une destination
      qu'on ne sait pas nommer n'est pas une destination sûre.

    ⚠️ Un trade dont la destination reste NON RÉSOLUE pèse sur **chaque**
    compte réel. Quand on ne sait pas, on protège — l'inverse laisserait un
    trade inconnu échapper au garde-fou.

    ⛔ Rendre ce gel chirurgical OUVRE une porte dérobée : la démo continue de
    trader pendant que le réel est gelé, et le miroir démo→réel ne rejoue pas
    les portes de décision. C'est `_mirror_fill_to_live` qui la referme, en
    interrogeant ce plafond POUR SA CIBLE. Les deux vont ensemble.
    """
    if not destination_id:
        return silent_mode_active_any_user()

    reelles = _destinations_reelles()
    if not reelles:
        logger.warning(
            "plafond journalier: registre des destinations illisible — "
            "portée globale conservée")
        return silent_mode_active_any_user()

    if destination_id not in reelles:
        try:
            from backend.services.destinations_registry import is_known
            connue = is_known(destination_id)
        except Exception:
            connue = False
        if connue:
            return False
        logger.warning(
            f"plafond journalier: destination '{destination_id}' inconnue du "
            "registre — portée globale par prudence")
        return silent_mode_active_any_user()

    limite = -_capital_du_plafond(destination_id) * DAILY_LOSS_LIMIT_PCT / 100
    cumuls: dict[str, float] = {}
    for user, dest, pnl in _pnl_du_jour_par_destination():
        # `'?'` = non résolue : elle pèse sur tous les comptes réels.
        if dest in (destination_id, "?"):
            cumuls[user] = cumuls.get(user, 0.0) + pnl
    if not any(total <= limite for total in cumuls.values()):
        return False

    # Dépassement constaté. Depuis le 2026-09-04, à la demande de Xavier, il ne
    # gèle plus tout seul : il ouvre un ARBITRAGE. Le compte est bloqué dès cet
    # instant et le reste tant que la réponse n'est pas arrivée sur Telegram —
    # le blocage n'attend donc ni le message, ni le scheduler.
    try:
        from backend.services import plafond_arbitrage
    except Exception as e:
        # ⛔ Ne pas pouvoir arbitrer n'autorise rien : on retombe sur le gel
        # d'avant, jamais sur le passage libre.
        logger.warning(
            f"plafond journalier: arbitrage indisponible ({e}) — gel conservé")
        return True
    return plafond_arbitrage.doit_bloquer(
        destination_id, min(cumuls.values()), limite)


# Backward compat
def silent_mode_active() -> bool:
    return silent_mode_active_any_user()
