# ─── Historique des TICKS (2026-10-10) ───────────────────────────────────
#
# Pose pour repondre a UNE question, et elle est mesurable : les ticks d'un CFD
# sur l'or portent-ils l'information ACHETEUR / VENDEUR ?
#
# 🔑 POURQUOI ELLE COMPTE. Le document GOLD MICROTRADER V1 (§9) fonde un de ses
# signaux sur `TickImbalance = (UpTicks - DownTicks) / (UpTicks + DownTicks)`.
# C'est le SEUL element de ce document qui n'a pas pu etre refute le 2026-10-10,
# faute de donnee : `/rates` ne rend que `tv`, le nombre TOTAL de ticks de la
# bougie, jamais sa repartition. Toutes les autres pistes de direction ont ete
# fermees ce jour-la (motifs, indicateurs, dollar, taux, calendrier).
#
# ⛔ CE QUE CETTE ROUTE NE FAIT PAS : aucun ordre, aucune modification, aucune
# ecriture. Elle lit `copy_ticks_range` et rend du JSON. C'est la raison pour
# laquelle elle peut exister a cote de l'argent reel.
#
# ⚠️ LES TICKS SONT DENSES. Une minute d'or peut en porter plusieurs centaines :
# la ou `/rates` plafonne a 5 000 bougies, on plafonne ici a MAX_TICKS et on
# rend `suite_from`, exactement comme `/rates`.
#
# 🔑 ET LA REPONSE UTILE TIENT DANS LE RESUME, pas dans les ticks. `resume=1`
# rend les COMPTES sans le detail : c'est ce qu'il faut pour savoir si
# l'information existe, sans telecharger des centaines de milliers de lignes.

MAX_TICKS = int(os.getenv("TICKS_MAX", "20000"))
TRANCHE_TICKS_SEC = int(os.getenv("TICKS_TRANCHE_SEC", "3600"))

# Les drapeaux de MetaTrader 5, nommes ici pour que la reponse se lise.
_DRAPEAUX_TICK = (
    ("bid", 2), ("ask", 4), ("last", 8), ("volume", 16),
    ("buy", 32), ("sell", 64),
)


def _classer_ticks(ticks):
    """Compte les ticks montants / descendants, de DEUX facons.

    1. **Par les drapeaux** `TICK_FLAG_BUY` / `TICK_FLAG_SELL` : c'est le vrai
       sens de la transaction, celui du §9. ⚠️ Sur un CFD il n'y a pas de
       carnet d'ordres centralise, donc ces drapeaux peuvent ne JAMAIS
       apparaitre — et c'est precisement ce qu'on vient verifier.

    2. **Par la variation du BID** (la regle classique du uptick / downtick) :
       disponible quoi qu'il arrive, mais c'est un SUBSTITUT. Un bid qui monte
       n'est pas une transaction a l'achat.

    🔑 Rendre les deux cote a cote est le seul moyen de savoir si le substitut
    vaut quelque chose : si les drapeaux existent, on peut les comparer.
    """
    par_drapeau = {nom: 0 for nom, _ in _DRAPEAUX_TICK}
    hausse = baisse = egal = 0
    precedent = None
    for t in ticks:
        f = int(t["flags"])
        for nom, bit in _DRAPEAUX_TICK:
            if f & bit:
                par_drapeau[nom] += 1
        bid = float(t["bid"])
        if precedent is not None:
            if bid > precedent:
                hausse += 1
            elif bid < precedent:
                baisse += 1
            else:
                egal += 1
        precedent = bid
    n_dir = hausse + baisse
    n_bs = par_drapeau["buy"] + par_drapeau["sell"]
    return {
        # par les drapeaux — la vraie question
        "drapeaux": par_drapeau,
        "imbalance_drapeaux": (
            (par_drapeau["buy"] - par_drapeau["sell"]) / n_bs if n_bs else None),
        # par la variation du bid — le substitut
        "bid_hausse": hausse, "bid_baisse": baisse, "bid_egal": egal,
        "imbalance_bid": ((hausse - baisse) / n_dir) if n_dir else None,
        # ⛔ LA REPONSE A LA QUESTION POSEE, explicite et non deductible
        "sens_reel_disponible": n_bs > 0,
    }


@app.route("/ticks", methods=["GET"])
@require_api_key
def ticks():
    """Historique des ticks entre deux instants. LECTURE SEULE.

    Parametres : pair, from, to (ISO 8601, UTC), resume (0/1).

    ⚠️ Comme pour `/rates`, les bornes envoyees sont en UTC et converties en
    heure SERVEUR ici. Le decalage mesure est renvoye pour que l'appelant
    puisse verifier plutot que croire.
    """
    pair = request.args.get("pair", "")
    resume_seul = str(request.args.get("resume", "0")).strip() in ("1", "true",
                                                                  "yes", "on")
    if not pair:
        return jsonify({"error": "pair requis"}), 400
    try:
        debut = datetime.fromisoformat(request.args["from"].replace("Z", "+00:00"))
        fin = datetime.fromisoformat(request.args["to"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return jsonify({"error": "from et to requis, en ISO 8601"}), 400
    # ⛔ Meme defaut latent que `/rates` avait le 2026-10-08 : une borne naive
    # et l'autre aware faisaient LEVER la comparaison. Les bornes sont
    # documentees UTC, donc on declare l'UTC pour celle qui se taît.
    if debut.tzinfo is None:
        debut = debut.replace(tzinfo=timezone.utc)
    if fin.tzinfo is None:
        fin = fin.replace(tzinfo=timezone.utc)
    if fin <= debut:
        return jsonify({"error": "to doit suivre from"}), 400

    if not ensure_mt5_connected():
        return jsonify({"error": "MT5 not connected"}), 503
    symbole = resolve_symbol(pair)
    if not symbole:
        return jsonify({"error": f"symbole introuvable pour {pair}"}), 404

    decalage = _decalage_serveur_sec() or 0
    drapeau = getattr(mt5, "COPY_TICKS_ALL", 3)

    # Decoupage par tranches de temps, comme `/rates` decoupe par barres : une
    # plage large n'est pas refusee pour ses donnees mais pour sa largeur.
    brut, tranches, ratees, derniere = [], 0, 0, None
    curseur = debut
    while curseur < fin and len(brut) < MAX_TICKS and tranches < 500:
        borne = min(curseur + timedelta(seconds=TRANCHE_TICKS_SEC), fin)
        a_srv = datetime.fromtimestamp(curseur.timestamp() + decalage,
                                       tz=timezone.utc)
        b_srv = datetime.fromtimestamp(borne.timestamp() + decalage,
                                       tz=timezone.utc)
        part = mt5.copy_ticks_range(symbole, a_srv, b_srv, drapeau)
        tranches += 1
        if part is None:
            # ⛔ Une tranche ratee ne doit pas annuler les autres, mais elle
            # doit se COMPTER : un trou doit se lire, pas se deviner.
            ratees += 1
            logger.warning("ticks: tranche %s -> %s refusee par le terminal (%s)",
                           curseur.isoformat(), borne.isoformat(),
                           mt5.last_error())
        else:
            brut.extend(part)
            derniere = borne
        curseur = borne

    if not brut and ratees:
        return jsonify({
            "error": f"copy_ticks_range a echoue: {mt5.last_error()}",
            "tranches": tranches, "tranches_ratees": ratees,
        }), 502

    brut.sort(key=lambda x: (int(x["time_msc"]), int(x["flags"])))
    tronque = len(brut) > MAX_TICKS
    gardes = brut[:MAX_TICKS]
    resume = _classer_ticks(gardes)

    suite = None
    if tronque and gardes:
        suite = datetime.fromtimestamp(
            float(gardes[-1]["time"]) - decalage, tz=timezone.utc).isoformat()
    elif derniere is not None and derniere < fin:
        suite = derniere.isoformat()

    reponse = {
        "pair": pair,
        "symbole": symbole,
        "decalage_serveur_sec": decalage,
        "point": float(getattr(mt5.symbol_info(symbole), "point", 0) or 0),
        "tronque": tronque,
        "tranches": tranches,
        "tranches_ratees": ratees,
        "suite_from": suite,
        "n": len(gardes),
        "resume": resume,
    }
    if not resume_seul:
        reponse["ticks"] = [{
            "t": datetime.fromtimestamp(float(x["time"]) - decalage,
                                        tz=timezone.utc).isoformat(),
            "ms": int(x["time_msc"]),
            "bid": float(x["bid"]),
            "ask": float(x["ask"]),
            "last": float(x["last"]),
            "vol": float(x["volume"]),
            "flags": int(x["flags"]),
        } for x in gardes]
    return jsonify(reponse)


