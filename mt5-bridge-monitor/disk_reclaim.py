#!/usr/bin/env python3
"""Recuperation automatique d'espace disque sur l'EC2 scalping-radar.

DECLENCHEUR
-----------
Meme condition que la sonde `disk_root` de `bridge_monitor.py` : le seuil est
lu dans `monitor.env` (`DISK_WARN_PCT`), donc les deux ne peuvent pas diverger.
Lance par `disk-reclaim.timer` toutes les 5 min, en root.

POURQUOI UN SERVICE SEPARE ET NON LE MONITOR
--------------------------------------------
`scalping-bridge-monitor.service` tourne en `ec2-user` avec
`NoNewPrivileges=yes` : `sudo` y est impossible, et `/opt/scalping/data` est
possede par root. Le monitor ne peut donc pas liberer la ou est la place.
Son action `docker_prune` recuperait 0 B pendant que le disque montait a 97 %.

GARANTIES
---------
- AUCUNE SUPPRESSION DE DONNEES. Pas un seul `rm` sur un `.db`. Les bases
  inertes sont *compressees* (`gzip`), donc restaurables par `gunzip`.
- Les bases vivantes sont exclues par liste dure ET par la condition d'age.
- Budget de temps borne, un seul `gzip` par passage : le timer converge en
  plusieurs passes au lieu de bloquer longtemps.
- Verrou `flock` : jamais deux passages en parallele.
- Journal JSONL durable : `/var/log/scalping/disk_reclaim.log`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:  # absent sous Windows : le module doit rester importable pour les tests
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

MONITOR_ENV = Path(os.getenv("MONITOR_ENV", "/opt/scalping-bridge-monitor/monitor.env"))
APP_ENV = Path(os.getenv("APP_ENV", "/opt/scalping/.env"))
DATA_DIR = Path(os.getenv("RECLAIM_DATA_DIR", "/opt/scalping/data"))
LOG_PATH = Path(os.getenv("RECLAIM_LOG", "/var/log/scalping/disk_reclaim.log"))
STATE_PATH = Path(os.getenv("RECLAIM_STATE", "/var/log/scalping/disk_reclaim_state.json"))
LOCK_PATH = Path(os.getenv("RECLAIM_LOCK", "/run/disk_reclaim.lock"))

CONTAINER = os.getenv("RECLAIM_CONTAINER", "scalping-radar")
HYSTERESIS_PCT = float(os.getenv("RECLAIM_HYSTERESIS_PCT", "3"))
BUDGET_SEC = float(os.getenv("RECLAIM_BUDGET_SEC", "240"))
JOURNAL_KEEP = os.getenv("RECLAIM_JOURNAL_KEEP", "200M")
DOCKER_LOG_MAX_MO = float(os.getenv("RECLAIM_DOCKER_LOG_MAX_MO", "100"))
GZIP_MIN_MO = float(os.getenv("RECLAIM_GZIP_MIN_MO", "10"))
GZIP_MIN_AGE_J = float(os.getenv("RECLAIM_GZIP_MIN_AGE_J", "7"))
MUET_SI_RIEN_SEC = float(os.getenv("RECLAIM_MUET_SI_RIEN_SEC", "21600"))  # 6 h

# Motifs de bases INERTES : des instantanes dates, jamais relus par un service.
MOTIFS_INERTES = (
    "*.db.bak-*",
    "*.db.bak.*",
    "*.db.backup.*",
    "*.db.avant-*",
    "avant-*.db",
    "*.db.old",
    "*.db-pre-*",
)

# Ceinture ET bretelles : ces noms ne doivent JAMAIS etre touches, quel que
# soit le motif qui les attraperait.
JAMAIS = {
    "backtest.db",
    "trades.db",
    "macro.db",
    "scalping.db",
    "analytics.db",
    "audit.db",
    "bridge_audit.db",
    "mt5_pushes.db",
    "scalping_prod.db",
    "candles_5min.db",
    "ml_dataset.db",
    "rejeu_bougies.db",
}


def lire_env(chemin: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for ligne in chemin.read_text(errors="replace").splitlines():
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            cle, _, val = ligne.partition("=")
            out[cle.strip()] = val.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def usage() -> tuple[float, int, int]:
    u = shutil.disk_usage("/")
    return (u.used / u.total) * 100.0, u.free, u.total


def run(cmd: list[str], timeout: float) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        sortie = ((r.stdout or "") + (r.stderr or "")).strip()
        return r.returncode == 0, sortie[:300]
    except Exception as e:  # noqa: BLE001 - on ne veut jamais planter le timer
        return False, "%s: %s" % (type(e).__name__, e)


def mo(n: float) -> str:
    return "%.0f Mo" % (n / 1_000_000)


_UNITES = {
    "B": 1, "KB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000,
    "TB": 1_000_000_000_000, "KIB": 1024, "MIB": 1024 ** 2,
    "GIB": 1024 ** 3, "TIB": 1024 ** 4, "K": 1_000, "M": 1_000_000,
    "G": 1_000_000_000,
}


def octets(texte: str) -> int:
    """Extrait le dernier volume cite par docker/journalctl. 0 si illisible.

    `docker` ecrit « Total reclaimed space: 215.1MB », `journalctl` ecrit
    « freed 152.9M of archived journals ». On ne devine pas : si rien ne
    ressemble a un volume, on rend 0, et le gain attribue reste nul.
    """
    trouves = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*([KMGT]i?B|B|[KMG])\b", texte)
    if not trouves:
        return 0
    val, unite = trouves[-1]
    return int(float(val) * _UNITES.get(unite.upper(), 1))


# ------------------------ les etapes, de la plus sure a la moins --------------
# Chaque etape rend (nom, ok, detail, gagne_octets). `gagne` est le volume
# ATTRIBUABLE a l'etape, pas la variation d'espace libre : la machine ecrit
# pendant qu'on nettoie, et confondre les deux produit des nombres credibles
# et faux (un passage a rendu 87 Mo et affichait « -8 Mo »).
def etape_builder_prune(sec: bool) -> tuple[str, bool, str, int]:
    if sec:
        return "docker_builder_prune", True, "simulation", 0
    ok, out = run(["docker", "builder", "prune", "-f"], 90)
    ligne = out.splitlines()[-1] if out else "ran"
    return "docker_builder_prune", ok, ligne, octets(ligne) if ok else 0


def etape_image_prune(sec: bool) -> tuple[str, bool, str, int]:
    if sec:
        return "docker_image_prune", True, "simulation", 0
    ok, out = run(["docker", "image", "prune", "-f"], 90)
    ligne = out.splitlines()[-1] if out else "ran"
    return "docker_image_prune", ok, ligne, octets(ligne) if ok else 0


def etape_journal(sec: bool) -> tuple[str, bool, str, int]:
    """Vide le journal systemd — mais seulement s'il y a quelque chose a vider.

    Un `--vacuum-size` qui n'a rien a retirer fait quand meme tourner le
    journal, ce qui alloue un fichier neuf : l'etape COUTE alors de l'espace
    au lieu d'en rendre.
    """
    ok, u = run(["journalctl", "--disk-usage"], 20)
    actuel = octets(u) if ok else 0
    garde = octets(JOURNAL_KEEP)
    if actuel and garde and actuel <= garde:
        return (
            "journal_vacuum", True,
            "%s <= %s garde, pas de rotation inutile" % (mo(actuel), mo(garde)), 0,
        )
    if sec:
        return "journal_vacuum", True, "simulation (garderait %s)" % JOURNAL_KEEP, 0
    ok, out = run(["journalctl", "--vacuum-size=%s" % JOURNAL_KEEP], 60)
    ligne = out.splitlines()[-1] if out else "ran"
    return "journal_vacuum", ok, ligne, octets(ligne) if ok else 0


def etape_journal_conteneur(sec: bool) -> tuple[str, bool, str, int]:
    ok, chemin = run(["docker", "inspect", "-f", "{{.LogPath}}", CONTAINER], 20)
    if not ok or not chemin:
        return "journal_conteneur", False, "introuvable: %s" % chemin, 0
    p = Path(chemin)
    try:
        taille = p.stat().st_size
    except OSError as e:
        return "journal_conteneur", False, "%s: %s" % (type(e).__name__, e), 0
    if taille < DOCKER_LOG_MAX_MO * 1_000_000:
        return "journal_conteneur", True, "%s < seuil, intact" % mo(taille), 0
    if sec:
        return "journal_conteneur", True, "simulation, tronquerait %s" % mo(taille), 0
    try:
        os.truncate(p, 0)
    except OSError as e:
        return "journal_conteneur", False, "%s: %s" % (type(e).__name__, e), 0
    return "journal_conteneur", True, "tronque, %s rendus" % mo(taille), taille


def candidats_inertes() -> list[Path]:
    """Bases figees, compressables. Trois conditions cumulatives + liste dure."""
    vus: dict[Path, os.stat_result] = {}
    limite = time.time() - GZIP_MIN_AGE_J * 86400
    for motif in MOTIFS_INERTES:
        for p in DATA_DIR.glob(motif):
            if p.suffix == ".gz" or not p.is_file() or p.name in JAMAIS:
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size < GZIP_MIN_MO * 1_000_000 or st.st_mtime > limite:
                continue
            vus[p] = st
    return sorted(vus, key=lambda q: vus[q].st_size, reverse=True)


def etape_gzip(sec: bool) -> tuple[str, bool, str, int]:
    cands = candidats_inertes()
    if not cands:
        return "gzip_bases_inertes", True, "aucun candidat", 0
    cible = cands[0]
    avant = cible.stat().st_size
    if sec:
        return (
            "gzip_bases_inertes",
            True,
            "simulation : %s (%s), %d candidat(s)" % (cible.name, mo(avant), len(cands)),
            0,
        )
    ok, out = run(["nice", "-n", "19", "gzip", "-6", str(cible)], 600)
    if not ok:
        return "gzip_bases_inertes", False, "%s: %s" % (cible.name, out), 0
    try:
        apres = Path(str(cible) + ".gz").stat().st_size
    except OSError:
        apres = 0
    return (
        "gzip_bases_inertes",
        True,
        "%s: %s -> %s, %d candidat(s) restant(s)"
        % (cible.name, mo(avant), mo(apres), len(cands) - 1),
        max(avant - apres, 0),
    )


ETAPES = (
    etape_builder_prune,
    etape_image_prune,
    etape_journal,
    etape_journal_conteneur,
    etape_gzip,
)


# ------------------------------- Telegram ------------------------------------
def telegram(msg: str) -> bool:
    env = {**lire_env(APP_ENV), **lire_env(MONITOR_ENV)}
    jeton = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = env.get("TELEGRAM_CHAT_ID", "").strip()
    if not jeton or not chat:
        return False
    data = urllib.parse.urlencode(
        {"chat_id": chat, "text": msg, "disable_web_page_preview": "true"}
    ).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendMessage" % jeton, data=data
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def lire_etat() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


def ecrire_etat(d: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(d))
    except OSError:
        pass


def journaliser(entree: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(entree, ensure_ascii=False) + "\n")
    except OSError:
        pass


# --------------------------------- main --------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Recuperation d'espace disque.")
    ap.add_argument(
        "--dry-run", action="store_true", help="n'execute rien, montre ce qui serait fait"
    )
    ap.add_argument(
        "--force", action="store_true", help="agit meme sous le seuil (temoin de test)"
    )
    ap.add_argument(
        "--seuil", type=float, default=None, help="force le seuil au lieu de DISK_WARN_PCT"
    )
    args = ap.parse_args(argv)

    env = lire_env(MONITOR_ENV)
    seuil = (
        args.seuil
        if args.seuil is not None
        else float(env.get("DISK_WARN_PCT", "85"))
    )
    cible = max(seuil - HYSTERESIS_PCT, 5.0)

    pct0, libre0, _total = usage()
    entree: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "seuil_pct": seuil,
        "cible_pct": cible,
        "avant": {"used_pct": round(pct0, 1), "free_mo": round(libre0 / 1e6)},
        "dry_run": args.dry_run,
        "etapes": [],
    }

    if pct0 < seuil and not args.force:
        entree["decision"] = "sous_le_seuil_rien_a_faire"
        entree["libere_mo"] = 0
        print("%.1f%% < seuil %.1f%% — rien a faire" % (pct0, seuil))
        return 0

    # Verrou : un seul passage a la fois. systemd empeche deja deux instances
    # du meme service ; ce flock protege les lancements a la main.
    if fcntl is None:
        entree["verrou"] = "indisponible (pas de fcntl)"
    else:
        try:
            LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
            verrou = LOCK_PATH.open("w")
            fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
            entree["verrou"] = "pris"
        except OSError:
            entree["decision"] = "deja_en_cours"
            journaliser(entree)
            print("un autre passage est en cours")
            return 0

    t0 = time.monotonic()
    attribue = 0
    for etape in ETAPES:
        if time.monotonic() - t0 > BUDGET_SEC:
            entree["etapes"].append(
                {"nom": "arret", "ok": True, "detail": "budget de temps epuise",
                 "gagne_mo": 0}
            )
            break
        pct, _, _ = usage()
        if pct < cible and not args.force:
            entree["etapes"].append(
                {
                    "nom": "arret",
                    "ok": True,
                    "detail": "cible %.1f%% atteinte (%.1f%%)" % (cible, pct),
                }
            )
            break
        nom, ok, detail, gagne = etape(args.dry_run)
        attribue += gagne
        pct_ap, libre_ap, _ = usage()
        entree["etapes"].append(
            {
                "nom": nom,
                "ok": ok,
                "detail": detail,
                "gagne_mo": round(gagne / 1e6),
                "used_pct": round(pct_ap, 1),
                "free_mo": round(libre_ap / 1e6),
            }
        )
        print("  %-24s %s %s" % (nom, "ok   " if ok else "ECHEC", detail))

    pct1, libre1, _ = usage()
    entree["apres"] = {"used_pct": round(pct1, 1), "free_mo": round(libre1 / 1e6)}
    # DEUX nombres distincts, et il faut les deux :
    #  - `libere_mo` = ce que le nettoyage a rendu, somme des gains attribues ;
    #  - `delta_libre_mo` = la variation d'espace libre observee, qui inclut
    #    tout ce que la machine a ecrit pendant ce temps et peut donc etre
    #    negative alors que le nettoyage a bien travaille.
    entree["libere_mo"] = round(attribue / 1e6)
    entree["delta_libre_mo"] = round((libre1 - libre0) / 1e6)
    entree["decision"] = "simulation" if args.dry_run else "execute"
    journaliser(entree)

    resume = "%.1f%% -> %.1f%%  (%s rendus par le nettoyage ; espace libre %s -> %s)" % (
        pct0,
        pct1,
        mo(attribue),
        mo(libre0),
        mo(libre1),
    )
    print(resume)

    if not args.dry_run:
        etat = lire_etat()
        maintenant = time.time()
        assez = attribue > 5_000_000
        trop_vieux = maintenant - float(etat.get("dernier_cri", 0)) > MUET_SI_RIEN_SEC
        if assez or trop_vieux:
            lignes = ["🧹 Disque EC2 — recuperation auto : %s" % resume]
            for e in entree["etapes"]:
                marque = "•" if e["ok"] else "⛔"
                lignes.append("%s %s : %s" % (marque, e["nom"], e["detail"]))
            if pct1 >= seuil:
                lignes.append(
                    "⚠️ TOUJOURS au-dessus du seuil %.0f %% — il faut agrandir le "
                    "volume ou poser une retention." % seuil
                )
            if telegram("\n".join(lignes)):
                etat["dernier_cri"] = maintenant
                ecrire_etat(etat)

    return 0


if __name__ == "__main__":
    sys.exit(main())
