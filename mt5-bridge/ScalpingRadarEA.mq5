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
#property version     "1.00"
#property strict

//─── Inputs (modifiables par l'user au drag sur chart) ──────────────
input string   InpApiKey              = "";                                    // API key (depuis Settings → Auto-exec MT5)
input string   InpServerUrl           = "https://app.scalping-radar.online";   // SaaS base URL
input int      InpPollingIntervalSec  = 30;                                    // Période de polling (secondes)
input double   InpDefaultLot          = 0.01;                                  // Lot fixe V1 (sizing dynamique V2)
input int      InpMagicNumber         = 20260429;                              // Magic number pour identifier les trades EA
input int      InpDeviationPoints     = 20;                                    // Slippage max accepté (points)
input bool     InpDryRun              = false;                                 // Si true, log les ordres sans OrderSend (test)

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
    if(InpPollingIntervalSec < 5 || InpPollingIntervalSec > 300)
    {
        Print("[ScalpingRadarEA] ERREUR : polling_interval doit être entre 5 et 300s");
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
    string response = HttpGet("/api/ea/pending?api_key=" + InpApiKey);
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
    string comment = ExtractStringField(payload_json, "comment");

    if(pair == "" || direction == "" || sl == 0.0 || tp == 0.0)
    {
        AckResult(order_id, false, 0, "champs payload manquants");
        return;
    }

    // Mapping symbole : EUR/USD → EURUSD (Pepperstone et la plupart des brokers retail)
    string symbol = pair;
    StringReplace(symbol, "/", "");

    if(InpDryRun)
    {
        Print("[ScalpingRadarEA] DRY_RUN order_id=", order_id, " ", symbol, " ", direction,
              " sl=", sl, " tp=", tp);
        AckResult(order_id, true, 999000 + order_id, "DRY_RUN");
        return;
    }

    // Execute via OrderSend natif. ExecuteOrderSend remplit out_retcode
    // dans tous les cas (succès comme échec) pour qu'on l'envoie dans
    // l'ack — utile pour le debug à distance via mt5_pending_orders.mt5_error.
    uint out_retcode = 0;
    int ticket = ExecuteOrderSend(symbol, direction, sl, tp, comment, order_id, out_retcode);
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
//| ExecuteOrderSend — wrap MqlTradeRequest                          |
//+------------------------------------------------------------------+
int ExecuteOrderSend(
    const string symbol,
    const string direction,
    const double sl,
    const double tp,
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

    MqlTradeRequest request = {};
    MqlTradeResult result = {};
    request.action = TRADE_ACTION_DEAL;
    request.symbol = symbol;
    request.volume = InpDefaultLot;

    bool is_buy = (direction == "buy" || direction == "BUY");
    request.type = is_buy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
    request.price = is_buy
        ? SymbolInfoDouble(symbol, SYMBOL_ASK)
        : SymbolInfoDouble(symbol, SYMBOL_BID);
    request.sl = sl;
    request.tp = tp;
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
