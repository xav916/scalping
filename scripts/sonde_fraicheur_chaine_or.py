#!/usr/bin/env python3
"""La chaine de l'or produit-elle encore de la DONNEE FRAICHE ?

Ecrite le 25/10 apres CINQ pannes silencieuses trouvees le meme jour :

  1. le magasin de ticks affichait "tranches lues : 0" et sortait en code 0
  2. un de ses passages a PENDU 29 h, sans timeout
  3. le `flock -n` de la crontab faisait sauter les suivants SANS une ligne
  4. la reconciliation de `shadow_setups` est morte le 21/08, et le rapport
     hebdomadaire republiait le meme n=971 en concluant
     "echantillon insuffisant" -- un verdict d'apparence NORMALE
  5. l'EC2 s'etait deconnecte du tailnet : plus aucune route vers le pont

🔑 CE QUE J'AI VERIFIE TOUTE LA JOURNEE ET QUI NE PROUVE RIEN :
   un cron arme, un script present, un conteneur "Up 11 days".
   La SEULE chose qui prouve que la chaine fonctionne, c'est de la donnee
   RECENTE. Cette sonde ne demande donc jamais "le job tourne-t-il ?" mais
   "la donnee est-elle fraiche ?".

⛔ ELLE EST FAIL-CLOSED : si elle ne PEUT PAS verifier (base illisible, pont
muet, table absente), elle CRIE. Une sonde qui se taise faute de pouvoir
mesurer reproduit exactement le defaut qu'elle surveille.

Usage :
    python3 sonde_fraicheur_chaine_or.py            # verifie et alerte
    python3 sonde_fraicheur_chaine_or.py --a-blanc  # verifie et AFFICHE, sans envoyer

Code de sortie : 0 si tout est frais, 1 si au moins une assertion echoue.
"""
from __future__ import annotations

import os
import sys
import sqlite3
import datetime as dt
import urllib.request

TICKS = os.environ.get("SONDE_TICKS_DB", "/app/data/ticks_courtier.db")
TRADES = os.environ.get("SONDE_TRADES_DB", "/app/data/trades.db")
# ⛔ DEFAUT DU 25/10 : je surveillais `MT5_BRIDGE_URL`, qui est le pont DEMO
# (Pepperstone, port 8787). Le pont qui porte l'argent est `MT5_BRIDGE_LIVE_URL`
# (IC Markets, port 8788) -- c'est lui que lisent `batir_magasin_ticks.py` et
# `bougies_du_pont` (destination `admin_live`). J'ai passe une journee a
# diagnostiquer le demo en le prenant pour le reel : le demo etait bien casse
# ("Authorization failed"), le reel repondait.
# 🔑 Surveiller la mauvaise adresse, c'est etre rassure par le mauvais signal.
PONT = (os.environ.get("MT5_BRIDGE_LIVE_URL")
        or os.environ.get("MT5_BRIDGE_URL", ""))
# Le pont DEMO est surveille aussi, mais sans faire echouer la chaine de l'or :
# son arret n'empeche ni une mesure ni un trade reel.
PONT_DEMO = os.environ.get("MT5_BRIDGE_URL", "")
CANAL = os.environ.get("SONDE_FRAICHEUR_CANAL", "ic_markets")

# Les seuils. Chacun est un CHOIX, pas une verite : ils sont la pour etre
# discutes, et un seuil franchi doit valoir un message, pas un haussement
# d'epaules.
SEUIL_TICK_MIN = float(os.environ.get("SONDE_SEUIL_TICK_MIN", "30"))
# 🔑 LE PLAFOND QUE LA FERMETURE PEUT EXPLIQUER. La coupure hebdomadaire va du
# vendredi ~20h55 UTC au dimanche 22h00 UTC, soit ~49 h. Une donnee plus vieille
# que ca n'est PAS explicable par le marche ferme : c'est une panne, et la sonde
# doit le dire meme le dimanche soir.
# ⛔ Sans ce plafond, mon premier jet affichait "OK" sur un magasin vieux de
# 13 786 minutes -- un week-end suffisait a endormir la sonde. C'est exactement
# le defaut qu'elle existe pour attraper.
PLAFOND_FERMETURE_MIN = float(os.environ.get("SONDE_PLAFOND_FERMETURE_MIN", "3600"))
SEUIL_DETECTION_MIN = float(os.environ.get("SONDE_SEUIL_DETECTION_MIN", "120"))
SEUIL_RECONCILIATION_J = float(os.environ.get("SONDE_SEUIL_RECONCILIATION_J", "7"))
TIMEOUT_PONT = float(os.environ.get("SONDE_TIMEOUT_PONT", "10"))


ETAT = os.environ.get("SONDE_FRAICHEUR_ETAT",
                      "/app/data/sonde_fraicheur_etat.json")
# 🔑 ANTI-REPETITION. Une alerte qui revient toutes les 15 min s'apprend a
# s'ignorer, et une sonde qu'on ignore ne sert a rien : mesure du 04/09,
# « une sonde qui repete devient du bruit ». On ne reparle donc que si la
# LISTE des echecs CHANGE, ou apres ce delai de rappel.
RAPPEL_H = float(os.environ.get("SONDE_FRAICHEUR_RAPPEL_H", "6"))


def maintenant() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _envoi_direct(titre: str, corps: str) -> tuple[bool, str]:
    """Poste sur Telegram SANS passer par l'application. (parti, detail)

    🔑 POURQUOI CETTE VOIE EXISTE, mesure du 25/10 : `notifier()` poste sur
    l'API interne (`127.0.0.1:8000`). Or cette API etait MUETTE
    (`http=000` apres 8 s) parce que la boucle d'evenements du radar etait
    saturee par les appels au pont qui pendaient — alors que
    `api.telegram.org` repondait en 0,096 s.

    ⛔ LA CHAINE COMPLETE : le pont tombe -> les appels pendent -> la boucle
    sature -> l'API interne meurt -> AUCUNE alerte ne peut partir. La panne
    emportait le mecanisme cense la signaler. Une sonde qui ne sait parler que
    par l'application serait donc muette exactement dans le cas qu'elle
    surveille.
    """
    try:
        sys.path.insert(0, "/app")
        from backend.services.canaux_telegram import jeton_et_chat
        jeton, chat = jeton_et_chat(CANAL)
    except Exception as e:  # noqa: BLE001
        return False, "jeton introuvable (%s)" % e
    if not jeton or not chat:
        return False, "jeton ou chat_id absent de l'environnement"
    try:
        import json
        donnees = json.dumps({"chat_id": chat,
                              "text": "%s\n\n%s" % (titre, corps)}).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot%s/sendMessage" % jeton,
            data=donnees, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return (r.getcode() == 200), "http=%s" % r.getcode()
    except Exception as e:  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


def _etat_lu() -> dict:
    try:
        import json
        with open(ETAT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _etat_ecrit(signature: str, t: dt.datetime) -> None:
    try:
        import json
        with open(ETAT, "w", encoding="utf-8") as f:
            json.dump({"signature": signature, "envoye_a": t.isoformat()}, f)
    except Exception as e:  # noqa: BLE001
        # ⛔ Ne pas pouvoir memoriser ne doit pas empecher d'alerter : on le DIT
        # et on continue, quitte a repeter. Repeter vaut mieux que se taire.
        print("⚠️ etat non ecrit (%s) — la prochaine alerte se repetera" % e)


def _doit_parler(echecs: list[str], t: dt.datetime) -> tuple[bool, str]:
    """(parler, signature). On parle si les echecs CHANGENT ou si le rappel
    est echu.

    ⛔ FAIL-CLOSED : un etat absent ou illisible fait PARLER. Se taire parce
    qu'on n'arrive pas a lire sa propre memoire serait le comble.
    """
    signature = " | ".join(sorted(echecs))
    ancien = _etat_lu()
    if ancien.get("signature") != signature:
        return True, signature
    try:
        depuis = (t - dt.datetime.fromisoformat(ancien["envoye_a"])
                  ).total_seconds() / 3600.0
    except Exception:
        return True, signature
    return (depuis >= RAPPEL_H), signature


def marche_ouvert(t: dt.datetime) -> tuple[bool, str]:
    """L'or est-il cote ? (ouvert, raison)

    Horaires REELS mesures le 10/10 sur le magasin du courtier : coupure
    hebdomadaire du vendredi ~20h55 UTC au dimanche 22h00 UTC.

    ⚠️ L'heure d'ete americaine se termine le 01/11/2026. Le courtier suit
    l'heure des Etats-Unis, donc l'ouverture du dimanche devrait glisser de
    22h00 a 23h00 UTC ce jour-la. Ce seuil n'est PAS encore verifie : la
    premiere bougie du dimanche 01/11 doit etre mesuree. En attendant, on
    reste volontairement LARGE (on considere ferme jusqu'a 23h00 le dimanche)
    pour ne pas crier a tort -- une fausse alarme hebdomadaire ferait ignorer
    les vraies.
    """
    jour = t.weekday()            # 0 = lundi, 6 = dimanche
    if jour == 5:                 # samedi
        return False, "samedi"
    if jour == 4 and t.hour >= 21:
        return False, "vendredi apres la cloture"
    if jour == 6 and t.hour < 23:
        return False, "dimanche avant l'ouverture"
    return True, ""


def _age_minutes(horodatage: str | None, t: dt.datetime) -> float | None:
    if not horodatage:
        return None
    try:
        s = str(horodatage).replace(" ", "T")[:19]
        d = dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc)
        return (t - d).total_seconds() / 60.0
    except Exception:
        return None


def _age_invalide(age: float | None) -> bool:
    """Un horodatage dans le FUTUR trahit une horloge decalee ou un fuseau
    melange. Ca ne doit JAMAIS passer pour frais.

    ⛔ Vu a l'ecriture : la sonde affichait "OK  detection : il y a -0 min".
    Une donnee du futur lue comme fraiche, c'est le defaut exact qu'elle
    surveille, place dans la sonde elle-meme.
    """
    return age is not None and age < -2.0


def _une_valeur(chemin: str, requete: str, params: tuple = ()) -> tuple[object, str | None]:
    """(valeur, erreur). L'erreur est un texte quand la lecture a echoue."""
    try:
        c = sqlite3.connect("file:%s?mode=ro" % chemin, uri=True)
        return c.execute(requete, params).fetchone()[0], None
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


def verifier() -> list[tuple[bool, str]]:
    """Les assertions, dans l'ordre de la chaine. (ok, message)"""
    t = maintenant()
    ouvert, raison = marche_ouvert(t)
    resultats: list[tuple[bool, str]] = []

    # 1. LE PONT — la seule source de prix ET la seule voie d'execution.
    #    On le teste meme marche ferme : le serveur repond a /health en
    #    permanence, et c'est precisement sa disparition qui nous a echappe
    #    9 jours.
    if not PONT:
        resultats.append((False, "pont : MT5_BRIDGE_URL absente de l'environnement"))
    else:
        try:
            req = urllib.request.Request(PONT.rstrip("/") + "/health")
            with urllib.request.urlopen(req, timeout=TIMEOUT_PONT) as r:
                code = r.getcode()
            resultats.append((code == 200, "pont : /health rend %s" % code))
        except Exception as e:  # noqa: BLE001
            resultats.append((False, "pont : INJOIGNABLE (%s) — ni prix, ni execution"
                                     % type(e).__name__))

    # 1 bis. LE PONT DEMO — signale, mais NON BLOQUANT : son arret n'empeche
    #         ni une mesure ni un trade reel. On le DIT quand meme, sinon on
    #         decouvre sa panne des semaines plus tard, comme aujourd'hui.
    if PONT_DEMO and PONT_DEMO != PONT:
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(PONT_DEMO.rstrip("/") + "/health"),
                    timeout=TIMEOUT_PONT) as r:
                code = r.getcode()
            resultats.append((True, "pont demo : /health rend %s (informatif)" % code))
        except Exception as e:  # noqa: BLE001
            resultats.append((True, "pont demo : injoignable (%s) — informatif, "
                                    "n'empeche ni mesure ni trade reel"
                                    % type(e).__name__))

    # 2. LE MAGASIN DE TICKS — fraicheur, et seulement en seance.
    val, err = _une_valeur(TICKS, "select max(ts_utc) from ticks where pair=?",
                           ("XAU/USD",))
    if err:
        resultats.append((False, "magasin : ILLISIBLE (%s)" % err))
    else:
        age = _age_minutes(val, t)
        if age is None or _age_invalide(age):
            resultats.append((False, "magasin : dernier tick illisible ou dans le FUTUR (%r)" % val))
        elif not ouvert:
            # La fermeture explique au plus ~49 h. Au-dela, c'est une panne.
            resultats.append((age <= PLAFOND_FERMETURE_MIN,
                              "magasin : dernier tick il y a %.0f min "
                              "(marche ferme : %s — la fermeture n'explique "
                              "que %.0f min)" % (age, raison, PLAFOND_FERMETURE_MIN)))
        else:
            resultats.append((age <= SEUIL_TICK_MIN,
                              "magasin : dernier tick il y a %.0f min "
                              "(seuil %.0f)" % (age, SEUIL_TICK_MIN)))

    # 3. LA DETECTION — elle s'est arretee le 16/10 a 10h27 avec le pont, et
    #    personne ne l'a vu.
    val, err = _une_valeur(TRADES, "select max(detected_at) from shadow_setups")
    if err:
        resultats.append((False, "detection : table ILLISIBLE (%s)" % err))
    else:
        age = _age_minutes(val, t)
        if age is None or _age_invalide(age):
            resultats.append((False, "detection : dernier setup illisible ou dans le FUTUR (%r)" % val))
        elif not ouvert:
            resultats.append((age <= PLAFOND_FERMETURE_MIN,
                              "detection : dernier setup il y a %.0f min "
                              "(marche ferme — la fermeture n'explique que "
                              "%.0f min)" % (age, PLAFOND_FERMETURE_MIN)))
        else:
            resultats.append((age <= SEUIL_DETECTION_MIN,
                              "detection : dernier setup il y a %.0f min "
                              "(seuil %.0f)" % (age, SEUIL_DETECTION_MIN)))

    # 4. LA RECONCILIATION — morte depuis le 21/08, et le rapport hebdomadaire
    #    la camouflait en republiant le meme n=971 avec un verdict plausible.
    #    Ce seuil est en JOURS : un setup se resout quand son issue tombe, pas
    #    dans la minute.
    val, err = _une_valeur(
        TRADES, "select max(detected_at) from shadow_setups where outcome is not null")
    if err:
        resultats.append((False, "reconciliation : table ILLISIBLE (%s)" % err))
    else:
        age = _age_minutes(val, t)
        if age is None or _age_invalide(age):
            resultats.append((False, "reconciliation : aucun setup resolu, ou date dans le FUTUR (%r)" % val))
        else:
            jours = age / 1440.0
            resultats.append((jours <= SEUIL_RECONCILIATION_J,
                              "reconciliation : dernier setup resolu il y a "
                              "%.1f j (seuil %.0f)" % (jours, SEUIL_RECONCILIATION_J)))
    return resultats


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    a_blanc = "--a-blanc" in argv

    resultats = verifier()
    echecs = [m for ok, m in resultats if not ok]
    t = maintenant().strftime("%Y-%m-%d %H:%M UTC")

    for ok, message in resultats:
        print("  %s %s" % ("OK  " if ok else "ECHEC", message))

    if not echecs:
        print("\n%s — chaine de l'or : donnee FRAICHE sur les %d assertions"
              % (t, len(resultats)))
        # 🔑 LE RETOUR A LA NORMALE SE DIT AUSSI. Sans ca, on ne sait jamais si
        # le silence veut dire « repare » ou « la sonde est morte elle aussi ».
        if _etat_lu().get("signature") and not a_blanc:
            try:
                sys.path.insert(0, "/app")
                from backend.services.canaux_telegram import notifier
                parti = notifier(
                    CANAL, "✅ Chaine de l'or : donnee a nouveau FRAICHE",
                    "%s\n\nLes %d assertions passent. Ce qui etait en echec "
                    "est resolu." % (t, len(resultats)))
                if parti:
                    # L'etat n'est efface que si le retour a ete ANNONCE :
                    # sinon on reessaie, sans quoi le retour passe inapercu.
                    _etat_ecrit("", maintenant())
                    print("retour a la normale annonce sur le fil %s" % CANAL)
                else:
                    print("⚠️ retour a la normale NON annonce (routeur) — "
                          "le prochain passage reessaiera")
            except Exception as e:  # noqa: BLE001
                print("⚠️ annonce de retour impossible (%s)" % e)
        return 0

    corps = ("%s\n\n%d assertion(s) en echec sur %d :\n\n%s\n\n"
             "Ce que ca implique : tant qu'une de ces lignes est en echec, "
             "aucune mesure et aucun trade de l'or ne reposent sur de la "
             "donnee a jour." % (t, len(echecs), len(resultats),
                                 "\n".join("• " + m for m in echecs)))
    print("\n--- message ---\n%s" % corps)

    if a_blanc:
        print("\n(--a-blanc : rien n'a ete envoye)")
        return 1

    parler, signature = _doit_parler(echecs, maintenant())
    if not parler:
        print("\n(echecs INCHANGES et rappel de %.0f h non echu — pas de nouveau "
              "message, l'alerte precedente tient)" % RAPPEL_H)
        return 1

    try:
        sys.path.insert(0, "/app")
        from backend.services.canaux_telegram import notifier
        # ⛔ DEFAUT DE MON PREMIER JET, attrape des le premier passage reel :
        # `notifier` NE LEVE PAS quand l'envoi echoue -- elle rend False et le
        # dit dans ses logs. J'ignorais ce retour, donc j'imprimais « alerte
        # envoyee » sur un envoi qui avait expire, ET je memorisais l'etat, ce
        # qui faisait taire la sonde 6 h. Une alarme qui pretend avoir prevenu
        # est pire que pas d'alarme -- et c'est la classe de defaut que cette
        # sonde existe pour attraper. Sa docstring le disait deja.
        parti = notifier(CANAL, "🔴 Chaine de l'or : donnee PERIMEE", corps)
        if parti:
            # 🔑 L'etat n'est memorise QUE si le message est parti : sinon le
            # passage suivant doit REESSAYER, pas se croire quitte.
            _etat_ecrit(signature, maintenant())
            print("\nalerte envoyee sur le fil %s" % CANAL)
        else:
            # Le routeur passe par l'API interne, qui meurt avec la boucle du
            # radar. On repasse par la voie DIRECTE.
            direct, detail = _envoi_direct("🔴 Chaine de l'or : donnee PERIMEE",
                                           corps)
            if direct:
                _etat_ecrit(signature, maintenant())
                print("\nrouteur muet — alerte partie par la VOIE DIRECTE (%s)"
                      % detail)
            else:
                print("\n⚠️ NI le routeur NI la voie directe (%s) — l'alerte "
                      "n'est QUE dans ce journal, et le prochain passage "
                      "REESSAIERA" % detail)
    except Exception as e:  # noqa: BLE001
        # ⛔ Un envoi qui echoue ne doit pas rendre la sonde muette : on le DIT
        # sur la sortie standard, qui part dans le journal de la crontab.
        print("\n⚠️ ENVOI IMPOSSIBLE (%s: %s) — l'alerte n'est QUE dans ce journal"
              % (type(e).__name__, e))
    return 1


if __name__ == "__main__":
    sys.exit(main())
