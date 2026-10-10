"""La commande Telegram `/trade` : ce qu'elle accepte et ce qu'elle refuse.

Demandé par Xavier le 2026-10-10, option **A**.

## ⛔ Pourquoi l'analyse de la commande est une fonction PURE testée ici

Le reste du moniteur (`mt5-bridge-monitor/bridge_monitor.py`) parle à Telegram
et à Docker : il n'est pas testable sans réseau. Mais la partie qui peut être
FAUSSE — lire « /trade », en extraire une paire, refuser le reste — est du
calcul pur. Elle est donc isolée dans `parse_commande_trade`, et c'est elle
qu'on éprouve.

⚠️ Un `/trade` mal lu sur de l'argent réel, c'est soit un cycle qui ne part
pas (il croit que tu n'as rien demandé), soit un cycle sur la mauvaise paire.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SRC = (Path(__file__).resolve().parents[2] / "mt5-bridge-monitor"
        / "bridge_monitor.py")


@pytest.fixture(scope="module")
def M():
    """⚠️ Le moniteur lit `os.environ["BRIDGE_VPS_URL"]` a l'import. On ne
    l'importe donc PAS : on extrait la fonction pure de sa source.

    🔑 C'est moins elegant qu'un import, mais un import qui exige six variables
    d'environnement ferait de ce test un test d'environnement.
    """
    src = _SRC.read_text(encoding="utf-8")
    # ⚠️ On part des CONSTANTES, pas du `def` : extraire la seule fonction
    # laissait `_TRADE_SENS` non defini, et le test tombait sur une
    # `NameError` qui ne disait rien du comportement.
    debut = src.index("_TRADE_OR = {")
    fin = src.index("\ndef declencher_analyse_or(", debut)
    ns: dict = {}
    exec(compile(src[debut:fin], str(_SRC), "exec"), ns)  # noqa: S102
    assert "parse_commande_trade" in ns, "l'extraction a rate la fonction"
    return ns


# ─────────────────────────────────────────────────────────────────────────
# 1. Ce qu'elle accepte
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texte", [
    "/trade",
    "/trade ",
    "/TRADE",
    "/trade@mon_bot",
    "  /trade  ",
])
def test_un_trade_NU_vise_l_or_par_defaut(M, texte):
    """🔑 L'or est la seule paire ouverte au réel : `/trade` tout court doit
    marcher, sinon la commande est pénible à taper sur un téléphone."""
    assert M["parse_commande_trade"](texte) == "XAU/USD"


@pytest.mark.parametrize("texte,attendu", [
    ("/trade XAUUSD", "XAU/USD"),
    ("/trade xau/usd", "XAU/USD"),
    ("/trade or", "XAU/USD"),
    ("/trade gold", "XAU/USD"),
])
def test_les_noms_de_l_or_sont_RECONNUS(M, texte, attendu):
    assert M["parse_commande_trade"](texte) == attendu


# ─────────────────────────────────────────────────────────────────────────
# 2. ⛔ Ce qu'elle refuse
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texte", [
    "/status",
    "/start",
    "trade",                 # sans la barre
    "je voudrais un trade",
    "",
    "   ",
    "/trades",               # pluriel : une AUTRE commande possible demain
    "/tradeur",
])
def test_ce_qui_n_est_PAS_la_commande_est_refuse(M, texte):
    """⛔ `/trades` et `/tradeur` doivent être refusés : accepter tout ce qui
    COMMENCE par `/trade` volerait le nom de commandes futures."""
    assert M["parse_commande_trade"](texte) is None


def test_un_SENS_demande_est_refuse_AVEC_un_motif(M):
    """⛔ LE POINT QUI COMPTE. Xavier avait demandé `/trade buy`. La mesure du
    2026-10-10 a écarté la direction : indiscernable du hasard sur 5 jours
    (n=59, aucune p sous 0,27). Et l'entrée des signaux externes est barrée de
    l'argent réel par conception.

    ⇒ `/trade buy` ne doit PAS être silencieusement traité comme `/trade` : ça
    lui ferait croire que son sens a été pris en compte. On refuse, et on
    explique.
    """
    r = M["parse_commande_trade"]("/trade buy")
    assert r is None or isinstance(r, str) and r.startswith("REFUS:"), r
    if isinstance(r, str) and r.startswith("REFUS:"):
        assert "sens" in r.lower() or "direction" in r.lower(), r


@pytest.mark.parametrize("texte", ["/trade buy", "/trade sell",
                                   "/trade achat", "/trade vente"])
def test_les_quatre_formes_de_SENS_sont_refusees_de_la_meme_facon(M, texte):
    r = M["parse_commande_trade"](texte)
    assert isinstance(r, str) and r.startswith("REFUS:"), (texte, r)


def test_une_AUTRE_paire_est_refusee(M):
    """⚠️ L'or est la seule paire en liste blanche au réel
    (`MT5_BRIDGE_LIVE_WHITELIST_PAIRS=XAU/USD`). Accepter `/trade EURUSD`
    produirait un cycle qui ne peut rien faire, et un silence inexplicable."""
    r = M["parse_commande_trade"]("/trade EURUSD")
    assert r is None or (isinstance(r, str) and r.startswith("REFUS:")), r


# ═══════════════════════════════════════════════════════════════════════
# LE DIAGNOSTIC — 2026-10-10
# ═══════════════════════════════════════════════════════════════════════
#
# 🔑 Xavier a posé TROIS FOIS la question « pourquoi je n'ai plus de trades ».
# Un `/trade` qui répond « rien ne s'est passé » la contourne. Celui-ci NOMME
# le blocage dominant, compte les positions en vie et dit quand le dernier
# ordre est parti.

@pytest.fixture(scope="module")
def F():
    """La fonction de formatage, extraite comme la précédente."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("_MOTIFS_FR = {")
    fin = src.index("\ndef lire_diagnostic_or(", debut)
    ns: dict = {}
    exec(compile(src[debut:fin], str(_SRC), "exec"), ns)  # noqa: S102
    assert "formater_diagnostic" in ns
    return ns["formater_diagnostic"]


def test_il_NOMME_le_blocage_dominant_en_francais(F):
    """⛔ `heure_spread_defavorable` ne veut rien dire pour qui n'a pas écrit
    le code. Un diagnostic illisible n'est pas un diagnostic."""
    t = F({"total": 0, "radar": 0, "main": 0},
          [("heure_spread_defavorable", 2377), ("pattern_not_allowed", 1565)],
          None)

    assert "heure_spread_defavorable" in t
    assert "hors des heures" in t, t
    assert "2377" in t


def test_il_compte_les_positions_RADAR_et_MAIN_separement(F):
    """🔑 Les mélanger masquerait le signal : sa main gagne, le radar perd."""
    t = F({"total": 3, "radar": 2, "main": 1}, [], 12.0)

    assert "3" in t and "radar 2" in t and "main 1" in t


def test_le_texte_ne_contient_AUCUNE_emphase_Markdown(F):
    """⛔ LE DEFAUT QUI A FAIT QUE XAVIER N'A RIEN RECU. Les codes de refus
    portent des underscores (`verdict_blocker`,
    `max_positions_per_pair_indecidable`) que le Markdown de Telegram lit comme
    une italique OUVERTE. L'envoi rendait :

        400 Bad Request: can't parse entities: Can't find end of the entity
            starting at byte offset 451

    ⇒ le message etait construit, l'envoi refuse, et il ne recevait RIEN.
    Le diagnostic est donc du TEXTE BRUT, et l'envoi se fait sans parse_mode.
    """
    t = F({"total": 3, "radar": 2, "main": 1},
          [("max_positions_per_pair_indecidable", 593),
           ("verdict_blocker", 122)], 12.0,
          {"marche": False, "fenetre": False})

    assert "*" not in t, t
    assert "_" in t, "les codes de refus doivent rester LISIBLES tels quels"


def test_l_envoi_sur_le_fil_TRADES_se_fait_SANS_parse_mode():
    """⛔ Le pendant du test ci-dessus, cote envoi : un `parse_mode` remis un
    jour ramenerait le 400."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def tg_send_trades(")
    fin = src.index("\ndef ", debut + 10)
    bloc = src[debut:fin]

    # ⚠️ On cherche la CLE du dictionnaire, entre guillemets — pas le mot :
    # mon premier jet attrapait `parse_mode` dans le commentaire qui explique
    # justement pourquoi il n'y en a pas.
    assert '"parse_mode"' not in bloc, bloc
    assert "'parse_mode'" not in bloc, bloc


def test_un_courtier_ILLISIBLE_se_DIT_au_lieu_de_valoir_zero(F):
    """⛔ Le défaut nommé le 09/10 : `max_positions_per_pair_indecidable` a
    refusé 593 signaux parce qu'on ne POUVAIT PAS compter. Afficher « 0 » dans
    ce cas ferait croire que la place est libre."""
    t = F({}, [], None)

    assert "illisibles" in t.lower(), t
    assert "en vie : 0" not in t


def test_le_dernier_ordre_est_dit_en_MINUTES_puis_en_HEURES(F):
    assert "il y a 12 min" in F({"total": 0}, [], 12.4)
    assert "il y a 3.0 h" in F({"total": 0}, [], 180.0)
    assert "aucun" in F({"total": 0}, [], None).lower()


def test_AUCUN_refus_est_une_information_aussi(F):
    """⚠️ Un silence sur les refus se lirait comme une panne du diagnostic."""
    t = F({"total": 1, "radar": 1, "main": 0}, [], 5.0)

    assert "aucun refus" in t.lower(), t


def test_un_motif_INCONNU_ne_fait_pas_LEVER(F):
    """⚠️ Un code de refus ajouté demain ne doit pas rendre le diagnostic
    muet : il s'affiche brut, avec la mention qu'il n'est pas traduit."""
    t = F({"total": 0}, [("un_motif_tout_neuf", 7)], None)

    assert "un_motif_tout_neuf" in t
    assert "non traduit" in t


def test_le_diagnostic_dit_D_ABORD_si_le_marche_est_FERME(F):
    """⛔ LE DEFAUT. Lance un samedi, le diagnostic remontait `verdict_blocker`
    — un blocage ANTERIEUR dans la chaine — alors que la seule chose a savoir
    etait << le marche est ferme >>. Les deux faits les plus basiques passent
    donc EN PREMIER."""
    t = F({"total": 0, "radar": 0, "main": 0},
          [("verdict_blocker", 122)], None,
          {"marche": False, "fenetre": False})

    lignes = t.splitlines()
    assert "FERME" in lignes[0], lignes
    assert "FERMEE" in lignes[1], lignes
    assert "*" not in t, "emphase Markdown : l'envoi echouerait en 400"


def test_marche_OUVERT_se_dit_aussi(F):
    t = F({"total": 1, "radar": 1, "main": 0}, [], 3.0,
          {"marche": True, "fenetre": True})
    assert "ouvert" in t.splitlines()[0]
    assert "ouverte" in t.splitlines()[1]


def test_des_portes_ILLISIBLES_se_TAISENT_au_lieu_d_inventer(F):
    """⚠️ Un dict vide ne doit pas produire << marche : ouvert >> par defaut :
    affirmer l'inverse de la realite est pire que de se taire."""
    t = F({"total": 0}, [], None, {})
    assert "Marche de l'or" not in t
    t2 = F({"total": 0}, [], None, None)
    assert "fenetre hebdo" not in t2
