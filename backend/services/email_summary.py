"""Resume email quotidien des signaux et trades.

Envoi via SMTP (Gmail, Sendgrid, etc.). Configuration via variables d'env.
Si EMAIL_SMTP_HOST n'est pas defini, le service est inactif.
"""

import logging
import smtplib
from datetime import date, datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from backend.services import backtest_service, trade_log_service
from config.settings import (
    EMAIL_FROM,
    EMAIL_RECIPIENTS,
    EMAIL_SMTP_HOST,
    EMAIL_SMTP_PASSWORD,
    EMAIL_SMTP_PORT,
    EMAIL_SMTP_USER,
)

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(EMAIL_SMTP_HOST and EMAIL_FROM and EMAIL_RECIPIENTS)


def _build_summary_html(user: str | None = None) -> tuple[str, str]:
    """Retourne (subject, html) du resume du jour."""
    today = date.today().isoformat()
    bt_stats = backtest_service.get_stats()
    user_label = user or "tous les utilisateurs"

    if user:
        daily = trade_log_service.get_daily_status(user=user)
        trades = trade_log_service.list_trades(limit=50, user=user)
    else:
        daily = {"pnl_today": 0, "n_trades_today": 0}
        trades = []

    subject = f"[Scalping Radar] Recap {today} ({user_label})"
    rows = "".join([
        f"<tr><td>{t['pair']}</td><td>{t['direction'].upper()}</td><td>{t['status']}</td><td>{t.get('pnl', 0):+.2f}</td></tr>"
        for t in trades[:20]
    ])
    html = f"""
    <h2>📡 Scalping Radar — Récap du {today}</h2>
    <p><strong>Utilisateur :</strong> {user_label}</p>
    <h3>Activité personnelle</h3>
    <ul>
      <li>Trades du jour : {daily.get('n_trades_today', 0)}</li>
      <li>PnL du jour : <strong>{daily.get('pnl_today', 0):+.2f} USD</strong> ({daily.get('pnl_pct', 0):+.2f}%)</li>
    </ul>
    <h3>Backtest signaux radar</h3>
    <ul>
      <li>Total trades trackés : {bt_stats['total_trades']}</li>
      <li>Win rate : {bt_stats['win_rate_pct']}%</li>
      <li>R:R moyen : {bt_stats['avg_rr_realized']}</li>
    </ul>
    <h3>Vos derniers trades</h3>
    <table border="1" cellpadding="5" style="border-collapse:collapse">
      <tr><th>Paire</th><th>Direction</th><th>Statut</th><th>PnL</th></tr>
      {rows}
    </table>
    <p style="margin-top:20px;color:#888">--<br>Scalping Radar (auto)</p>
    """
    return subject, html


def send_daily_summary(user: str | None = None) -> bool:
    if not is_configured():
        logger.info("Email summary non configure (EMAIL_SMTP_HOST vide)")
        return False
    subject, html = _build_summary_html(user=user)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(EMAIL_RECIPIENTS)
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as s:
            if EMAIL_SMTP_USER and EMAIL_SMTP_PASSWORD:
                s.login(EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD)
            s.sendmail(EMAIL_FROM, EMAIL_RECIPIENTS, msg.as_string())
        logger.info(f"Email summary envoye a {EMAIL_RECIPIENTS}")
        return True
    except Exception as e:
        logger.warning(f"Email summary erreur: {e}")
        return False
