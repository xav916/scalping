"""Tests pour la whitelist signup (bypass SAAS_SIGNUP_ENABLED=false).

Permet de tester le funnel signup end-to-end en prod pendant la beta
fermée. Le match supporte le wildcard `*` dans la partie locale
(ex: `couderc.xavier+*@gmail.com`).
"""

from config.settings import email_in_whitelist


class TestEmailInWhitelist:
    def test_empty_whitelist_rejects_everything(self):
        assert email_in_whitelist("foo@bar.com", patterns=[]) is False

    def test_empty_email_always_false(self):
        assert email_in_whitelist("", patterns=["foo@bar.com"]) is False

    def test_exact_match_case_insensitive(self):
        patterns = ["couderc.xavier@gmail.com"]
        assert email_in_whitelist("couderc.xavier@gmail.com", patterns) is True
        assert email_in_whitelist("COUDERC.XAVIER@gmail.com", patterns) is True
        assert email_in_whitelist(" couderc.xavier@gmail.com ", patterns) is True

    def test_non_match_returns_false(self):
        patterns = ["couderc.xavier@gmail.com"]
        assert email_in_whitelist("other@gmail.com", patterns) is False
        assert email_in_whitelist("couderc.xavier@yahoo.com", patterns) is False

    def test_wildcard_gmail_alias(self):
        patterns = ["couderc.xavier+*@gmail.com"]
        assert email_in_whitelist("couderc.xavier+test1@gmail.com", patterns) is True
        assert email_in_whitelist("couderc.xavier+beta@gmail.com", patterns) is True
        assert email_in_whitelist("couderc.xavier+a.b.c@gmail.com", patterns) is True
        # Empty alias still matches (star is 0+)
        assert email_in_whitelist("couderc.xavier+@gmail.com", patterns) is True
        # Without the + prefix doesn't match the +* pattern
        assert email_in_whitelist("couderc.xavier@gmail.com", patterns) is False
        # Different domain doesn't match
        assert email_in_whitelist("couderc.xavier+test@yahoo.com", patterns) is False

    def test_multiple_patterns(self):
        patterns = [
            "admin@company.com",
            "couderc.xavier+*@gmail.com",
            "tester@example.org",
        ]
        assert email_in_whitelist("admin@company.com", patterns) is True
        assert email_in_whitelist("couderc.xavier+test@gmail.com", patterns) is True
        assert email_in_whitelist("tester@example.org", patterns) is True
        assert email_in_whitelist("intruder@other.com", patterns) is False

    def test_wildcard_on_domain_works_too(self):
        # fnmatchcase supports * anywhere, including in domain part.
        # Kept permissive — if the admin wants to whitelist all @company.com,
        # pattern `*@company.com` works.
        patterns = ["*@company.com"]
        assert email_in_whitelist("alice@company.com", patterns) is True
        assert email_in_whitelist("bob@company.com", patterns) is True
        assert email_in_whitelist("alice@other.com", patterns) is False
