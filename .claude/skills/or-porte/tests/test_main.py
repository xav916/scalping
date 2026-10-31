"""Tests de `main()` : le contrat des codes de sortie et la banniere vivier.

Ni `collecter` ni `_lot_depuis_vivier` ne sont appeles reellement (reseau) --
ils sont monkeypatches, comme `or-etat` le fait pour les memes raisons.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import porte as P  # noqa: E402

S = {"pair": "XAU/USD", "direction": "buy", "entry_price": 2412.50,
     "stop_loss": 2404.10, "confidence_score": 71, "pattern": "range_bounce",
     "horizon": "30min", "chaine": None, "shadow_system_id": None,
     "is_simulated": False, "verdict_blockers": [], "risk_pct": 0.35}

LOT = {"destinations": ["admin_live"], "setups": [S]}

LIM_OK = {"order_cooldown_sec": 0, "max_risque_engage_pct": 5.0,
         "max_risque_engage_or_argent_pct": 15.0, "max_open_positions": 2}


def _brut(**kw):
    base = {
        "fingerprint_running": "a4d9aedeee17",
        "rem002_allowed": False, "rem002_reason": "DISARMED_MANUALLY",
        "verdicts": [{"i": 0, "destination": "admin_live",
                      "reason_code": None, "classe": "metal",
                      "admission": "AUTO_EXEC"}],
        "limites": {"admin_live": dict(LIM_OK)},
        "libelles": {}, "sans_libelle": [],
    }
    base.update(kw)
    return base


# ──────────────────────────────────────────────────────────────────────
# Important 3 : `juger()` n'est plus nu dans `main()` -- une valeur
# `/health` non numerique ne doit JAMAIS faire sortir Python en 1, le code
# reserve a « au moins un BLOCK ».
# ──────────────────────────────────────────────────────────────────────

def test_une_limite_non_numerique_rend_2_jamais_1(tmp_path, monkeypatch, capsys):
    lot_path = tmp_path / "lot.json"
    lot_path.write_text(json.dumps(LOT), encoding="utf-8")

    brut = _brut()
    brut["limites"]["admin_live"]["order_cooldown_sec"] = "pas-un-nombre"
    monkeypatch.setattr(P, "collecter", lambda depot, lot_valide: brut)

    code = P.main(["--lot", str(lot_path), "--no-write"])

    assert code == 2, "une valeur illisible ne doit jamais rendre 1"
    sortie = capsys.readouterr().out
    assert "ECHEC" in sortie


def test_un_lot_entierement_passe_rend_bien_0(tmp_path, monkeypatch):
    """Temoin : le chemin heureux n'est pas casse par le wrap."""
    lot_path = tmp_path / "lot.json"
    lot_path.write_text(json.dumps(LOT), encoding="utf-8")
    monkeypatch.setattr(P, "collecter", lambda depot, lot_valide: _brut())

    code = P.main(["--lot", str(lot_path), "--no-write"])
    assert code == 0


# ──────────────────────────────────────────────────────────────────────
# Important 4 : la banniere `--depuis-vivier` doit nommer TOUS les champs
# fabriques, pas seulement le prix.
# ──────────────────────────────────────────────────────────────────────

def test_la_banniere_vivier_nomme_tous_les_champs_fabriques(monkeypatch, capsys):
    lot_vivier = {"destinations": ["admin_live"], "setups": [
        {"pair": "XAU/USD", "direction": "buy", "entry_price": 0.0,
         "stop_loss": 0.0, "confidence_score": 100, "pattern": None,
         "horizon": None, "chaine": None, "shadow_system_id": None,
         "is_simulated": False, "verdict_blockers": [], "risk_pct": 0.0}]}
    monkeypatch.setattr(P, "_lot_depuis_vivier",
                        lambda depot, dest: lot_vivier)
    monkeypatch.setattr(P, "collecter", lambda depot, lot_valide: _brut())

    code = P.main(["--depuis-vivier", "admin_kraken", "--no-write"])

    assert code == 0
    sortie = capsys.readouterr().out
    for attendu in ("entry_price=0", "stop_loss=0", "confidence_score=100",
                    "below_confidence", "verdict_blockers=[]",
                    "is_simulated=False", "simulated_data",
                    "pattern=None", "horizon=None", "chaine=None",
                    "shadow_system_id=None", "risk_pct=0.0",
                    "lot_risque_engage"):
        assert attendu in sortie, "banniere vivier incomplete : %r manquant" % attendu


# ─── `--json` doit rester du JSON, SURTOUT sur l'echec (2026-10-31) ───────
#
# Le defaut : `--json` n'agissait qu'a la toute fin. Chaque echec precoce
# imprimait de la PROSE, donc un consommateur machine recevait du texte non
# analysable avec un code 2. Et quand `juger` rendait 2 avec un etat vide,
# `--json` imprimait `{}` : du JSON valide qui ne dit RIEN.
#
# 🔑 Un mode machine qui retombe en prose sur l'echec est pire qu'absent : il
# marche a tous les essais sauf celui ou l'on a besoin de savoir pourquoi.

def _json_de(sortie):
    """Le dernier objet JSON imprime, ou l'echec du test."""
    import json as _j
    debut = sortie.find("{")
    assert debut >= 0, "aucun objet JSON dans la sortie : %r" % sortie[:200]
    return _j.loads(sortie[debut:])


def test_un_lot_ILLISIBLE_rend_du_JSON_en_mode_json(tmp_path, capsys):
    """⛔ LE test qui compte : un fichier absent est un echec PRECOCE."""
    code = P.main(["--lot", str(tmp_path / "jamais.json"), "--json",
                   "--no-write"])
    assert code == 2
    d = _json_de(capsys.readouterr().out)
    assert d["code"] == 2
    assert d["verdict"] == "ECHEC"
    assert d["motif"], "le motif doit etre nomme"
    assert d["cause"], "la cause doit etre nommee"
    assert d["etat"] is None


def test_un_lot_NON_JUGEABLE_rend_du_JSON(tmp_path, capsys):
    """Un lot syntaxiquement bon mais invalide : meme exigence."""
    f = tmp_path / "lot.json"
    f.write_text('{"setups": [{"pair": "XAU/USD"}]}', encoding="utf-8")
    code = P.main(["--lot", str(f), "--json", "--no-write"])
    assert code == 2
    d = _json_de(capsys.readouterr().out)
    assert d["code"] == 2 and d["verdict"] == "ECHEC"
    assert d["etat"] is None


def test_en_mode_HUMAIN_l_echec_reste_de_la_prose(tmp_path, capsys):
    """La correction ne doit pas transformer le mode humain en JSON."""
    code = P.main(["--lot", str(tmp_path / "jamais.json"), "--no-write"])
    assert code == 2
    sortie = capsys.readouterr().out
    assert "ECHEC" in sortie
    assert not sortie.lstrip().startswith("{"), "le mode humain reste lisible"


def test_le_motif_et_la_cause_ne_se_confondent_pas(tmp_path, capsys):
    """Le motif classe l'echec, la cause le detaille. Deux champs, parce
    qu'un consommateur veut trier sur le premier sans lire le second."""
    P.main(["--lot", str(tmp_path / "jamais.json"), "--json", "--no-write"])
    d = _json_de(capsys.readouterr().out)
    assert d["motif"] != d["cause"]
    assert d["motif"] in ("lot illisible", "lot non jugeable")
