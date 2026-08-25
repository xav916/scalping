"""Banc d'essai hors-échantillon — une hypothèse se déclare avant de produire un chiffre.

## Pourquoi

Le journal de recherche compte 65 entrées, dont quinze `closed-positive` d'affilée
avec des profit factors annoncés de 1,24 à 5,60. Le résultat en argent réel sur les
quatre mois qui ont suivi : **−982,67 € sur 1 085 clôtures**, taux de réussite 28,6 %.

L'écart entre ces deux chiffres n'est pas une erreur de calcul. Il vient de ce que
soixante-cinq hypothèses ont été essayées sur le même historique et que la meilleure
a été retenue **parce qu'elle était la meilleure**. L'audit du 2026-08-25 l'a chiffré :
la plus performante des 75 variantes rend un Sharpe journalier de +0,1703, quand le
maximum attendu sous H₀ après 75 essais vaut +0,1925. `DSR = 0,350`.

> ⛔ **Sans compteur d'essais, la 76ᵉ variante paraîtra bonne pour exactement la
> raison qui a fait paraître bonnes les 75 précédentes.**

## Les trois règles

1. **Le futur seul.** Tout l'historique a été fouillé 65 fois — il est brûlé comme
   hors-échantillon. Un essai n'est jugé que sur des clôtures postérieures à sa
   déclaration, et la borne est **en SQL**, pas dans un avertissement.
2. **N ne décroît jamais.** Il somme les variantes *déclarées*, abandonnées comprises.
   Sinon il suffirait d'abandonner ce qui ne marche pas pour faire redescendre le
   plafond du hasard.
3. **La porte refuse le passage à l'argent réel**, et rien d'autre. Le reste de la
   recherche demeure libre.

Ce module ne trouve pas d'edge et n'en promet aucun. Il rend seulement impossible
d'en affirmer un sans l'avoir mesuré sur des données que personne n'avait vues au
moment où l'hypothèse a été écrite.

Conception : `docs/superpowers/specs/2026-08-25-banc-essai-hors-echantillon-design.md`
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import statistics
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Constante d'Euler-Mascheroni, dans l'espérance du maximum de N tirages.
_GAMMA_EM = 0.5772156649015329

#: Seuil de significativité. Bailey retient 0,95 ; on ne le desserre pas.
DSR_SEUIL = 0.95

#: Variance des Sharpe entre variantes, mesurée sur la grille de référence du
#: 2026-08-25 (75 variantes, 128 jours). Sert de repli quand un essai ne fournit
#: pas ses propres Sharpe par variante. **Inscrite telle quelle dans le verdict**
#: — un lecteur doit pouvoir savoir d'où sort le chiffre qui l'a jugé.
VAR_SR_REFERENCE = 0.006286

_ETAT_OUVERT, _ETAT_DEPENSE = "open", "spent"
_ETAT_ABANDONNE, _ETAT_HERITAGE = "abandoned", "legacy"

_SCHEMA_ENSURED = False


class DeclarationAlteree(Exception):
    """Les champs de déclaration ne correspondent plus à leur empreinte."""


class EssaiDepense(Exception):
    """Un essai jugé, ou abandonné, ne se rejoue pas."""


# ─── Socle ──────────────────────────────────────────────────────────────


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def _ensure_schema() -> None:
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return
    with sqlite3.connect(_db_path()) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS bench_trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                declared_at TEXT NOT NULL,
                author TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                selector TEXT NOT NULL,
                variants_declared INTEGER NOT NULL,
                min_sample INTEGER NOT NULL,
                declaration_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                verdict TEXT,
                passed INTEGER,
                dsr REAL, sr REAL, sr0 REAL, n_obs INTEGER,
                n_trials_at_verdict INTEGER,
                verdict_at TEXT,
                note TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS bench_legacy_grants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                direction TEXT,
                destination TEXT,
                granted_at TEXT NOT NULL,
                reason TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_bench_status ON bench_trials(status)")
    _SCHEMA_ENSURED = True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empreinte(slug: str, hypothesis: str, selector: dict,
               variants: int, min_sample: int, declared_at: str) -> str:
    """SHA-256 des champs de déclaration.

    ⛔ `sort_keys=True` : sans ordre stable, un aller-retour JSON changerait
    l'empreinte et invaliderait un essai parfaitement honnête.
    """
    charge = json.dumps(
        {"slug": slug, "hypothesis": hypothesis, "selector": selector,
         "variants_declared": variants, "min_sample": min_sample,
         "declared_at": declared_at},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(charge.encode("utf-8")).hexdigest()


def _ligne(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["selector"] = json.loads(d["selector"])
    if d.get("passed") is not None:
        d["passed"] = bool(d["passed"])
    return d


# ─── Le calcul ──────────────────────────────────────────────────────────


def sharpe_attendu_sous_h0(var_sr: float, n_trials: int) -> float:
    """Sharpe maximal **attendu sans le moindre edge**, après `n_trials` essais.

    C'est le plafond du bruit. Il monte avec le nombre d'essais : plus on cherche,
    plus il faut trouver fort pour que ça veuille dire quelque chose.
    """
    if n_trials < 2 or var_sr <= 0:
        return 0.0
    from scipy import stats
    return math.sqrt(var_sr) * (
        (1 - _GAMMA_EM) * stats.norm.ppf(1 - 1.0 / n_trials)
        + _GAMMA_EM * stats.norm.ppf(1 - 1.0 / (n_trials * math.e))
    )


def deflated_sharpe(sr: float, T: int, skew: float, kurt: float,
                    var_sr: float, n_trials: int) -> dict[str, Any]:
    """Sharpe déflaté — Bailey & López de Prado.

    `kurt` est l'aplatissement **non centré** (3 pour une gaussienne), comme dans
    l'article. Le dénominateur corrige l'asymétrie et l'épaisseur des queues : un
    Sharpe porté par quelques trades extrêmes vaut moins qu'un Sharpe régulier.
    """
    from scipy import stats
    sr0 = sharpe_attendu_sous_h0(var_sr, n_trials)
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4.0 * sr ** 2))
    z = (sr - sr0) * math.sqrt(max(1, T - 1)) / denom
    dsr = float(stats.norm.cdf(z))
    return {"sr": sr, "sr0": sr0, "dsr": dsr, "T": T, "skew": skew,
            "kurt": kurt, "var_sr": var_sr, "n_trials": n_trials,
            "passed": dsr > DSR_SEUIL}


# ─── Registre ───────────────────────────────────────────────────────────


def declare(slug: str, hypothesis: str, selector: dict, variants_declared: int,
            author: str, min_sample: int = 30) -> int:
    """Pré-enregistre une hypothèse. C'est l'instant qui fixe la frontière."""
    _ensure_schema()
    if variants_declared < 1:
        raise ValueError("variants_declared doit valoir au moins 1")
    if get_trial(slug) is not None:
        raise ValueError(f"L'essai « {slug} » existe déjà — un slug ne se redéclare pas")
    declared_at = _now()
    h = _empreinte(slug, hypothesis, selector, variants_declared, min_sample, declared_at)
    with sqlite3.connect(_db_path()) as c:
        cur = c.execute(
            """INSERT INTO bench_trials (slug, declared_at, author, hypothesis, selector,
                    variants_declared, min_sample, declaration_hash, status)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (slug, declared_at, author, hypothesis,
             json.dumps(selector, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
             variants_declared, min_sample, h, _ETAT_OUVERT))
    logger.warning("banc: essai « %s » déclaré — %d variantes, N devient %d",
                   slug, variants_declared, counter())
    return int(cur.lastrowid)


def get_trial(slug: str) -> Optional[dict[str, Any]]:
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM bench_trials WHERE slug = ?", (slug,)).fetchone()
    return _ligne(r) if r else None


def list_trials(status: Optional[str] = None) -> list[dict[str, Any]]:
    _ensure_schema()
    q = "SELECT * FROM bench_trials"
    a: tuple = ()
    if status:
        q += " WHERE status = ?"
        a = (status,)
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        return [_ligne(r) for r in c.execute(q + " ORDER BY declared_at DESC", a)]


def abandon(slug: str, reason: str) -> bool:
    """Ferme un essai sans verdict. ⛔ Ses variantes restent comptées."""
    _ensure_schema()
    t = get_trial(slug)
    if not t or t["status"] != _ETAT_OUVERT:
        return False
    with sqlite3.connect(_db_path()) as c:
        c.execute("UPDATE bench_trials SET status = ?, note = ?, verdict_at = ? WHERE slug = ?",
                  (_ETAT_ABANDONNE, reason, _now(), slug))
    logger.warning("banc: essai « %s » abandonné — N reste à %d", slug, counter())
    return True


def seed_legacy(slug: str, variants_declared: int, note: str) -> int:
    """Inscrit l'héritage du journal dans le compteur, une fois pour toutes."""
    _ensure_schema()
    if get_trial(slug) is not None:
        raise ValueError(f"L'héritage « {slug} » est déjà inscrit")
    now = _now()
    with sqlite3.connect(_db_path()) as c:
        cur = c.execute(
            """INSERT INTO bench_trials (slug, declared_at, author, hypothesis, selector,
                    variants_declared, min_sample, declaration_hash, status, note)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (slug, now, "import", "Héritage du journal de recherche — non jugeable",
             "{}", variants_declared, 0, "", _ETAT_HERITAGE, note))
    logger.warning("banc: héritage « %s » inscrit — %d variantes", slug, variants_declared)
    return int(cur.lastrowid)


def counter() -> int:
    """N — somme des variantes déclarées sur **tous** les essais.

    ⛔ Un cliquet. Aucun statut n'en retire : abandonner un essai ne le rend pas.
    """
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        return int(c.execute("SELECT COALESCE(SUM(variants_declared), 0) FROM bench_trials")
                   .fetchone()[0])


# ─── Verdict ────────────────────────────────────────────────────────────


def _clotures_eligibles(selector: dict, declared_at: str) -> list[dict]:
    """Clôtures **postérieures à la déclaration** qui satisfont le sélecteur.

    ⛔ La borne temporelle est dans le `WHERE`, pas dans un contrôle applicatif :
    une donnée antérieure ne doit jamais atteindre le calcul, même par erreur.
    """
    ou = ["status = 'CLOSED'", "is_auto = 1", "pnl IS NOT NULL", "closed_at > ?"]
    args: list = [declared_at]

    paires = selector.get("pairs")
    if paires:
        ou.append("pair IN (%s)" % ",".join("?" * len(paires)))
        args += list(paires)
    sens = selector.get("direction")
    if sens:
        ou.append("LOWER(direction) = ?")
        args.append(str(sens).lower())
    conf = selector.get("min_confidence")
    if conf is not None:
        ou.append("COALESCE(signal_confidence, -1) >= ?")
        args.append(float(conf))
    dests = selector.get("destinations")
    if dests:
        ou.append("destination_id IN (%s)" % ",".join("?" * len(dests)))
        args += list(dests)

    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(
            "SELECT pnl, closed_at FROM personal_trades WHERE " + " AND ".join(ou)
            + " ORDER BY closed_at ASC", args)]


def evaluate(slug: str) -> dict[str, Any]:
    """Juge un essai. Sous `min_sample`, ne rend **aucun** chiffre.

    Un chiffre indicatif est un chiffre qui sera lu, puis cité sans sa réserve.
    """
    _ensure_schema()
    t = get_trial(slug)
    if t is None:
        raise ValueError(f"Essai inconnu : {slug}")
    if t["status"] != _ETAT_OUVERT:
        raise EssaiDepense(f"L'essai « {slug} » est {t['status']} — il ne se rejoue pas")

    attendu = _empreinte(t["slug"], t["hypothesis"], t["selector"],
                         t["variants_declared"], t["min_sample"], t["declared_at"])
    if attendu != t["declaration_hash"]:
        raise DeclarationAlteree(
            f"La déclaration de « {slug} » a été modifiée après coup — essai nul")

    lignes = _clotures_eligibles(t["selector"], t["declared_at"])
    n = len(lignes)
    if n < t["min_sample"]:
        return {"slug": slug, "status": _ETAT_OUVERT, "n_obs": n,
                "min_sample": t["min_sample"],
                "message": f"{n}/{t['min_sample']} clôtures — rien à lire"}

    from config.settings import TRADING_CAPITAL
    capital = float(TRADING_CAPITAL) or 1.0
    par_jour: dict[str, float] = {}
    for x in lignes:
        par_jour.setdefault(str(x["closed_at"])[:10], 0.0)
        par_jour[str(x["closed_at"])[:10]] += float(x["pnl"])
    r = [v / capital for _, v in sorted(par_jour.items())]

    if len(r) > 1 and statistics.pstdev(r) > 0:
        from scipy import stats as _st
        sr = statistics.mean(r) / statistics.stdev(r)
        skew, kurt = float(_st.skew(r)), float(_st.kurtosis(r, fisher=False))
    else:
        sr, skew, kurt = 0.0, 0.0, 3.0

    n_trials = counter()
    o = deflated_sharpe(sr, len(r), skew, kurt, VAR_SR_REFERENCE, n_trials)
    verdict = ("passé — le Sharpe survit à %d essais" if o["passed"]
               else "refusé — sous le plafond du hasard à %d essais") % n_trials

    with sqlite3.connect(_db_path()) as c:
        c.execute("""UPDATE bench_trials SET status=?, verdict=?, passed=?, dsr=?, sr=?,
                        sr0=?, n_obs=?, n_trials_at_verdict=?, verdict_at=? WHERE slug=?""",
                  (_ETAT_DEPENSE, verdict, int(o["passed"]), o["dsr"], o["sr"],
                   o["sr0"], n, n_trials, _now(), slug))
    logger.warning("banc: essai « %s » %s — DSR %.4f sur %d clôtures",
                   slug, "PASSÉ" if o["passed"] else "REFUSÉ", o["dsr"], n)

    return {"slug": slug, "status": _ETAT_DEPENSE, "n_obs": n,
            "sum_pnl": round(sum(float(x["pnl"]) for x in lignes), 2),
            "verdict": verdict, **o}


def _forcer_verdict(slug: str, passed: bool) -> None:
    """Utilitaire de test : scelle un verdict sans attendre l'échantillon.

    ⚠️ Réservé aux tests de la porte. Aucun chemin de production ne l'appelle —
    il court-circuite précisément ce que le banc existe pour imposer.
    """
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.execute("UPDATE bench_trials SET status=?, passed=?, verdict=?, verdict_at=? "
                  "WHERE slug=?",
                  (_ETAT_DEPENSE, int(passed), "forcé (test)", _now(), slug))


# ─── La porte ───────────────────────────────────────────────────────────


def grant_legacy(pair: str, direction: Optional[str], destination: Optional[str],
                 reason: str) -> int:
    """Inscrit une configuration déjà en place au moment de l'installation.

    ⚠️ **Sans clause d'antériorité, installer le banc arrête tout le trading** :
    rien aujourd'hui ne dispose d'un essai passé. C'est aussi sa limite — le banc
    ne juge pas rétroactivement l'existant.
    """
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        cur = c.execute(
            "INSERT INTO bench_legacy_grants (pair, direction, destination, granted_at, reason)"
            " VALUES (?,?,?,?,?)",
            (pair, (direction or "").lower() or None, destination, _now(), reason))
    return int(cur.lastrowid)


def _porte_armee() -> bool:
    try:
        from config.settings import RESEARCH_BENCH_GATE_ENABLED
        return bool(RESEARCH_BENCH_GATE_ENABLED)
    except Exception:  # noqa: BLE001 — un banc non installé ne gèle personne
        return False


def _touche_argent_reel(destination: Optional[str]) -> bool:
    """⛔ `None` signifie « toutes les destinations », donc **inclut l'argent réel**.

    `destinations_registry.is_real_money(None)` rend `False`, et c'est correct pour
    son usage — on ne suppose jamais sur l'argent. Ce serait un trou béant ici : une
    promotion globale contournerait la porte en silence.

    Le dépôt a déjà payé ce défaut exact le 2026-08-04, quand `_normalize_destination`
    repliait une destination inconnue sur `None` et **élargissait** les permissions
    au lieu de les restreindre.
    """
    if destination is None:
        return True
    try:
        from backend.services.destinations_registry import is_real_money
        return bool(is_real_money(destination))
    except Exception:  # noqa: BLE001
        return True  # sur l'argent, le doute retient


def _couvert_par_essai(pair: str, direction: Optional[str],
                       destination: Optional[str]) -> bool:
    d = (direction or "").lower() or None
    for t in list_trials(_ETAT_DEPENSE):
        if not t.get("passed"):
            continue
        s = t["selector"]
        if s.get("pairs") and pair not in s["pairs"]:
            continue
        if s.get("direction") and d and str(s["direction"]).lower() != d:
            continue
        if s.get("destinations") and destination not in s["destinations"]:
            continue
        return True
    return False


def _couvert_par_anteriorite(pair: str, direction: Optional[str],
                             destination: Optional[str]) -> bool:
    _ensure_schema()
    d = (direction or "").lower() or None
    with sqlite3.connect(_db_path()) as c:
        n = c.execute(
            """SELECT COUNT(*) FROM bench_legacy_grants
                WHERE pair = ?
                  AND (direction IS NULL OR ? IS NULL OR direction = ?)
                  AND (destination IS NULL OR ? IS NULL OR destination = ?)""",
            (pair, d, d, destination, destination)).fetchone()[0]
    return int(n) > 0


def gate_promotion(pair: str, new_state: str, direction: Optional[str] = None,
                   destination: Optional[str] = None,
                   transitioned_by: str = "auto") -> tuple[bool, str]:
    """`(autorisé, motif)` pour une transition d'état d'admission.

    Ne s'interpose que sur l'acte de promotion vers `AUTO_EXEC` en argent réel.
    """
    if not _porte_armee():
        return True, "banc désarmé"
    if str(new_state).upper() != "AUTO_EXEC":
        return True, "l'état n'engage pas d'argent"
    if not _touche_argent_reel(destination):
        return True, "destination fictive"
    if transitioned_by == "admin_override":
        logger.warning(
            "banc: PROMOTION FORCÉE %s/%s@%s — admin_override, aucun essai ne la couvre",
            pair, direction, destination or "TOUTES")
        return True, "dérogation explicite, journalisée"
    if _couvert_par_anteriorite(pair, direction, destination):
        return True, "couvert par la clause d'antériorité"
    if _couvert_par_essai(pair, direction, destination):
        return True, "couvert par un essai passé"

    cible = destination or "TOUTES destinations (donc l'argent réel)"
    return False, (
        f"aucun essai passé ne couvre {pair}/{direction or 'tous sens'}@{cible}. "
        f"Déclarer une hypothèse au banc, attendre son échantillon, puis l'évaluer — "
        f"ou forcer avec transitioned_by='admin_override'.")
