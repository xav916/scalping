"""Le laboratoire ignorait l'heure — et une chaîne pouvait se briser en route.

Deux manques comblés le 2026-09-12.

## 1. Les sessions

Aucune notion d'heure nulle part. Or « opening range », « killzone » et
« comportement du Gold dans son range d'open » sont tous des objets horaires :
sans session, ils ne sont pas exprimables.

⛔ **Heures LOCALES de chaque place, jamais UTC fixe.** Londres et New York
changent d'heure, et à des dates différentes de l'Europe continentale. Des
bornes en UTC fixe décaleraient les sessions d'une heure **la moitié de
l'année** — et la mesure dirait « ce motif marche le matin » en ayant regardé
deux fenêtres différentes selon la saison.

⚠️ Ces bornes sont une **convention déclarée**, pas une mesure. Elles ne sont
la propriété de personne : ce sont les horaires d'ouverture publics des
places. Si un jour on les déplace, ce sera un choix à écrire, pas un réglage à
optimiser.

## 2. L'invalidation

Une chaîne accepte un maillon jusqu'à 30 bougies avant son déclencheur. Rien
n'interdisait qu'entre les deux, le marché ait fait **exactement le contraire**
— un balayage haussier, puis une cassure baissière, puis la cassure haussière
du déclencheur. La chaîne se déclenchait quand même, sur un maillon que les
faits avaient déjà démenti.

🔑 `invalidants` nomme ce qui tue la chaîne s'il apparaît **entre** le maillon
et le déclencheur. Sans lui, la fenêtre de 30 bougies était une passoire.

## ⚠️ Le coût, assumé

Ajouter des chaînes relève le plafond du hasard pour TOUT LE MONDE. C'est
voulu : mesurer plus doit coûter plus cher à prouver.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import laboratoire_or as labo


class _Pat:
    def __init__(self, nom): self.pattern = nom


class _Dir:
    def __init__(self, v): self.value = v


class _Setup:
    def __init__(self, nom, sens, entree=4000.0, stop=3960.0, tp=4080.0):
        self.pattern = _Pat(nom)
        self.direction = _Dir(sens)
        self.entry_price = entree
        self.stop_loss = stop
        self.take_profit_1 = tp


def _bougies_a(heure_utc: int, n=80, comme_datetime=False):
    """`n` bougies de 5 min démarrant à `heure_utc` le 2026-09-11 (jeudi)."""
    t0 = datetime(2026, 9, 11, heure_utc, 0, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        t = t0 + timedelta(minutes=5 * i)
        out.append({"t": t if comme_datetime else t.isoformat(),
                    "o": 4000.0, "h": 4010.0, "l": 3990.0, "c": 4005.0,
                    "s": 24, "tv": 100})
    return out


# ─── Les sessions ───────────────────────────────────────────────────


def test_les_sessions_sont_DECLAREES():
    for nom in ("session_londres", "session_newyork", "session_asie",
                "killzone_londres", "killzone_newyork"):
        assert nom in labo._PREDICATS, f"{nom} n'est pas un predicat connu"


def test_londres_OUI_a_9h_locales_NON_a_3h():
    """09:00 à Londres = 08:00 UTC en heure d'été britannique."""
    assert labo._PREDICATS["session_londres"](_bougies_a(8), 5)
    assert not labo._PREDICATS["session_londres"](_bougies_a(3), 5)


def test_new_york_OUI_l_apres_midi_NON_le_matin():
    """14:00 UTC = 10:00 à New York en heure d'été. 06:00 UTC = 02:00."""
    assert labo._PREDICATS["session_newyork"](_bougies_a(14), 5)
    assert not labo._PREDICATS["session_newyork"](_bougies_a(6), 5)


def test_l_asie_couvre_la_nuit_europeenne():
    assert labo._PREDICATS["session_asie"](_bougies_a(2), 5)
    assert not labo._PREDICATS["session_asie"](_bougies_a(14), 5)


def test_la_KILLZONE_est_plus_ETROITE_que_sa_session():
    """Une killzone qui vaudrait sa session ne mesurerait rien de neuf."""
    for kz, sess, dedans, dehors in (
            ("killzone_londres", "session_londres", 8, 14),
            ("killzone_newyork", "session_newyork", 14, 19)):
        assert labo._PREDICATS[kz](_bougies_a(dedans), 5), kz
        assert labo._PREDICATS[sess](_bougies_a(dehors), 5), sess
        assert not labo._PREDICATS[kz](_bougies_a(dehors), 5), (
            f"{kz} est aussi large que {sess}")


def test_l_heure_est_lue_sur_la_bougie_du_SIGNAL():
    """⚠️ `i` designe la bougie d'entree ; la session doit etre celle-la, pas
    celle du debut de la serie."""
    b = _bougies_a(5, n=80)          # 05:00 UTC -> traverse 05:00..11:35
    assert not labo._PREDICATS["session_londres"](b, 5)      # 05:20 UTC
    assert labo._PREDICATS["session_londres"](b, 60)         # 10:00 UTC


def test_un_horodatage_DATETIME_marche_aussi():
    """⛔ `t` est une chaine dans les bougies brutes et un `datetime` apres
    agregation. Ne gerer qu'une forme rendrait les sessions muettes sur M15,
    M30 et H1 — en silence, comme le volume l'a ete."""
    assert labo._PREDICATS["session_londres"](
        _bougies_a(8, comme_datetime=True), 5)


def test_un_horodatage_ILLISIBLE_rend_NON():
    """Fail-closed : une date qu'on ne sait pas lire ne valide aucune session."""
    # ⚠️ La bougie corrompue doit etre CELLE QU'ON INTERROGE : mon premier
    # essai abimait l'indice 5 et lisait le 6, qui portait une date valide.
    # Le predicat avait raison, pas le test.
    b = _bougies_a(8)
    b[5] = dict(b[5], t="pas une date")
    assert not labo._PREDICATS["session_londres"](b, 5)
    assert labo._PREDICATS["session_londres"](b, 6), (
        "une bougie abimee ne doit pas contaminer ses voisines")


# ─── L'invalidation ─────────────────────────────────────────────────


def test_un_INVALIDANT_entre_le_maillon_et_le_declencheur_TUE_la_chaine():
    """⛔ LE trou de la fenetre de 30 bougies : le marche a fait le contraire
    entre les deux, et la chaine se declenchait quand meme."""
    ch = {"nom": "essai", "motifs": ("liquidity_sweep_up", "bos_up"),
          "declencheur": "bos_up", "predicats": (), "fenetre": 30,
          "invalidants": ("bos_down",)}
    releve = {40: [_Setup("liquidity_sweep_up", "buy")],
              50: [_Setup("bos_down", "sell")],
              60: [_Setup("bos_up", "buy")]}
    out, compte = labo.chaines_detectees(releve, _bougies_a(8), chaines=(ch,))
    assert out == {}, "un dementi entre les deux n'a pas tue la chaine"
    assert compte["essai"] == 0


def test_un_invalidant_AVANT_le_maillon_ne_compte_pas():
    """Il appartient a une histoire anterieure ; l'invalider serait remonter
    indefiniment dans le passe."""
    ch = {"nom": "essai", "motifs": ("liquidity_sweep_up", "bos_up"),
          "declencheur": "bos_up", "predicats": (), "fenetre": 30,
          "invalidants": ("bos_down",)}
    releve = {30: [_Setup("bos_down", "sell")],
              40: [_Setup("liquidity_sweep_up", "buy")],
              60: [_Setup("bos_up", "buy")]}
    out, _ = labo.chaines_detectees(releve, _bougies_a(8), chaines=(ch,))
    assert 60 in out


def test_sans_invalidants_le_comportement_ne_change_PAS():
    """Compatibilite : les chaines deja mesurees doivent rester comparables."""
    ch = {"nom": "essai", "motifs": ("liquidity_sweep_up", "bos_up"),
          "declencheur": "bos_up", "predicats": (), "fenetre": 30}
    releve = {40: [_Setup("liquidity_sweep_up", "buy")],
              50: [_Setup("bos_down", "sell")],
              60: [_Setup("bos_up", "buy")]}
    out, _ = labo.chaines_detectees(releve, _bougies_a(8), chaines=(ch,))
    assert 60 in out


def test_les_chaines_DECLAREES_restent_peu_nombreuses():
    """⚠️ Chaque chaine ajoutee releve le plafond du hasard pour tout le
    monde. Le garde-fou contre la recherche exhaustive doit tenir."""
    assert len(labo.CHAINES) <= 14
    for c in labo.CHAINES:
        for m in c.get("invalidants", ()):
            assert m not in c["motifs"], (
                f"{c['nom']} : {m} est a la fois requis et invalidant")
