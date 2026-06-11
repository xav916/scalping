//+------------------------------------------------------------------+
//|                                            ScalpingRadarEA.mq5 |
//|                              Scalping Radar — multi-tenant EA     |
//|                                                                  |
//| Polling-based EA pour exécuter automatiquement les setups générés |
//| par le SaaS Scalping Radar (https://app.scalping-radar.online).   |
//|                                                                  |
//| Architecture (Phase MQL.D du pivot bridge Python → EA) :          |
//|   1. SaaS enqueue les ordres dans mt5_pending_orders DB           |
//|   2. Cet EA poll GET /api/ea/pending toutes les N secondes        |
//|   3. Pour chaque order PENDING : OrderSend natif MT5              |
//|   4. POST /api/ea/result avec mt5_ticket / error                  |
//|                                                                  |
//| Setup user (5 min) :                                              |
//|   1. Drop ce .ex5 dans <MT5>/MQL5/Experts/                        |
//|   2. Restart MT5                                                  |
//|   3. Drag l'EA sur n'importe quel chart                           |
//|   4. Saisir api_key dans les Inputs                               |
//|   5. Tools → Options → Expert Advisors → "Allow WebRequest"       |
//|      + ajouter https://app.scalping-radar.online                  |
//|   6. AutoTrading ON                                               |
//|                                                                  |
//| Voir docs/superpowers/specs/2026-04-29-mql5-ea-pivot-spec.md      |
//+------------------------------------------------------------------+
#property copyright   "Scalping Radar"
#property link        "https://app.scalping-radar.online"
#property version     "1.05"
#property strict

// Version envoyée au backend dans le query string du poll (telemetry).
// v1.06 (2026-06-11) : support du champ ``broker_symbol`` dans le payload.
//   Si présent et non vide, override le résultat de MapSymbol(pair). Permet
//   au backend de gérer le mapping multi-tenant côté serveur (per-user via
//   ``broker_config.symbol_map``) sans que l'user ait à saisir InpSymbolMap
//   au drag de l'EA. Driver = Cédric Pepperstone UK Demo, 0 exec sur 152
//   dispatches faute de mapping symbole (cf. project_cedric_zero_exec_*).
#define EA_VERSION_STRING "1.06"

//─── Inputs (modifiables par l'user au drag sur chart) ──────────────
input string   InpApiKey              = "";                                    // API key (depuis Settings → Auto-exec MT5)
input string   InpServerUrl           = "https://app.scalping-radar.online";   // SaaS base URL
input int      InpPollingIntervalSec  = 30;                                    // Période de polling (secondes)
input double   InpDefaultLot          = 0.01;                                  // Lot fixe V1 (sizing dynamique V2)
input int      InpMagicNumber         = 20260429;                              // Magic number pour identifier les trades EA
input int      InpDeviationPoints     = 20;                                    // Slippage max accepté (points)
input bool     InpDryRun              = false;                                 // Si true, log les ordres sans OrderSend (test)
input string   InpSymbolMap           = "";                                    // Mapping pair→broker_symbol (csv: "WTI/USD=USOIL,SPX=SPX500"). Vide = auto-detect
input bool     InpSymbolAutoMap       = true;                                  // Si true, essaie une liste d'alias par défaut quand pair pas dans InpSymbolMap

//─── État interne ──────────────────────────────────────────────────
int g_poll_count = 0;
int g_orders_executed = 0;
int g_orders_failed = 0;
datetime g_last_heartbeat_log = 0;

//+------------------------------------------------------------------+
//| OnInit — validation + démarrage timer                            |
//+------------------------------------------------------------------+
int OnInit()
{
    // Validation inputs
    if(StringLen(InpApiKey) < 16)
    {
        Print("[ScalpingRadarEA] ERREUR : api_key manquant ou < 16 chars. Configure-le dans les Inputs.");
        return INIT_PARAMETERS_INCORRECT;
    }
    if(StringFind(InpServerUrl, "://") < 0)
    {
        Print("[ScalpingRadarEA] ERREUR : server_url invalide (doit contenir http:// ou https://)");
        return INIT_PARAMETERS_INCORRECT;
    }
    if(InpPollingIntervalSec < 1 || InpPollingIntervalSec > 300)
    {
        Print("[ScalpingRadarEA] ERREUR : polling_interval doit être entre 1 et 300s");
        return INIT_PARAMETERS_INCORRECT;
    }

    // Setup timer
    EventSetTimer(InpPollingIntervalSec);

    Print("[ScalpingRadarEA] Initialized — server=", InpServerUrl,
          " polling=", InpPollingIntervalSec, "s default_lot=", InpDefaultLot,
          " magic=", InpMagicNumber, " dry_run=", InpDryRun);
    Print("[ScalpingRadarEA] N'oublie pas Tools→Options→Expert Advisors→Allow WebRequest et ajouter ", InpServerUrl);

    // Premier poll immédiat (pas attendre 30s pour le premier ordre)
    OnTimer();

    return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit — cleanup                                               |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    EventKillTimer();
    Print("[ScalpingRadarEA] Stopped — polls=", g_poll_count,
          " executed=", g_orders_executed, " failed=", g_orders_failed,
          " reason=", reason);
}

//+------------------------------------------------------------------+
//| OnTimer — poll les pending orders et les exécuter               |
//+------------------------------------------------------------------+
void OnTimer()
{
    g_poll_count++;
    string response = HttpGet("/api/ea/pending?api_key=" + InpApiKey + "&ea_version=" + EA_VERSION_STRING);
    if(response == "")
    {
        // Erreur réseau ou auth — déjà logguée par HttpGet
        return;
    }

    // Heartbeat log toutes les 10 min pour confirmer que l'EA tourne
    if(TimeCurrent() - g_last_heartbeat_log >= 600)
    {
        Print("[ScalpingRadarEA] alive — polls=", g_poll_count,
              " exec=", g_orders_executed, " fail=", g_orders_failed);
        g_last_heartbeat_log = TimeCurrent();
    }

    // Parse + exécute chaque order
    ProcessOrdersResponse(response);
}

//+------------------------------------------------------------------+
//| HttpGet — wrapper WebRequest GET                                 |
//+------------------------------------------------------------------+
string HttpGet(const string path)
{
    string url = InpServerUrl + path;
    string headers = "";
    char post_data[];
    char result_data[];
    string result_headers;

    int timeout = 5000;  // 5s
    ResetLastError();
    int status = WebRequest("GET", url, headers, timeout, post_data, result_data, result_headers);

    if(status == -1)
    {
        int err = GetLastError();
        if(err == 4060)
        {
            Print("[ScalpingRadarEA] ERREUR WebRequest : URL non whitelistée. Tools→Options→Expert Advisors→Allow WebRequest et ajoute ", InpServerUrl);
        }
        else
        {
            Print("[ScalpingRadarEA] HttpGet ", path, " err=", err);
        }
        return "";
    }
    if(status != 200)
    {
        if(status == 401)
            Print("[ScalpingRadarEA] HttpGet 401 — api_key invalide");
        else if(status == 403)
            Print("[ScalpingRadarEA] HttpGet 403 — Premium tier requis");
        else
            Print("[ScalpingRadarEA] HttpGet ", path, " HTTP ", status);
        return "";
    }
    return CharArrayToString(result_data, 0, ArraySize(result_data), CP_UTF8);
}

//+------------------------------------------------------------------+
//| HttpPostJson — wrapper WebRequest POST avec body JSON           |
//+------------------------------------------------------------------+
bool HttpPostJson(const string path, const string body)
{
    string url = InpServerUrl + path;
    string headers = "Content-Type: application/json\r\n";
    char post_data[];
    StringToCharArray(body, post_data, 0, StringLen(body), CP_UTF8);
    // Truncate trailing null byte
    if(ArraySize(post_data) > 0 && post_data[ArraySize(post_data) - 1] == 0)
        ArrayResize(post_data, ArraySize(post_data) - 1);

    char result_data[];
    string result_headers;

    int timeout = 5000;
    ResetLastError();
    int status = WebRequest("POST", url, headers, timeout, post_data, result_data, result_headers);

    if(status == -1)
    {
        Print("[ScalpingRadarEA] HttpPost ", path, " err=", GetLastError());
        return false;
    }
    if(status != 200)
    {
        Print("[ScalpingRadarEA] HttpPost ", path, " HTTP ", status);
        return false;
    }
    return true;
}

//+------------------------------------------------------------------+
//| ProcessOrdersResponse — parse JSON list of orders et execute    |
//+------------------------------------------------------------------+
void ProcessOrdersResponse(const string json)
{
    // Format attendu : {"orders":[{...}, {...}]}
    int orders_start = StringFind(json, "\"orders\":[");
    if(orders_start < 0) return;
    int array_start = orders_start + 10;  // après "orders":[
    int array_end = FindMatchingBracket(json, array_start - 1);
    if(array_end < 0) return;
    if(array_end - array_start < 5) return;  // array vide []

    string array_content = StringSubstr(json, array_start, array_end - array_start);

    // Split par "},{" en respectant les sous-objets imbriqués (payload est un dict)
    // Approche : iterate caractère par caractère et détecte la fin d'un order au niveau brace = 0
    int depth = 0;
    int order_start = 0;
    for(int i = 0; i < StringLen(array_content); i++)
    {
        ushort ch = StringGetCharacter(array_content, i);
        if(ch == '{') depth++;
        else if(ch == '}')
        {
            depth--;
            if(depth == 0)
            {
                string order_json = StringSubstr(array_content, order_start, i - order_start + 1);
                ProcessSingleOrder(order_json);
                // Skip jusqu'au prochain '{'
                while(i < StringLen(array_content) && StringGetCharacter(array_content, i) != '{')
                    i++;
                order_start = i;
                i--;  // for-loop incrémentera
            }
        }
    }
}

//+------------------------------------------------------------------+
//| FindMatchingBracket — position du ']' qui ferme le '[' à start  |
//+------------------------------------------------------------------+
int FindMatchingBracket(const string s, const int start)
{
    int depth = 0;
    for(int i = start; i < StringLen(s); i++)
    {
        ushort ch = StringGetCharacter(s, i);
        if(ch == '[') depth++;
        else if(ch == ']')
        {
            depth--;
            if(depth == 0) return i;
        }
    }
    return -1;
}

//+------------------------------------------------------------------+
//| ProcessSingleOrder — extract champs + OrderSend + ack            |
//+------------------------------------------------------------------+
void ProcessSingleOrder(const string order_json)
{
    int order_id = (int)ExtractIntField(order_json, "order_id");
    if(order_id <= 0) return;

    // Extract payload nested
    int payload_start = StringFind(order_json, "\"payload\":{");
    if(payload_start < 0)
    {
        AckResult(order_id, false, 0, "payload manquant");
        return;
    }
    int payload_open = payload_start + 11 - 1;  // position du '{'
    int payload_close = FindMatchingBrace(order_json, payload_open);
    if(payload_close < 0)
    {
        AckResult(order_id, false, 0, "payload mal formé");
        return;
    }
    string payload_json = StringSubstr(order_json, payload_open, payload_close - payload_open + 1);

    string pair = ExtractStringField(payload_json, "pair");
    string direction = ExtractStringField(payload_json, "direction");
    double entry = ExtractDoubleField(payload_json, "entry");
    double sl = ExtractDoubleField(payload_json, "sl");
    double tp = ExtractDoubleField(payload_json, "tp");
    // v1.05 : distances relatives — si présentes et > 0, on les utilise pour
    // recalculer SL/TP à partir du fill price effectif après market order.
    // Élimine le biais slippage qui rognait le R:R réel (0.7-1.3 au lieu de
    // 1.8 sur ETH/USD le 2026-05-18). Backward compat : si le backend
    // n'envoie pas sl_dist/tp_dist (legacy v≤1.04), on garde la logique
    // historique SL/TP absolus.
    double sl_dist = ExtractDoubleField(payload_json, "sl_dist");
    double tp_dist = ExtractDoubleField(payload_json, "tp_dist");
    string comment = ExtractStringField(payload_json, "comment");

    if(pair == "" || direction == "" || sl == 0.0 || tp == 0.0)
    {
        AckResult(order_id, false, 0, "champs payload manquants");
        return;
    }

    // Mapping symbole v1.06 : priorité absolue à ``broker_symbol`` du payload
    // (envoyé par le backend si ``broker_config.symbol_map`` est configuré pour
    // ce user). Sinon fallback sur InpSymbolMap user-config local, puis
    // alias auto, puis strip-slash. Le server-side mapping élimine le besoin
    // de saisir InpSymbolMap au drag pour les Premium multi-tenant.
    string broker_symbol = ExtractStringField(payload_json, "broker_symbol");
    string symbol = (broker_symbol != "") ? broker_symbol : MapSymbol(pair);

    if(InpDryRun)
    {
        Print("[ScalpingRadarEA] DRY_RUN order_id=", order_id, " ", symbol, " ", direction,
              " sl=", sl, " tp=", tp, " sl_dist=", sl_dist, " tp_dist=", tp_dist);
        AckResult(order_id, true, 999000 + order_id, "DRY_RUN");
        return;
    }

    // Execute via OrderSend natif. ExecuteOrderSend remplit out_retcode
    // dans tous les cas (succès comme échec) pour qu'on l'envoie dans
    // l'ack — utile pour le debug à distance via mt5_pending_orders.mt5_error.
    uint out_retcode = 0;
    int ticket = ExecuteOrderSend(symbol, direction, sl, tp, sl_dist, tp_dist, comment, order_id, out_retcode);
    if(ticket > 0)
    {
        g_orders_executed++;
        AckResult(order_id, true, ticket, "");
        Print("[ScalpingRadarEA] order_id=", order_id, " EXECUTED ticket=", ticket, " ", symbol, " ", direction);
    }
    else
    {
        g_orders_failed++;
        string err = "OrderSend failed retcode=" + IntegerToString(out_retcode);
        AckResult(order_id, false, 0, err);
        Print("[ScalpingRadarEA] order_id=", order_id, " FAILED ", err, " ", symbol, " ", direction);
    }
}

//+------------------------------------------------------------------+
//| GetSymbolAliasesCsv — alias broker connus par pair (v1.03)       |
//|                                                                  |
//| Chaque CFD non-forex est nommé différemment selon le broker      |
//| (Pepperstone: USOIL / IC Markets: WTI / OANDA: WTICOUSD...).     |
//| On liste les alias connus ; MapSymbol tente chacun via           |
//| SymbolSelect, le premier qui existe gagne.                       |
//|                                                                  |
//| Pour forex/métaux simples, on garde le strip-slash               |
//| (EUR/USD → EURUSD) qui marche chez 95% des brokers.              |
//+------------------------------------------------------------------+
string GetSymbolAliasesCsv(const string pair)
{
    if(pair == "WTI/USD") return "USOIL,WTI,XTIUSD,WTI.cash,WTIUSD";
    if(pair == "SPX")     return "US500,SPX500,SP500,SPX.cash,SPXm,SPX";
    if(pair == "NDX")     return "NAS100,US100,USTECH100,NDX100,NAS.cash,NDXm";
    if(pair == "XAU/USD") return "XAUUSD,GOLD,XAU.cash,XAUUSDm";
    if(pair == "XAG/USD") return "XAGUSD,SILVER,XAG.cash,XAGUSDm";
    if(pair == "BTC/USD") return "BTCUSD,BTCUSDm,BTC.cash";
    if(pair == "ETH/USD") return "ETHUSD,ETHUSDm,ETH.cash";
    // Forex default — strip slash
    string fallback = pair;
    StringReplace(fallback, "/", "");
    return fallback;
}

//+------------------------------------------------------------------+
//| MapSymbol — traduit le pair SaaS vers le symbole broker          |
//|                                                                  |
//| Ordre de résolution :                                            |
//| 1. InpSymbolMap user override (priorité absolue) si non vide.    |
//| 2. Si InpSymbolAutoMap : itère la liste d'alias connus du pair,  |
//|    garde le premier qui passe SymbolSelect (= existe chez le     |
//|    broker). Ajoute aussi au Market Watch comme effet de bord.    |
//| 3. Fallback strip-slash (EUR/USD → EURUSD).                      |
//|                                                                  |
//| Format InpSymbolMap : "PAIR1=BROKER1,PAIR2=BROKER2,..." (csv).   |
//| Pas de quoting, pas d'espaces tolérés dans les valeurs.          |
//|                                                                  |
//| Driver : Cédric (Pepperstone) avait 100% FAILED sur WTI/USD car  |
//| Pepperstone connaît USOIL pas WTIUSD. v1.02 ajoutait InpSymbolMap|
//| manuel mais l'user devait le saisir au drag de l'EA, oubli       |
//| fréquent. v1.03 essaie automatiquement les alias connus.         |
//+------------------------------------------------------------------+
string MapSymbol(const string pair)
{
    // 1. InpSymbolMap user override
    if(InpSymbolMap != "")
    {
        string entries[];
        int n = StringSplit(InpSymbolMap, ',', entries);
        for(int i = 0; i < n; i++)
        {
            int eq = StringFind(entries[i], "=");
            if(eq <= 0) continue;
            string key = StringSubstr(entries[i], 0, eq);
            string val = StringSubstr(entries[i], eq + 1);
            if(key == pair) return val;
        }
    }

    // 2. Auto-detect via alias list
    if(InpSymbolAutoMap)
    {
        string aliases_csv = GetSymbolAliasesCsv(pair);
        // Si pas d'alias spécifique (fallback strip-slash a été retourné en
        // un seul item), on essaie quand même via SymbolSelect — ça normalise
        // les forex avec suffixe broker (EURUSDm chez IC Markets par exemple).
        string aliases[];
        int n = StringSplit(aliases_csv, ',', aliases);
        for(int i = 0; i < n; i++)
        {
            if(SymbolSelect(aliases[i], true)) return aliases[i];
        }
        // Aucun alias dispo — on continue vers le fallback brut pour
        // qu'au moins le log d'erreur mentionne le pair tel quel.
        Print("[ScalpingRadarEA] aucun alias dispo pour ", pair,
              " — testés: ", aliases_csv);
    }

    // 3. Fallback brut
    string fallback = pair;
    StringReplace(fallback, "/", "");
    return fallback;
}

//+------------------------------------------------------------------+
//| DetermineFilling — choisit le filling mode supporté par le symbole|
//|                                                                  |
//| Bug fix MQL.E review : hardcoder ORDER_FILLING_IOC ne marche pas |
//| avec tous les brokers (Pepperstone, IC Markets, etc. peuvent     |
//| n'autoriser que FOK ou RETURN selon le symbole). MT5 expose la   |
//| bitmask SYMBOL_FILLING_MODE pour query les modes autorisés ;     |
//| sans cette détection dynamique, l'EA enverrait des ordres avec   |
//| retcode 10030 INVALID_FILL et zéro trade ne passerait.           |
//+------------------------------------------------------------------+
ENUM_ORDER_TYPE_FILLING DetermineFilling(const string symbol)
{
    long modes = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
    // SYMBOL_FILLING_FOK = 1, SYMBOL_FILLING_IOC = 2 (bitmask).
    // Préférence IOC (partial fills tolérés) > FOK (all-or-nothing) > RETURN.
    if((modes & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
    if((modes & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
    return ORDER_FILLING_RETURN;  // fallback (instant exec, partial OK)
}

//+------------------------------------------------------------------+
//| ApplySlTpFromFill — TRADE_ACTION_SLTP après market order         |
//|                                                                  |
//| v1.05 : pose SL/TP en relatif au fill price plutôt qu'en absolu  |
//| pour neutraliser le slippage entry signal vs entry réel.         |
//| Backend envoie sl_dist/tp_dist (distances positives en unités    |
//| de prix), on calcule sl = fill ± sl_dist et tp = fill ± tp_dist. |
//+------------------------------------------------------------------+
void ApplySlTpFromFill(
    const string symbol,
    const ulong position_ticket,
    const bool is_buy,
    const double fill,
    const double sl_dist,
    const double tp_dist
)
{
    if(fill <= 0.0 || sl_dist <= 0.0 || tp_dist <= 0.0) return;

    int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
    double new_sl = is_buy ? (fill - sl_dist) : (fill + sl_dist);
    double new_tp = is_buy ? (fill + tp_dist) : (fill - tp_dist);
    new_sl = NormalizeDouble(new_sl, digits);
    new_tp = NormalizeDouble(new_tp, digits);

    MqlTradeRequest mod_req = {};
    MqlTradeResult mod_result = {};
    mod_req.action = TRADE_ACTION_SLTP;
    mod_req.position = position_ticket;
    mod_req.symbol = symbol;
    mod_req.sl = new_sl;
    mod_req.tp = new_tp;

    if(!OrderSend(mod_req, mod_result))
    {
        Print("[ScalpingRadarEA] ApplySlTpFromFill OrderSend FAILED ticket=",
              position_ticket, " err=", GetLastError(),
              " retcode=", mod_result.retcode);
        return;
    }
    if(mod_result.retcode != TRADE_RETCODE_DONE)
    {
        Print("[ScalpingRadarEA] ApplySlTpFromFill retcode=", mod_result.retcode,
              " ticket=", position_ticket, " sl=", new_sl, " tp=", new_tp);
        return;
    }
    Print("[ScalpingRadarEA] SL/TP set from fill=", fill,
          " sl=", new_sl, " tp=", new_tp, " ticket=", position_ticket);
}


//+------------------------------------------------------------------+
//| ExecuteOrderSend — wrap MqlTradeRequest                          |
//|                                                                  |
//| sl_dist / tp_dist (v1.05) : si > 0, place le market order SANS   |
//| SL/TP puis pose SL/TP relatifs au fill price via TRADE_ACTION_SLTP.|
//| Si == 0, fallback legacy : SL/TP absolus from payload (v≤1.04). |
//+------------------------------------------------------------------+
int ExecuteOrderSend(
    const string symbol,
    const string direction,
    const double sl,
    const double tp,
    const double sl_dist,
    const double tp_dist,
    const string comment,
    const int order_id,
    uint &out_retcode
)
{
    if(!SymbolSelect(symbol, true))
    {
        Print("[ScalpingRadarEA] symbol non disponible : ", symbol);
        out_retcode = 0;
        return 0;
    }

    bool use_dist = (sl_dist > 0.0 && tp_dist > 0.0);
    bool is_buy = (direction == "buy" || direction == "BUY");

    MqlTradeRequest request = {};
    MqlTradeResult result = {};
    request.action = TRADE_ACTION_DEAL;
    request.symbol = symbol;
    request.volume = InpDefaultLot;
    request.type = is_buy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
    request.price = is_buy
        ? SymbolInfoDouble(symbol, SYMBOL_ASK)
        : SymbolInfoDouble(symbol, SYMBOL_BID);
    // Si on a les distances : market order sans SL/TP, on les pose ensuite
    // depuis le fill price effectif. Sinon legacy.
    if(use_dist)
    {
        request.sl = 0;
        request.tp = 0;
    }
    else
    {
        request.sl = sl;
        request.tp = tp;
    }
    request.deviation = InpDeviationPoints;
    request.magic = InpMagicNumber;
    string short_comment = "scalping-radar-" + IntegerToString(order_id);
    request.comment = (StringLen(short_comment) <= 31) ? short_comment : StringSubstr(short_comment, 0, 31);
    request.type_filling = DetermineFilling(symbol);

    if(!OrderSend(request, result))
    {
        out_retcode = result.retcode;
        Print("[ScalpingRadarEA] OrderSend FAILED retcode=", result.retcode,
              " comment=", result.comment);
        return 0;
    }
    if(result.retcode != TRADE_RETCODE_DONE && result.retcode != TRADE_RETCODE_PLACED)
    {
        out_retcode = result.retcode;
        Print("[ScalpingRadarEA] OrderSend retcode=", result.retcode,
              " comment=", result.comment);
        return 0;
    }
    out_retcode = result.retcode;

    if(use_dist)
    {
        // result.order = ticket de l'ordre qui a ouvert la position.
        // En MT5, pour un market order rempli, position_ticket = order_ticket.
        ApplySlTpFromFill(symbol, result.order, is_buy, result.price, sl_dist, tp_dist);
    }

    return (int)result.order;
}

//+------------------------------------------------------------------+
//| AckResult — POST /api/ea/result                                  |
//+------------------------------------------------------------------+
void AckResult(const int order_id, const bool ok, const int mt5_ticket, const string error)
{
    string body = "{";
    body += "\"api_key\":\"" + InpApiKey + "\",";
    body += "\"order_id\":" + IntegerToString(order_id) + ",";
    body += "\"ok\":" + (ok ? "true" : "false");
    if(mt5_ticket > 0)
        body += ",\"mt5_ticket\":" + IntegerToString(mt5_ticket);
    if(error != "")
    {
        string esc_error = error;
        StringReplace(esc_error, "\\", "\\\\");
        StringReplace(esc_error, "\"", "\\\"");
        body += ",\"error\":\"" + esc_error + "\"";
    }
    body += "}";
    HttpPostJson("/api/ea/result", body);
}

//+------------------------------------------------------------------+
//| Helpers JSON parsing (manuel, simple)                            |
//+------------------------------------------------------------------+
string ExtractStringField(const string json, const string key)
{
    string needle = "\"" + key + "\":\"";
    int pos = StringFind(json, needle);
    if(pos < 0) return "";
    pos += StringLen(needle);
    int end = StringFind(json, "\"", pos);
    if(end < 0) return "";
    return StringSubstr(json, pos, end - pos);
}

double ExtractDoubleField(const string json, const string key)
{
    string needle = "\"" + key + "\":";
    int pos = StringFind(json, needle);
    if(pos < 0) return 0.0;
    pos += StringLen(needle);
    int end = pos;
    while(end < StringLen(json))
    {
        ushort ch = StringGetCharacter(json, end);
        if(ch == ',' || ch == '}' || ch == ']') break;
        end++;
    }
    string val = StringSubstr(json, pos, end - pos);
    return StringToDouble(val);
}

long ExtractIntField(const string json, const string key)
{
    return (long)ExtractDoubleField(json, key);
}

int FindMatchingBrace(const string s, const int start)
{
    int depth = 0;
    for(int i = start; i < StringLen(s); i++)
    {
        ushort ch = StringGetCharacter(s, i);
        if(ch == '{') depth++;
        else if(ch == '}')
        {
            depth--;
            if(depth == 0) return i;
        }
    }
    return -1;
}

//+------------------------------------------------------------------+
//| OnTick — pas utilisé, on poll via OnTimer pour pas saturer       |
//+------------------------------------------------------------------+
void OnTick()
{
    // No-op. Le polling se fait dans OnTimer pour ne pas dépendre de
    // l'activité du marché (un EA en weekend doit aussi pouvoir poll).
}

//+------------------------------------------------------------------+
//| OnTradeTransaction — report des trades fermés vers le backend    |
//|                                                                  |
//| Détecte les fermetures de position (DEAL_ADD avec DEAL_ENTRY_OUT)|
//| posées par cet EA (magic = InpMagicNumber), récupère le PnL réel |
//| broker et POST /api/ea/closed-trade. Permet à pair_pnl_regulator |
//| côté backend d'évaluer la santé d'un pair multi-tenant — pas     |
//| seulement Xavier admin via personal_trades legacy.               |
//|                                                                  |
//| Ajouté en v1.04 le 2026-05-13.                                   |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& request,
                        const MqlTradeResult& result)
{
    if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
    ulong deal_id = trans.deal;
    if(deal_id == 0) return;

    // Charger l'history pour récupérer le deal
    if(!HistorySelectByPosition(trans.position))
    {
        if(!HistoryDealSelect(deal_id)) return;
    }

    // Filtre magic (= trades posés par cet EA, pas les manuels)
    long magic = HistoryDealGetInteger(deal_id, DEAL_MAGIC);
    if(magic != InpMagicNumber) return;

    // Filtre type d'entrée : OUT (= fermeture) ou INOUT (= reverse close+open)
    long entry = HistoryDealGetInteger(deal_id, DEAL_ENTRY);
    if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT) return;

    // Collecte des champs du deal de fermeture
    string symbol = HistoryDealGetString(deal_id, DEAL_SYMBOL);
    double profit = HistoryDealGetDouble(deal_id, DEAL_PROFIT);
    double volume = HistoryDealGetDouble(deal_id, DEAL_VOLUME);
    double exit_price = HistoryDealGetDouble(deal_id, DEAL_PRICE);
    long close_time = HistoryDealGetInteger(deal_id, DEAL_TIME);
    long position_id = HistoryDealGetInteger(deal_id, DEAL_POSITION_ID);
    long deal_type = HistoryDealGetInteger(deal_id, DEAL_TYPE);
    // Direction de la position originale : un DEAL_TYPE_BUY de sortie ferme une vente,
    // un DEAL_TYPE_SELL de sortie ferme un achat.
    string direction = (deal_type == DEAL_TYPE_BUY) ? "sell" : "buy";

    // Récupère l'entry_price en cherchant le deal IN sur la même position
    double entry_price = 0.0;
    if(HistorySelectByPosition(position_id))
    {
        int total = HistoryDealsTotal();
        for(int i = 0; i < total; i++)
        {
            ulong d = HistoryDealGetTicket(i);
            if(d == 0) continue;
            long e = HistoryDealGetInteger(d, DEAL_ENTRY);
            if(e == DEAL_ENTRY_IN)
            {
                entry_price = HistoryDealGetDouble(d, DEAL_PRICE);
                break;
            }
        }
    }

    // Format closed_at ISO 8601 UTC (MT5 stocke les datetime en GMT)
    MqlDateTime dt;
    TimeToStruct((datetime)close_time, dt);
    string closed_at = StringFormat("%04d-%02d-%02dT%02d:%02d:%02d+00:00",
                                    dt.year, dt.mon, dt.day, dt.hour, dt.min, dt.sec);

    // Construit le JSON et POST
    string body = "{";
    body += "\"api_key\":\"" + InpApiKey + "\",";
    body += "\"pair\":\"" + symbol + "\",";  // broker symbol, backend normalise
    body += "\"direction\":\"" + direction + "\",";
    body += "\"entry_price\":" + DoubleToString(entry_price, 5) + ",";
    body += "\"exit_price\":" + DoubleToString(exit_price, 5) + ",";
    body += "\"pnl\":" + DoubleToString(profit, 2) + ",";
    body += "\"volume\":" + DoubleToString(volume, 2) + ",";
    body += "\"mt5_ticket\":" + IntegerToString(position_id) + ",";
    body += "\"mt5_deal_id\":" + IntegerToString((long)deal_id) + ",";
    body += "\"magic\":" + IntegerToString((long)magic) + ",";
    body += "\"closed_at\":\"" + closed_at + "\",";
    body += "\"ea_version\":\"" + EA_VERSION_STRING + "\"";
    body += "}";

    if(HttpPostJson("/api/ea/closed-trade", body))
    {
        Print("[ScalpingRadarEA] closed-trade reported deal=", deal_id,
              " symbol=", symbol, " pnl=", DoubleToString(profit, 2));
    }
    else
    {
        Print("[ScalpingRadarEA] closed-trade report FAILED deal=", deal_id,
              " symbol=", symbol);
    }
}
//+------------------------------------------------------------------+
