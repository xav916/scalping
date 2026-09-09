"""Le courtier n'enregistre pas la position à l'instant du remplissage.

⛔ MESURE DU 2026-09-09, compte réel, sur les poussées où le champ existe :

    fill_source   sl_applied=True   sl_applied=False
    result              56                 0
    position            35                 0
    None                 5                 0
    requested           14                 6      ← les SIX echecs sont ICI

`fill_source="requested"` n'est pas un détail de mesure : c'est le DERNIER
repli de `_resolve_fill_price`, celui qu'on n'atteint qu'après avoir essayé
`positions_get(ticket)` **et n'avoir rien trouvé**. Il dit donc littéralement
« la position n'était pas visible ».

Et la ligne suivante envoie `TRADE_ACTION_SLTP` avec `"position": ticket` sur
cette même position invisible. MT5 répond `Invalid request`, le stop n'est pas
posé, et la position vit NUE jusqu'au passage du garde-fou — jusqu'à 60 s.

🔑 Les 14 `requested` qui RÉUSSISSENT quand même prouvent que ce n'est pas
déterministe : la position est apparue entre les deux appels. **C'est une
course**, et le bridge ne l'attend pas. Preuve indépendante : le garde-fou
rejoue exactement la même requête 50 s plus tard, sur le même ticket, et
obtient `retcode=10009`.

⇒ Attendre que le courtier enregistre la position répare les DEUX symptômes
d'un coup : le prix de remplissage redevient mesurable (`position` au lieu de
`requested`, ce dont dépend toute la statistique de glissement) et le stop se
pose.

⚠️ L'attente est BORNÉE. Un `/order` qui bloque indéfiniment serait pire que le
défaut qu'il répare : le garde-fou reste le filet, il n'est pas remplacé.

Cf. [[project_analyse_clotures_main_2026_08_24]] ·
    [[project_entry_price_absent_reel_2026_08_24]]
"""
import logging
import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


class _MT5:
    """Courtier simulé : la position n'apparaît qu'après N interrogations."""

    def __init__(self, apparait_au_bout_de: int | None):
        self.apparait_au_bout_de = apparait_au_bout_de
        self.appels = 0

    def positions_get(self, ticket=None):
        self.appels += 1
        if self.apparait_au_bout_de is None:
            return ()
        if self.appels >= self.apparait_au_bout_de:
            return (types.SimpleNamespace(ticket=ticket, price_open=4447.47),)
        return ()


class _MT5QuiLeve(_MT5):
    def positions_get(self, ticket=None):
        self.appels += 1
        raise RuntimeError("terminal deconnecte")


@pytest.fixture(scope="module")
def source() -> str:
    return _SRC.read_text(encoding="utf-8")


def _module(source: str, mt5, dormir):
    """Extrait `_attendre_la_position` et l'exécute seule, sans MetaTrader5."""
    debut = source.index("def _attendre_la_position(")
    fin = source.index("def _resolve_fill_price(")
    mod = types.ModuleType("bridge_attente")
    faux_temps = {"t": 0.0}

    def monotonic():
        return faux_temps["t"]

    def sleep(s):
        faux_temps["t"] += s
        dormir.append(s)

    mod.__dict__["mt5"] = mt5
    mod.__dict__["time"] = types.SimpleNamespace(monotonic=monotonic, sleep=sleep)
    mod.__dict__["logger"] = logging.getLogger("bridge_attente")
    exec(compile(source[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


def test_la_position_deja_la_ne_fait_pas_attendre(source):
    """Le cas nominal — 91 remplissages sur 116 — ne doit rien coûter."""
    dormir: list[float] = []
    mod = _module(source, _MT5(apparait_au_bout_de=1), dormir)

    assert mod._attendre_la_position(1357451117) is True
    assert dormir == [], "le cas nominal a attendu alors que la position était là"


def test_la_position_qui_tarde_est_attendue(source):
    """⛔ Le cœur du défaut : elle arrive, mais quelques dizaines de ms trop tard."""
    dormir: list[float] = []
    mt5 = _MT5(apparait_au_bout_de=4)
    mod = _module(source, mt5, dormir)

    assert mod._attendre_la_position(1357451117) is True
    assert mt5.appels >= 4
    assert dormir, "aucune attente : la course n'est pas fermée"


def test_l_attente_est_BORNEE(source):
    """⚠️ Un `/order` qui bloque serait pire que le défaut réparé."""
    dormir: list[float] = []
    mod = _module(source, _MT5(apparait_au_bout_de=None), dormir)

    assert mod._attendre_la_position(1357451117, delai_max_s=1.0) is False
    assert sum(dormir) <= 1.0 + 1e-9, (
        f"l'attente a depasse sa borne : {sum(dormir)} s"
    )


def test_un_courtier_qui_LEVE_ne_fait_pas_echouer_l_ordre(source):
    """L'ordre est DÉJÀ passé quand on appelle : lever ici perdrait le ticket.

    On rend False — « pas vue » — et l'appelant fait ce qu'il faisait avant.
    """
    dormir: list[float] = []
    mod = _module(source, _MT5QuiLeve(apparait_au_bout_de=None), dormir)

    assert mod._attendre_la_position(1357451117, delai_max_s=0.2) is False


def test_le_bridge_attend_AVANT_de_resoudre_le_prix_et_de_poser_le_stop(source):
    """La règle ne vaut que si elle est appelée au bon endroit.

    ⛔ Un test qui ne vérifie que la fonction isolée passerait au vert avec un
    correctif jamais branché — c'est exactement ce qui a laissé `_resolve_fill_price`
    exister deux mois sans que l'audit s'en serve.
    """
    appel = source.index("_attendre_la_position(result.order")
    resolution = source.index("_resolve_fill_price(result, price)")
    pose = source.index("sltp_result = _apply_sltp_from_fill(")

    assert appel < resolution, (
        "l'attente doit précéder la résolution du prix, sinon `fill_source` "
        "retombe sur `requested`"
    )
    assert appel < pose, "l'attente doit précéder la pose du stop"
