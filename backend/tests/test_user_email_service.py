"""Tests emails transactionnels (Chantier 11 SaaS)."""

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.services import user_email_service, users_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE personal_trades (id INTEGER PRIMARY KEY, user TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(users_service, "_DB_PATH", db_file)
    users_service.init_users_schema()
    return db_file


@pytest.fixture
def smtp_on(monkeypatch):
    monkeypatch.setattr(user_email_service, "EMAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(user_email_service, "EMAIL_SMTP_PORT", 465)
    monkeypatch.setattr(user_email_service, "EMAIL_SMTP_USER", "bot@example.com")
    monkeypatch.setattr(user_email_service, "EMAIL_SMTP_PASSWORD", "pw")
    monkeypatch.setattr(user_email_service, "EMAIL_FROM", "Scalping <no-reply@example.com>")


# ─── is_configured + send_email fallback ──────────────────

def test_send_email_noop_when_smtp_unconfigured(monkeypatch):
    monkeypatch.setattr(user_email_service, "EMAIL_SMTP_HOST", "")
    monkeypatch.setattr(user_email_service, "EMAIL_FROM", "")
    # Ne lève pas, retourne False silencieusement.
    assert user_email_service.send_email("a@b.com", "s", "<p>h</p>") is False


def test_send_email_rejects_bad_email(smtp_on):
    assert user_email_service.send_email("", "s", "<p>h</p>") is False
    assert user_email_service.send_email("no-at-sign", "s", "<p>h</p>") is False


def test_send_email_calls_smtp(smtp_on):
    fake_server = MagicMock()
    with patch.object(user_email_service.smtplib, "SMTP_SSL", return_value=fake_server) as mk:
        ok = user_email_service.send_email("alice@test.com", "Sujet", "<p>Hello</p>")
    assert ok is True
    mk.assert_called_once()
    fake_server.login.assert_called_once_with("bot@example.com", "pw")
    fake_server.sendmail.assert_called_once()
    fake_server.quit.assert_called_once()


def test_send_email_swallows_smtp_errors(smtp_on):
    with patch.object(user_email_service.smtplib, "SMTP_SSL", side_effect=OSError("down")):
        ok = user_email_service.send_email("a@b.com", "s", "<p>h</p>")
    assert ok is False


# ─── Templates : juste vérifier qu'elles produisent un HTML non-vide ──

def test_welcome_template_contains_trial(smtp_on):
    with patch.object(user_email_service, "send_email", return_value=True) as mk:
        user_email_service.send_welcome("x@y.com", trial_days=14)
    args = mk.call_args
    assert "Bienvenue" in args.args[1]  # subject
    assert "14 jours" in args.args[2] or "trial" in args.args[2].lower()


def test_trial_reminder_1d_variant(smtp_on):
    with patch.object(user_email_service, "send_email", return_value=True) as mk:
        user_email_service.send_trial_reminder("x@y.com", days_left=1)
    subject = mk.call_args.args[1]
    html = mk.call_args.args[2]
    assert "1 jour" in subject
    assert "demain" in html.lower()


def test_trial_reminder_3d_variant(smtp_on):
    with patch.object(user_email_service, "send_email", return_value=True) as mk:
        user_email_service.send_trial_reminder("x@y.com", days_left=3)
    assert "3 jours" in mk.call_args.args[1]


def test_sub_confirmed_template(smtp_on):
    with patch.object(user_email_service, "send_email", return_value=True) as mk:
        user_email_service.send_sub_confirmed("x@y.com", tier="premium", billing_cycle="yearly")
    html = mk.call_args.args[2]
    assert "Premium" in html
    assert "annuel" in html.lower()


def test_dispatch_subscription_event(smtp_on):
    with patch.object(user_email_service, "send_sub_confirmed", return_value=True) as mk_c:
        user_email_service.dispatch_subscription_event(
            "x@y.com", kind="confirmed", tier="pro", billing_cycle="monthly"
        )
    mk_c.assert_called_once()

    with patch.object(user_email_service, "send_sub_cancelled", return_value=True) as mk_x:
        user_email_service.dispatch_subscription_event("x@y.com", kind="cancelled")
    mk_x.assert_called_once()


# ─── Trial reminders scheduled job ─────────────────────────

def _now_plus(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_reminder_key_j3_j1():
    assert user_email_service._trial_reminder_key(3) == "3d"
    assert user_email_service._trial_reminder_key(1) == "1d"
    assert user_email_service._trial_reminder_key(5) is None
    assert user_email_service._trial_reminder_key(0) is None


def test_run_trial_reminders_noop_when_smtp_unconfigured(db, monkeypatch):
    monkeypatch.setattr(user_email_service, "EMAIL_SMTP_HOST", "")
    monkeypatch.setattr(user_email_service, "EMAIL_FROM", "")
    result = user_email_service.run_trial_reminders()
    assert result["smtp_configured"] is False
    assert result["sent"] == 0


def test_run_trial_reminders_sends_j3(db, smtp_on):
    # User avec trial qui expire dans ~3 jours
    uid = users_service.create_user(
        "alice@test.com", "pw12345678", tier="pro",
        trial_ends_at=_now_plus(3.1),  # légèrement plus de 3j (int days truncate à 3)
    )
    with patch.object(user_email_service, "send_email", return_value=True) as mk:
        result = user_email_service.run_trial_reminders()
    assert result["sent"] == 1
    mk.assert_called_once()
    # Flag persisté.
    user = users_service.get_user_by_id(uid)
    assert "3d" in users_service.get_trial_reminders_sent(user)


def test_run_trial_reminders_idempotent(db, smtp_on):
    uid = users_service.create_user(
        "alice@test.com", "pw12345678", tier="pro",
        trial_ends_at=_now_plus(3.1),
    )
    with patch.object(user_email_service, "send_email", return_value=True):
        user_email_service.run_trial_reminders()
        # 2e appel : doit skipper car déjà envoyé.
        second = user_email_service.run_trial_reminders()
    assert second["sent"] == 0
    assert second["skipped"] >= 1


def test_run_trial_reminders_skips_non_reminder_windows(db, smtp_on):
    users_service.create_user(
        "x@y.com", "pw12345678", tier="pro",
        trial_ends_at=_now_plus(7.1),  # trop loin
    )
    with patch.object(user_email_service, "send_email", return_value=True) as mk:
        result = user_email_service.run_trial_reminders()
    assert result["sent"] == 0
    mk.assert_not_called()


def test_run_trial_reminders_ignores_paying_users(db, smtp_on):
    """Un user qui a upgradé ne reçoit plus de rappels (stripe_subscription_id set)."""
    uid = users_service.create_user(
        "x@y.com", "pw12345678", tier="pro",
        trial_ends_at=_now_plus(1.1),
    )
    users_service.update_stripe_subscription(
        uid, subscription_id="sub_abc", tier="pro", billing_cycle="monthly"
    )
    with patch.object(user_email_service, "send_email", return_value=True) as mk:
        result = user_email_service.run_trial_reminders()
    assert result["sent"] == 0
    mk.assert_not_called()


def test_list_users_with_active_trial(db):
    uid_active = users_service.create_user(
        "alice@test.com", "pw12345678", tier="pro",
        trial_ends_at=_now_plus(5),
    )
    users_service.create_user(
        "expired@test.com", "pw12345678", tier="pro",
        trial_ends_at=_now_plus(-1),
    )
    users_service.create_user("free@test.com", "pw12345678", tier="free")

    active = users_service.list_users_with_active_trial()
    active_ids = [u["id"] for u in active]
    assert uid_active in active_ids
    assert len(active) == 1


def test_mark_trial_reminder_sent_dedup(db):
    uid = users_service.create_user(
        "x@y.com", "pw12345678", tier="pro",
        trial_ends_at=_now_plus(3),
    )
    users_service.mark_trial_reminder_sent(uid, "3d")
    users_service.mark_trial_reminder_sent(uid, "3d")  # no-op
    users_service.mark_trial_reminder_sent(uid, "1d")
    user = users_service.get_user_by_id(uid)
    assert users_service.get_trial_reminders_sent(user) == ["3d", "1d"]
