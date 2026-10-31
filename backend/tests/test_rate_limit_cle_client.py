"""La clé de limitation ne doit pas être choisie par l'attaquant (audit S-2).

## Le défaut corrigé

`_get_client_ip` prenait le **premier saut** de `X-Forwarded-For`. Or nginx
transmet `$proxy_add_x_forwarded_for`, qui **ajoute** l'IP réelle à la valeur
envoyée par le client : `X-Forwarded-For: 1.2.3.4` devenait
`1.2.3.4, <ip_reelle>`, et l'application retenait `1.2.3.4`.

⇒ Changer un en-tête à chaque requête suffisait à obtenir une clé neuve.
**La protection anti-force-brute de `login`, `signup`, `password-reset`,
`email-verify`, `stripe-checkout` et `delete-account` était nulle en
pratique.**

## Ce que ces tests garantissent

1. Une requête dont le `X-Forwarded-For` est **forgé** compte sur la **même
   clé** qu'une requête honnête venue du même client.
2. `X-Forwarded-For` n'influence **jamais** la clé.
3. Sans en-tête, on retombe sur l'IP du socket, et jamais sur une valeur
   fournie par l'appelant.
"""
from __future__ import annotations

import pytest
from starlette.requests import Request

from backend.rate_limit import _get_client_ip

_IP_REELLE = "203.0.113.7"       # celle que nginx pose dans X-Real-IP
_IP_FORGEE = "1.2.3.4"           # celle que l'attaquant choisit


def _requete(entetes: dict[str, str], socket: str | None = "10.0.0.1") -> Request:
    brut = [(k.lower().encode(), v.encode()) for k, v in entetes.items()]
    portee = {
        "type": "http", "method": "POST", "path": "/api/auth/login",
        "headers": brut, "query_string": b"", "scheme": "https",
        "server": ("app", 443),
    }
    if socket is not None:
        portee["client"] = (socket, 1234)
    return Request(portee)


# --- LE test de l'audit -------------------------------------------------

def test_un_XFF_FORGE_compte_sur_la_MEME_cle_que_la_requete_honnete():
    """⛔ LE test qui compte, et la demande exacte du brief : une requête avec
    `X-Forwarded-For` forgé et `X-Real-IP` identique doit être comptée sur la
    même clé."""
    honnete = _get_client_ip(_requete({"X-Real-IP": _IP_REELLE}))
    forgee = _get_client_ip(_requete({
        "X-Real-IP": _IP_REELLE,
        # ce que nginx produit quand le client envoie deja un XFF
        "X-Forwarded-For": "%s, %s" % (_IP_FORGEE, _IP_REELLE),
    }))
    assert forgee == honnete == _IP_REELLE, (
        "la cle doit venir de X-Real-IP, pas du premier saut de XFF")


def test_CENT_XFF_differents_rendent_la_MEME_cle():
    """La contournabilité tenait à ceci : une clé neuve à chaque requête.
    Cent en-têtes différents ne doivent plus donner qu'une seule clé."""
    cles = {
        _get_client_ip(_requete({
            "X-Real-IP": _IP_REELLE,
            "X-Forwarded-For": "10.1.%d.%d, %s" % (i // 256, i % 256, _IP_REELLE),
        }))
        for i in range(100)
    }
    assert cles == {_IP_REELLE}, "cles distinctes obtenues : %s" % sorted(cles)[:5]


def test_XFF_SEUL_n_est_jamais_retenu():
    """⛔ Sans `X-Real-IP`, un XFF forgé ne doit PAS devenir la clé : on
    retombe sur le socket, qu'un client ne peut pas choisir."""
    cle = _get_client_ip(_requete({"X-Forwarded-For": _IP_FORGEE},
                                  socket="10.0.0.1"))
    assert cle == "10.0.0.1"
    assert cle != _IP_FORGEE


# --- la cascade ---------------------------------------------------------

def test_sans_aucun_entete_on_prend_le_socket():
    assert _get_client_ip(_requete({}, socket="198.51.100.9")) == "198.51.100.9"


def test_sans_entete_ni_socket_on_rend_unknown():
    """Une clé unique partagée vaut mieux qu'une exception : le limiteur
    continue de compter, de façon pessimiste."""
    assert _get_client_ip(_requete({}, socket=None)) == "unknown"


@pytest.mark.parametrize("vide", ["", "   "])
def test_un_X_Real_IP_VIDE_retombe_sur_le_socket(vide):
    """Un en-tête present mais vide est une absence, pas une IP vide."""
    assert _get_client_ip(
        _requete({"X-Real-IP": vide}, socket="10.0.0.1")) == "10.0.0.1"


def test_X_Real_IP_est_lu_sans_tenir_compte_de_la_casse():
    """Les en-têtes HTTP sont insensibles à la casse ; la clé ne doit pas
    dépendre de la façon dont le proxy les écrit."""
    assert _get_client_ip(_requete({"x-real-ip": _IP_REELLE})) == _IP_REELLE
    assert _get_client_ip(_requete({"X-REAL-IP": _IP_REELLE})) == _IP_REELLE


# --- la condition EXTERNE dont depend tout le correctif ----------------

def test_nginx_ECRASE_bien_X_Real_IP_dans_les_deux_configs():
    """🔑 Ce correctif ne vaut que si nginx pose `X-Real-IP $remote_addr` —
    il ECRASE, là où `$proxy_add_x_forwarded_for` CONCATENE. Si quelqu'un
    retire la directive, `X-Real-IP` redevient aussi forgeable que XFF
    l'était, et ce test doit le dire AVANT la mise en production."""
    import pathlib
    racine = pathlib.Path(__file__).resolve().parents[2] / "deploy"
    confs = sorted(racine.glob("nginx*.conf"))
    assert confs, "aucune configuration nginx trouvee dans deploy/"
    for c in confs:
        texte = c.read_text(encoding="utf-8", errors="ignore")
        n_proxy = texte.count("proxy_pass")
        n_real = texte.count("proxy_set_header X-Real-IP $remote_addr")
        assert n_real >= 1, "%s ne pose pas X-Real-IP" % c.name
        assert n_real >= n_proxy - 1, (
            "%s : %d proxy_pass pour %d X-Real-IP — un emplacement oublie "
            "laisserait la cle forgeable sur cette route" % (c.name, n_proxy, n_real))
