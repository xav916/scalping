"""Les corrélations forex/métaux mesurées chez le courtier (2026-08-23).

La table historique ne couvrait que **cinq** couples forex/métaux. Pour tous
les autres, ``correlation()`` rendait ``None`` — donc le garde ne comptait
rien sur presque tout ce que les comptes MT5 tradent.

Le trou, constaté sur le compte réel : les quatre positions ouvertes étaient
GBP/USD ×2, EUR/GBP et GBP/JPY. **Le couple GBP/USD × GBP/JPY n'existait pas
dans la table**, donc était invisible au garde.

⚠️ Et l'intuition s'y trompe. « Deux fois de la livre » suggère de les
bloquer ; la mesure dit qu'ils sont faiblement corrélés (+0,19), parce que
GBP/JPY est dominé par le yen — 2,3× plus volatil que la livre, et USD/JPY
est anti-corrélé à GBP/USD. **Le vrai doublon de ce carnet, c'était les deux
GBP/USD**, pas la paire qui en avait l'air.

Ce que ces tests verrouillent :

1. les couples mesurés sont **chargés** — un fichier absent ferait
   silencieusement retomber tout le forex à ``None`` ;
2. la mesure **prime** sur la table historique ;
3. ``n`` est conservé, pour qu'on sache toujours sur quoi repose un chiffre ;
4. le cas contre-intuitif ne bloque pas, et le vrai doublon bloque.
"""
from __future__ import annotations

import backend.services.correlation_guard as cg


def test_le_fichier_forex_est_charge():
    """⛔ S'il manquait, le forex retomberait à ``None`` **sans erreur** — le
    garde cesserait de compter et rien ne le dirait."""
    forex = cg._charger_fichier("correlations_forex_1h.json")
    assert len(forex) >= 40, f"seulement {len(forex)} couples chargés"


def test_les_paires_du_carnet_reel_sont_toutes_couvertes():
    """Les quatre positions ouvertes le 23/08, deux à deux."""
    for a, b in (("GBP/USD", "GBP/JPY"), ("EUR/GBP", "GBP/USD"),
                 ("EUR/GBP", "GBP/JPY")):
        assert cg.correlation(a, b) is not None, f"{a}x{b} jamais mesuré"


def test_GBP_USD_et_GBP_JPY_ne_sont_PAS_le_meme_pari():
    """⚠️ Le résultat contre-intuitif, et la raison d'avoir mesuré.

    GBP/JPY suit le yen, pas la livre. Un garde-fou posé à l'intuition aurait
    bloqué ce couple pour la mauvaise raison.
    """
    r = cg.correlation("GBP/USD", "GBP/JPY")
    assert r is not None
    assert abs(r) < cg.SEUIL_CORRELATION, (
        f"mesuré {r} : au-delà du seuil, la lecture du carnet change")
    assert cg.exposition("GBP/USD", "buy", "GBP/JPY", "buy") < cg.SEUIL_CORRELATION


def test_le_VRAI_doublon_du_carnet_est_bien_vu():
    """Deux GBP/USD acheteurs : c'est une paire avec elle-même, donc 1,0."""
    assert cg.correlation("GBP/USD", "GBP/USD") == 1.0
    assert cg.exposition("GBP/USD", "buy", "GBP/USD", "buy") == 1.0
    assert cg.exposition("GBP/USD", "buy", "GBP/USD", "buy") >= cg.SEUIL_CORRELATION


def test_EUR_GBP_COMPENSE_un_achat_de_GBP_USD():
    """EUR/GBP à l'achat est vendeur de livre : les deux se compensent, ils
    ne doivent surtout pas compter comme un doublon."""
    e = cg.exposition("EUR/GBP", "buy", "GBP/USD", "buy")
    assert e is not None and e < 0, f"attendu compensatoire, mesuré {e}"


def test_la_mesure_forex_PRIME_sur_la_table_historique():
    """Échantillon continu et plus large : c'est elle qui doit gagner."""
    assert ("EUR/USD", "USD/CHF") in cg.CORRELATIONS
    r = cg.correlation("EUR/USD", "USD/CHF")
    historique = cg.CORRELATIONS[("EUR/USD", "USD/CHF")][0]
    assert r != historique, "la table historique a repris le dessus"
    assert r <= -cg.SEUIL_CORRELATION, "le signe et la force doivent tenir"


def test_le_nombre_d_observations_est_conserve():
    """Une corrélation sur 200 points ne vaut pas celle sur 1 500."""
    forex = cg._charger_fichier("correlations_forex_1h.json")
    for (a, b), (r, n) in forex.items():
        assert n >= 300, f"{a}x{b} n'a que {n} observations"
        assert -1.0 <= r <= 1.0


def test_un_couple_jamais_mesure_reste_None():
    """``None`` et ``0.0`` sont deux états différents : « pas mesuré » ne doit
    jamais se lire « décorrélé »."""
    assert cg.correlation("EUR/USD", "PAIRE/INEXISTANTE") is None
