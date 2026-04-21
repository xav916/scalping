/** Catalogue centralisé des descriptions de métriques. Un seul endroit pour
 *  éditer les explications — si le vocabulaire change, on corrige ici.
 *  Clés groupées par zone pour faciliter la navigation. */

export const TIPS = {
  /* ─────────── Header / status global ─────────── */
  header: {
    v2Badge: 'Version 2 du dashboard (React + Vite). Coexiste avec la version legacy sur /.',
    statusLive: 'WebSocket temps réel connecté. Les setups, prix et cockpit sont poussés par le serveur sans rafraîchir.',
    statusSync: 'Connexion WebSocket en cours. Mode dégradé (poll 60s) le temps que le socket rétablisse.',
    statusOffline: 'WebSocket indisponible. On continue avec du polling périodique mais avec latence.',
    soundOn: 'Bip audio sur nouveau setup TAKE (verdict = exécution conseillée). Un seul bip même si plusieurs arrivent ensemble.',
    soundOff: 'Alertes audio désactivées. Telegram reste la source principale des notifications.',
  },

  /* ─────────── Kill switch + alertes ─────────── */
  killSwitch: {
    title: "Coupe-circuit global de l'auto-exec. Bloque l'envoi de nouveaux ordres au bridge MT5 sans toucher aux trades déjà ouverts (ils vont à leur SL/TP).",
    active: "Auto-exec GELÉ. Cause possible : perte journalière ≥ 3% du capital (trigger auto) ou activation manuelle.",
    okState: "Auto-exec opérationnel. Un setup TAKE qui dépasse le seuil MIN_CONFIDENCE sera envoyé au bridge.",
    autoTrigger: "Le kill switch s'active automatiquement si le PnL du jour atteint -DAILY_LOSS_LIMIT_PCT (3% par défaut) du capital.",
    manualToggle: "Gel/dégel manuel. Utile pour maintenance broker, doute sur une news imminente, ou weekend.",
  },

  alerts: {
    title: "Notifications issues du backend. Critiques (rouge) = action requise, warnings (orange) = vigilance, infos (cyan) = contexte.",
    kill_switch: "Auto-exec gelé — aucun nouvel ordre ne part tant que le kill switch est actif.",
    near_sl: "Un trade ouvert est à moins de 30% de sa distance entry→SL. Potentiel stop imminent.",
    high_impact_event: "Event macro HIGH impact dans les 4 prochaines heures (NFP, CPI, FOMC, BCE…).",
    event_blackout: "Blackout actif autour d'un event HIGH impact : les setups sur la devise concernée sont ignorés.",
    cot_extreme: "Positionnement CFTC à ≥ 2σ de la moyenne 52s. Signal contrarien potentiel.",
    fear_greed_extreme: "CNN Fear & Greed en zone extrême (< 25 ou > 75). Souvent associé à des retournements courts terme.",
  },

  /* ─────────── Aujourd'hui (stats du jour) ─────────── */
  today: {
    pnlJour: "PnL réalisé sur les trades clôturés aujourd'hui (0h UTC → maintenant). Exclut les positions encore ouvertes.",
    pnlPct: "PnL du jour en pourcentage du capital de référence (TRADING_CAPITAL).",
    nonRealise: "Somme des PnL des positions encore ouvertes, calculée au dernier prix connu. Varie en temps réel.",
    exposition: "Somme des tailles en lots de toutes les positions ouvertes.",
    trades: "Nombre total de trades crées aujourd'hui (ouverts + clôturés). Inclut les auto-exec et les manuels si relevants.",
    closurés: "Nombre de trades ayant atteint leur SL/TP ou fermés manuellement aujourd'hui.",
    ouverts: "Nombre de positions actuellement live côté broker.",
    capital: "Capital de référence (env var TRADING_CAPITAL). Utilisé pour calculer les % de risque, pas le solde broker réel.",
  },

  /* ─────────── Capital en jeu ─────────── */
  capital: {
    titre: "Synthèse du capital engagé sur les positions ouvertes. Le calcul utilise abs(entry-SL) × units × size — approximation USD ignorant les conversions cross-currency.",
    aRisque: "Perte maximale cumulée si TOUTES les positions touchent leur SL en même temps. C'est le vrai montant à risque.",
    risquePct: "Capital à risque exprimé en % du TRADING_CAPITAL de référence. En général on vise < 5% cumulé.",
    notionnel: "Valeur sous-jacente totale (entry × units × size). Pas ce qui est à risque, mais ce qui est exposé aux mouvements de marché.",
    expositionTotale: "Autre nom pour le notionnel. Indique le 'levier' total des positions.",
    top5: "Les 5 positions qui pèsent le plus en perte potentielle. Utile pour identifier une concentration.",
  },

  /* ─────────── Répartition / asset class ─────────── */
  repartition: {
    titre: "Répartition du risque (perte max cumulée) par classe d'actif. Aide à détecter une sur-exposition sur un type d'instrument.",
    forex: "Paires de devises (EUR/USD, USD/JPY, etc.).",
    metal: "Métaux précieux (XAU/USD, XAG/USD).",
    crypto: "Crypto-actifs (BTC/USD, ETH/USD).",
    equity_index: "Indices boursiers (SPX, NDX).",
    energy: "Énergie (WTI/USD, Brent).",
    unknown: "Actifs non classés (rare — indique souvent un mapping manquant).",
  },

  /* ─────────── Fear & Greed ─────────── */
  fearGreed: {
    titre: "CNN Fear & Greed Index 0-100 basé sur 7 sous-indicateurs (momentum S&P, nouveaux highs/lows, put/call, VIX, safe haven demand, junk bond demand, breadth). Fetch quotidien 22:30 UTC.",
    extreme_fear: "0-25 : panique maximale. Historiquement zone d'achat contrarien mais peut persister.",
    fear: "25-45 : prudence. Les marchés actions sous-performent en général.",
    neutral: "45-55 : sentiment équilibré.",
    greed: "55-75 : appétit au risque. Les assets risqués montent.",
    extreme_greed: "75-100 : euphorie. Historiquement zone de vente contrarienne.",
  },

  /* ─────────── Santé système ─────────── */
  sante: {
    titre: "Check rapide de l'infra : scheduler vivant, bridge MT5 joignable, WebSocket clients, session en cours.",
    cycle: "Temps écoulé depuis le dernier cycle d'analyse. < 600s = healthy. Au-delà, on a un problème côté scheduler ou data source.",
    bridge: "État du bridge MT5 (VPS Windows) : UP = répond aux pings, DOWN = injoignable (firewall/VPN/process mort), N/A = pas configuré.",
    clientsWs: "Nombre de tabs/devices connectés en WebSocket. Si tu es seul sur le dashboard, ça devrait être 1.",
    session: "Session forex active (Asian/London/NY overlap, etc.). Utilisé dans le sizing multiplier.",
  },

  /* ─────────── Drift ─────────── */
  drift: {
    titre: "Détection de régression : paires ou patterns dont le win rate des 7 derniers jours chute de > 15 points vs la baseline historique. Minimum 10 trades récents pour éviter le bruit.",
    delta: "Écart en points de pourcentage entre win rate récent et baseline. Plus c'est négatif, plus la régression est forte.",
    action: "Un drift soutenu suggère de désactiver le pattern ou la paire, ou d'enquêter sur un changement de régime.",
  },

  /* ─────────── COT ─────────── */
  cot: {
    titre: "Commitments of Traders (CFTC) : positionnement des leveraged funds (smart money) et petits traders (contrarien). Fetch hebdo samedi 01h UTC. Extremes = z-score ≥ 2σ sur 52 semaines.",
    leveraged_funds: "Hedge funds / traders institutionnels. Long extrême = momentum bull, short extrême = pression baissière.",
    non_reportables: "Petits traders non déclarés. Souvent contrariens : leur long extrême signale souvent un top proche.",
    z: "Z-score de la position nette actuelle vs moyenne 52 semaines. |z| ≥ 2 = extrême statistique.",
  },

  /* ─────────── Events macro ─────────── */
  events: {
    titre: "Events macro de ForexFactory dans les 4 prochaines heures. HIGH impact déclenche un blackout sur la devise concernée.",
    impactHigh: "Event à fort impact : NFP, CPI, décision FOMC/BCE, GDP. Volatilité explosive, setups bloqués ±15 min autour.",
    impactMedium: "Impact modéré : PMI, unemployment claims, sentiment. À surveiller mais pas toujours bloquant.",
    impactLow: "Impact faible. Rarement action mais visible dans le calendrier.",
  },

  /* ─────────── Trades actifs ─────────── */
  trade: {
    pair: "Symbole de l'instrument tradé (base/quote).",
    direction: "Sens de la position : buy (long = parie sur la hausse) ou sell (short = parie sur la baisse).",
    entryPrice: "Prix d'entrée théorique du setup. Peut différer légèrement du fill réel chez le broker.",
    currentPrice: "Dernier prix connu (tick WebSocket Twelve Data ou dernière bougie 5m).",
    stopLoss: "Prix de sortie si la position perd. Placé par l'algo selon pattern + ATR. Ne peut plus être modifié une fois l'ordre envoyé.",
    takeProfit: "Prix cible de sortie en profit. TP1 premier palier, TP2 (si présent) extension.",
    sizeLot: "Taille de la position en lots MT5. Déterminée par le sizing dynamique côté bridge.",
    riskMoney: "Perte maximale si le SL est touché. Calculé avec une approximation USD (units_per_lot × taille × distance SL).",
    notional: "Valeur notionnelle de la position (prix × units × size). Mesure l'exposition sous-jacente.",
    pnlUnrealized: "Gain/perte latent au prix actuel. Se matérialisera qu'à la fermeture.",
    pnlPips: "Variation en pips depuis l'entrée. 1 pip = 0.0001 sur forex standard, 0.01 sur JPY et métaux.",
    distanceSl: "Pourcentage de la distance entry→SL encore disponible. < 30% = alerte near_sl.",
    distanceTp: "Pourcentage de la distance entry→TP restant à parcourir.",
    nearSl: "La position est à moins de 30% de son stop. Stop probable dans les prochaines minutes sauf rebond.",
    duration: "Temps écoulé depuis l'ouverture du trade (minutes).",
    isAuto: "1 = envoyé automatiquement par le bridge, 0 = trade manuel (l'ancien flow, désormais supprimé).",
    mt5Ticket: "Numéro de ticket côté broker. Utilisé pour la réconciliation et le suivi de fermeture.",
    assetClass: "Classe d'actif (forex/metal/crypto/equity_index/energy). Détermine les règles de sizing et les horaires autorisés.",
  },

  /* ─────────── Confidence / verdict (setup cards) ─────────── */
  setup: {
    confidenceGauge: "Score de confiance 0-100 agrégeant pattern, R/R, contexte macro, session. Seuil auto-exec : ≥ 55 (env var MT5_BRIDGE_MIN_CONFIDENCE).",
    rr: "Ratio Risk/Reward : distance entry→TP divisée par entry→SL. 1:1.5 signifie qu'on vise 1.5× le risque.",
    verdictTake: "TAKE = l'algo recommande l'exécution (confidence ≥ seuil + alignement macro + pas de blackout).",
    verdictWait: "WAIT = signal valide mais contexte défavorable (session calme, macro contre, SL trop serré). On patiente.",
    verdictSkip: "SKIP = on ignore (blackout event, kill switch, is_simulated, marché fermé, etc.).",
  },

  /* ─────────── Macro banner ─────────── */
  macro: {
    risk_regime: "Régime macro synthétique dérivé de DXY + VIX + SPX + US10Y. risk_on = appétit au risque, risk_off = fuite vers actifs sûrs, neutral = indécis.",
    dxy: "Dollar Index (USD vs panier 6 devises). UP = dollar fort (pression sur gold, indices US, cross USD), DOWN = dollar faible.",
    spx: "S&P 500 sur la journée. UP = appétit equity, DOWN = aversion au risque.",
    vix: "VIX = volatilité implicite S&P 30 jours. low (<15) = calme, normal (15-20), elevated (20-30), high (>30) = stress.",
    us10y: "Rendement obligataire US 10 ans. UP = inflation/hawk Fed, DOWN = recherche de sécurité / dovish.",
    de10y: "Rendement Bund allemand 10 ans. Comparé à US10Y pour le spread trans-Atlantique (influence EUR/USD).",
    oil: "WTI. UP = inflation + CAD/NOK renforcés, DOWN = déflation + JPY/CHF privilégiés.",
    nikkei: "Nikkei 225. UP = risk-on asiatique, DOWN = JPY en fuite.",
    gold: "XAU/USD. UP = flight to safety ou dollar faible, DOWN = confiance + USD fort.",
  },

  /* ─────────── Sessions forex ─────────── */
  session: {
    syd: "Sydney : 22h-07h UTC. Faible volume, mouvements en général contenus. AUD/NZD actifs.",
    tky: "Tokyo : 00h-09h UTC. Volume modéré. JPY crosses actifs, ranges serrés.",
    ldn: "London : 08h-17h UTC. ~35% du volume forex daily. EUR/GBP/CHF dynamiques.",
    ny: "New York : 13h-22h UTC. ~25% du volume. Overlap London-NY (13h-17h) = fenêtre la plus liquide.",
    weekend: "Marché forex fermé (vendredi 22h UTC → dimanche 22h UTC). Aucun setup ne part.",
    active: "Session(s) actuellement ouverte(s). Peut y en avoir 0 (weekend), 1 (overlap matin/soir) ou 2 (overlap Londres-NY).",
  },

  /* ─────────── Performance / insights ─────────── */
  perf: {
    titreBucket: "Agrégat de win rate / PnL par dimension. Source : /api/insights/performance. Limité aux trades post-fix (2026-04-20T21:14).",
    tradesTotal: "Nombre total de trades clôturés depuis POST_FIX_CUTOFF (pipeline fiabilisé).",
    winRateGlobal: "Ratio trades gagnants / trades totaux. Au-dessus de 50% = plus de wins que de losses (mais le PnL dépend aussi du R:R).",
    pnlTotal: "Somme cumulée des PnL de tous les trades clôturés depuis le cutoff.",
    bucketName: 'Nom du bucket : intervalle de score, classe d\'actif, paire, session, régime macro, ou sens selon l\'onglet.',
    bucketCount: 'Nombre de trades tombés dans ce bucket.',
    bucketWinrate: 'Win rate du bucket. Barre colorée verte > 60%, orange 45-60%, rouge < 45%.',
    bucketPnl: 'PnL cumulé du bucket. Un win rate élevé avec PnL négatif = on gagne souvent mais on perd gros quand on perd.',
  },

  /* ─────────── Équité ─────────── */
  equity: {
    titre: "Courbe d'équité : PnL cumulé trade après trade depuis POST_FIX_CUTOFF. Un trade = un point. Ne reflète pas le temps calendrier mais la chronologie des fermetures.",
    final: "Gain/perte cumulé à la fin de la série. Positif = stratégie rentable sur la période.",
    trades: "Nombre de trades clôturés dans la série.",
  },
} as const;
