"""Le compte de démonstration pilote le compte réel (2026-08-06).

Demandé par Xavier après avoir refinancé le compte réel dans ce but précis :
plutôt que les deux comptes décidant en parallèle depuis le même signal, un
fill CONFIRMÉ en démo déclenche l'ouverture d'un ordre identique sur le réel.

⚠️ Ce que ces tests verrouillent en priorité, ce sont les façons dont un
miroir peut faire des dégâts :
  - se déclencher sur un push simplement accepté au lieu d'un fill confirmé ;
  - dupliquer une position si le même fill est rejoué ;
  - envoyer au courtier réel un symbole que seul l'autre courtier connaît ;
  - se déclencher dans le mauvais sens (le réel ne doit jamais piloter le démo).
"""
import pytest

from backend.services import mt5_bridge as mb


class _Dest:
    def __init__(self, dest_id, url="http://live", symbol_map=None):
        self.destination_id = dest_id
        self.bridge_url = url
        self.bridge_api_key = "cle"
        self.symbol_map = symbol_map
        self.user_id = None


def _setup():
    class S: pass
    s = S()
    s.pair = "WTI/USD"; s.direction = "buy"
    s.entry_price = 74.00; s.stop_loss = 73.40; s.take_profit_1 = 75.08
    s.take_profit_2 = None; s.confidence_score = 70.0
    return s


@pytest.fixture
def env(monkeypatch):
    """Miroir armé, destination réelle disponible, HTTP capturé."""
    import config.settings
    monkeypatch.setattr(config.settings, "MIRROR_DEMO_TO_LIVE_ENABLED", True)

    live = _Dest("admin_live", symbol_map={"WTI/USD": "WTI_N6"})
    monkeypatch.setattr(
        "backend.services.bridge_destinations._admin_live_destination", lambda: live
    )
    envoye = {}

    class _C:
        async def __aenter__(self_): return self_
        async def __aexit__(self_, *a): return False
        async def post(self_, url, json=None, headers=None):
            envoye["url"] = url
            envoye["payload"] = json
            class _R:
                status_code = 200
                text = ""
                def json(self_r): return {"ok": True, "ticket": 999, "volume": json.get("lots")}
            return _R()

    monkeypatch.setattr(mb.httpx, "AsyncClient", lambda *a, **k: _C())
    monkeypatch.setattr("backend.services.rejection_service.record_rejection",
                        lambda **k: None)

    poses = []
    monkeypatch.setattr(
        "backend.services.mt5_pushes_service.try_register_push",
        lambda *a, **k: poses.append(a) or True)
    monkeypatch.setattr(
        "backend.services.mt5_pushes_service.update_push_result", lambda *a, **k: None)
    monkeypatch.setattr(
        "backend.services.mt5_pushes_service.discard_push", lambda *a, **k: None)
    envoye["registres"] = poses
    return envoye


# ── Le miroir fait ce qu'on attend ────────────────────────────────────

@pytest.mark.asyncio
async def test_un_fill_demo_ouvre_un_ordre_reel(env):
    await mb._mirror_fill_to_live(
        _setup(), {"risk_money": 3.25}, {"volume": 0.02, "ticket": 1}, "admin_legacy")
    assert "live" in env["url"]
    assert env["payload"]["lots"] == pytest.approx(0.02), "le volume REMPLI est copié"


@pytest.mark.asyncio
async def test_le_symbole_est_celui_du_courtier_REEL(env):
    """Les deux courtiers ne nomment pas WTI pareil. Réutiliser le payload du
    démo enverrait un symbole qu'IC Markets ne connaît pas."""
    await mb._mirror_fill_to_live(
        _setup(), {"risk_money": 3.25}, {"volume": 0.01}, "admin_legacy")
    assert env["payload"].get("broker_symbol") == "WTI_N6"


# ── Les façons dont un miroir peut nuire ──────────────────────────────

@pytest.mark.asyncio
async def test_rien_ne_part_si_le_miroir_est_desarme(env, monkeypatch):
    import config.settings
    monkeypatch.setattr(config.settings, "MIRROR_DEMO_TO_LIVE_ENABLED", False)
    await mb._mirror_fill_to_live(
        _setup(), {"risk_money": 3.25}, {"volume": 0.01}, "admin_legacy")
    assert "url" not in env


@pytest.mark.asyncio
async def test_le_miroir_ne_va_que_dans_UN_sens(env):
    """Le réel ne doit jamais piloter le démo : ce serait une boucle."""
    await mb._mirror_fill_to_live(
        _setup(), {"risk_money": 3.25}, {"volume": 0.01}, "admin_live")
    assert "url" not in env


@pytest.mark.asyncio
async def test_un_fill_rejoue_n_ouvre_pas_deux_positions(env, monkeypatch):
    """La dedup passe par la base, comme un push normal."""
    monkeypatch.setattr(
        "backend.services.mt5_pushes_service.try_register_push", lambda *a, **k: False)
    await mb._mirror_fill_to_live(
        _setup(), {"risk_money": 3.25}, {"volume": 0.01}, "admin_legacy")
    assert "url" not in env


@pytest.mark.asyncio
async def test_destination_reelle_absente_ne_plante_pas(env, monkeypatch):
    monkeypatch.setattr(
        "backend.services.bridge_destinations._admin_live_destination", lambda: None)
    await mb._mirror_fill_to_live(
        _setup(), {"risk_money": 3.25}, {"volume": 0.01}, "admin_legacy")
    assert "url" not in env


@pytest.mark.asyncio
async def test_un_refus_du_courtier_reel_est_journalise_sans_lever(env, monkeypatch):
    """Le compte réel peut refuser (marge, plafond) — c'est attendu, et ça ne
    doit ni lever ni interrompre le flux démo."""
    class _C:
        async def __aenter__(self_): return self_
        async def __aexit__(self_, *a): return False
        async def post(self_, url, json=None, headers=None):
            class _R:
                status_code = 500
                text = '{"message":"No money"}'
                def json(self_r): return {}
            return _R()
    monkeypatch.setattr(mb.httpx, "AsyncClient", lambda *a, **k: _C())
    rejets = []
    monkeypatch.setattr("backend.services.rejection_service.record_rejection",
                        lambda **k: rejets.append(k))
    await mb._mirror_fill_to_live(
        _setup(), {"risk_money": 3.25}, {"volume": 0.01}, "admin_legacy")
    assert rejets and rejets[0]["destination_id"] == "admin_live"


# ─── ⛔ Une issue INCONNUE n'est pas un echec (2026-08-28) ────────────────

@pytest.mark.asyncio
async def test_une_exception_APRES_un_POST_ne_libere_PAS_la_reservation(
        monkeypatch):
    """⛔ La boucle de reprise poste jusqu'a quatre fois, avec des pauses de
    3, 10 et 20 s. Une exception levee APRES qu'une tentative a atteint le
    courtier effacait la ligne — donc autorisait un RETRY d'un ordre qui
    existe peut-etre deja.

    Un delai de 5 s cote client n'annule rien cote broker.

    > **Une issue inconnue n'est pas un echec.** Les traiter pareil transforme
    > un doute en second ordre.

    Semantique de `flag_unknown` du `PushLedger`, que les routes IBKR et
    Kraken appliquent deja ; le miroir, lui, effacait.
    """
    from backend.services import mt5_bridge, mt5_pushes_service

    appels = {"discard": 0, "marque": []}
    monkeypatch.setattr(mt5_pushes_service, "try_register_push",
                        lambda *a, **k: True)
    monkeypatch.setattr(mt5_pushes_service, "discard_push",
                        lambda *a, **k: appels.__setitem__(
                            "discard", appels["discard"] + 1))
    monkeypatch.setattr(mt5_pushes_service, "update_push_result",
                        lambda *a, **k: appels["marque"].append(k))

    class _ClientQuiLeveApresAvoirPoste:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise RuntimeError("le reseau lache APRES l'envoi")

    monkeypatch.setattr(mt5_bridge.httpx, "AsyncClient",
                        _ClientQuiLeveApresAvoirPoste)
    monkeypatch.setattr(mt5_bridge, "_mirror_active", lambda: True)
    monkeypatch.setattr(mt5_bridge, "_horizon_rejection", lambda s, d: None)
    monkeypatch.setattr(
        "backend.services.bridge_destinations._admin_live_destination",
        lambda: _Dest("admin_live"))

    await mt5_bridge._mirror_fill_to_live(
        _setup(), {"risk_money": 5.0}, {"ok": True, "ticket": 1, "volume": 0.01},
        "admin_legacy")

    assert appels["discard"] == 0, "la reservation a ete liberee malgre un POST parti"
    assert appels["marque"], "l'issue inconnue doit etre MARQUEE, pas effacee"
    assert appels["marque"][0]["ok"] is False
    assert appels["marque"][0]["response"]["issue"] == "inconnue"


@pytest.mark.asyncio
async def test_une_exception_AVANT_tout_POST_libere_bien_la_reservation(
        monkeypatch):
    """Le garde-fou ne doit pas empecher la liberation qu'il sert a encadrer :
    si rien n'est parti, aucun ordre ne peut exister."""
    from backend.services import mt5_bridge, mt5_pushes_service

    appels = {"discard": 0}
    monkeypatch.setattr(mt5_pushes_service, "try_register_push",
                        lambda *a, **k: True)
    monkeypatch.setattr(mt5_pushes_service, "discard_push",
                        lambda *a, **k: appels.__setitem__(
                            "discard", appels["discard"] + 1))
    monkeypatch.setattr(mt5_bridge, "_mirror_active", lambda: True)
    monkeypatch.setattr(mt5_bridge, "_horizon_rejection", lambda s, d: None)
    monkeypatch.setattr(
        "backend.services.bridge_destinations._admin_live_destination",
        lambda: _Dest("admin_live"))
    # Echoue a l'ouverture du client : aucun POST n'a pu partir.
    class _ClientQuiLeveALOuverture:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            raise RuntimeError("connexion impossible")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(mt5_bridge.httpx, "AsyncClient",
                        _ClientQuiLeveALOuverture)

    await mt5_bridge._mirror_fill_to_live(
        _setup(), {"risk_money": 5.0}, {"ok": True, "ticket": 1}, "admin_legacy")

    assert appels["discard"] == 1


# ── La porte dérobée ouverte par le gel par destination ───────────────

@pytest.mark.asyncio
async def test_le_miroir_ne_copie_pas_vers_un_compte_gele(env, monkeypatch):
    """Le plafond journalier du compte RÉEL doit arrêter la copie.

    Depuis que le gel est par destination (2026-09-03), la démo continue de
    trader quand le réel a atteint son plafond. Or le miroir ne rejoue pas
    les portes de DÉCISION : sans ce garde-fou, chaque fill démo rouvrirait
    une position sur le compte que le plafond venait de fermer, et le
    plafond ne protégerait plus rien.

    C'est le garde-fou qui rend le gel chirurgical sûr : les deux vont
    ensemble, retirer celui-ci rouvre la porte.
    """
    monkeypatch.setattr(
        "backend.services.kill_switch.is_active",
        lambda pair=None, destination_id=None: destination_id == "admin_live")

    await mb._mirror_fill_to_live(
        _setup(), {"risk_money": 3.25}, {"volume": 0.01}, "admin_legacy")

    assert "url" not in env, "un compte gelé ne doit rien recevoir du miroir"


@pytest.mark.asyncio
async def test_le_miroir_copie_quand_le_reel_n_est_PAS_gele(env, monkeypatch):
    """Le garde-fou ne doit pas fermer la vanne en permanence."""
    monkeypatch.setattr(
        "backend.services.kill_switch.is_active",
        lambda pair=None, destination_id=None: False)

    await mb._mirror_fill_to_live(
        _setup(), {"risk_money": 3.25}, {"volume": 0.01}, "admin_legacy")

    assert "live" in env["url"]


@pytest.mark.asyncio
async def test_un_kill_switch_illisible_ARRETE_la_copie(env, monkeypatch):
    """Ne pas pouvoir lire le garde-fou n'est pas une autorisation.

    Le doute doit fermer : c'est de l'argent réel, et l'inverse ferait d'une
    panne de lecture une porte grande ouverte.
    """
    def _explose(pair=None, destination_id=None):
        raise RuntimeError("état illisible")

    monkeypatch.setattr("backend.services.kill_switch.is_active", _explose)

    await mb._mirror_fill_to_live(
        _setup(), {"risk_money": 3.25}, {"volume": 0.01}, "admin_legacy")

    assert "url" not in env
