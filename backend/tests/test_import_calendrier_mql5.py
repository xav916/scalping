"""L'import de l'historique calendrier exporte du terminal MT5.

Compagnon de [[test_calendrier_historique]] : celui-la empeche de DETRUIRE
l'historique a venir, celui-ci RATTRAPE le passe deja perdu. Au 04/10, le plus
ancien evenement en base datait du 27/09 — sept jours exactement.

## ⚠️ LE PIEGE CENTRAL : UN FUSEAU, PAS UN DECALAGE

Un serveur MT5 typique tourne en EET/EEST : UTC+2 en hiver, UTC+3 en ete. Un
decalage FIXE applique a cinq ans d'historique se trompe donc d'une heure la
moitie de l'annee. Trois erreurs du meme projet disent quoi NE PAS faire :

- le spread mesure a un INSTANT, puis applique a un banc entier ;
- la derive du pont lue sur un tick perime, qui decalait chaque bougie ;
- le taux EUR/USD FIGE a 1,155 quand le courtier cotait 1,1250.

🔑 Ce fichier a d'abord ete ecrit avec un `decalage_h` entier. C'est une
ASSERTION QUI A ECHOUE qui a montre le defaut de modele, pas une relecture :
le gabarit n'avait aucune ligne anterieure a la couverture ForexFactory, donc
l'import n'ecrivait rien. En le rendant realiste (une ligne de 2021 a ecrire,
des lignes de septembre pour calibrer), le probleme de l'heure d'ete est
devenu visible.

## ⛔ ET LA FENETRE DE RECOUVREMENT ACTUELLE NE TRANCHE PAS

27/09 -> aujourd'hui ne traverse PAS le changement d'heure du 25 octobre. Sur
cette fenetre, `Europe/Helsinki` (+3 l'ete) et `Etc/GMT-3` (+3 toute l'annee)
apparient exactement les memes lignes — et divergent d'une heure sur janvier.
Deux tests fixent les deux faces de ce constat : l'ambiguite est levee comme
telle, et elle DISPARAIT des que la fenetre passe le 25 octobre.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import import_calendrier_mql5 as imp


# ─── Un export tel que le script MQL5 l'ecrit vraiment ──────────────────────
# ⚠️ Format COPIE sur CalendrierExport.mq5 : tabulations, deux lignes d'en-tete
# commencant par #, instants au format TimeToString « 2026.10.04 12:30:00 ».
# Un test qui se doublerait un format a lui ne prouverait rien — c'est
# exactement comment 13 tests sur 15 ont valide un `/rates` qui envoyait un
# parametre `count` inexistant du pont.
#
# 🔑 Les heures sont celles d'un serveur en EET/EEST, et les vraies :
#   emploi canadien   15h30 serveur l'ete  -> 12h30 UTC
#   emploi americain  15h30 serveur l'hiver -> 13h30 UTC
_ENTETE = (
    "#export\tgmt=2026.10.04 15:00:00\tserveur=2026.10.04 18:00:00\tbuild=4885\n"
    "#colonnes\tvalue_id\tevent_id\ttime_brut\tperiod\trevision\tactual\t"
    "forecast\tprevious\trevised_previous\timpact_type\timportance\t"
    "code_pays\tdevise\tnom\tsecteur\tunite\tdigits\tevent_code\n"
)
EXPORT = _ENTETE + (
    # publie : actual tres loin du consensus
    "100\t840010\t2026.09.05 15:30:00\t2026.08.01 00:00:00\t0\t"
    "-41.700000\t9.000000\t83.100000\t\t1\t3\tCA\tCAD\t"
    "Employment Change\t4\t8\t1\tCA_EMPL\n"
    # sans chiffre publie : actual VIDE, pas zero
    "101\t840011\t2026.09.05 15:30:00\t2026.08.01 00:00:00\t0\t"
    "\t6.500000\t6.400000\t\t0\t3\tCA\tCAD\t"
    "Unemployment Rate\t4\t1\t1\tCA_UNEMP\n"
    # faible importance, et `period` absente
    "102\t840012\t2026.09.10 11:00:00\t\t0\t"
    "1.200000\t\t\t\t0\t1\tDE\tEUR\t"
    "Retail Sales\t4\t1\t1\tDE_RET\n"
    # ⛔ LA LIGNE QUI COMPTE : cinq ans en arriere, en HIVER. C'est elle que
    # l'import doit ecrire, et c'est sur elle que les fuseaux se contredisent.
    "103\t840013\t2021.01.08 15:30:00\t2020.12.01 00:00:00\t0\t"
    "-140.000000\t50.000000\t336.000000\t\t1\t3\tUS\tUSD\t"
    "Nonfarm Payrolls\t4\t8\t1\tUS_NFP\n"
)

# Un export dont la fenetre recente TRAVERSE le changement d'heure du 25/10 :
# 24 octobre (heure d'ete, +3) et 7 novembre (heure d'hiver, +2). Les deux
# tombent sur 12h30 UTC — ce qu'un decalage fixe ne peut pas reproduire.
EXPORT_TRAVERSE_LE_CHANGEMENT = _ENTETE + (
    "200\t840010\t2026.10.24 15:30:00\t\t0\t"
    "1.000000\t\t\t\t1\t3\tCA\tCAD\tEmployment Change\t4\t8\t1\tCA_EMPL\n"
    "201\t840010\t2026.11.07 14:30:00\t\t0\t"
    "2.000000\t\t\t\t1\t3\tCA\tCAD\tEmployment Change\t4\t8\t1\tCA_EMPL\n"
)


@pytest.fixture
def base(tmp_path):
    """Une base avec le schema reel, vide de toute ligne ForexFactory."""
    chemin = tmp_path / "scalping.db"
    with sqlite3.connect(chemin) as c:
        c.execute("""CREATE TABLE economic_events (
            id TEXT PRIMARY KEY, ts_utc TEXT NOT NULL, currency TEXT NOT NULL,
            event_name TEXT NOT NULL, impact TEXT NOT NULL, actual TEXT,
            forecast TEXT, previous TEXT, fetched_at TEXT NOT NULL)""")
    return chemin


def _ff(chemin, ts_utc: str, devise: str, nom: str, impact: str = "High"):
    """Insere une ligne telle que ForexFactory la produit, id compris.

    ⚠️ Les colonnes sont NOMMEES, comme dans `refresh_calendar()`. La premiere
    version de cette aide ecrivait `VALUES (?,?,...)` sans les nommer — et
    cassait des que l'import ajoutait la colonne `source`. Le vrai code de
    production, lui, les nomme : c'etait ma doublure qui etait irrealiste, au
    point precis ou cela comptait.
    """
    with sqlite3.connect(chemin) as c:
        c.execute(
            "INSERT OR REPLACE INTO economic_events "
            "(id, ts_utc, currency, event_name, impact, actual, forecast, "
            " previous, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{ts_utc}_{devise}_{nom[:40]}", ts_utc, devise, nom, impact,
             None, None, None, "2026-10-04T15:00:00+00:00"))


def _calibre(chemin):
    """Les deux reperes de septembre qui fixent le fuseau (12h30 UTC)."""
    _ff(chemin, "2026-09-05T12:30:00+00:00", "CAD", "Employment Change")
    _ff(chemin, "2026-09-05T12:30:00+00:00", "CAD", "Unemployment Rate")


# ─── La lecture du fichier ──────────────────────────────────────────────────

def test_lit_les_lignes_et_ignore_les_en_tetes():
    lignes = imp.lire_export(EXPORT)
    assert len(lignes) == 4
    assert lignes[0]["value_id"] == "100"
    assert lignes[0]["nom"] == "Employment Change"
    assert lignes[0]["devise"] == "CAD"
    assert lignes[3]["nom"] == "Nonfarm Payrolls"


def test_un_actual_VIDE_reste_vide_et_ne_devient_pas_zero():
    """⛔ Confondre « pas de chiffre publie » et « zero » fabriquerait des
    surprises nulles la ou il n'y a aucune donnee."""
    lignes = imp.lire_export(EXPORT)
    assert lignes[0]["actual"] == "-41.700000"
    assert lignes[1]["actual"] is None, "un champ vide a ete converti en valeur"
    assert lignes[2]["forecast"] is None
    assert lignes[2]["period"] is None


def test_l_importance_MQL5_devient_le_vocabulaire_maison():
    """3 -> High, 2 -> Medium, 1 -> Low. Le reste n'est pas devine."""
    assert imp.impact_depuis_importance("3") == "High"
    assert imp.impact_depuis_importance("2") == "Medium"
    assert imp.impact_depuis_importance("1") == "Low"
    assert imp.impact_depuis_importance("0") == "Low"
    assert imp.impact_depuis_importance("") == "Low"
    assert imp.impact_depuis_importance(None) == "Low"


def test_l_en_tete_rend_gmt_et_serveur():
    """⚠️ Ces deux instants ne donnent le decalage que d'UN instant. Ils
    servent a constater, pas a convertir."""
    meta = imp.lire_entete(EXPORT)
    assert meta["gmt"] == "2026.10.04 15:00:00"
    assert meta["serveur"] == "2026.10.04 18:00:00"
    assert meta["build"] == "4885"


def test_un_export_TRONQUE_est_refuse():
    """⚠️ Un export coupe au milieu d'une ligne passerait pour complet. Le
    `/rates` du pont avait exactement ce defaut : il tronquait en silence, et
    gardait les bougies les plus ANCIENNES."""
    tronque = EXPORT[: EXPORT.rindex("\n", 0, EXPORT.rindex("\n")) + 60]
    with pytest.raises(imp.ExportInvalide):
        imp.lire_export(tronque)


def test_un_fichier_sans_en_tete_de_colonnes_est_refuse():
    with pytest.raises(imp.ExportInvalide):
        imp.lire_export("100\t840010\t2026.09.05 14:30:00\n")


# ─── La conversion, heure d'ete comprise ────────────────────────────────────

def test_l_heure_d_ete_est_appliquee_instant_par_instant():
    """⛔ LE TEST QUI JUSTIFIE TOUT LE MODELE. Le MEME fuseau rend +3 en
    septembre et +2 en janvier. Un decalage fixe ne peut pas faire les deux."""
    ete = imp.instant_utc("2026.09.05 15:30:00", "Europe/Helsinki")
    hiver = imp.instant_utc("2021.01.08 15:30:00", "Europe/Helsinki")
    assert ete == "2026-09-05T12:30:00+00:00", "ete : +3 attendu"
    assert hiver == "2021-01-08T13:30:00+00:00", "hiver : +2 attendu"


def test_un_fuseau_FIXE_ignore_l_heure_d_ete():
    """Le contre-exemple : `Etc/GMT-3` c'est UTC+3 toute l'annee. Il colle en
    septembre et se trompe d'une heure en janvier."""
    assert imp.instant_utc("2026.09.05 15:30:00", "Etc/GMT-3") == \
        "2026-09-05T12:30:00+00:00"
    assert imp.instant_utc("2021.01.08 15:30:00", "Etc/GMT-3") == \
        "2021-01-08T12:30:00+00:00"


def test_un_instant_illisible_rend_None_sans_lever():
    assert imp.instant_utc("pas une date", "UTC") is None
    assert imp.instant_utc(None, "UTC") is None
    assert imp.instant_utc("", "UTC") is None


# ─── La mesure du fuseau ────────────────────────────────────────────────────

def test_le_fuseau_est_MESURE_contre_forexfactory(base):
    """Les deux reperes de septembre sont a 12h30 UTC. Les fuseaux a +3 en
    septembre apparient 2 lignes ; les autres, zero."""
    _calibre(base)
    scores = imp.mesurer_fuseau(EXPORT, base)
    assert scores["Europe/Helsinki"] == 2
    assert scores["Etc/GMT-3"] == 2
    assert scores["UTC"] == 0
    assert scores["Europe/Paris"] == 0


def test_la_mesure_refuse_de_trancher_sans_recouvrement(base):
    """⛔ Aucune ligne ForexFactory sur la periode exportee ⇒ on ne devine
    pas. Mieux vaut AUCUN import qu'un import decale d'une heure."""
    with pytest.raises(imp.RecouvrementInsuffisant):
        imp.choisir_fuseau(EXPORT, base)


def test_la_fenetre_de_SEPTEMBRE_est_AMBIGUE(base):
    """⛔ LE CONSTAT HONNETE. Septembre ne traverse pas le changement d'heure
    du 25 octobre : Helsinki (+3 l'ete) et Etc/GMT-3 (+3 toujours) apparient
    les MEMES lignes, et divergent d'une heure sur la ligne de 2021. La mesure
    refuse, et dit sur quoi."""
    _calibre(base)
    with pytest.raises(imp.MesureAmbigue) as e:
        imp.choisir_fuseau(EXPORT, base)
    message = str(e.value)
    assert "Europe/Helsinki" in message
    assert "Etc/GMT-3" in message
    assert "2021-01-08T13:30:00+00:00" in message, (
        "le message doit NOMMER la ligne sur laquelle les candidats se "
        "contredisent — sinon « ambigu » n'apprend rien")


def test_la_mesure_TRANCHE_des_que_la_fenetre_passe_le_25_octobre(base):
    """🔑 LA SORTIE. Avec un repere avant ET un apres le changement d'heure,
    seul un fuseau a heure d'ete explique les deux. C'est ce que Xavier gagne
    en attendant que la couverture ForexFactory passe le 25/10."""
    _ff(base, "2026-10-24T12:30:00+00:00", "CAD", "Employment Change")
    _ff(base, "2026-11-07T12:30:00+00:00", "CAD", "Employment Change")

    retenu, scores = imp.choisir_fuseau(EXPORT_TRAVERSE_LE_CHANGEMENT, base)
    assert scores["Europe/Helsinki"] == 2
    assert scores["Etc/GMT-3"] == 1, "un fuseau fixe ne peut pas expliquer les deux"
    assert retenu in ("Europe/Athens", "Europe/Helsinki")


def test_des_ex_aequo_EQUIVALENTS_ne_sont_pas_une_ambiguite(base):
    """⚠️ Helsinki et Athenes ont les memes regles : ils convertissent tout a
    l'identique. Lever la serait refuser pour rien."""
    _ff(base, "2026-10-24T12:30:00+00:00", "CAD", "Employment Change")
    _ff(base, "2026-11-07T12:30:00+00:00", "CAD", "Employment Change")
    retenu, _ = imp.choisir_fuseau(
        EXPORT_TRAVERSE_LE_CHANGEMENT, base,
        candidats=("Europe/Helsinki", "Europe/Athens"))
    assert retenu in ("Europe/Athens", "Europe/Helsinki")


# ─── L'ecriture ─────────────────────────────────────────────────────────────

def test_n_ecrit_RIEN_dans_la_fenetre_de_forexfactory(base):
    """🔑 LA REGLE : l'import n'ecrit que ce qui est STRICTEMENT ANTERIEUR a
    la plus ancienne ligne ForexFactory. Ecrire par-dessus creerait le MEME
    evenement sous deux identifiants differents — un doublon invisible,
    puisque les ids ne se ressemblent pas."""
    _calibre(base)  # la plus ancienne ligne ForexFactory est le 05/09

    n = imp.importer(EXPORT, base, fuseau="Europe/Helsinki")

    with sqlite3.connect(base) as c:
        lignes = list(c.execute(
            "SELECT ts_utc, event_name FROM economic_events "
            "WHERE id LIKE 'mql5_%' ORDER BY ts_utc"))
    assert n == 1, f"{n} lignes ecrites : seule celle de 2021 devait passer"
    assert lignes[0][1] == "Nonfarm Payrolls"
    assert lignes[0][0] == "2021-01-08T13:30:00+00:00"


def test_ecrit_le_passe_ANTERIEUR_a_forexfactory(base):
    """Le cas d'usage reel : ForexFactory commence au 27/09, l'export remonte
    a 2021. Tout ce qui precede le 27/09 doit entrer."""
    _ff(base, "2026-09-27T23:50:00+00:00", "USD", "Un evenement recent")

    n = imp.importer(EXPORT, base, fuseau="Europe/Helsinki")
    assert n == 4, f"{n} lignes ecrites au lieu de 4"

    with sqlite3.connect(base) as c:
        lignes = list(c.execute(
            "SELECT ts_utc, currency, event_name, impact, actual, forecast "
            "FROM economic_events WHERE id LIKE 'mql5_%' ORDER BY ts_utc"))
    assert lignes[0][0] == "2021-01-08T13:30:00+00:00", "hiver : +2 attendu"
    assert lignes[0][1] == "USD"
    assert lignes[0][2] == "Nonfarm Payrolls"
    assert lignes[0][3] == "High"
    assert lignes[0][4] == "-140.0", "le nombre doit perdre ses zeros inutiles"
    assert lignes[0][5] == "50.0"
    assert lignes[1][0] == "2026-09-05T12:30:00+00:00", "ete : +3 attendu"


def test_un_reimport_ne_duplique_pas(base):
    """Les value_id du terminal sont stables : deux imports du meme fichier
    donnent les memes lignes, pas le double."""
    _ff(base, "2026-09-27T23:50:00+00:00", "USD", "Un evenement recent")
    imp.importer(EXPORT, base, fuseau="Europe/Helsinki")
    imp.importer(EXPORT, base, fuseau="Europe/Helsinki")
    with sqlite3.connect(base) as c:
        n, = c.execute(
            "SELECT COUNT(*) FROM economic_events WHERE id LIKE 'mql5_%'").fetchone()
    assert n == 4, f"{n} lignes apres deux imports identiques"


def test_la_provenance_est_INSCRITE_en_base(base):
    """⛔ Un chiffre dont on ne connait pas la source est un chiffre d'air."""
    _ff(base, "2026-09-27T23:50:00+00:00", "USD", "Un evenement recent")
    imp.importer(EXPORT, base, fuseau="Europe/Helsinki")
    with sqlite3.connect(base) as c:
        sources = dict(c.execute(
            "SELECT COALESCE(source,'(nul)'), COUNT(*) FROM economic_events "
            "GROUP BY 1"))
    assert sources.get("mql5") == 4
    assert sources.get("forexfactory") == 1, (
        "les lignes ForexFactory existantes n'ont pas ete etiquetees")


def test_l_ajout_de_la_colonne_source_est_IDEMPOTENT(base):
    """Deux imports de suite ne doivent pas echouer sur « duplicate column »."""
    _ff(base, "2026-09-27T23:50:00+00:00", "USD", "Un evenement recent")
    imp.importer(EXPORT, base, fuseau="Europe/Helsinki")
    imp.importer(EXPORT, base, fuseau="Europe/Helsinki")  # ne doit pas lever


def test_une_ligne_sans_devise_ni_nom_est_ignoree(base):
    """`CalendarEventById` peut echouer : le script MQL5 garde alors la valeur
    avec des metadonnees vides, pour ne pas perdre un `actual` publie. Mais
    sans devise on ne saurait a quelle paire la rattacher."""
    _ff(base, "2026-09-27T23:50:00+00:00", "USD", "Un evenement recent")
    orpheline = _ENTETE + (
        "900\t999\t2021.02.01 10:00:00\t\t0\t1.000000\t\t\t\t1\t\t\t\t\t\t\t\t\n")
    assert imp.importer(orpheline, base, fuseau="Europe/Helsinki") == 0


# ─── L'outil en ligne de commande ───────────────────────────────────────────
#
# ⚠️ Teste par le VRAI `main()`, avec un argv monkeypatche. Me redoubler une
# couche d'orchestration dans le test ne prouverait rien.

def _cli(monkeypatch, *argv):
    import importlib
    m = importlib.import_module("scripts.importer_calendrier_mql5")
    monkeypatch.setattr("sys.argv", ["importer_calendrier_mql5.py", *argv])
    return m.main()


@pytest.fixture
def export_sur_disque(tmp_path):
    f = tmp_path / "calendrier_export.tsv"
    f.write_text(EXPORT, encoding="utf-8")
    return f


def test_cli_SANS_ecrire_ne_touche_a_rien(base, export_sur_disque, monkeypatch,
                                          capsys):
    """⛔ Le defaut est l'inaction : le fuseau se regarde avant de s'appliquer."""
    _ff(base, "2026-09-27T23:50:00+00:00", "USD", "Recent")
    _calibre(base)

    code = _cli(monkeypatch, "--fichier", str(export_sur_disque),
                "--db", str(base), "--fuseau", "Europe/Helsinki")
    assert code == 0
    assert "rien n'a ete ecrit" in capsys.readouterr().out

    with sqlite3.connect(base) as c:
        n, = c.execute(
            "SELECT COUNT(*) FROM economic_events WHERE id LIKE 'mql5_%'").fetchone()
    assert n == 0


def test_cli_avec_ecrire_importe_au_fuseau_MESURE(base, tmp_path, monkeypatch,
                                                  capsys):
    """La fenetre qui traverse le 25/10 laisse la mesure trancher seule."""
    f = tmp_path / "x.tsv"
    f.write_text(EXPORT_TRAVERSE_LE_CHANGEMENT, encoding="utf-8")
    _ff(base, "2026-10-24T12:30:00+00:00", "CAD", "Employment Change")
    _ff(base, "2026-11-07T12:30:00+00:00", "CAD", "Employment Change")

    code = _cli(monkeypatch, "--fichier", str(f), "--db", str(base), "--ecrire")
    sortie = capsys.readouterr().out
    assert code == 0
    assert "Europe/" in sortie
    # Les deux lignes tombent DANS la fenetre ForexFactory : rien a ecrire,
    # et le script doit le dire au lieu de laisser croire a un succes.
    assert "zero ligne" in sortie


def test_cli_REFUSE_sans_recouvrement(base, export_sur_disque, monkeypatch):
    """Base sans aucune ligne ForexFactory : sortie 3, et rien d'ecrit."""
    code = _cli(monkeypatch, "--fichier", str(export_sur_disque),
                "--db", str(base), "--ecrire")
    assert code == 3
    with sqlite3.connect(base) as c:
        n, = c.execute(
            "SELECT COUNT(*) FROM economic_events WHERE id LIKE 'mql5_%'").fetchone()
    assert n == 0


def test_cli_REFUSE_une_mesure_ambigue_et_ne_devine_pas(base, export_sur_disque,
                                                        monkeypatch):
    """⛔ Septembre seul ne tranche pas. Le script sort en 3 plutot que de
    choisir a la place de Xavier."""
    _calibre(base)
    code = _cli(monkeypatch, "--fichier", str(export_sur_disque),
                "--db", str(base), "--ecrire")
    assert code == 3
    with sqlite3.connect(base) as c:
        n, = c.execute(
            "SELECT COUNT(*) FROM economic_events WHERE id LIKE 'mql5_%'").fetchone()
    assert n == 0


def test_cli_accepte_un_fuseau_IMPOSE_malgre_l_ambiguite(base, export_sur_disque,
                                                         monkeypatch, capsys):
    """La deuxieme sortie : trancher explicitement. ⚠️ Le script doit DIRE que
    la mesure a ete contournee."""
    _ff(base, "2026-09-27T23:50:00+00:00", "USD", "Recent")
    code = _cli(monkeypatch, "--fichier", str(export_sur_disque), "--db", str(base),
                "--fuseau", "Europe/Helsinki", "--ecrire")
    sortie = capsys.readouterr().out
    assert code == 0
    assert "IMPOSE" in sortie or "impose" in sortie
    with sqlite3.connect(base) as c:
        n, = c.execute(
            "SELECT COUNT(*) FROM economic_events WHERE id LIKE 'mql5_%'").fetchone()
    assert n == 4


def test_cli_refuse_un_fuseau_INCONNU(base, export_sur_disque, monkeypatch):
    code = _cli(monkeypatch, "--fichier", str(export_sur_disque), "--db", str(base),
                "--fuseau", "Mars/Olympus_Mons", "--ecrire")
    assert code == 2


def test_cli_refuse_un_fichier_absent(base, monkeypatch, tmp_path):
    code = _cli(monkeypatch, "--fichier", str(tmp_path / "rien.tsv"),
                "--db", str(base))
    assert code == 2


def test_cli_refuse_un_export_tronque(base, tmp_path, monkeypatch):
    f = tmp_path / "coupe.tsv"
    f.write_text(EXPORT[: EXPORT.rindex("\n", 0, EXPORT.rindex("\n")) + 60],
                 encoding="utf-8")
    code = _cli(monkeypatch, "--fichier", str(f), "--db", str(base))
    assert code == 2


def test_une_ligne_ForexFactory_ECRITE_APRES_un_import_reste_a_NULL(base):
    """⚠️ Fixe la convention au lieu de la laisser implicite.

    `refresh_calendar()` ne renseigne pas `source`. Une ligne ForexFactory
    ajoutee APRES un import reste donc a NULL jusqu'au suivant.

    ⛔ NULL ne veut pas dire « inconnu » : par construction il ne peut venir
    que de `refresh_calendar()`, puisque l'import MQL5 ecrit toujours `mql5`.
    Donc NULL vaut `forexfactory`, et toute requete doit faire
    `COALESCE(source, 'forexfactory')`. Ce test est la pour que la prochaine
    personne qui lise cette colonne tombe sur la regle, pas sur la surprise.
    """
    _ff(base, "2026-09-27T23:50:00+00:00", "USD", "Avant l import")
    imp.importer(EXPORT, base, fuseau="Europe/Helsinki")
    _ff(base, "2026-09-28T12:00:00+00:00", "USD", "Apres l import")

    with sqlite3.connect(base) as c:
        brut = dict(c.execute(
            "SELECT COALESCE(source,'(nul)'), COUNT(*) FROM economic_events "
            "GROUP BY 1"))
        avec_convention = dict(c.execute(
            "SELECT COALESCE(source,'forexfactory'), COUNT(*) "
            "FROM economic_events GROUP BY 1"))

    assert brut.get("(nul)") == 1, "la ligne ajoutee apres devrait etre a NULL"
    assert avec_convention["forexfactory"] == 2
    assert avec_convention["mql5"] == 4
