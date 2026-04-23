"""Emails transactionnels user (Chantier 11 SaaS).

Envois SMTP via la config existante (EMAIL_SMTP_*). Best-effort : si SMTP
n'est pas configuré ou l'envoi échoue, on log et on renvoie False — aucune
exception ne remonte, pas de blocage du flow signup / checkout / webhook.

Templates :
- welcome : après signup, mentionne les 14j de trial Pro
- trial_reminder : J-3 ou J-1 avant expiration trial
- sub_confirmed : après checkout réussi (upgrade/renewal)
- sub_cancelled : après annulation

Tous les templates sont en FR, tutoiement, ton simple et clair.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Literal

from config.settings import (
    EMAIL_FROM,
    EMAIL_SMTP_HOST,
    EMAIL_SMTP_PASSWORD,
    EMAIL_SMTP_PORT,
    EMAIL_SMTP_USER,
)

logger = logging.getLogger(__name__)

# URL publique de l'app pour les CTAs email. Surchargeable via env.
import os as _os

APP_URL = _os.getenv("APP_PUBLIC_URL", "https://app.scalping-radar.com/v2")


def is_configured() -> bool:
    """True si SMTP est configuré pour envoyer des emails."""
    return bool(EMAIL_SMTP_HOST and EMAIL_FROM)


def send_email(to_email: str, subject: str, html: str) -> bool:
    """Envoie un email. Best-effort : False si SMTP non configuré ou erreur.
    Ne lève jamais.
    """
    if not is_configured():
        logger.info("user_email_service inactif (EMAIL_SMTP_HOST vide) — skip %r", subject)
        return False
    if not to_email or "@" not in to_email:
        logger.warning("send_email : destination invalide %r", to_email)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if EMAIL_SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=10)
            server.starttls()
        try:
            if EMAIL_SMTP_USER and EMAIL_SMTP_PASSWORD:
                server.login(EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, [to_email], msg.as_string())
        finally:
            server.quit()
        logger.info("Email envoyé → %s : %s", to_email, subject)
        return True
    except Exception:
        logger.exception("send_email a échoué vers %s : %s", to_email, subject)
        return False


# ─── Templates ──────────────────────────────────────────────

_LAYOUT_HEAD = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #0b0f1a; color: #e7e9ee; margin: 0; padding: 20px; }
  .wrap { max-width: 520px; margin: 0 auto; background: #111726; border-radius: 16px;
          padding: 28px; border: 1px solid rgba(255,255,255,0.08); }
  .title { background: linear-gradient(135deg, #22d3ee, #ec4899); -webkit-background-clip: text;
           background-clip: text; color: transparent; font-size: 26px; font-weight: 700;
           margin: 0 0 12px; letter-spacing: -0.01em; }
  p { color: #d8dbe3; line-height: 1.6; margin: 10px 0; }
  .muted { color: #8a8f9b; font-size: 13px; }
  .btn { display: inline-block; padding: 12px 22px; margin-top: 12px;
         border-radius: 12px; background: linear-gradient(135deg, #22d3ee, #ec4899);
         color: #0b0f1a !important; text-decoration: none; font-weight: 600; font-size: 14px; }
  .callout { background: rgba(34,211,238,0.08); border: 1px solid rgba(34,211,238,0.25);
             border-radius: 10px; padding: 12px 16px; margin: 16px 0; color: #b9e9f5; font-size: 14px; }
  .foot { color: #6b707a; font-size: 12px; margin-top: 24px; text-align: center; }
</style>
"""


def _layout(title: str, body_html: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8">{_LAYOUT_HEAD}</head>
<body><div class="wrap">
<h1 class="title">{title}</h1>
{body_html}
<p class="foot">Scalping Radar · <a href="{APP_URL}/settings" style="color:#22d3ee">Gérer mon compte</a></p>
</div></body></html>"""


def send_welcome(to_email: str, trial_days: int = 14) -> bool:
    subject = "Bienvenue sur Scalping Radar 👋"
    body = f"""
<p>Hello,</p>
<p>Ton compte est créé et ton <strong>trial Pro de {trial_days} jours</strong> vient de démarrer — aucune CB requise.</p>
<div class="callout">
  Pendant {trial_days} jours, tu as accès à toutes les features Pro :
  5 paires surveillées, alertes Telegram, historique illimité, rejections log.
</div>
<p>Prochaine étape : <strong>installe le bridge MT5</strong> sur ton PC Windows
pour qu'on puisse exécuter automatiquement les setups détectés.</p>
<p><a href="{APP_URL}/onboarding" class="btn">Configurer mon bridge →</a></p>
<p class="muted">Besoin d'aide ? Consulte le <a href="/docs/bridge-setup.html" style="color:#22d3ee">guide d'installation</a> ou réponds à cet email.</p>
"""
    return send_email(to_email, subject, _layout("Bienvenue", body))


def send_trial_reminder(to_email: str, days_left: int) -> bool:
    """Rappel envoyé à J-3 ou J-1 avant expiration trial."""
    if days_left <= 1:
        subject = "⏳ Il te reste 1 jour de Trial Pro"
        accent = "expire <strong>demain</strong>"
    else:
        subject = f"⏳ Plus que {days_left} jours de Trial Pro"
        accent = f"expire dans <strong>{days_left} jours</strong>"
    body = f"""
<p>Hello,</p>
<p>Ton trial Pro {accent}. Au-delà, tes features Pro (alertes Telegram, rejections,
historique illimité) ne seront plus accessibles tant que tu n'auras pas upgradé.</p>
<p>Continue à bénéficier de tout ce que tu utilises déjà :</p>
<p><a href="{APP_URL}/pricing" class="btn">Passer en payant →</a></p>
<p class="muted">Si tu ne comptes pas continuer, rien à faire — ton compte reste actif en tier gratuit
avec 1 paire surveillée et 7 jours d'historique.</p>
"""
    return send_email(to_email, subject, _layout("Trial Pro", body))


def send_sub_confirmed(to_email: str, tier: str, billing_cycle: str | None) -> bool:
    subject = f"✅ Abonnement {tier.capitalize()} activé"
    cycle_label = (
        "annuel (12 mois)" if billing_cycle == "yearly"
        else "mensuel" if billing_cycle == "monthly"
        else ""
    )
    cycle_line = f"<p>Cycle de facturation : <strong>{cycle_label}</strong>.</p>" if cycle_label else ""
    body = f"""
<p>Hello,</p>
<p>Ton abonnement <strong>{tier.capitalize()}</strong> est actif.</p>
{cycle_line}
<p>Merci pour ta confiance — tu peux gérer ton abonnement, ta carte et tes factures
depuis ton espace :</p>
<p><a href="{APP_URL}/settings" class="btn">Mon compte →</a></p>
<p class="muted">Tu reçois cet email pour chaque changement important de ton abonnement.</p>
"""
    return send_email(to_email, subject, _layout("Abonnement activé", body))


def send_email_verification(to_email: str, token: str) -> bool:
    """Envoie le magic link de vérification email post-signup."""
    subject = "📧 Vérifie ton email Scalping Radar"
    verify_url = f"{APP_URL}/verify-email?token={token}"
    body = f"""
<p>Hello,</p>
<p>Merci d'avoir créé ton compte. Pour activer toutes les fonctionnalités
et recevoir tes alertes et rappels, clique sur le bouton ci-dessous pour
confirmer ton adresse email :</p>
<p><a href="{verify_url}" class="btn">Vérifier mon email →</a></p>
<p class="muted">Tu peux continuer à utiliser le radar en attendant, mais
certaines actions (upgrade, alertes) nécessitent un email vérifié.</p>
<p class="muted" style="font-size:11px;">Lien direct si le bouton ne marche pas :<br>
<span style="word-break:break-all">{verify_url}</span></p>
"""
    return send_email(to_email, subject, _layout("Vérification email", body))


def send_password_reset(to_email: str, token: str) -> bool:
    """Envoie le magic link de reset password. Valide 1h (côté backend)."""
    subject = "🔑 Réinitialise ton mot de passe Scalping Radar"
    reset_url = f"{APP_URL}/reset-password?token={token}"
    body = f"""
<p>Hello,</p>
<p>Tu as demandé à réinitialiser ton mot de passe. Clique sur le bouton ci-dessous
pour en choisir un nouveau. Ce lien expire dans <strong>1 heure</strong>.</p>
<p><a href="{reset_url}" class="btn">Choisir un nouveau mot de passe →</a></p>
<p class="muted">Si tu n'as pas fait cette demande, ignore cet email — ton mot de passe
actuel reste inchangé.</p>
<p class="muted" style="font-size:11px;">Lien direct si le bouton ne marche pas :<br>
<span style="word-break:break-all">{reset_url}</span></p>
"""
    return send_email(to_email, subject, _layout("Reset password", body))


def send_sub_cancelled(to_email: str) -> bool:
    subject = "Abonnement annulé · ton compte reste actif"
    body = f"""
<p>Hello,</p>
<p>Ton abonnement vient d'être annulé. Ton compte reste actif en tier gratuit
(1 paire surveillée, 7 jours d'historique).</p>
<p>Tu peux réactiver un plan à tout moment :</p>
<p><a href="{APP_URL}/pricing" class="btn">Voir les plans →</a></p>
<p class="muted">Si c'est une erreur ou si tu as des retours, réponds à cet email —
on lit tout.</p>
"""
    return send_email(to_email, subject, _layout("Annulation", body))


# ─── Sélection de template depuis un event Stripe ────────────

SubEventKind = Literal["confirmed", "cancelled"]


def dispatch_subscription_event(
    to_email: str,
    kind: SubEventKind,
    tier: str = "pro",
    billing_cycle: str | None = None,
) -> bool:
    if kind == "confirmed":
        return send_sub_confirmed(to_email, tier=tier, billing_cycle=billing_cycle)
    if kind == "cancelled":
        return send_sub_cancelled(to_email)
    logger.warning("dispatch_subscription_event : kind inconnu %r", kind)
    return False


# ─── Trial reminders (job scheduled) ─────────────────────────

def _trial_reminder_key(days_left: int) -> str | None:
    """Retourne la clé idempotente pour un rappel donné, ou None si pas à envoyer.

    On cible précisément J-3 et J-1 pour éviter le spam. Les users qui ratent
    la fenêtre (ex. job down pendant 2 jours) n'ont pas de rattrapage — c'est
    OK, le banner dans l'app suffit en redondance.
    """
    if days_left == 3:
        return "3d"
    if days_left == 1:
        return "1d"
    return None


def run_trial_reminders() -> dict:
    """Parcourt les users avec trial actif et envoie les rappels J-3 / J-1
    non encore envoyés. Idempotent.

    Retourne un dict résumé {considered, sent, skipped} pour observability.
    """
    from datetime import datetime, timezone

    from backend.services import users_service

    if not is_configured():
        return {"considered": 0, "sent": 0, "skipped": 0, "smtp_configured": False}

    users = users_service.list_users_with_active_trial()
    sent = 0
    skipped = 0
    for u in users:
        try:
            end = datetime.fromisoformat(u["trial_ends_at"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            skipped += 1
            continue
        days_left = (end - datetime.now(timezone.utc)).days
        key = _trial_reminder_key(days_left)
        if key is None:
            skipped += 1
            continue
        if key in users_service.get_trial_reminders_sent(u):
            skipped += 1
            continue
        if send_trial_reminder(u["email"], days_left=days_left):
            users_service.mark_trial_reminder_sent(u["id"], key)
            sent += 1
        else:
            skipped += 1

    logger.info(
        "trial_reminders : %d users, %d envoyés, %d skippés", len(users), sent, skipped
    )
    return {"considered": len(users), "sent": sent, "skipped": skipped, "smtp_configured": True}
