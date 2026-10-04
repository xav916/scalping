//+------------------------------------------------------------------+
//|                                         CalendrierExport.mq5     |
//|            Scalping Radar — export de l'HISTORIQUE du calendrier |
//+------------------------------------------------------------------+
//| POURQUOI CE SCRIPT EXISTE
//|
//| `economic_events` ne contenait que 7 jours : `refresh_calendar()`
//| purgeait tout le reste « pour garder la table legere ». La purge est
//| retiree (2026-10-04), donc l'historique s'accumule DESORMAIS — mais le
//| passe, lui, est perdu. Au 04/10 le plus ancien evenement en base datait
//| du 27/09.
//|
//| Xavier : « si le pattern a eu lieu il y a 3 semaines, comment on fait ? »
//| On ne fait pas. Sauf par ici : le terminal MT5 embarque la base
//| calendrier de MetaQuotes, avec `actual` / `forecast` / `previous` sur
//| PLUSIEURS ANNEES. C'est la seule source de rattrapage qu'on ait.
//|
//| ⛔ LE BINDING PYTHON N'EXPOSE AUCUNE FONCTION CALENDRIER. Verifie, pas
//| suppose, sur le binding 5.0.5735 installe :
//|
//|     [n for n in dir(MetaTrader5) if 'calendar' in n.lower()]  ->  []
//|
//| D'ou ce passage par MQL5 : c'est le seul endroit du systeme qui sait lire
//| `CalendarValueHistory()`.
//|
//| ⚠️ FUSEAU HORAIRE — LE PIEGE PRINCIPAL, NON TRANCHE ICI.
//| `MqlCalendarValue.time` n'est pas garanti en UTC. Ce script n'applique
//| DONC AUCUNE conversion : il ecrit l'instant brut, et met dans l'en-tete
//| `TimeGMT()` et `TimeCurrent()` au moment de l'export.
//|
//| 🔑 C'est l'importateur Python qui tranche, par MESURE, et il mesure un
//| FUSEAU, pas un decalage : un serveur MT5 typique tourne en EET/EEST, donc
//| UTC+2 l'hiver et UTC+3 l'ete. Un decalage fixe applique a cinq ans
//| d'historique se tromperait d'une heure la moitie de l'annee — l'erreur
//| deja commise trois fois ici (spread d'un instant applique a un banc,
//| derive lue sur un tick perime, taux EUR/USD fige a 1,155).
//|
//| ⛔ NE PAS CONVERTIR ICI. Exporter brut, mesurer ensuite.
//|
//| COMMENT LE LANCER
//|   1. deposer ce .mq5 dans <donnees terminal>\MQL5\Scripts\
//|   2. compiler SANS interface graphique, par SSH :
//|        metaeditor64.exe /compile:"...\MQL5\Scripts\CalendrierExport.mq5" /log
//|   3. ⚠️ l'EXECUTION d'un script demande un graphique (glisser-deposer).
//|      Alternative sans RDP : `terminal64.exe /config:x.ini` avec une
//|      section [StartUp] Script=... — mais cela REDEMARRE un terminal, et
//|      le pont Python tient la session MT5 du compte REEL
//|      (cf. feedback_mt5_bridge_session_conflict). A ne faire que sur le
//|      terminal de DEMO : la base calendrier vient de MetaQuotes, elle est
//|      la MEME quel que soit le compte. Aucune raison de risquer le reel.
//|   4. le fichier sort dans <donnees terminal>\MQL5\Files\
//|
//| ⚠️ CE FICHIER N'A PAS ETE COMPILE. Aucun terminal MT5 n'est joignable
//| depuis le poste (Tailscale bloque par ProtonVPN sur 100.64.0.0/10). La
//| premiere compilation dira la verite ; tout ce qui pouvait etre evite sans
//| compilateur l'a ete (aucune concatenation implicite de litteraux, chaque
//| fonction definie avant son premier appel).
//+------------------------------------------------------------------+
#property copyright "Scalping Radar"
#property version   "1.01"
#property strict
// ⛔ PAS de `#property script_show_inputs` — retire le 2026-10-05.
//
// Il ouvre une boite de dialogue pour saisir les entrees. Au glisser-deposer
// c'est pratique ; en demarrage automatique (`terminal64.exe /config:...`,
// section `[StartUp] Script=`) **elle attend un clic que personne ne fera**, et
// le terminal reste bloque indefiniment — session ouverte sur le compte pour
// rien.
//
// 🔑 Les entrees gardent leurs valeurs par defaut ci-dessous, qui sont celles
// qu'on veut : tout l'historique disponible. Pour les changer sans dialogue,
// passer un fichier `.set` via `ScriptParameters=`.

input datetime InpDepuis  = D'2021.01.01';           // Debut de l'export
input datetime InpJusqua  = D'2027.01.01';           // Fin de l'export
input string   InpFichier = "calendrier_export.tsv"; // Fichier produit

// Separateur TABULATION, pas virgule : les noms d'evenements en contiennent
// (« Employment Change, s.a. »). Les tabulations et sauts de ligne presents
// dans un champ sont remplaces par un espace avant ecriture.
#define SEP "\t"

//--- metadonnees d'evenement, mises en cache : des milliers de valeurs
//--- partagent quelques centaines d'evenements.
ulong  g_ev_id[];
string g_ev_ligne[];

//+------------------------------------------------------------------+
//| Ecriture UTF-8. ⚠️ FILE_ANSI perdrait les accents des noms       |
//| d'evenements, FILE_UNICODE donnerait de l'UTF-16 penible a lire  |
//| cote Python. On passe donc par du binaire + conversion explicite.|
//+------------------------------------------------------------------+
void Ecrire(const int h, const string s)
{
   uchar octets[];
   int n = StringToCharArray(s, octets, 0, -1, CP_UTF8);
   if(n > 1)
      FileWriteArray(h, octets, 0, n - 1);  // -1 : sans le \0 terminal
}

//+------------------------------------------------------------------+
//| Neutralise ce qui casserait le format : tabulation, CR, LF.      |
//+------------------------------------------------------------------+
string Propre(const string s)
{
   string r = s;
   StringReplace(r, SEP, " ");
   StringReplace(r, "\r", " ");
   StringReplace(r, "\n", " ");
   return r;
}

//+------------------------------------------------------------------+
//| Une valeur manquante vaut LONG_MIN. On ecrit un champ VIDE, pas  |
//| un zero : ⛔ confondre « pas de chiffre publie » et « zero »     |
//| fabriquerait des surprises nulles la ou il n'y a pas de donnee.  |
//+------------------------------------------------------------------+
string Valeur(const long v)
{
   if(v == LONG_MIN)
      return "";
   // Les valeurs du calendrier sont des entiers a l'echelle 1e6.
   return DoubleToString((double)v / 1000000.0, 6);
}

//+------------------------------------------------------------------+
//| Un instant nul s'ecrit VIDE. ⚠️ TimeToString(0) rendrait         |
//| « 1970.01.01 00:00:00 », une fausse date que l'import prendrait  |
//| pour une vraie.                                                  |
//+------------------------------------------------------------------+
string Instant(const datetime t)
{
   if(t == 0)
      return "";
   return TimeToString(t, TIME_DATE | TIME_SECONDS);
}

//+------------------------------------------------------------------+
//| Les 8 champs de metadonnees d'un event_id, via le cache.         |
//+------------------------------------------------------------------+
string MetaEvenement(const ulong event_id)
{
   int n = ArraySize(g_ev_id);
   for(int i = 0; i < n; i++)
      if(g_ev_id[i] == event_id)
         return g_ev_ligne[i];

   MqlCalendarEvent ev;
   string ligne;
   if(!CalendarEventById(event_id, ev))
   {
      // ⚠️ On garde la valeur meme sans metadonnees : perdre la ligne
      // serait perdre un `actual` publie. L'importateur verra les champs
      // vides et ignorera la ligne faute de devise — mais il le dira.
      // 8 champs vides = 7 separateurs.
      ligne = SEP + SEP + SEP + SEP + SEP + SEP + SEP;
   }
   else
   {
      MqlCalendarCountry pays;
      string code   = "";
      string devise = "";
      if(CalendarCountryById(ev.country_id, pays))
      {
         code   = pays.code;
         devise = pays.currency;
      }
      // ⚠️ Concatenation EXPLICITE par `+`. La concatenation implicite de
      // litteraux adjacents (« "a" SEP "b" ») n'est pas garantie en MQL5 et
      // je ne peux pas compiler pour le verifier.
      ligne = StringFormat(
                 "%d" + SEP + "%s" + SEP + "%s" + SEP + "%s" + SEP
                 + "%d" + SEP + "%d" + SEP + "%d" + SEP + "%s",
                 (int)ev.importance,   // 0 none / 1 low / 2 moderate / 3 high
                 Propre(code),
                 Propre(devise),
                 Propre(ev.name),
                 (int)ev.sector,
                 (int)ev.unit,
                 (int)ev.digits,
                 Propre(ev.event_code));
   }

   ArrayResize(g_ev_id,    n + 1);
   ArrayResize(g_ev_ligne, n + 1);
   g_ev_id[n]    = event_id;
   g_ev_ligne[n] = ligne;
   return ligne;
}

//+------------------------------------------------------------------+
void OnStart()
{
   int h = FileOpen(InpFichier, FILE_WRITE | FILE_BIN);
   if(h == INVALID_HANDLE)
   {
      Print("ECHEC ouverture de ", InpFichier, " erreur ", GetLastError());
      return;
   }

   // En-tete : deux lignes de metadonnees, puis les colonnes.
   // 🔑 `gmt` et `serveur` sont la pour qu'on puisse CONSTATER le decalage
   // d'un instant — pas pour convertir : ils ne disent rien des changements
   // d'heure d'ete sur cinq ans.
   Ecrire(h, StringFormat("#export" + SEP + "gmt=%s" + SEP + "serveur=%s"
                          + SEP + "build=%d\n",
                          TimeToString(TimeGMT(),     TIME_DATE | TIME_SECONDS),
                          TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS),
                          (int)TerminalInfoInteger(TERMINAL_BUILD)));

   Ecrire(h, "#colonnes" + SEP + "value_id" + SEP + "event_id" + SEP
          + "time_brut" + SEP + "period" + SEP + "revision" + SEP + "actual"
          + SEP + "forecast" + SEP + "previous" + SEP + "revised_previous"
          + SEP + "impact_type" + SEP + "importance" + SEP + "code_pays"
          + SEP + "devise" + SEP + "nom" + SEP + "secteur" + SEP + "unite"
          + SEP + "digits" + SEP + "event_code\n");

   int total  = 0;
   int mois   = 0;
   int echecs = 0;

   // Decoupage MOIS par MOIS : un seul appel sur cinq ans peut etre tronque
   // par le terminal, et un export tronque en silence est pire que pas
   // d'export (cf. le `/rates` du pont, qui tronquait en gardant les bougies
   // les plus ANCIENNES).
   datetime curseur = InpDepuis;
   while(curseur < InpJusqua)
   {
      MqlDateTime d;
      TimeToStruct(curseur, d);
      d.mon++;
      if(d.mon > 12)
      {
         d.mon = 1;
         d.year++;
      }
      d.day  = 1;
      d.hour = 0;
      d.min  = 0;
      d.sec  = 0;
      datetime fin = StructToTime(d);
      if(fin > InpJusqua)
         fin = InpJusqua;

      MqlCalendarValue valeurs[];
      int n = CalendarValueHistory(valeurs, curseur, fin);
      mois++;
      if(n < 0)
      {
         // ⚠️ On ne s'arrete PAS : un mois en echec ne doit pas emporter les
         // soixante autres. Il est trace, et compte.
         Print("mois ", TimeToString(curseur, TIME_DATE),
               " : erreur ", GetLastError());
         echecs++;
      }
      else
      {
         for(int i = 0; i < n; i++)
         {
            Ecrire(h, StringFormat(
                      "%I64u" + SEP + "%I64u" + SEP + "%s" + SEP + "%s" + SEP
                      + "%d" + SEP + "%s" + SEP + "%s" + SEP + "%s" + SEP
                      + "%s" + SEP + "%d" + SEP + "%s\n",
                      valeurs[i].id,
                      valeurs[i].event_id,
                      Instant(valeurs[i].time),
                      Instant(valeurs[i].period),
                      valeurs[i].revision,
                      Valeur(valeurs[i].actual_value),
                      Valeur(valeurs[i].forecast_value),
                      Valeur(valeurs[i].prev_value),
                      Valeur(valeurs[i].revised_prev_value),
                      (int)valeurs[i].impact_type,
                      MetaEvenement(valeurs[i].event_id)));
            total++;
         }
      }
      curseur = fin;
   }

   FileClose(h);
   // Ligne lue par l'operateur : elle dit combien de mois ont echoue, pour
   // qu'un export partiel ne passe jamais pour complet.
   PrintFormat("export termine : %d valeurs, %d mois parcourus, "
               "%d mois en ECHEC -> %s",
               total, mois, echecs, InpFichier);
}
//+------------------------------------------------------------------+
