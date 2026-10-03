"""La veille des canaux : triage deterministe, et le garde qui protege le reseau.

⛔ **LE RISQUE LE PLUS GRAVE DE CE MODULE N'EST PAS DE MAL TRIER.** C'est de
faire appeler une URL arbitraire par NOTRE serveur. Celui-ci peut joindre ce
que le monde ne peut pas :

    100.74.160.72:8788   le pont MT5 — il PLACE DES ORDRES
    127.0.0.1:8000       notre propre API
    169.254.169.254      les metadonnees EC2 — elles rendent des identifiants IAM

Un lien dans un canal public suffirait. Ces tests verrouillent le garde, y
compris sur le contournement evident : une URL publique qui REDIRIGE vers une
adresse interne.

⚠️ Et le second risque : une page lue est de la **donnee**, jamais une
instruction. La defense n'est pas le prompt — c'est que la sortie de ce module
ne peut rien armer. Elle produit une notion a pre-enregistrer, qu'un humain lit.
"""
from __future__ import annotations

import pytest

from backend.services import veille_canaux as vc


# ─── LE GARDE RESEAU ─────────────────────────────────────────────────────

@pytest.mark.parametrize("url,ce_qui_est_vise", [
    ("http://100.74.160.72:8788/order", "le pont MT5, qui place des ordres"),
    ("http://127.0.0.1:8000/api/signals/external", "notre propre API"),
    ("http://localhost:8000/", "notre propre API, par son nom"),
    ("http://169.254.169.254/latest/meta-data/iam/", "les identifiants IAM EC2"),
    ("http://10.0.0.5/", "un reseau prive"),
    ("http://192.168.1.1/", "un routeur local"),
    ("http://172.16.0.9/", "un reseau prive"),
    ("http://[::1]:8000/", "le bouclage IPv6"),
    ("http://0.0.0.0/", "l'adresse nulle"),
])
def test_une_adresse_INTERNE_est_refusee(url, ce_qui_est_vise):
    ok, motif = vc.url_autorisee(url)
    assert ok is False, f"{url} viserait {ce_qui_est_vise} — motif rendu : {motif}"


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://exemple.com/x",
    "gopher://exemple.com/",
    "data:text/html,<b>x</b>",
    "http://",
    "pas-une-url",
])
def test_un_schema_NON_http_est_refuse(url):
    ok, _ = vc.url_autorisee(url)
    assert ok is False, url


def test_un_hote_PUBLIC_est_autorise(monkeypatch):
    monkeypatch.setattr(vc.socket, "getaddrinfo",
                        lambda h, p: [(2, 1, 6, "", ("93.184.216.34", 0))])
    ok, motif = vc.url_autorisee("https://exemple.com/article")
    assert ok is True, motif


def test_un_hote_qui_resout_vers_DEUX_adresses_dont_une_privee_est_refuse(
        monkeypatch):
    """⛔ Sinon le choix reviendrait a la pile reseau, et le garde serait un
    tirage au sort."""
    monkeypatch.setattr(vc.socket, "getaddrinfo", lambda h, p: [
        (2, 1, 6, "", ("93.184.216.34", 0)),     # publique
        (2, 1, 6, "", ("127.0.0.1", 0)),         # ⛔ bouclage
    ])
    ok, motif = vc.url_autorisee("https://piege.exemple/x")
    assert ok is False, motif
    assert "127.0.0.1" in motif


def test_un_DNS_illisible_est_refuse(monkeypatch):
    def _boum(h, p):
        raise OSError("pas de DNS")
    monkeypatch.setattr(vc.socket, "getaddrinfo", _boum)
    ok, motif = vc.url_autorisee("https://inexistant.exemple/")
    assert ok is False and "DNS" in motif


def test_une_REDIRECTION_vers_une_adresse_interne_est_refusee(monkeypatch):
    """⛔ Le contournement evident : l'URL de depart est publique, la cible
    ne l'est pas. Le garde doit re-verifier a CHAQUE saut."""
    vus = []

    def _faux_getaddrinfo(h, p):
        vus.append(h)
        if h in ("exemple.com",):
            return [(2, 1, 6, "", ("93.184.216.34", 0))]
        return [(2, 1, 6, "", ("127.0.0.1", 0))]       # la cible est interne

    monkeypatch.setattr(vc.socket, "getaddrinfo", _faux_getaddrinfo)

    def _ouvreur(*a, **k):
        class _O:
            def open(self, req, timeout=None):
                raise vc._Redirige("http://interne.exemple/secret")
        return _O()

    monkeypatch.setattr(vc.urllib.request, "build_opener", _ouvreur)
    r = vc.lire_page("https://exemple.com/depart")
    assert "refus" in r, r
    assert "interne" in r["refus"] or "127.0.0.1" in r["refus"], r


def test_une_boucle_de_redirections_s_arrete(monkeypatch):
    monkeypatch.setattr(vc.socket, "getaddrinfo",
                        lambda h, p: [(2, 1, 6, "", ("93.184.216.34", 0))])

    def _ouvreur(*a, **k):
        class _O:
            def open(self, req, timeout=None):
                raise vc._Redirige("https://exemple.com/encore")
        return _O()

    monkeypatch.setattr(vc.urllib.request, "build_opener", _ouvreur)
    r = vc.lire_page("https://exemple.com/a")
    assert "refus" in r and "redirection" in r["refus"]


# ─── L'EXTRACTION des liens et du texte ──────────────────────────────────

def test_les_liens_sont_extraits_dans_l_ordre_et_sans_doublon():
    t = ("Voir https://www.mql5.com/fr/articles/12345 et aussi "
         "https://exemple.com/a, puis https://www.mql5.com/fr/articles/12345.")
    assert vc.liens(t) == ["https://www.mql5.com/fr/articles/12345",
                           "https://exemple.com/a"]


def test_la_ponctuation_finale_n_entre_pas_dans_l_URL():
    assert vc.liens("lire https://exemple.com/page.") == \
        ["https://exemple.com/page"]


def test_un_message_sans_lien_rend_une_liste_vide():
    assert vc.liens("pin bar en 5min sur l'or") == []


def test_le_script_et_le_style_ne_passent_PAS_dans_le_texte():
    html = ("<html><head><title>t</title><style>p{color:red}</style></head>"
            "<body><script>alert('x')</script><p>Le regime de marche</p>"
            "<p>par Hurst</p></body></html>")
    t = vc._en_texte(html)
    assert "alert" not in t and "color:red" not in t
    assert "Le regime de marche" in t and "par Hurst" in t


def test_les_entites_HTML_sont_rendues_lisibles():
    assert "H > 0,5" in vc._en_texte("<p>H &gt; 0,5</p>")


# ─── LE TRIAGE, deterministe ─────────────────────────────────────────────

def test_un_OSCILLATEUR_est_classe_comme_tel_et_le_POURQUOI_est_ecrit():
    """⛔ Les deux tiers du canal MQL5 sont de cette famille. Un oscillateur
    rend une valeur continue : le seuil ET la regle seraient les NOTRES."""
    c = vc.classer("Nouvel indicateur : RSI lisse sur 14 periodes")
    assert c["famille"] == vc.OSCILLATEUR
    assert any("oscillateur" in p for p in c["pourquoi"])
    assert vc.recevable(c) is False


def test_un_PREDICAT_passe_devant_tout_quand_il_porte_son_seuil_et_son_echelle():
    """C'est exactement le cas de Hurst, le seul retenu sur 35 messages."""
    c = vc.classer("Regime de marche via exposant de Hurst : H > 0,5 "
                   "persistance, en 15min sur l'or")
    assert c["famille"] == vc.PREDICAT
    assert c["porte_son_seuil"] is True
    assert c["echelle"] == "15min"
    assert c["rang"] == -1, "il doit passer devant tout"
    assert vc.recevable(c) is True


def test_un_MOTIF_est_recevable_mais_classe_apres_un_predicat():
    m = vc.classer("Pin bar en 5min sur XAU/USD")
    p = vc.classer("Filtre de regime : persistance, 5min, or, seuil de 0,5")
    assert m["famille"] == vc.MOTIF and vc.recevable(m)
    assert p["rang"] < m["rang"], "un predicat passe avant un motif"


def test_la_GESTION_de_position_est_recevable():
    c = vc.classer("Stop suiveur apres 1R, en 15min")
    assert c["famille"] == vc.GESTION and vc.recevable(c)


def test_une_PUBLICITE_pour_un_robot_n_est_pas_une_idee():
    c = vc.classer("Expert Advisor gratuit a telecharger sur mql5.com !")
    assert c["famille"] == vc.OUTIL
    assert vc.recevable(c) is False


def test_une_publicite_QUI_CONTIENT_une_idee_n_est_pas_jetee():
    """⚠️ « EA gratuit utilisant un filtre de regime en 4h » porte une idee."""
    c = vc.classer("Expert Advisor gratuit : filtre de regime de volatilite "
                   "en 4h sur l'or")
    assert c["famille"] == vc.PREDICAT, c["pourquoi"]
    assert vc.recevable(c) is True


def test_le_BRUIT_est_classe_bruit():
    for t in ("Bonjour a tous !", "https://t.me/canal", ""):
        assert vc.classer(t)["famille"] == vc.BRUIT, t


def test_l_absence_d_echelle_est_DITE_et_non_cachee():
    c = vc.classer("Pin bar sur l'or")
    assert c["echelle"] is None
    assert any("echelle" in p for p in c["pourquoi"])


@pytest.mark.parametrize("texte,attendu", [
    ("en M5 sur l'or", "5min"),
    ("sur 15 min", "15min"),
    ("timeframe H4", "4h"),
    ("en daily", "1day"),
    ("graphique horaire", "1h"),
    ("sur 30min", "30min"),
])
def test_les_echelles_sont_traduites_dans_le_vocabulaire_du_RADAR(texte, attendu):
    """⚠️ Une echelle que le radar ne nomme pas n'est pas utilisable."""
    assert vc.echelle_nommee(texte) == attendu


def test_une_echelle_inventee_n_est_pas_reconnue():
    assert vc.echelle_nommee("en 7 minutes") is None
    assert vc.echelle_nommee("en M7") is None


# ─── LA NOTION, et ses champs vides ──────────────────────────────────────

def test_une_notion_neuve_a_ses_SIX_champs_vides():
    """⛔ C'est l'etat honnete du savoir. Les remplir de memoire serait une
    invention — `notions_vivien` tient cette porte fermee."""
    n = vc.notion_vide("canal @x, message 42")
    assert set(vc.CHAMPS) <= set(n)
    assert all(n[c] is None for c in vc.CHAMPS)
    assert vc.manques(n) == tuple(vc.CHAMPS)


def test_manques_ne_liste_que_ce_qui_est_VIDE():
    n = vc.notion_vide("src")
    n["declencheur"] = "pin bar"
    n["echelle"] = "5min"
    assert "declencheur" not in vc.manques(n)
    assert "echelle" not in vc.manques(n)
    assert "stop" in vc.manques(n)


# ─── LE CHROME de navigation ─────────────────────────────────────────────
#
# ⛔ MESURE DU 2026-10-03 sur une vraie page mql5.com/en/articles : 24 365
# caracteres, dont le debut est integralement du menu — « Forum / Market /
# Signals / Freelance / VPS / Quotes / MetaTrader / Articles / CodeBase… ».
# Envoyer cela au modele, c est payer des jetons pour de la navigation et
# diluer le signal dans du bruit repete sur chaque page du site.

def test_le_menu_de_navigation_est_RETIRE():
    page = ("Forum\nMarket\nSignals\nFreelance\nVPS\nQuotes\nMetaTrader\n"
            "L exposant de Hurst mesure la persistance des rendements, et son "
            "seuil de 0,5 correspond a la marche aleatoire.\n"
            "About\nTools\n")
    d = vc.densifier(page)
    assert "Hurst" in d
    for chrome in ("Forum", "Market", "Signals", "Freelance", "VPS", "Quotes"):
        assert chrome not in d, chrome


def test_densifier_ne_vide_PAS_une_page_de_prose():
    prose = ("Cette methode consiste a attendre la cassure puis le retour sur "
             "le niveau avant d entrer dans le sens du mouvement.\n"
             "Le stop se place sous le plus bas de la bougie de rejet.\n")
    assert len(vc.densifier(prose).splitlines()) == 2


def test_une_page_SANS_prose_rend_un_texte_vide_et_le_DIT():
    """⚠️ Elle ne devine aucune structure de site. Une page dont le contenu
    tiendrait en lignes de trois mots serait vide apres passage — et c est
    `caracteres_densifies` qui doit le dire, au lieu de le cacher."""
    assert vc.densifier("A\nB\nC\nun deux trois\n") == ""


def test_lire_page_rend_les_DEUX_tailles(monkeypatch):
    """Le brut ET le densifie : on doit pouvoir constater ce qui a ete retire."""
    monkeypatch.setattr(vc.socket, "getaddrinfo",
                        lambda h, p: [(2, 1, 6, "", ("93.184.216.34", 0))])

    html = (b"<html><body><p>Forum</p><p>Market</p>"
            b"<p>Le regime de marche se mesure par l exposant de Hurst, "
            b"dont le seuil de 0,5 est la marche aleatoire.</p></body></html>")

    class _Rep:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def read(self, n=None):
            return html

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(vc.urllib.request, "build_opener",
                        lambda *a, **k: type("O", (), {
                            "open": lambda s, req, timeout=None: _Rep()})())
    r = vc.lire_page("https://exemple.com/a")
    assert "Hurst" in r["texte"]
    assert "Forum" in r["texte_brut"] and "Forum" not in r["texte"]
    assert r["caracteres_densifies"] < r["caracteres"]
