"""Le laboratoire ne savait mesurer qu'un motif SEUL.

⛔ LE MANQUE, constaté le 2026-09-12. Une cellule vaut
`paire × échelle × UN motif × sens`. Or les méthodes qu'on veut éprouver ne
sont pas des motifs isolés, ce sont des **chaînes** :

    contexte -> niveau majeur -> liquidite -> prise de liquidite
             -> retest -> confirmation volume -> BUY/SELL

Mesurer les maillons séparément ne dit rien de la chaîne montée. Tant que
cette capacité manque, coder vingt notions de plus n'ajoute rien.

## 🔑 Une chaîne est un motif comme un autre

Le choix de conception qui rend tout le reste gratuit : une chaîne produit un
setup **synthétique** nommé `chaine:<nom>`, injecté dans le même relevé. Elle
hérite alors, sans une ligne de plus :

- du stockage (`labo_or_cellules.motif`), sans changement de schéma ;
- du **contrôle aléatoire** de son échelle ;
- et surtout du **plafond du hasard COMMUN** — `plafond_commun` compte toutes
  les cellules, donc ajouter des chaînes **relève la barre pour tout le
  monde**. C'est voulu : plus de tests, exigence plus haute.

⛔ **Elle ne peut jamais être armée.** `chaine:...` n'est pas un `PatternType`,
donc la liste blanche fail-closed du pont la refuse (`pattern_not_allowed`).
Le laboratoire mesure, il n'ouvre pas de porte. C'est vrai par construction,
et un test le verrouille.

## ⛔ Les chaînes sont DÉCLARÉES, jamais cherchées

Six conditions librement combinables font des dizaines de milliers de chaînes.
Les essayer toutes garantirait d'en « trouver » une qui gagne, et ce serait
exactement le geste que l'audit du 25/08 condamne : **PBO = 0,579** sur
l'argent réel — sélectionner sur la performance mesurée ne généralise pas,
pire que pile ou face.

⇒ `CHAINES` est une liste écrite À L'AVANCE, courte, et un test refuse qu'elle
grossisse sans que quelqu'un l'ait voulu.

## ⚠️ Ce que ces chaînes sont, et ne sont pas

Elles sont **notre formalisation** d'un vocabulaire (liquidité, niveau,
structure, confirmation par les volumes). Elles ne sont la méthode de personne :
personne n'a publié ces seuils. La distinction « ce qui est dit » / « ce qui est
déduit » doit rester lisible, sinon on croira avoir reproduit une méthode qu'on
a en réalité inventée.

## ⛔ Une chaîne qui ne se déclenche JAMAIS doit se voir

Sans trade, aucune cellule n'est créée — la chaîne disparaît du relevé et
devient indiscernable d'une chaîne qui ne marche pas. C'est la forme de silence
déjà payée quatre fois ici. `chaines_detectees` rend donc un décompte par
chaîne, y compris les zéros.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import laboratoire_or as labo


class _Pat:
    def __init__(self, nom): self.pattern = nom


class _Dir:
    def __init__(self, v): self.value = v


class _Setup:
    """Ce que `calculate_trade_setup` rend, réduit à ce que le labo lit."""

    def __init__(self, nom, sens, entree=4000.0, stop=3960.0, tp=4080.0):
        self.pattern = _Pat(nom)
        self.direction = _Dir(sens)
        self.entry_price = entree
        self.stop_loss = stop
        self.take_profit_1 = tp


def _bougies(n, volumes=None):
    t0 = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    return [{"t": (t0 + timedelta(minutes=5 * i)).isoformat(),
             "o": 4000.0, "h": 4010.0, "l": 3990.0, "c": 4005.0, "s": 24,
             "tv": (volumes[i] if volumes else 100)}
            for i in range(n)]


# ─── La liste déclarée ──────────────────────────────────────────────


def test_les_chaines_sont_DECLAREES_et_peu_nombreuses():
    """⛔ Le garde-fou contre la recherche exhaustive. Six conditions
    combinables font des dizaines de milliers de chaînes ; les essayer toutes
    fabriquerait une gagnante à coup sûr (PBO 0,579)."""
    assert 1 <= len(labo.CHAINES) <= 12, (
        f"{len(labo.CHAINES)} chaines — au-dela, ce n'est plus une liste "
        "declaree, c'est une recherche")
    noms = [c["nom"] for c in labo.CHAINES]
    assert len(noms) == len(set(noms)), "deux chaines portent le meme nom"


def test_chaque_chaine_declare_son_DECLENCHEUR():
    """🔑 Le setup de la chaîne est celui du motif déclencheur : SL et TP
    viennent du chemin déjà éprouvé. En inventer de nouveaux ajouterait des
    réglages libres — donc de l'edge fabriqué."""
    for c in labo.CHAINES:
        assert c["declencheur"] in c["motifs"], (
            f"{c['nom']} : le declencheur doit faire partie des motifs requis")
        assert len(c["motifs"]) >= 1


# ─── La détection ───────────────────────────────────────────────────


def test_une_chaine_se_declenche_quand_TOUS_ses_motifs_sont_la():
    ch = {"nom": "essai", "motifs": ("liquidity_sweep_up", "bos_up"),
          "declencheur": "bos_up", "predicats": ()}
    releve = {60: [_Setup("liquidity_sweep_up", "buy"), _Setup("bos_up", "buy")]}
    out, compte = labo.chaines_detectees(releve, _bougies(80), chaines=(ch,))
    assert 60 in out
    assert labo._nom_motif(out[60][0]) == "chaine:essai"
    assert compte["essai"] == 1


def test_une_chaine_NE_se_declenche_PAS_s_il_manque_un_maillon():
    ch = {"nom": "essai", "motifs": ("liquidity_sweep_up", "bos_up"),
          "declencheur": "bos_up", "predicats": ()}
    releve = {60: [_Setup("bos_up", "buy")]}
    out, compte = labo.chaines_detectees(releve, _bougies(80), chaines=(ch,))
    assert out == {}
    assert compte["essai"] == 0, "une chaine jamais declenchee doit etre COMPTEE"


def test_les_maillons_doivent_aller_dans_le_MEME_SENS():
    """⚠️ Un balayage haussier plus une cassure baissiere n'est pas une
    confluence, c'est une contradiction."""
    ch = {"nom": "essai", "motifs": ("liquidity_sweep_up", "bos_up"),
          "declencheur": "bos_up", "predicats": ()}
    releve = {60: [_Setup("liquidity_sweep_up", "buy"),
                   _Setup("bos_up", "sell")]}
    out, _ = labo.chaines_detectees(releve, _bougies(80), chaines=(ch,))
    assert out == {}


def test_le_setup_rendu_est_celui_du_DECLENCHEUR():
    """SL et TP ne sont pas reinventes."""
    ch = {"nom": "essai", "motifs": ("liquidity_sweep_up", "bos_up"),
          "declencheur": "bos_up", "predicats": ()}
    releve = {60: [_Setup("liquidity_sweep_up", "buy", entree=1.0, stop=0.5),
                   _Setup("bos_up", "buy", entree=4000.0, stop=3960.0,
                          tp=4080.0)]}
    out, _ = labo.chaines_detectees(releve, _bougies(80), chaines=(ch,))
    s = out[60][0]
    assert s.entry_price == pytest.approx(4000.0)
    assert s.stop_loss == pytest.approx(3960.0)
    assert s.take_profit_1 == pytest.approx(4080.0)
    assert labo._sens(s) == "buy"


# ─── Les prédicats de contexte ──────────────────────────────────────


def test_le_predicat_VOLUME_FORT_filtre():
    """🔑 Rendu possible le 12/09 seulement : avant, le volume valait zero
    partout et ce predicat n'aurait jamais pu se declencher."""
    ch = {"nom": "essai", "motifs": ("bos_up",), "declencheur": "bos_up",
          "predicats": ("volume_fort",)}
    calme = _bougies(80, volumes=[100] * 80)
    pic = _bougies(80, volumes=[100] * 79 + [100])
    pic[59]["tv"] = 900

    releve = {60: [_Setup("bos_up", "buy")]}
    assert labo.chaines_detectees(releve, calme, chaines=(ch,))[0] == {}
    assert 60 in labo.chaines_detectees(releve, pic, chaines=(ch,))[0]


def test_un_volume_ABSENT_ne_valide_jamais_le_predicat(monkeypatch):
    """⛔ Un pont pas encore redeploye rend `tv` absent. Le predicat doit dire
    NON, jamais OUI par defaut — sinon la chaine se declencherait partout en
    pretendant avoir vu un volume."""
    ch = {"nom": "essai", "motifs": ("bos_up",), "declencheur": "bos_up",
          "predicats": ("volume_fort",)}
    sans = [{k: v for k, v in b.items() if k != "tv"} for b in _bougies(80)]
    releve = {60: [_Setup("bos_up", "buy")]}
    assert labo.chaines_detectees(releve, sans, chaines=(ch,))[0] == {}


def test_un_predicat_INCONNU_leve_au_lieu_de_passer_en_silence():
    """⛔ Fail-closed. Un predicat mal orthographie qui rendrait True ferait
    mesurer une chaine sans sa condition, et le verdict serait faux sans que
    rien ne le dise."""
    ch = {"nom": "essai", "motifs": ("bos_up",), "declencheur": "bos_up",
          "predicats": ("predicat_qui_nexiste_pas",)}
    with pytest.raises(KeyError):
        labo.chaines_detectees({60: [_Setup("bos_up", "buy")]},
                               _bougies(80), chaines=(ch,))


# ─── L'insertion dans la machinerie ─────────────────────────────────


def test_une_chaine_ne_peut_JAMAIS_etre_armee():
    """⛔ L'invariant de securite. `chaine:...` n'est pas un `PatternType`,
    donc la liste blanche fail-closed du pont la refuse. Le laboratoire
    mesure ; il n'ouvre aucune porte."""
    from backend.models.schemas import PatternType
    connus = {p.value for p in PatternType}
    for c in labo.CHAINES:
        assert f"chaine:{c['nom']}" not in connus


# ─── La fenetre temporelle : « PUIS », pas « ET » ───────────────────


def test_un_maillon_ANTERIEUR_compte_dans_la_fenetre():
    """⛔ MESURE DU 2026-09-12 sur 4 111 bougies d'or reelles :

        liquidity_sweep_up   194 occurrences
        bos_up               131 occurrences
        au MEME indice       0
        a 1, 2, 3, 5, 10 bougies d'ecart : 0
        a 20 bougies d'ecart : 10

    J'avais code « ET » quand le vocabulaire dit « PUIS ». Et les deux
    detecteurs sont structurellement exclusifs : ils lisent la meme fenetre de
    30 bougies et disent l'inverse l'un de l'autre — un balayage REJETTE un
    extreme, une cassure CLOTURE au-dela du meme extreme.
    """
    ch = {"nom": "essai", "motifs": ("liquidity_sweep_up", "bos_up"),
          "declencheur": "bos_up", "predicats": (), "fenetre": 30}
    releve = {40: [_Setup("liquidity_sweep_up", "buy")],
              60: [_Setup("bos_up", "buy")]}
    out, compte = labo.chaines_detectees(releve, _bougies(80), chaines=(ch,))
    assert 60 in out, "un maillon a 20 bougies d'ecart n'est pas vu"
    assert compte["essai"] == 1


def test_hors_de_la_fenetre_la_chaine_ne_se_declenche_PAS():
    ch = {"nom": "essai", "motifs": ("liquidity_sweep_up", "bos_up"),
          "declencheur": "bos_up", "predicats": (), "fenetre": 5}
    releve = {40: [_Setup("liquidity_sweep_up", "buy")],
              60: [_Setup("bos_up", "buy")]}
    out, _ = labo.chaines_detectees(releve, _bougies(80), chaines=(ch,))
    assert out == {}


def test_le_maillon_POSTERIEUR_ne_compte_pas():
    """« puis » a un sens : la condition precede le declencheur. Accepter
    l'ordre inverse mesurerait une autre chaine sous le meme nom."""
    ch = {"nom": "essai", "motifs": ("liquidity_sweep_up", "bos_up"),
          "declencheur": "bos_up", "predicats": (), "fenetre": 30}
    releve = {60: [_Setup("bos_up", "buy")],
              70: [_Setup("liquidity_sweep_up", "buy")]}
    out, _ = labo.chaines_detectees(releve, _bougies(90), chaines=(ch,))
    assert out == {}


def test_le_declencheur_reste_a_SON_indice():
    """Le setup — donc le SL et le TP — vient du declencheur, pas du maillon
    anterieur, dont les niveaux seraient perimes de 30 bougies."""
    ch = {"nom": "essai", "motifs": ("liquidity_sweep_up", "bos_up"),
          "declencheur": "bos_up", "predicats": (), "fenetre": 30}
    releve = {40: [_Setup("liquidity_sweep_up", "buy", entree=1.0, stop=0.5)],
              60: [_Setup("bos_up", "buy", entree=4000.0, stop=3960.0)]}
    out, _ = labo.chaines_detectees(releve, _bougies(80), chaines=(ch,))
    assert out[60][0].entry_price == pytest.approx(4000.0)


def test_la_FENETRE_est_declaree_sur_chaque_chaine():
    """⛔ Le garde-fou contre le reglage sur la donnee. N ne doit PAS etre
    choisi pour que la chaine se declenche — ce serait de l'edge fabrique, et
    le PBO de 0,579 dit ou ca mene. Les chaines sequentielles heritent de la
    geometrie des detecteurs (le lookback de 30 de `_detect_breakout`,
    partage par le balayage, le BOS et le CHoCH) ; les confirmations
    simultanees valent 0."""
    for c in labo.CHAINES:
        assert "fenetre" in c, f"{c['nom']} ne declare pas sa fenetre"
        assert c["fenetre"] in (0, labo.FENETRE_SEQUENCE), (
            f"{c['nom']} : fenetre {c['fenetre']} — valeur libre, donc reglee")


def test_une_fenetre_ABSENTE_vaut_zero_et_ne_leve_pas():
    """Compatibilite : une chaine sans fenetre reste une co-occurrence."""
    ch = {"nom": "essai", "motifs": ("bos_up",), "declencheur": "bos_up",
          "predicats": ()}
    out, _ = labo.chaines_detectees({60: [_Setup("bos_up", "buy")]},
                                    _bougies(80), chaines=(ch,))
    assert 60 in out


def test_l_AGREGATION_ne_jette_pas_le_volume():
    """⛔ Le defaut silencieux trouve en cablant la confluence.

    `_agreger_brut` ne rendait que `t o c h l`. Sur M15, M30 et H1, `tv`
    disparaissait donc — et `_volume_fort` repondait NON partout. Les quatre
    chaines a confirmation par volume n'auraient jamais pu se declencher
    ailleurs qu'en 5 min, **sans qu'aucune erreur ne soit levee**.

    C'est la maladie du depot : une mesure qui n'a pas lieu, indiscernable
    d'une mesure sans resultat.
    """
    m5 = _bougies(12, volumes=[10] * 12)
    agregees = labo._agreger_brut(m5, 3, None)      # 15 min
    assert agregees, "aucune bougie agregee"
    assert "tv" in agregees[0], "le volume est jete a l'agregation"
    assert agregees[0]["tv"] == 30, "le volume doit etre SOMME, pas moyenne"


def test_le_predicat_volume_fonctionne_sur_une_echelle_AGREGEE():
    """La preuve par l'usage : sans le correctif ci-dessus, ce test echoue."""
    # ⚠️ Le pic doit tomber APRES la 20e bougie agregee : `_volume_fort` exige
    # une fenetre de reference de 20, et repond NON en deca. Mon premier essai
    # le placait a l'indice 19 et echouait pour cette raison — le predicat
    # avait raison, pas le test.
    vols = [10] * 120
    vols[90] = vols[91] = vols[92] = 400            # -> bougie M15 n°30
    m5 = _bougies(120, volumes=vols)
    agregees = labo._agreger_brut(m5, 3, None)
    assert agregees[30]["tv"] == 1200
    assert labo._volume_fort(agregees, 31), "le pic n'est pas vu en M15"
    assert not labo._volume_fort(agregees, 25), "un calme est pris pour un pic"


def test_les_chaines_ENTRENT_dans_le_releve_sans_ecraser_les_motifs():
    """Les motifs simples restent mesures a l'identique."""
    ch = {"nom": "essai", "motifs": ("bos_up",), "declencheur": "bos_up",
          "predicats": ()}
    releve = {60: [_Setup("bos_up", "buy")]}
    fusionne = labo.fusionner_chaines(releve, _bougies(80), chaines=(ch,))
    noms = {labo._nom_motif(s) for liste in fusionne.values() for s in liste}
    assert "bos_up" in noms, "le motif simple a disparu"
    assert "chaine:essai" in noms, "la chaine n'est pas entree"
