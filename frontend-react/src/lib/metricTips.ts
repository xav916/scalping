/** Catalogue centralisé des descriptions de métriques. Un seul endroit pour
 *  éditer les explications — si le vocabulaire change, on corrige ici.
 *  Chaque tip commence par la définition des sigles (anglais + français)
 *  puis l'explication métier. */

export const TIPS = {
  /* ─────────── Header / status global ─────────── */
  header: {
    v2Badge: 'V2 (Version 2) : nouveau dashboard React + Vite. Coexiste avec la version legacy sur /.',
    statusLive: 'LIVE : WebSocket (canal bidirectionnel temps réel) connecté. Les setups, prix et cockpit sont poussés par le serveur sans avoir à rafraîchir.',
    statusSync: 'SYNC (synchronisation) : connexion WebSocket en cours d\'établissement. Mode dégradé (poll périodique) le temps que le socket rétablisse.',
    statusOffline: 'OFFLINE (hors-ligne) : le WebSocket (/ws) entre ton navigateur et le backend est fermé. Le dashboard retombe sur du polling React Query (latence 10-60s). Causes fréquentes : (1) cookie session expiré → relogin ; (2) backend qui redémarre → passe à SYNC puis LIVE tout seul ; (3) VPN/proxy qui bloque l\'upgrade WS ; (4) nginx qui a perdu les headers Upgrade. Les données restent à jour, juste moins vite.',
    soundOn: 'Alertes audio activées : un bip court est joué sur chaque nouveau setup TAKE (signal d\'exécution conseillé). Un seul bip même si plusieurs arrivent ensemble.',
    soundOff: 'Alertes audio désactivées. Telegram reste la source principale des notifications.',
  },

  /* ─────────── Kill switch + alertes ─────────── */
  killSwitch: {
    title: 'Kill switch (coupe-circuit) global de l\'auto-exec. Bloque l\'envoi de nouveaux ordres au bridge MT5 (MetaTrader 5) sans toucher aux trades déjà ouverts (ils vont à leur SL/TP).',
    active: 'ACTIF : auto-exec GELÉ. Cause possible : perte journalière ≥ 3% du capital (trigger automatique) ou activation manuelle.',
    okState: 'OK : auto-exec opérationnel. Un setup TAKE qui dépasse le seuil MIN_CONFIDENCE sera envoyé au bridge.',
    autoTrigger: 'Le kill switch s\'active automatiquement si le PnL (Profit and Loss — profits/pertes) du jour atteint -DAILY_LOSS_LIMIT_PCT (3% par défaut) du capital.',
    manualToggle: 'Gel/dégel manuel. Utile pour maintenance broker, doute sur une news imminente, ou weekend.',
  },

  alerts: {
    title: 'Notifications issues du backend. Critiques (rouge) = action requise, warnings (orange) = vigilance, infos (cyan) = contexte.',
    kill_switch: 'Auto-exec gelé — aucun nouvel ordre ne part tant que le kill switch est actif.',
    near_sl: 'Un trade ouvert est à moins de 30% de sa distance entry→SL (Stop Loss — seuil de perte). Stop probable.',
    high_impact_event: 'Event macro HIGH impact dans les 4 prochaines heures : NFP (Non-Farm Payrolls, emploi US hors agriculture), CPI (Consumer Price Index, inflation), FOMC (Federal Open Market Committee, politique Fed), BCE (Banque Centrale Européenne)…',
    event_blackout: 'Blackout (fenêtre de gel) autour d\'un event HIGH impact : les setups sur la devise concernée sont ignorés pendant quelques minutes avant/après.',
    cot_extreme: 'Positionnement CFTC (Commodity Futures Trading Commission, régulateur US des futures) à ≥ 2σ de la moyenne 52 semaines. Signal contrarien potentiel.',
    fear_greed_extreme: 'CNN (Cable News Network) Fear & Greed (Peur & Avidité) Index en zone extrême (< 25 ou > 75). Souvent associé à des retournements courts terme.',
  },

  /* ─────────── Aujourd'hui (stats du jour) ─────────── */
  today: {
    pnlJour: 'PnL (Profit and Loss — profits/pertes) réalisé sur les trades clôturés aujourd\'hui (0h UTC → maintenant). Exclut les positions encore ouvertes.',
    pnlPct: 'PnL du jour en pourcentage du capital de référence (variable d\'environnement TRADING_CAPITAL).',
    nonRealise: 'Non réalisé (unrealized PnL) : somme des PnL des positions encore ouvertes, calculée au dernier prix connu. Varie en temps réel.',
    exposition: 'Exposition : somme des tailles en lots (unité standard MT5) de toutes les positions ouvertes.',
    trades: 'Nombre total de trades créés aujourd\'hui (ouverts + clôturés). Inclut les auto-exec et les manuels si relevants.',
    closurés: 'Nombre de trades ayant atteint leur SL (Stop Loss) ou TP (Take Profit — prise de profit), ou fermés manuellement aujourd\'hui.',
    ouverts: 'Nombre de positions actuellement actives côté broker.',
    capital: 'Capital de référence (variable d\'environnement TRADING_CAPITAL). Utilisé pour calculer les pourcentages de risque, pas le solde broker réel.',
  },

  /* ─────────── Capital en jeu ─────────── */
  capital: {
    titre: 'Synthèse du capital engagé sur les positions ouvertes. Calcul : |entry − SL| × units × size — approximation USD ignorant les conversions cross-devises.',
    aRisque: 'À risque : perte maximale cumulée si TOUTES les positions touchent leur SL (Stop Loss) en même temps. Le vrai montant que tu peux perdre.',
    risquePct: 'Capital à risque exprimé en % du TRADING_CAPITAL de référence. En général on vise < 5% cumulé.',
    notionnel: 'Notionnel (notional value) : valeur sous-jacente totale (prix × units × size). Pas ce qui est à risque, mais ce qui est exposé aux mouvements de marché.',
    expositionTotale: 'Autre nom pour le notionnel. Indique le "levier" total des positions.',
    top5: 'Les 5 positions qui pèsent le plus en perte potentielle. Utile pour identifier une sur-concentration.',
  },

  /* ─────────── Répartition / asset class ─────────── */
  repartition: {
    titre: 'Répartition du risque (perte max cumulée) par classe d\'actif. Aide à détecter une sur-exposition sur un type d\'instrument.',
    forex: 'Forex (FOReign EXchange — marché des changes) : paires de devises (EUR/USD, USD/JPY…).',
    metal: 'Métaux précieux : XAU/USD (or, de aurum), XAG/USD (argent, de argentum).',
    crypto: 'Crypto-actifs : BTC (Bitcoin), ETH (Ethereum)…',
    equity_index: 'Indices boursiers (equity indices) : SPX (S&P 500 — Standard & Poor\'s 500), NDX (Nasdaq 100)…',
    energy: 'Énergie : WTI (West Texas Intermediate — pétrole léger US), Brent…',
    unknown: 'Actifs non classés (rare — indique souvent un mapping manquant).',
  },

  /* ─────────── Fear & Greed ─────────── */
  fearGreed: {
    titre: 'CNN Fear & Greed Index (Indice Peur & Avidité) 0-100 basé sur 7 sous-indicateurs : momentum S&P 500, nouveaux hauts/bas, put/call ratio, VIX (volatilité), safe haven demand, junk bond demand, breadth. Récupération quotidienne 22:30 UTC.',
    extreme_fear: 'Extreme Fear (panique) 0-25 : zone d\'achat contrarien historique mais peut persister.',
    fear: 'Fear (peur) 25-45 : prudence. Les marchés actions sous-performent en général.',
    neutral: 'Neutral (neutre) 45-55 : sentiment équilibré.',
    greed: 'Greed (avidité) 55-75 : appétit au risque. Les actifs risqués montent.',
    extreme_greed: 'Extreme Greed (euphorie) 75-100 : zone de vente contrarienne historique.',
  },

  /* ─────────── Santé système ─────────── */
  sante: {
    titre: 'Check rapide de l\'infrastructure : scheduler vivant, bridge MT5 (MetaTrader 5) joignable, WebSocket clients, session en cours.',
    cycle: 'Temps écoulé depuis le dernier cycle d\'analyse du radar. < 600 secondes = sain. Au-delà, problème côté scheduler ou source de données.',
    bridge: 'État du bridge MT5 (MetaTrader 5, sur VPS Windows) : UP = répond aux pings, DOWN = injoignable (firewall/VPN/process mort), N/A = pas configuré.',
    clientsWs: 'Nombre de tabs/devices connectés en WebSocket (WS). Si tu es seul sur le dashboard, c\'est 1.',
    session: 'Session forex active (Asian / London / NY overlap…). Utilisé dans le calcul du sizing multiplier.',
  },

  /* ─────────── Drift ─────────── */
  drift: {
    titre: 'Détection de drift (dérive) : paires ou patterns dont le win rate des 7 derniers jours chute de > 15 points vs la baseline historique. Minimum 10 trades récents pour éviter le bruit statistique.',
    delta: 'Delta : écart en points de pourcentage entre win rate récent et baseline. Plus c\'est négatif, plus la régression est forte.',
    action: 'Un drift soutenu suggère de désactiver le pattern/la paire, ou d\'enquêter sur un changement de régime marché.',
  },

  /* ─────────── COT ─────────── */
  cot: {
    titre: 'COT (Commitments of Traders — engagements des traders) : rapports hebdomadaires de la CFTC (Commodity Futures Trading Commission, régulateur US des futures) publiant le positionnement des acteurs. Récupération samedi 01h UTC. Extrêmes = z-score ≥ 2σ sur 52 semaines.',
    leveraged_funds: 'Leveraged funds (hedge funds / fonds spéculatifs) : traders institutionnels, souvent considérés comme "smart money". Long extrême = momentum haussier, short extrême = pression baissière.',
    non_reportables: 'Non reportables (petits traders non déclarés). Souvent contrariens : leur long extrême signale souvent un top proche.',
    z: 'Z-score : distance (en écarts-types σ) de la position nette actuelle vs moyenne 52 semaines. |z| ≥ 2 = extrême statistique (≈ 5% des observations).',
  },

  /* ─────────── Events macro ─────────── */
  events: {
    titre: 'Events (événements économiques) de ForexFactory dans les 4 prochaines heures. HIGH impact déclenche un blackout sur la devise concernée.',
    impactHigh: 'HIGH (fort impact) : NFP (Non-Farm Payrolls, emploi US hors agriculture), CPI (Consumer Price Index, inflation), décision FOMC (Federal Open Market Committee), décision BCE (Banque Centrale Européenne), GDP (Gross Domestic Product, PIB). Volatilité explosive, setups bloqués ±15 min.',
    impactMedium: 'MEDIUM (impact modéré) : PMI (Purchasing Managers Index, indice des directeurs d\'achat), unemployment claims (allocations chômage), sentiment. À surveiller mais pas toujours bloquant.',
    impactLow: 'LOW (impact faible). Rarement action mais visible dans le calendrier.',
  },

  /* ─────────── Trades actifs ─────────── */
  trade: {
    pair: 'Pair (paire) : symbole de l\'instrument tradé au format base/quote (cotation). Ex : EUR/USD = combien de dollars US pour 1 euro.',
    direction: 'Direction (sens) : buy (long — pari à la hausse) ou sell (short — pari à la baisse).',
    entryPrice: 'Entry price (prix d\'entrée) théorique du setup. Peut différer légèrement du fill price (prix d\'exécution réel) chez le broker.',
    currentPrice: 'Current price (prix actuel) : dernier prix connu (tick WebSocket Twelve Data ou dernière bougie 5 minutes).',
    stopLoss: 'SL (Stop Loss — seuil de perte) : prix de sortie automatique si la position perd. Placé par l\'algo selon pattern + ATR (Average True Range — volatilité moyenne). Ne peut plus être modifié une fois l\'ordre envoyé.',
    takeProfit: 'TP (Take Profit — prise de profit) : prix cible de sortie en profit. TP1 = premier palier, TP2 (si présent) = extension.',
    sizeLot: 'Size (taille) en lots MT5 (MetaTrader 5). 1 lot forex standard = 100 000 unités, 1 lot XAU = 100 onces.',
    riskMoney: 'Risk money (capital à risque) : perte maximale si le SL est touché. Calcul : |entry − SL| × units_per_lot × size (approximation USD).',
    notional: 'Notional (valeur notionnelle) : prix × units × size. Mesure l\'exposition sous-jacente totale.',
    pnlUnrealized: 'PnL (Profit and Loss) unrealized / latent : gain ou perte au prix actuel. Ne se matérialise qu\'à la fermeture.',
    pnlPips: 'PnL en pips (percentage in points). 1 pip = 0.0001 sur forex standard, 0.01 sur JPY et métaux.',
    distanceSl: 'Distance au SL : pourcentage de la distance entry→SL encore disponible. < 30% = alerte "near_sl" (proche stop).',
    distanceTp: 'Distance au TP : pourcentage de la distance entry→TP restant à parcourir.',
    nearSl: 'Near SL (proche stop) : la position est à moins de 30% de son stop. Sortie probable dans les prochaines minutes sauf rebond.',
    duration: 'Durée du trade en minutes depuis son ouverture.',
    isAuto: 'is_auto = 1 : ordre envoyé automatiquement par le bridge. 0 : trade manuel (ancien flow, désormais supprimé).',
    mt5Ticket: 'Ticket MT5 (MetaTrader 5) : numéro d\'ordre côté broker. Utilisé pour la réconciliation et le suivi de fermeture.',
    assetClass: 'Asset class (classe d\'actif) : forex / metal / crypto / equity_index / energy. Détermine les règles de sizing et les horaires autorisés.',
  },

  /* ─────────── Confidence / verdict (setup cards) ─────────── */
  setup: {
    confidenceGauge: 'Confidence score (score de confiance) 0-100 agrégeant pattern, R:R, contexte macro, session. Seuil auto-exec : ≥ 55 (variable d\'env MT5_BRIDGE_MIN_CONFIDENCE).',
    rr: 'R:R (Risk / Reward — ratio risque / gain) : distance entry→TP divisée par entry→SL. Exemple 1:1.5 signifie qu\'on vise 1.5× le risque pris.',
    verdictTake: 'TAKE (prendre) : l\'algo recommande l\'exécution (confidence ≥ seuil + alignement macro + pas de blackout).',
    verdictWait: 'WAIT (attendre) : signal valide mais contexte défavorable (session calme, macro contre, SL trop serré). On patiente.',
    verdictSkip: 'SKIP (ignorer) : on ignore (blackout event, kill switch actif, is_simulated, marché fermé…).',
  },

  /* ─────────── Macro banner ─────────── */
  macro: {
    risk_regime: 'Risk regime (régime de risque) : synthèse dérivée de DXY + VIX + SPX + US10Y. risk_on = appétit au risque, risk_off = fuite vers actifs sûrs, neutral = indécis.',
    dxy: 'DXY (Dollar Index — indice du dollar) : USD vs panier de 6 devises. UP = dollar fort (pression sur or, indices US, cross USD), DOWN = dollar faible.',
    spx: 'SPX (S&P 500 — Standard & Poor\'s 500) : indice des 500 plus grosses capitalisations US. UP = appétit equity, DOWN = aversion au risque.',
    vix: 'VIX (CBOE Volatility Index — indice de volatilité du CBOE, Chicago Board Options Exchange) : volatilité implicite S&P 500 sur 30 jours. low < 15 = calme, normal 15-20, elevated 20-30, high > 30 = stress.',
    us10y: 'US10Y (rendement de l\'obligation US à 10 ans). UP = inflation / Fed hawkish (restrictive), DOWN = recherche de sécurité / Fed dovish (accommodante).',
    de10y: 'DE10Y (rendement du Bund allemand 10 ans). Comparé au US10Y pour le spread trans-Atlantique (influence EUR/USD).',
    oil: 'WTI (West Texas Intermediate — pétrole léger US). UP = inflation + CAD/NOK renforcés, DOWN = déflation + JPY/CHF privilégiés.',
    nikkei: 'Nikkei 225 : indice boursier japonais. UP = risk-on asiatique, DOWN = JPY (yen) en fuite.',
    gold: 'XAU/USD (or, de aurum). UP = flight to safety (fuite vers la sécurité) ou dollar faible, DOWN = confiance + USD fort.',
  },

  /* ─────────── Sessions forex ─────────── */
  session: {
    syd: 'SYD (Sydney) : 22h-07h UTC. Faible volume, mouvements en général contenus. AUD (dollar australien), NZD (dollar néo-zélandais) actifs.',
    tky: 'TKY (Tokyo) : 00h-09h UTC. Volume modéré. JPY (yen) crosses actifs, ranges serrés.',
    ldn: 'LDN (London — Londres) : 08h-17h UTC. ~35% du volume forex quotidien. EUR, GBP, CHF dynamiques.',
    ny: 'NY (New York) : 13h-22h UTC. ~25% du volume. Overlap London-NY (13h-17h UTC) = fenêtre la plus liquide.',
    weekend: 'Marché forex fermé : du vendredi 22h UTC au dimanche 22h UTC. Aucun setup ne part.',
    active: 'Session(s) actuellement ouverte(s). Peut y en avoir 0 (weekend), 1 (overlap matin/soir) ou 2 (overlap Londres-NY).',
  },

  /* ─────────── Performance / insights ─────────── */
  perf: {
    titreBucket: 'Agrégat de win rate (taux de réussite) et PnL par dimension. Source : endpoint /api/insights/performance. Limité aux trades post-fix (2026-04-20T21:14 UTC).',
    tradesTotal: 'Nombre total de trades clôturés depuis POST_FIX_CUTOFF (pipeline fiabilisé).',
    winRateGlobal: 'Win rate (taux de réussite) : ratio trades gagnants / trades totaux. Au-dessus de 50% = plus de wins que de losses (mais le PnL dépend aussi du R:R).',
    pnlTotal: 'PnL (Profit and Loss) total : somme cumulée des gains/pertes de tous les trades clôturés depuis le cutoff.',
    bucketName: 'Nom du bucket (panier) : intervalle de score, classe d\'actif, paire, session, régime macro ou sens selon l\'onglet sélectionné.',
    bucketCount: 'Count : nombre de trades tombés dans ce bucket.',
    bucketWinrate: 'Win rate du bucket. Barre colorée : verte > 60%, orange 45-60%, rouge < 45%.',
    bucketPnl: 'PnL cumulé du bucket. Un win rate élevé avec PnL négatif = on gagne souvent mais on perd gros quand on perd.',
  },

  /* ─────────── Équité ─────────── */
  equity: {
    titre: 'Equity curve (courbe d\'équité) : PnL (Profit and Loss) cumulé trade après trade depuis POST_FIX_CUTOFF. Un trade = un point. Reflète la chronologie des fermetures, pas le temps calendrier.',
    final: 'Final : gain ou perte cumulé à la fin de la série. Positif = stratégie rentable sur la période.',
    trades: 'Nombre de trades clôturés dans la série.',
  },

  /* ─────────── Analytics (breakdowns modèle) ─────────── */
  analytics: {
    titre: 'Analytics : décomposition du win rate (taux de réussite) par feature du signal. Source : table backtest.db (outcomes théoriques). Répond à "quelles dimensions prédisent le succès ?" — oriente les filtres à ajouter, instruments à retirer, heures à éviter.',
    byHour: 'Win rate par heure UTC (Coordinated Universal Time). Détecte les creux intraday (sessions asiatiques calmes, rollover 22h, etc.).',
    byPair: 'Win rate par paire. Un écart net entre paires = candidat au retrait des perdantes dans WATCHED_PAIRS.',
    byPattern: 'Win rate par pattern détecté (breakout, engulfing, etc.). Un pattern systématiquement en dessous de 45% = candidat à désactivation.',
    byConfidence: 'Win rate par bucket de confidence_score (score de confiance 0-100). Si la courbe est plate, le scoring n\'a pas de signal. Si elle monte avec le score, le modèle est calibré.',
    byAssetClass: 'Win rate par classe d\'actif (forex / metal / crypto / equity_index / energy). Aide à décider quelle classe activer en auto-exec (MT5_BRIDGE_ALLOWED_ASSET_CLASSES).',
    byRiskRegime: 'Win rate par régime macro (risk_on / risk_off / neutral). Si le modèle sous-performe fort en risk_off, activer MACRO_VETO_ENABLED.',
    executionQuality: 'Qualité d\'exécution : différence entre prix théorique du signal et fill réel au broker (slippage en pips) + répartition des raisons de fermeture (TP1 / TP2 / SL / MANUAL / TIMEOUT).',
    slippage: 'Slippage (glissement) : écart en pips entre le prix d\'entrée théorique du signal et le prix d\'exécution réel chez le broker. Positif = en notre faveur, négatif = contre nous. Moyenne haute = liquidité insuffisante sur l\'instrument.',
    closeReason: 'Close reason (raison de fermeture) : TP1/TP2 = take profit atteint, SL = stop loss touché, MANUAL = fermeture manuelle, TIMEOUT = maximum duration atteint, UNKNOWN = raison non remontée par le broker.',
    signalVolume: 'Signal volume : combien de signaux le radar génère par jour. Une baisse brutale = bug ou data source down. La répartition TAKE vs SKIP indique à quel point les filtres aval éliminent les signaux.',
    takeRatio: 'Take ratio : pourcentage de signaux qui passent tous les filtres et atteignent verdict TAKE. Typiquement 10-30% sain, < 5% = filtres trop stricts, > 50% = pas assez sélectif.',
    winRatePct: 'Win rate en pourcentage. Au-dessus de 50% = plus de trades gagnants que perdants. Mais le PnL dépend aussi du R:R : 40% de wins avec R:R 1:3 = stratégie rentable.',
    totalTrades: 'Nombre total de trades dans ce bucket (wins + losses). Plus c\'est élevé, plus la stat est fiable. < 10 trades = bruit statistique, à prendre avec des pincettes.',
  },
} as const;
