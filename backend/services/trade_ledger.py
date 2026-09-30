#!/usr/bin/env python3
"""REM-005 — le ledger financier central.

UNE ligne par trade, les 31 colonnes nommées par le cahier de remédiation.
Une seule règle gouverne tout le module :

⛔ **UN CHAMP INCONNU VAUT `NULL`, JAMAIS `0`.**
Un zéro est une affirmation : « le swap était nul », « la commission était
nulle », « le risque valait zéro euro ». Écrire 0 là où on ne sait pas
fabrique exactement le défaut que ce cahier existe pour tuer — un nombre
crédible et faux. Le ledger a donc le droit d'être largement VIDE ; il n'a
pas le droit d'être faux. `rapport_completude()` mesure ce vide et le publie.

🔑 **ET IL DIT D'OÙ VIENT CHAQUE EURO.** Cinq colonnes `src_*` portent la
provenance. L'argent vient-il de l'instantané du courtier — la vérité de
terrain — ou du stock local, qui n'est qu'une intention ? Sans elles, 496
trades mesurés chez le courtier et 848 trades devinés se ressemblent dans
une requête, et toute conclusion tirée du mélange est indéfendable.

## Couverture des sources, mesurée le 2026-10-01 sur 1 353 trades

| source                   | porte                              | couverture |
|--------------------------|------------------------------------|------------|
| `personal_trades`        | l'existence du trade, l'intention  | 1 353      |
| `broker_close_snapshots` | l'argent **vérifié** (9 champs)    | 496 (36,9 % des fermés) |
| `mt5_pushes`             | le prix **demandé**, la chaîne     | 85 / 10    |
| `risk_eur.calculer`      | le risque en euros                 | calculé    |

⚠️ `mt5_pushes` n'a que ~16 jours de rétention (plus ancien : 2026-09-15).
`entry_requested` et `chain_id` sont donc structurellement absents de
l'histoire ancienne, et le resteront.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.services import destinations_registry
from backend.services.risk_eur import calculer as _risque_eur

TABLE = "trade_financial_ledger"

# ⛔ L'ORDRE ET LES NOMS VIENNENT DU CAHIER, mot pour mot. Un test compare
# cette liste au cahier : renommer une colonne « pour faire plus clair »
# casserait la correspondance avec le document d'audit, qui est la seule
# raison d'être de la table.
COLONNES_CAHIER = (
    "trade_id", "broker_trade_id", "account_id", "environment",
    "strategy_id", "experiment_id", "signal_id", "chain_id",
    "human_intervention", "bug_affected", "execution_type",
    "entry_requested", "entry_executed", "exit_executed",
    "quantity", "stop", "take_profit",
    "gross_pnl", "spread_cost", "commission", "swap", "slippage",
    "fx_effect", "net_pnl", "risk_amount", "r_multiple",
    "opened_at", "closed_at", "close_reason",
    "deployment_commit", "configuration_hash",
)

# 🔑 AU-DELÀ DU CAHIER, et c'est délibéré : la provenance. Le cahier demande
# les chiffres ; il ne demande pas de pouvoir les auditer. Sans ces cinq
# colonnes le ledger serait un tableau de bord, pas un registre.
COLONNES_PROVENANCE = (
    "src_argent",    # 'courtier' | 'stock' | NULL
    "src_entree",    # 'courtier' | 'fill_price' | NULL
    "src_sortie",    # 'courtier' | 'stock' | NULL
    "src_cloture",   # 'courtier_confirme' | 'stock_seul' | NULL
    "src_risque",    # 'calcule' | NULL
    "categorie_pnl",  # REM-006, voir `categorie_pnl()`
    "construit_le",
)

# REM-006 — les trois catégories primaires du cahier, mot pour mot.
CAT_ALGO = "VALID_ALGORITHM"
CAT_RECHERCHE = "RESEARCH_EXPERIMENT"
CAT_MAIN = "HUMAN_INTERVENTION"

_TYPES = {
    "trade_id": "INTEGER PRIMARY KEY",
    "human_intervention": "INTEGER",
    "bug_affected": "INTEGER",
}
_REELS = frozenset({
    "entry_requested", "entry_executed", "exit_executed", "quantity",
    "stop", "take_profit", "gross_pnl", "spread_cost", "commission",
    "swap", "slippage", "fx_effect", "net_pnl", "risk_amount", "r_multiple",
})

# ⛔ Les 10 ordres nés du fail-open de la chaîne (16→25/09). La preuve est
# figée dans `docs/audit/ordres-chaine-16-25-09-candidats-bug-affected.json`.
# Ils sont marqués `bug_affected=1` ; TOUT LE RESTE VAUT NULL, jamais 0 —
# affirmer « ce trade n'est affecté par aucun défaut » demanderait d'avoir
# audité tous les défauts, ce que personne n'a fait.
TICKETS_BUG_CHAINE = frozenset({
    "1358904857", "90137586", "1359026109", "90144531", "1359027588",
    "90161617", "1359031757", "1359483129", "1359573589", "1359580018",
})


def _schema() -> str:
    morceaux = []
    for col in COLONNES_CAHIER + COLONNES_PROVENANCE:
        if col in _TYPES:
            t = _TYPES[col]
        elif col in _REELS:
            t = "REAL"
        else:
            t = "TEXT"
        morceaux.append("  %s %s" % (col, t))
    return "CREATE TABLE IF NOT EXISTS %s (\n%s\n)" % (TABLE,
                                                       ",\n".join(morceaux))


def creer_table(conn: sqlite3.Connection) -> list[str]:
    """Crée la table, et RATTRAPE les colonnes ajoutées après coup.

    ⛔ `CREATE TABLE IF NOT EXISTS` ne touche pas une table qui existe déjà.
    Sans le rattrapage ci-dessous, ajouter une colonne au module laisserait
    la table d'hier telle quelle, et `construire()` mourrait sur un
    `no such column` — ou pire, dans une variante où l'insertion nomme ses
    colonnes, écrirait un ledger amputé sans rien dire. Rend la liste des
    colonnes ajoutées, pour que la migration soit visible et non devinée.
    """
    conn.execute(_schema())
    presentes = {r[1] for r in conn.execute("pragma table_info(%s)" % TABLE)}
    ajoutees = []
    for col in COLONNES_CAHIER + COLONNES_PROVENANCE:
        if col in presentes:
            continue
        t = "REAL" if col in _REELS else _TYPES.get(col, "TEXT")
        # ⛔ Jamais de DEFAULT : une colonne neuve vaut NULL sur l'histoire,
        # pas 0. Un DEFAULT 0 réécrirait 1 353 lignes avec une affirmation.
        conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (TABLE, col, t))
        ajoutees.append(col)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_compte ON %s(account_id)"
                 % TABLE)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ledger_ferme ON %s(closed_at)"
                 % TABLE)
    conn.commit()
    return ajoutees


# --------------------------------------------------------------------------
# Les champs, un par un, avec la raison de chaque NULL

def _argent(r: sqlite3.Row) -> dict:
    """Les champs d'argent et leur provenance.

    ⛔ LA CONVENTION DE SIGNE EST `net = brut + swap + commission + fee`.
    Elle a été VÉRIFIÉE sur les 496 instantanés : 488 concordent à 0,005 €
    près. Je l'avais d'abord écrite `brut − net = swap + …` et 78 lignes
    « divergeaient » — c'était mon signe, pas les données. Les 8 écarts qui
    restent sont réels et `verifier_identite_courtier()` les publie.

    🔑 `commission` et `fee` valent 0 sur les 496 instantanés, et ce zéro est
    CELUI DU COURTIER, pas un défaut du pont : le payload brut porte bien les
    deux clés et le courtier y répond `0.0`. Il est donc légitime de l'écrire,
    contrairement à tous les autres zéros de ce module.
    """
    if r["b_net"] is not None:
        return {
            "gross_pnl": r["b_pnl"], "net_pnl": r["b_net"],
            "swap": r["b_swap"], "commission": r["b_comm"],
            "src_argent": "courtier",
        }
    # Le stock ne connaît qu'un `pnl` sans décomposition. On le prend pour
    # `gross_pnl` et on laisse `net_pnl` INCONNU : le présenter comme net
    # laisserait croire que le swap a été retiré alors qu'on l'ignore.
    return {
        "gross_pnl": r["pnl"], "net_pnl": None,
        "swap": None, "commission": None,
        "src_argent": "stock" if r["pnl"] is not None else None,
    }


def _prix(r: sqlite3.Row) -> dict:
    """Prix demandé, prix exécuté, prix de sortie.

    ⛔ `entry_executed` NE TOMBE JAMAIS SUR `entry_price`. Ce champ du stock
    est un mélange : parfois le prix du signal, parfois le remplissage réel
    (217 lignes valaient même 0 avant le rattrapage du 24/08). Le confondre
    avec l'exécution rendrait le slippage inmesurable en le noyant. Seules
    deux sources disent le prix VRAIMENT obtenu : l'instantané du courtier,
    et `fill_price` quand le pont l'a capté.
    """
    if r["b_entry"] is not None:
        entree, src_e = r["b_entry"], "courtier"
    elif r["fill_price"]:
        entree, src_e = r["fill_price"], "fill_price"
    else:
        entree, src_e = None, None
    if r["b_exit"] is not None:
        sortie, src_s = r["b_exit"], "courtier"
    elif r["exit_price"]:
        sortie, src_s = r["exit_price"], "stock"
    else:
        sortie, src_s = None, None
    return {
        "entry_requested": r["p_demande"], "entry_executed": entree,
        "exit_executed": sortie, "src_entree": src_e, "src_sortie": src_s,
    }


def _risque(r: sqlite3.Row, net: float | None) -> dict:
    """Risque en euros par le calcul de PRODUCTION, et le R qui en découle.

    ⛔ `r_multiple` est calculé SUR L'ARGENT (`net / risque`), pas sur les
    prix. C'est le sens même d'un ledger financier ; et le projet a déjà payé
    le piège d'unité, où des R moyennés sur des risques de 8 à 65 € donnaient
    un chiffre sans traduction en caisse.

    ⚠️ Il exige donc `net_pnl`, donc l'instantané du courtier. Sur un trade
    sans instantané il vaut NULL même quand le stock connaît un `pnl` :
    diviser un brut par un risque produirait un R qui ignore le swap.
    """
    stop = r["stop_loss"]
    if not (r["entry_price"] and stop and r["size_lot"]):
        return {"risk_amount": None, "r_multiple": None, "src_risque": None}
    try:
        m = _risque_eur(r["pair"], float(r["entry_price"]), float(stop),
                        0.0, float(r["size_lot"]))
    except Exception:  # noqa: BLE001
        return {"risk_amount": None, "r_multiple": None, "src_risque": None}
    if not m or not m.get("risque_eur"):
        return {"risk_amount": None, "r_multiple": None, "src_risque": None}
    risque = float(m["risque_eur"])
    return {
        "risk_amount": risque,
        "r_multiple": (net / risque) if net is not None else None,
        "src_risque": "calcule",
    }


def _cloture(r: sqlite3.Row) -> dict:
    """Motif de clôture, main humaine, et qui l'atteste.

    🔑 LE COURTIER NE CONTREDIT JAMAIS LE STOCK, IL LE RÉSUME : `TP1` devient
    `TP` (42 fois), `TRAILING_SL` devient `SL` (8 fois). Le motif fin du stock
    est donc plus informatif, et c'est lui qu'on garde — mais `src_cloture`
    dit si le courtier l'a confirmé.

    ⚠️ `human_intervention` mérite cette prudence : `MANUAL` a été écrit PAR
    DÉFAUT pendant une période (défaut du 10/08). Un `MANUAL` confirmé par le
    courtier est une main ; un `MANUAL` orphelin reste un `MANUAL` déclaré, et
    seule `src_cloture` permet de les distinguer après coup.
    """
    motif = r["close_reason"]
    if motif is None:
        return {"close_reason": None, "human_intervention": None,
                "src_cloture": None, "closed_at": r["closed_at"]}
    return {
        "close_reason": motif,
        "human_intervention": 1 if motif == "MANUAL" else 0,
        "src_cloture": "courtier_confirme" if r["b_reason"] else "stock_seul",
        "closed_at": r["b_closed"] or r["closed_at"],
    }


def _compte(r: sqlite3.Row) -> dict:
    """Compte et environnement.

    ⛔ `environment` PASSE PAR `destinations_registry.is_real_money()`, le
    même juge que la production. Réécrire la règle ici créerait une seconde
    définition de « argent réel », et deux définitions finissent toujours par
    divorcer. 385 trades n'ont pas de `destination_id` (antérieurs à la
    notion) : leur environnement est INCONNU, pas « démo par défaut ».
    """
    dest = r["destination_id"]
    if not dest:
        return {"account_id": None, "environment": None}
    return {
        "account_id": dest,
        "environment": ("REAL" if destinations_registry.is_real_money(dest)
                        else "DEMO"),
    }


def categorie_pnl(main: int | None, env: str | None) -> str | None:
    """REM-006 — la catégorie primaire d'un trade.

    ⛔ ELLE PEUT VALOIR `NULL`, et le cahier ne l'avait pas prévu. « Tout
    trade devra appartenir à exactement une catégorie primaire » suppose
    qu'on sache sur quel compte il a vécu ; 385 trades sont antérieurs à la
    notion de destination. Leur attribuer `VALID_ALGORITHM` par défaut ferait
    entrer 385 trades d'origine inconnue dans le compte de performance de
    l'algorithme. Le trou est donc laissé visible et comptable.

    🔑 LA CATÉGORIE NE DIT RIEN DU DÉFAUT. Un ordre né du fail-open de la
    chaîne reste `VALID_ALGORITHM` ici, parce que c'est bien l'algorithme qui
    l'a émis — ce qui était invalide, c'est la porte. Le cahier a prévu pour
    ça une colonne SÉPARÉE, `bug_affected` : les deux se lisent ensemble, et
    `rapport_categories()` les croise toujours. Ranger un ordre défectueux
    dans « recherche » le blanchirait en expérience.
    """
    if main == 1:
        return CAT_MAIN
    if env == "DEMO":
        return CAT_RECHERCHE
    if env == "REAL":
        return CAT_ALGO
    return None


REQUETE_SOURCE = """
select
  t.id, t.mt5_ticket, t.destination_id, t.signal_id, t.pair, t.direction,
  t.entry_price, t.fill_price, t.exit_price, t.stop_loss, t.take_profit,
  t.size_lot, t.pnl, t.slippage_pips, t.close_reason, t.created_at,
  t.closed_at, t.is_auto, t.source,
  b.pnl        as b_pnl,   b.pnl_net as b_net,    b.swap  as b_swap,
  b.commission as b_comm,  b.fee     as b_fee,    b.entry_price as b_entry,
  b.exit_price as b_exit,  b.volume  as b_vol,    b.reason as b_reason,
  b.closed_at  as b_closed,
  p.entry_price_5dp as p_demande, p.chaine as p_chaine
from personal_trades t
left join broker_close_snapshots b on b.ticket    = t.mt5_ticket
left join mt5_pushes            p on p.mt5_ticket = t.mt5_ticket
"""


def _ligne(r: sqlite3.Row, maintenant: str) -> dict:
    argent = _argent(r)
    ticket = str(r["mt5_ticket"]) if r["mt5_ticket"] is not None else None
    ligne = {
        "trade_id": r["id"],
        "broker_trade_id": ticket,
        "signal_id": r["signal_id"],
        "chain_id": r["p_chaine"] or None,
        # ⛔ NULL ASSUMÉ, ET DOCUMENTÉ. Aucune notion de stratégie ni
        # d'expérience n'existe dans les données. Y verser `signal_pattern`
        # inventerait une taxonomie : le projet n'a QU'UNE stratégie, et
        # créer de fausses distinctions dans un registre d'audit est pire
        # que d'y laisser un trou visible. Attend une décision de Xavier.
        "strategy_id": None,
        "experiment_id": None,
        # 🔑 `is_auto` vaut 1 sur 1 353 lignes sur 1 353 : le champ n'a jamais
        # pris d'autre valeur, donc il n'a AUCUN pouvoir discriminant. On
        # l'écrit parce que c'est ce que disent les données, et le rapport
        # signale qu'il ne prouve rien.
        "execution_type": "AUTO" if r["is_auto"] else None,
        "bug_affected": 1 if ticket in TICKETS_BUG_CHAINE else None,
        "quantity": r["b_vol"] if r["b_vol"] is not None else r["size_lot"],
        "stop": r["stop_loss"],
        "take_profit": r["take_profit"],
        # ⛔ INCONNU PAR CONSTRUCTION, pas par paresse. Le courtier intègre le
        # spread au prix d'exécution et renvoie commission=0 et fee=0 : il
        # n'est pas séparable a posteriori. Le connaître demanderait
        # d'enregistrer le bid ET le ask à l'instant du push, ce que le pont
        # ne fait pas. C'est le trou le plus coûteux du ledger, puisque la
        # mesure du 12/09 dit que le spread EST la perte entière.
        "spread_cost": None,
        "slippage": r["slippage_pips"],
        # ⛔ Le courtier rend déjà son P&L en devise de compte : l'effet de
        # change est DÉJÀ dedans et n'en est plus extractible.
        "fx_effect": None,
        "opened_at": r["created_at"],
        # ⛔ REM-003 n'horodate les déploiements que depuis le 28/09, et
        # `configuration_hash_build` hache aujourd'hui des valeurs vides —
        # il rend « un nombre crédible et faux ». Le stocker serait signer
        # l'histoire avec une empreinte qui ne prouve rien.
        "deployment_commit": None,
        "configuration_hash": None,
        "construit_le": maintenant,
    }
    ligne.update(argent)
    ligne.update(_prix(r))
    ligne.update(_compte(r))
    ligne.update(_cloture(r))
    ligne.update(_risque(r, argent["net_pnl"]))
    ligne["categorie_pnl"] = categorie_pnl(ligne["human_intervention"],
                                           ligne["environment"])
    return ligne


def construire(conn: sqlite3.Connection) -> dict:
    """Reconstruit le ledger de zéro et rend le compte rendu.

    ⛔ IL REFUSE DE PUBLIER UN LEDGER DÉMULTIPLIÉ. Les trois clés de jointure
    sont uniques aujourd'hui (vérifié le 01/10 : 496, 85 et 1 353 valeurs
    distinctes), mais un doublon futur dupliquerait des trades et gonflerait
    le P&L en silence. L'invariant « une ligne de ledger par trade » est donc
    contrôlé à chaque construction, et sa violation annule l'écriture.
    """
    creer_table(conn)
    conn.row_factory = sqlite3.Row
    attendu = conn.execute("select count(*) from personal_trades").fetchone()[0]
    maintenant = datetime.now(timezone.utc).isoformat()

    lignes = [_ligne(r, maintenant) for r in conn.execute(REQUETE_SOURCE)]
    if len(lignes) != attendu:
        raise RuntimeError(
            "⛔ jointure DÉMULTIPLIÉE : %d lignes pour %d trades. Le ledger "
            "n'est pas écrit — une clé de jointure a perdu son unicité."
            % (len(lignes), attendu))

    cols = COLONNES_CAHIER + COLONNES_PROVENANCE
    conn.execute("delete from %s" % TABLE)
    conn.executemany(
        "insert into %s (%s) values (%s)"
        % (TABLE, ",".join(cols), ",".join("?" * len(cols))),
        [tuple(li.get(c) for c in cols) for li in lignes])
    conn.commit()
    return {"trades": attendu, "lignes": len(lignes),
            "construit_le": maintenant}


def rapport_completude(conn: sqlite3.Connection) -> list[dict]:
    """Ce que le ledger IGNORE, colonne par colonne.

    🔑 C'est la moitié utile de REM-005. Un ledger qui remplit tout n'apprend
    rien ; un ledger qui dit précisément où il est aveugle permet de savoir
    quelles conclusions sont défendables et lesquelles ne le sont pas.
    """
    n = conn.execute("select count(*) from %s" % TABLE).fetchone()[0] or 1
    out = []
    for col in COLONNES_CAHIER:
        k = conn.execute("select count(%s) from %s" % (col, TABLE)).fetchone()[0]
        out.append({"colonne": col, "rempli": k, "sur": n,
                    "pct": round(100.0 * k / n, 1)})
    return out


def rapport_categories(conn: sqlite3.Connection,
                       verifie_seulement: bool = True) -> list[dict]:
    """REM-006 — le P&L par catégorie, croisé avec `bug_affected`.

    ⛔ `verifie_seulement` VAUT `True` PAR DÉFAUT, et ce défaut est le cœur
    du rapport : sommer `net_pnl` sur les trades sans instantané reviendrait
    à sommer des NULL et à publier le total des 36,7 % mesurés comme s'il
    était celui des 100 %. SQLite ignore les NULL dans un `sum()` sans le
    dire — le total aurait l'air complet.

    ⚠️ LES LITTÉRAUX SQL SONT EN PARAMÈTRES, jamais entre guillemets doubles.
    Une chaîne `"HUMAN_INTERVENTION"` en double quote est résolue par SQLite
    comme l'IDENTIFIANT `human_intervention` quand une colonne porte ce nom :
    elle rend la valeur de la colonne, pas la chaîne. C'est exactement ce qui
    a fusionné deux catégories dans ma première mesure.
    """
    ou = " where src_argent = ?" if verifie_seulement else ""
    args = ("courtier",) if verifie_seulement else ()
    lignes = conn.execute(
        "select categorie_pnl, bug_affected, count(*), sum(net_pnl), "
        "       count(net_pnl) "
        "from %s%s group by 1, 2 order by 1, 2" % (TABLE, ou), args)
    return [{"categorie": r[0], "bug_affected": r[1], "trades": r[2],
             "net": r[3], "net_connu_sur": r[4]} for r in lignes]


def verifier_identite_courtier(conn: sqlite3.Connection) -> dict:
    """`net = brut + swap + commission + fee` — tenue sur chaque instantané.

    ⚠️ 8 lignes sur 496 ne la tiennent pas. Ce n'est pas un défaut de ce
    module et le ledger ne les corrige PAS : il les nomme. Les deux plus gros
    écarts (+23,89 € et +6,47 €) sont des clôtures multi-deals dont le net
    dépasse le brut sans swap pour l'expliquer.
    """
    conn.row_factory = sqlite3.Row
    ok, divergents = 0, []
    for r in conn.execute("select ticket,pnl,pnl_net,swap,commission,fee "
                          "from broker_close_snapshots"):
        d = r["pnl_net"] - (r["pnl"] + r["swap"] + r["commission"] + r["fee"])
        if abs(d) < 0.005:
            ok += 1
        else:
            divergents.append({"ticket": r["ticket"], "ecart": round(d, 4),
                               "brut": r["pnl"], "net": r["pnl_net"]})
    divergents.sort(key=lambda x: -abs(x["ecart"]))
    return {"concordent": ok, "divergent": len(divergents),
            "pires": divergents[:10]}
