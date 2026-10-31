"""Les alertes du bridge monitor doivent ARRIVER, même mal formées.

## Le défaut corrigé

Relevé le 2026-10-31 en rejouant un contrôle manuel de la PR #3, resté coché
à zéro depuis le 2026-05-05.

`journalctl -u scalping-bridge-monitor.service --since '7 days ago'` :
**42 occurrences**, toutes la même, la dernière le jour même à 19:04:27 :

```
http=400 {"ok":false,"description":"Bad Request: can't parse entities:
          Can't find end of the entity starting at byte offset 464"}
```

`tg_send` envoie en `parse_mode="Markdown"` et les valeurs interpolées —
messages d'exception, `recovery.detail` — y arrivaient **brutes**. Un seul
`_` (un `__init__`, un nom de clé, une URL) ouvre une italique qui ne se
ferme jamais, et Telegram refuse le message **entier**.

⛔ **Le message n'est pas tronqué : il n'arrive PAS.** Et c'est ce service qui
prévient quand un pont tombe — `bridge_live` porte la mention « aucun ordre
Live ne part vers IC Markets — argent réel concerné ».

🔑 Trois couches de silence se superposaient :

1. le message rejeté, donc jamais livré ;
2. `log.warning("… body=%s", r.text)` journalisait **la réponse, jamais le
   message** — le défaut était donc indiagnosticable depuis les logs ;
3. un `warning`, donc rien ne le remontait.

## Les trois gestes, et pourquoi trois

- **échapper** les valeurs interpolées (la cause) ;
- **journaliser le message** (pour diagnostiquer la prochaine fois) ;
- **replier sans `parse_mode`** (pour que ça arrive quand même). Pour une
  sonde, la livraison passe avant la mise en forme : une alerte en texte brut
  vaut infiniment mieux qu'aucune alerte.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib

import pytest

_CHEMIN = (pathlib.Path(__file__).resolve().parents[2]
           / "mt5-bridge-monitor" / "bridge_monitor.py")


@pytest.fixture(scope="module")
def bm():
    """Charge le monitor. ⚠️ Il lit `BRIDGE_VPS_URL/KEY` en `os.environ[...]`
    STRICT au premier niveau : sans eux, l'import leve. C'est volontaire de sa
    part (audit du 2026-05-05), donc on les pose au lieu de l'assouplir."""
    for cle, val in (("BRIDGE_VPS_URL", "http://exemple.invalide"),
                     ("BRIDGE_VPS_KEY", "cle-de-test"),
                     ("TELEGRAM_BOT_TOKEN", "jeton-de-test"),
                     ("TELEGRAM_CHAT_ID", "0")):
        os.environ.setdefault(cle, val)
    spec = importlib.util.spec_from_file_location("bridge_monitor_sous_test",
                                                  _CHEMIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- l'echappement en texte libre ---------------------------------------

@pytest.mark.parametrize("brut", [
    "KeyError: 'some_key'",
    "module __init__ introuvable",
    "http://hote/a_b_c",
    "valeur *importante*",
    "liste [1, 2]",
])
def test_md_libre_neutralise_le_balisage(bm, brut):
    """⛔ LE test de la cause. Chaque caractère spécial doit ressortir
    échappé, sinon Telegram refuse le message entier."""
    sortie = bm._md_libre(brut)
    for c in bm._MD_SPECIAUX:
        if c in brut:
            assert "\\" + c in sortie, (
                "%r non echappe dans %r" % (c, sortie))


def test_md_libre_ne_touche_pas_un_texte_sain(bm):
    """Une sonde qui réécrit tout rendrait les messages illisibles."""
    assert bm._md_libre("Bridge Live hors service") == \
        "Bridge Live hors service"


# --- l'echappement DANS un span de code ---------------------------------

def test_md_code_retire_le_backtick(bm):
    """Seul le backtick fermerait le span trop tôt."""
    assert "`" not in bm._md_code("erreur `grave`")


def test_md_code_ne_echappe_PAS_le_souligne(bm):
    """⚠️ Le piège symétrique : dans un span de code, Markdown n'interprète
    plus `_`. L'échapper afficherait un `\\_` littéral au lecteur."""
    sortie = bm._md_code("KeyError: 'some_key'")
    assert "some_key" in sortie, (
        "le souligne a ete echappe dans un span de code : %r" % sortie)
    assert "\\_" not in sortie


# --- le message complet, la ou le defaut mordait ------------------------

def test_un_detail_de_recuperation_avec_souligne_ne_casse_plus(bm):
    """🔑 Le cas reel : `recovery.detail` etait interpole HORS backticks, en
    fin de message — coherent avec l'offset 464 rapporte par Telegram."""
    msg = bm.tg_format_alert(
        "bridge_live", "DOWN",
        {"kind": "bridge", "health_error": "timeout"},
        recovery={"ok": True, "action": "restart_systemd",
                  "detail": "unit scalping_radar.service restarted_ok"})
    # le souligne du detail doit etre echappe
    assert "restarted\\_ok" in msg or "restarted_ok" not in msg, (
        "le detail arrive encore brut : %r" % msg[-200:])


def test_les_soulignes_hors_code_sont_tous_echappes(bm):
    """Témoin structurel : hors des spans de code, tout `_` non échappé est un
    début d'entité. On vérifie la PARITÉ, qui est ce que Telegram évalue."""
    msg = bm.tg_format_alert(
        "disk_root", "DOWN",
        {"kind": "data", "error": "a_b_c failed", "age_sec": 90},
        recovery={"ok": False, "action": "docker_prune",
                  "detail": "no_space_left on device"})
    hors_code = "".join(part for i, part in enumerate(msg.split("`"))
                        if i % 2 == 0)
    non_echappes = sum(1 for i, c in enumerate(hors_code)
                       if c == "_" and (i == 0 or hors_code[i - 1] != "\\"))
    assert non_echappes % 2 == 0, (
        "%d souligne(s) non echappe(s) hors code : nombre IMPAIR, donc une "
        "entite ouverte que Telegram refusera.\n%r"
        % (non_echappes, hors_code))


# --- la journalisation et le repli --------------------------------------

def test_un_echec_journalise_le_MESSAGE(bm, monkeypatch, caplog):
    """⛔ Sans cela le defaut reste indiagnosticable : pendant des mois le
    journal a dit « can't parse entities » sans dire DE QUOI."""
    class _Rep:
        ok = False
        status_code = 400
        text = '{"ok":false,"description":"can\'t parse entities"}'

    appels = []

    def _faux_post(url, **kw):
        appels.append(kw.get("json", {}))
        return _Rep()

    monkeypatch.setattr(bm.requests, "post", _faux_post)
    monkeypatch.setattr(bm, "TELEGRAM_ENABLED", True)
    with caplog.at_level("WARNING"):
        bm.tg_send("un message *casse_")

    # `getMessage()` interpole les args ; `record.message` n'existe qu'apres
    # formatage, et `message % args` double alors l'interpolation.
    joint = " ".join(r.getMessage() for r in caplog.records)
    assert "msg=" in joint, "le message n'est pas journalise : %r" % joint
    assert "casse" in joint


def test_un_refus_de_balisage_DECLENCHE_le_repli_sans_parse_mode(bm, monkeypatch):
    """🔑 Le filet : l'alerte doit arriver, fût-ce en texte brut."""
    envois = []

    class _Rep:
        def __init__(self, ok):
            self.ok = ok
            self.status_code = 400 if not ok else 200
            self.text = ('{"description":"can\'t parse entities"}'
                         if not ok else "{}")

    def _faux_post(url, **kw):
        envois.append(kw.get("json", {}))
        return _Rep(ok=len(envois) > 1)   # le 1er echoue, le repli passe

    monkeypatch.setattr(bm.requests, "post", _faux_post)
    monkeypatch.setattr(bm, "TELEGRAM_ENABLED", True)
    bm.tg_send("alerte *importante_")

    assert len(envois) == 2, (
        "le repli n'a pas eu lieu : %d envoi(s)" % len(envois))
    assert "parse_mode" in envois[0], "le 1er envoi devait etre en Markdown"
    assert "parse_mode" not in envois[1], (
        "le repli doit etre SANS parse_mode, sinon il echouera pareil")
    assert envois[1]["text"] == envois[0]["text"], (
        "le repli doit porter le MEME texte")


def test_un_echec_qui_n_est_PAS_de_balisage_ne_declenche_pas_le_repli(bm, monkeypatch):
    """⚠️ Le pendant : un 429 ou un 500 ne doit pas doubler l'envoi. Reessayer
    un message refuse pour une AUTRE raison, c'est doubler la charge sur une
    API qui nous repousse deja."""
    envois = []

    class _Rep:
        ok = False
        status_code = 429
        text = '{"description":"Too Many Requests: retry after 30"}'

    def _faux_post(url, **kw):
        envois.append(kw.get("json", {}))
        return _Rep()

    monkeypatch.setattr(bm.requests, "post", _faux_post)
    monkeypatch.setattr(bm, "TELEGRAM_ENABLED", True)
    bm.tg_send("alerte")

    assert len(envois) == 1, (
        "un echec non lie au balisage a declenche un repli inutile")


# --- la reponse /status, la ou le defaut mordait VRAIMENT ---------------

#: Les sondes REELLES, lues sur `status.json` de production le 2026-10-31.
#: ⛔ Pas des noms inventes : `disk_root` est precisement celui que la table
#: `_NAME_FR` ne connait pas (elle dit « disk »), et c'est lui qui faisait
#: refuser chaque reponse /status.
_SONDES_REELLES = ("bridge_live", "bridge_vps", "disk_root", "nginx.service",
                   "radar_cycle", "scalping-bridge-monitor.service",
                   "scalping.service", "tailscale")


def test_la_reponse_status_echappe_les_noms_de_sondes_REELS(bm, monkeypatch):
    """⛔ LE test du vrai declencheur : 36 refus le seul 2026-10-31.

    `_NAME_FR.get(name, name)` retombe sur le nom BRUT. `disk_root` n'est pas
    dans la table, donc son souligne arrivait tel quel — un seul suffit a
    ouvrir une italique que rien ne ferme.

    🔑 Le correctif echappe au lieu d'ajouter `disk_root` a la table : une
    table derive au prochain ajout de sonde, l'echappement non.
    """
    import time as _t
    faux_etat = {nom: {"confirmed": "UP", "last_change_ts": _t.time() - 3600}
                 for nom in _SONDES_REELLES}
    monkeypatch.setattr(bm, "_state", faux_etat)
    monkeypatch.setattr(bm, "_last_cycle_ts", "2026-10-31T19:00:00Z")

    msg = bm.tg_build_status_reply()

    assert "disk" in msg, "la reponse ne mentionne plus les sondes : %r" % msg[:200]
    hors_code = "".join(part for i, part in enumerate(msg.split("`"))
                        if i % 2 == 0)
    non_echappes = sum(1 for i, c in enumerate(hors_code)
                       if c == "_" and (i == 0 or hors_code[i - 1] != "\\"))
    assert non_echappes % 2 == 0, (
        "%d souligne(s) non echappe(s) dans la reponse /status : nombre "
        "IMPAIR, Telegram la refusera comme il l'a fait 36 fois le 31/10. %r"
        % (non_echappes, hors_code))


def test_une_sonde_INCONNUE_de_la_table_ne_casse_pas_la_reponse(bm, monkeypatch):
    """Le pendant durable : demain une sonde s'ajoutera, et elle ne sera pas
    dans `_NAME_FR`. L'echappement doit la couvrir sans qu'on y pense."""
    import time as _t
    monkeypatch.setattr(bm, "_state", {
        "une_sonde_tout_a_fait_nouvelle": {
            "confirmed": "DOWN", "last_change_ts": _t.time() - 60}})
    monkeypatch.setattr(bm, "_last_cycle_ts", None)
    msg = bm.tg_build_status_reply()
    hors_code = "".join(p for i, p in enumerate(msg.split("`")) if i % 2 == 0)
    non_echappes = sum(1 for i, c in enumerate(hors_code)
                       if c == "_" and (i == 0 or hors_code[i - 1] != "\\"))
    assert non_echappes % 2 == 0, (
        "une sonde non mappee casse encore la reponse : %d souligne(s) "
        "non echappe(s)" % non_echappes)
