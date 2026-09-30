"""Garde-fous de `mt5-bridge-monitor/disk_reclaim.py`.

Ce que ces tests protegent, dans l'ordre d'importance :

1. La recuperation ne SUPPRIME jamais de donnees — verifie par AST, pas en
   lisant les commentaires ([[feedback_un_test_ne_doit_pas_lire_les_commentaires]]).
2. Une base VIVANTE n'est jamais candidate, meme si son nom attrape un motif.
3. Le seuil vient de `monitor.env`, donc il ne peut pas diverger de la sonde
   `disk_root` qui declenche l'alerte.
4. Sous le seuil, AUCUNE etape n'est executee.
"""

from __future__ import annotations

import ast
import importlib.util
import time
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "mt5-bridge-monitor" / "disk_reclaim.py"
)


def charger():
    spec = importlib.util.spec_from_file_location("disk_reclaim", MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dr():
    return charger()


# --------------------------------------------------------------------------
# 1. Aucune suppression — la garantie centrale
# --------------------------------------------------------------------------
def test_le_module_n_appelle_AUCUNE_primitive_de_suppression():
    """Un temoin structurel : si quelqu'un ajoute un `unlink`, ce test tombe.

    On parse l'AST au lieu de chercher une chaine dans le texte : un
    commentaire qui parle de suppression ne doit pas faire passer ni echouer
    le test.
    """
    arbre = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    interdits = {"remove", "unlink", "rmtree", "rmdir", "removedirs"}
    trouves = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        f = noeud.func
        nom = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        if nom in interdits:
            trouves.append((nom, noeud.lineno))
    assert trouves == [], "primitives de suppression appelees : %r" % trouves


def test_aucune_commande_externe_destructrice(dr):
    """`gzip` et les `prune` docker sont permis ; `rm` ne l'est pas."""
    arbre = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    binaires = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.List) and noeud.elts:
            prem = noeud.elts[0]
            if isinstance(prem, ast.Constant) and isinstance(prem.value, str):
                binaires.add(prem.value)
    assert "rm" not in binaires
    assert "shred" not in binaires
    assert "gzip" in binaires or "nice" in binaires


# --------------------------------------------------------------------------
# 2. Les bases vivantes sont hors d'atteinte
# --------------------------------------------------------------------------
def _vieux(p: Path, octets: int, jours: float = 30.0) -> Path:
    p.write_bytes(b"x" * octets)
    t = time.time() - jours * 86400
    import os

    os.utime(p, (t, t))
    return p


def test_un_instantane_date_est_candidat(dr, tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "DATA_DIR", tmp_path)
    cible = _vieux(tmp_path / "trades.db.bak-20260813T174019Z-pre-close-reason", 20_000_000)
    assert dr.candidats_inertes() == [cible]


def test_la_liste_JAMAIS_mord_meme_si_le_motif_attrape(dr, tmp_path, monkeypatch):
    """Temoin POSITIF de la ceinture-bretelles.

    On elargit volontairement les motifs a `*.db` pour que les bases vivantes
    soient attrapees, et on verifie que la liste dure les rejette quand meme.
    Sans ce test, `JAMAIS` serait du code jamais eprouve.
    """
    monkeypatch.setattr(dr, "DATA_DIR", tmp_path)
    monkeypatch.setattr(dr, "MOTIFS_INERTES", ("*.db",))
    for nom in ("backtest.db", "trades.db", "macro.db", "candles_5min.db"):
        _vieux(tmp_path / nom, 20_000_000)
    inerte = _vieux(tmp_path / "vieille-copie.db", 20_000_000)
    monkeypatch.setattr(dr, "MOTIFS_INERTES", ("*.db",))

    cands = dr.candidats_inertes()
    noms = {p.name for p in cands}
    assert noms == {inerte.name}, "une base vivante est passee : %r" % noms
    for nom in dr.JAMAIS:
        assert nom not in noms


def test_un_fichier_recent_n_est_pas_candidat(dr, tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "DATA_DIR", tmp_path)
    p = tmp_path / "trades.db.bak-20260930-tout-frais"
    p.write_bytes(b"x" * 20_000_000)  # mtime = maintenant
    assert dr.candidats_inertes() == []


def test_un_fichier_deja_compresse_n_est_pas_candidat(dr, tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "DATA_DIR", tmp_path)
    _vieux(tmp_path / "trades.db.bak-20260813-pre-truc.gz", 20_000_000)
    assert dr.candidats_inertes() == []


def test_un_petit_fichier_n_est_pas_candidat(dr, tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "DATA_DIR", tmp_path)
    _vieux(tmp_path / "trades.db.bak-20260813-petit", 1_000)
    assert dr.candidats_inertes() == []


def test_le_plus_gros_passe_en_premier(dr, tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "DATA_DIR", tmp_path)
    _vieux(tmp_path / "trades.db.bak-20260801-petit", 15_000_000)
    gros = _vieux(tmp_path / "trades.db.bak-20260802-gros", 40_000_000)
    assert dr.candidats_inertes()[0] == gros


# --------------------------------------------------------------------------
# 3. Le seuil ne peut pas diverger de la sonde disk_root
# --------------------------------------------------------------------------
def test_le_seuil_est_lu_dans_monitor_env(dr, tmp_path, monkeypatch, capsys):
    env = tmp_path / "monitor.env"
    env.write_text("# commentaire\nDISK_WARN_PCT=42\nAUTRE=x\n")
    monkeypatch.setattr(dr, "MONITOR_ENV", env)
    assert dr.lire_env(env)["DISK_WARN_PCT"] == "42"

    monkeypatch.setattr(dr, "usage", lambda: (10.0, 5_000_000_000, 16_000_000_000))
    monkeypatch.setattr(dr, "journaliser", lambda e: None)
    assert dr.main([]) == 0
    assert "seuil 42.0%" in capsys.readouterr().out


def test_sous_le_seuil_aucune_etape_n_est_executee(dr, monkeypatch, capsys):
    def interdit(_sec):
        raise AssertionError("une etape a tourne alors qu'on est sous le seuil")

    monkeypatch.setattr(dr, "ETAPES", (interdit,))
    monkeypatch.setattr(dr, "usage", lambda: (50.0, 8_000_000_000, 16_000_000_000))
    monkeypatch.setattr(dr, "journaliser", lambda e: None)
    assert dr.main(["--seuil", "85"]) == 0
    assert "rien a faire" in capsys.readouterr().out


def test_au_dessus_du_seuil_les_etapes_tournent_et_le_journal_est_ecrit(
    dr, monkeypatch
):
    appels = []
    monkeypatch.setattr(
        dr, "ETAPES", (lambda sec: (appels.append(sec) or ("bidon", True, "fait", 0)),)
    )
    monkeypatch.setattr(dr, "usage", lambda: (97.0, 500_000_000, 16_000_000_000))
    monkeypatch.setattr(dr, "telegram", lambda m: True)
    ecrits: list[dict] = []
    monkeypatch.setattr(dr, "journaliser", ecrits.append)
    monkeypatch.setattr(dr, "lire_etat", lambda: {})
    monkeypatch.setattr(dr, "ecrire_etat", lambda d: None)

    assert dr.main(["--seuil", "85"]) == 0
    assert appels == [False], "l'etape n'a pas tourne en mode reel"
    assert len(ecrits) == 1
    assert ecrits[0]["decision"] == "execute"
    assert ecrits[0]["etapes"][0]["nom"] == "bidon"


def test_dry_run_n_execute_rien_et_ne_parle_pas(dr, monkeypatch):
    monkeypatch.setattr(
        dr, "ETAPES", (lambda sec: ("bidon", True, "simulation" if sec else "REEL", 0),)
    )
    monkeypatch.setattr(dr, "usage", lambda: (97.0, 500_000_000, 16_000_000_000))
    dit = []
    monkeypatch.setattr(dr, "telegram", lambda m: dit.append(m) or True)
    ecrits: list[dict] = []
    monkeypatch.setattr(dr, "journaliser", ecrits.append)

    assert dr.main(["--dry-run", "--seuil", "85"]) == 0
    assert ecrits[0]["decision"] == "simulation"
    assert ecrits[0]["etapes"][0]["detail"] == "simulation"
    assert dit == [], "le mode simulation a envoye un Telegram"


# --------------------------------------------------------------------------
# 4. L'hysteresis : on s'arrete sous la cible, pas au seuil
# --------------------------------------------------------------------------
def test_on_s_arrete_des_que_la_cible_est_atteinte(dr, monkeypatch):
    mesures = iter([(97.0, 5e8, 1.6e10), (80.0, 3e9, 1.6e10), (80.0, 3e9, 1.6e10)])
    dernier = [(80.0, 3e9, 1.6e10)]

    def usage_fausse():
        try:
            dernier[0] = next(mesures)
        except StopIteration:
            pass
        return dernier[0]

    appels = []
    monkeypatch.setattr(dr, "usage", usage_fausse)
    monkeypatch.setattr(
        dr,
        "ETAPES",
        (
            lambda sec: (appels.append("a") or ("a", True, "", 0)),
            lambda sec: (appels.append("b") or ("b", True, "", 0)),
        ),
    )
    monkeypatch.setattr(dr, "journaliser", lambda e: None)
    monkeypatch.setattr(dr, "telegram", lambda m: True)
    monkeypatch.setattr(dr, "lire_etat", lambda: {})
    monkeypatch.setattr(dr, "ecrire_etat", lambda d: None)

    dr.main(["--seuil", "85"])
    assert appels == [], "on a agi alors que la cible etait deja atteinte"


# --------------------------------------------------------------------------
# 5. Le comptage : ce que le nettoyage rend != ce que l'espace libre fait
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "texte,attendu",
    [
        ("Total reclaimed space: 215.1MB", 215_100_000),
        ("Total reclaimed space: 0B", 0),
        ("freed 152.9M of archived journals", 152_900_000),
        ("Archived and active journals take up 58.3M in the file system.", 58_300_000),
        ("200M", 200_000_000),
        ("rien de chiffre ici", 0),
        ("", 0),
    ],
)
def test_octets_lit_les_volumes_cites(dr, texte, attendu):
    assert dr.octets(texte) == attendu


def test_libere_mo_compte_le_GAIN_pas_la_variation_d_espace(dr, monkeypatch):
    """Le defaut vu sur le vrai serveur : gzip avait rendu 87 Mo et le journal
    affichait « -8 Mo », parce que la machine avait ecrit a cote pendant ce
    temps. Les deux nombres doivent coexister et rester distincts.
    """
    # espace libre qui DIMINUE entre le debut et la fin
    mesures = iter([(97.0, 1_000_000_000, 1.6e10), (97.0, 992_000_000, 1.6e10)])
    dernier = [(97.0, 992_000_000, 1.6e10)]

    def usage_fausse():
        try:
            dernier[0] = next(mesures)
        except StopIteration:
            pass
        return dernier[0]

    monkeypatch.setattr(dr, "usage", usage_fausse)
    monkeypatch.setattr(
        dr, "ETAPES", (lambda sec: ("gzip_bases_inertes", True, "95 Mo -> 8 Mo", 87_000_000),)
    )
    ecrits: list[dict] = []
    monkeypatch.setattr(dr, "journaliser", ecrits.append)
    monkeypatch.setattr(dr, "telegram", lambda m: True)
    monkeypatch.setattr(dr, "lire_etat", lambda: {})
    monkeypatch.setattr(dr, "ecrire_etat", lambda d: None)

    dr.main(["--seuil", "85"])
    e = ecrits[0]
    assert e["libere_mo"] == 87, "le gain attribue au nettoyage est perdu"
    assert e["delta_libre_mo"] == -8, "la variation observee doit rester visible"


def test_la_porte_telegram_juge_sur_le_gain_attribue(dr, monkeypatch):
    """Sans ca, un vrai nettoyage de 87 Mo resterait muet parce que l'espace
    libre avait baisse."""
    monkeypatch.setattr(dr, "usage", lambda: (97.0, 992_000_000, 1.6e10))
    monkeypatch.setattr(
        dr, "ETAPES", (lambda sec: ("gzip_bases_inertes", True, "rendu", 87_000_000),)
    )
    monkeypatch.setattr(dr, "journaliser", lambda e: None)
    dits: list[str] = []
    monkeypatch.setattr(dr, "telegram", lambda m: dits.append(m) or True)
    # etat recent : seule la regle « assez libere » peut declencher la parole
    monkeypatch.setattr(dr, "lire_etat", lambda: {"dernier_cri": time.time()})
    monkeypatch.setattr(dr, "ecrire_etat", lambda d: None)

    dr.main(["--seuil", "85"])
    assert len(dits) == 1, "un nettoyage reel de 87 Mo est reste muet"
    assert "87 Mo rendus par le nettoyage" in dits[0]


def test_le_vacuum_du_journal_est_saute_s_il_n_a_rien_a_retirer(dr, monkeypatch):
    """Un `--vacuum-size` sans rien a retirer fait tourner le journal et
    ALLOUE un fichier neuf : l'etape couterait de l'espace."""
    appels: list[list[str]] = []

    def run_faux(cmd, timeout):
        appels.append(cmd)
        if "--disk-usage" in cmd:
            return True, "Archived and active journals take up 58.3M in the file system."
        return True, "Vacuuming done, freed 0B"

    monkeypatch.setattr(dr, "run", run_faux)
    monkeypatch.setattr(dr, "JOURNAL_KEEP", "200M")
    nom, ok, detail, gagne = dr.etape_journal(False)
    assert ok and gagne == 0
    assert "pas de rotation inutile" in detail
    assert not any("--vacuum-size=200M" in c for cmd in appels for c in cmd), (
        "le vacuum a tourne alors que le journal etait deja sous la garde"
    )


def test_le_vacuum_tourne_quand_le_journal_depasse(dr, monkeypatch):
    appels: list[list[str]] = []

    def run_faux(cmd, timeout):
        appels.append(cmd)
        if "--disk-usage" in cmd:
            return True, "Archived and active journals take up 900.0M in the file system."
        return True, "Vacuuming done, freed 700.0M of archived journals"

    monkeypatch.setattr(dr, "run", run_faux)
    monkeypatch.setattr(dr, "JOURNAL_KEEP", "200M")
    nom, ok, detail, gagne = dr.etape_journal(False)
    assert ok and gagne == 700_000_000
    assert any("--vacuum-size=200M" in c for cmd in appels for c in cmd)


def test_etape_gzip_compte_le_gain_reel_du_fichier(dr, tmp_path, monkeypatch):
    """Sans ce test, `etape_gzip` pouvait rendre 0 sans que rien ne tombe.

    On remplace l'appel a `gzip` par une vraie compression Python : le binaire
    (`nice`, `gzip`) n'existe pas partout, mais l'arithmetique du gain, elle,
    doit etre eprouvee.
    """
    import gzip as gzlib
    import os

    monkeypatch.setattr(dr, "DATA_DIR", tmp_path)
    src = tmp_path / "trades.db.bak-20260801-temoin"
    src.write_bytes(b"SQLite format 3\x00" + b"a" * 30_000_000)  # tres compressible
    vieux = time.time() - 30 * 86400
    os.utime(src, (vieux, vieux))
    avant = src.stat().st_size

    def run_faux(cmd, timeout):
        chemin = Path(cmd[-1])
        with open(chemin, "rb") as f, gzlib.open(str(chemin) + ".gz", "wb") as g:
            g.write(f.read())
        os.unlink(chemin)  # c'est `gzip` qui le fait, pas le module teste
        return True, ""

    monkeypatch.setattr(dr, "run", run_faux)
    nom, ok, detail, gagne = dr.etape_gzip(False)

    apres = Path(str(src) + ".gz").stat().st_size
    assert ok and nom == "gzip_bases_inertes"
    assert gagne == avant - apres, "le gain rendu ne correspond pas aux tailles"
    assert gagne > 20_000_000, "un fichier tres compressible doit rendre beaucoup"
    assert Path(str(src) + ".gz").exists(), "la donnee doit rester, compressee"


def test_etape_gzip_ne_compte_rien_si_gzip_echoue(dr, tmp_path, monkeypatch):
    import os

    monkeypatch.setattr(dr, "DATA_DIR", tmp_path)
    src = tmp_path / "trades.db.bak-20260801-temoin"
    src.write_bytes(b"x" * 30_000_000)
    vieux = time.time() - 30 * 86400
    os.utime(src, (vieux, vieux))

    monkeypatch.setattr(dr, "run", lambda cmd, timeout: (False, "disk full"))
    nom, ok, detail, gagne = dr.etape_gzip(False)
    assert not ok and gagne == 0
    assert src.exists(), "un echec ne doit pas faire disparaitre le fichier"
