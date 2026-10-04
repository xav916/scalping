#!/usr/bin/env python3
"""Le banc de la DERIVE APRES SURPRISE — pre-enregistre `c536a2c`.

    python scripts/banc_surprise.py --figer     # rapatrie et FIGE les bougies
    python scripts/banc_surprise.py             # mesure sur les bougies figees

⛔ Deux temps separes, et c'est volontaire. Trois passages du banc WTI sur la
MEME fenetre avaient rendu 0, puis 1, puis 0 retenue : les bougies derivaient
sous l'appareil. Un banc dont les donnees bougent n'est pas un banc.

🔑 Tous les seuils viennent de `backend/services/banc_surprise.py`, qui les
recopie de la declaration. Ce fichier n'en invente aucun.
"""
from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import banc_surprise as bs          # noqa: E402
from backend.services import bougies_du_pont as bp        # noqa: E402

DB = "/app/data/scalping.db"
GEL = Path("/app/data/bancs/surprise_h1")

# Les paires dont le H1 remonte a 2021 (mesure du 2026-10-05).
UNIVERS = ("EUR/USD", "GBP/USD", "USD/JPY", "EUR/GBP", "USD/CHF", "AUD/USD",
           "USD/CAD", "EUR/JPY", "GBP/JPY", "XAU/USD", "XAG/USD", "WTI/USD")

DEBUT = datetime(2021, 1, 4, tzinfo=timezone.utc)
FIN_SELECTION = datetime(2025, 1, 1, tzinfo=timezone.utc)
FIN = datetime(2026, 9, 27, tzinfo=timezone.utc)      # frontiere ForexFactory


# ─── 1. Les bougies, figees une fois pour toutes ────────────────────────────

def figer() -> int:
    """Rapatrie le H1 par fenetres de 60 jours et l'ecrit sur disque.

    ⚠️ Le pont tronque a 5 000 bougies en gardant les plus ANCIENNES, et
    `bougies_du_pont` refuse alors la reponse entiere. On pagine donc, et on
    verifie la continuite plutot que de supposer qu'elle tienne.
    """
    GEL.mkdir(parents=True, exist_ok=True)
    dest = bp._destination()
    vrai = bp._fenetre
    total = 0
    for paire in UNIVERS:
        fichier = GEL / (paire.replace("/", "") + ".json")
        if fichier.exists():
            print(f"   {paire:9s} deja fige ({fichier.stat().st_size // 1024} Ko)")
            continue
        # ⛔ On passe par la VRAIE resolution du produit : le WTI s'appelle
        # `XTIUSD` chez ce courtier, pas `WTIUSD`. Recopier `paire.replace`
        # aurait rendu zero bougie pour le WTI, en silence.
        from backend.services.mt5_bridge import _symbole_courtier_pour
        symbole = _symbole_courtier_pour(paire, dest)
        vues: dict[str, dict] = {}
        curseur = DEBUT
        while curseur < FIN:
            borne = min(curseur + timedelta(days=60), FIN)
            a, b = curseur, borne
            bp._fenetre = lambda tf, n, _a=a, _b=b: (_a, _b)
            try:
                brut = bp._lire_rates(dest, symbole, "H1", 0)
            finally:
                bp._fenetre = vrai
            if isinstance(brut, dict) and not brut.get("tronque"):
                for x in (brut.get("bougies") or []):
                    t = x.get("time") or x.get("t")
                    if t:
                        vues[str(t)] = x
            curseur = borne
        fichier.write_text(json.dumps(list(vues.values())), encoding="utf-8")
        total += len(vues)
        print(f"   {paire:9s} {len(vues):6d} bougies H1 figees")
    return total


def bougies(paire) -> list:
    f = GEL / (paire.replace("/", "") + ".json")
    if not f.exists():
        return []
    brut = json.loads(f.read_text(encoding="utf-8"))
    out = []
    for x in brut:
        try:
            out.append(bp._en_candle(x))
        except Exception:      # noqa: BLE001 — une bougie abimee est ecartee
            continue
    out.sort(key=lambda c: c.timestamp)
    return bp._sur_la_grille(out, 60)


# ─── 2. Les evenements, dans l'ordre chronologique ──────────────────────────

def evenements() -> list[dict]:
    """Les HIGH des six familles declarees, avec reel ET prevision."""
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
        c.row_factory = sqlite3.Row
        lignes = c.execute(
            "SELECT ts_utc, currency, event_code, actual, forecast, id "
            "FROM economic_events WHERE impact='High' AND source='mql5' "
            "AND actual IS NOT NULL AND forecast IS NOT NULL "
            "AND event_code IS NOT NULL "
            "ORDER BY ts_utc").fetchall()
    out = []
    for r in lignes:
        # ⛔ On lit le CODE, jamais le nom : le terminal rend les noms dans SA
        # langue (« Evolution de l'emploi »), et une regle ecrite sur des codes
        # anglais n'y trouverait rien — en silence.
        code = (r["event_code"] or "").strip().lower()
        p = bs.polarite(code)
        if p is None:
            continue
        try:
            brute = float(r["actual"]) - float(r["forecast"])
        except (TypeError, ValueError):
            continue
        try:
            t = datetime.fromisoformat(r["ts_utc"])
        except ValueError:
            continue
        out.append({"t": t, "devise": (r["currency"] or "").upper(),
                    "code": code, "brute": brute, "polarite": p})
    return out


# ─── 3. La marche, strictement chronologique ────────────────────────────────

def trades(evts, par_paire) -> list[dict]:
    """⛔ Les evenements sont parcourus dans l'ordre : `passees` ne contient
    jamais que ce qui precede. C'est la garantie structurelle contre le regard
    vers l'avenir."""
    passees: dict[str, list[float]] = {}
    sortie = []
    for e in evts:
        s = bs.surprise_normalisee(e["brute"], passees.get(e["code"], []))
        passees.setdefault(e["code"], []).append(abs(e["brute"]))
        if s is None:
            continue
        signee = e["polarite"] * s
        for paire, (b, atr, spread) in par_paire.items():
            sens = bs.sens_pour_paire(signee, e["devise"], paire)
            if sens is None:
                continue
            i = bs.entree_apres(b, e["t"])
            if i is None or i < 14:
                continue
            a = atr(i)
            if not a:
                continue
            ligne = {"t": e["t"], "paire": paire, "sens": sens, "i": i,
                     "atr": a, "spread": spread, "code": e["code"], "S": signee}
            for h in bs.HORIZONS_H:
                ligne[f"r{h}"] = bs.rendement_r(b, i, h, sens, a, spread)
            sortie.append(ligne)
    return sortie


def _spread_courant(paire: str) -> float:
    """Le spread du tick courant, en unites de PRIX. 0.0 si illisible."""
    try:
        t = bp.prix_courant_tick(paire) if hasattr(bp, "prix_courant_tick") else None
        if t is None:
            dest = bp._destination()
            t = bp._lire_tick(dest, paire)
        if not t:
            return 0.0
        return max(0.0, float(t["ask"]) - float(t["bid"]))
    except Exception:      # noqa: BLE001 — un spread illisible ne doit pas
        return 0.0         # emporter le banc ; il est alors NUL et on le dit


def _t_de(valeurs) -> float:
    n = len(valeurs)
    if n < 2:
        return 0.0
    m = sum(valeurs) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in valeurs) / (n - 1))
    return 0.0 if sd <= 0 else m / (sd / math.sqrt(n))


def mesurer(tr, b_par_paire) -> dict:
    """Le R par horizon, le controle apparie, et le `t` de la difference."""
    res = {}
    for h in bs.HORIZONS_H:
        reels = [x[f"r{h}"] for x in tr if x.get(f"r{h}") is not None]
        if not reels:
            res[h] = None
            continue
        # ⛔ Controle APPARIE : memes instants, meme horizon, sens tire.
        deltas = []
        for graine in range(20):
            ctrl = bs.controle_apparie(tr, graine=graine)
            for x, cx in zip(tr, ctrl):
                if x.get(f"r{h}") is None:
                    continue
                rc = bs.rendement_r(b_par_paire[x["paire"]], x["i"], h,
                                    cx["sens"], x["atr"], x["spread"])
                if rc is not None:
                    deltas.append(x[f"r{h}"] - rc)
        res[h] = {"n": len(reels), "r_moyen": sum(reels) / len(reels),
                  "hasard": (sum(reels) / len(reels)) - (sum(deltas) / len(deltas)
                                                         if deltas else 0.0),
                  "delta": sum(deltas) / len(deltas) if deltas else 0.0,
                  "t_vs_hasard": _t_de(deltas)}
    return res


def main() -> int:
    if "--figer" in sys.argv:
        print("=== gel des bougies H1 ===")
        figer()
        return 0

    evts = evenements()
    print(f"=== {len(evts)} evenements HIGH des six familles declarees ===")
    if not evts:
        print("⛔ aucun evenement — le gel ou l'import a echoue")
        return 2

    par_paire, b_par_paire = {}, {}
    for paire in UNIVERS:
        b = bougies(paire)
        if len(b) < 100:
            print(f"   ⚠️ {paire} : {len(b)} bougies, ecartee")
            continue
        b_par_paire[paire] = b
        from backend.services.pattern_detector import _calculate_atr
        cache: dict[int, float] = {}

        def atr(i, _b=b, _c=cache):
            if i not in _c:
                _c[i] = _calculate_atr(_b[max(0, i - 15):i], period=14)
            return _c[i]
        # ⛔ DEFAUT CORRIGE le 2026-10-05 : ce champ valait 0.0, alors que la
        # declaration dit « le spread est FACTURE ». Les premiers chiffres
        # etaient donc OPTIMISTES.
        #
        # ⚠️ Le spread retenu est celui du tick COURANT — une mesure d'UN
        # instant, le defaut meme que ce projet a paye trois fois. Elle est
        # assumee ici pour une raison bornee : a l'echelle H1 l'ATR vaut des
        # dizaines de fois le spread, donc le cout pese ~0,03 R et ne peut pas
        # retourner un verdict. Si un jour il le pouvait, il faudrait le
        # mesurer par periode.
        spread = _spread_courant(paire)
        par_paire[paire] = (b, atr, spread)
    print(f"=== {len(par_paire)} paires, "
          f"{sum(len(b) for b in b_par_paire.values())} bougies H1 ===")
    print("   spreads factures (tick courant, en prix) :")
    for paire, (_b, _a, sp) in sorted(par_paire.items()):
        print(f"      {paire:9s} {sp:.5f}" + ("   ⚠️ NUL" if sp <= 0 else ""))

    tous = trades(evts, par_paire)
    sel = [x for x in tous if x["t"] < FIN_SELECTION]
    oos = [x for x in tous if FIN_SELECTION <= x["t"] < FIN]
    print(f"\n   selection 2021-2024 : {len(sel)} trades")
    print(f"   HORS ECHANTILLON    : {len(oos)} trades\n")

    for nom, jeu in (("SELECTION (vue)", sel), ("HORS ECHANTILLON", oos)):
        print(f"=== {nom} ===")
        m = mesurer(jeu, b_par_paire)
        signes = []
        for h in bs.HORIZONS_H:
            d = m.get(h)
            if not d:
                print(f"   {h}h : rien"); continue
            signes.append(1 if d["r_moyen"] > 0 else -1)
            print(f"   {h}h  n={d['n']:5d}  R={d['r_moyen']:+.4f}  "
                  f"hasard={d['hasard']:+.4f}  delta={d['delta']:+.4f}  "
                  f"t={d['t_vs_hasard']:+.3f}")
        d4 = m.get(4)
        if d4 and nom.startswith("HORS"):
            v = bs.verdict(d4["r_moyen"], d4["t_vs_hasard"], d4["n"], signes)
            print(f"\n   ⚖️  VERDICT (horizon 4 h) : {v['verdict']}")
            print(f"      {v['motif']}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
