from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.password_reset_delivery import (
    InvitationDeliveryError,
    deliver_invitation_email,
    invitation_delivery_configuration_errors,
)


def _delivery_settings(**overrides) -> Settings:
    values = {
        "invitation_email_enabled": True,
        "auth_email_from": "OpenPartsFlow <security@example.com>",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "relay-user",
        "smtp_password": "relay-password",
        "smtp_use_starttls": True,
        "smtp_use_ssl": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class _SmtpRecorder:
    def __init__(self, *_args, **_kwargs):
        self.messages = []
        self.started_tls = False
        self.login_credentials = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def ehlo(self):
        return None

    def starttls(self, **_kwargs):
        self.started_tls = True

    def login(self, username, password):
        self.login_credentials = (username, password)

    def send_message(self, message):
        self.messages.append(message)


def test_invitation_email_uses_tls_and_contains_the_single_use_link(monkeypatch):
    recorder = _SmtpRecorder()
    monkeypatch.setattr(
        "app.services.password_reset_delivery.smtplib.SMTP",
        lambda *_args, **_kwargs: recorder,
    )
    config = _delivery_settings()

    deliver_invitation_email(
        recipient="engineer@example.com",
        recipient_name="Field Engineer",
        organization_name="Example Service",
        role="engineer",
        invitation_url="https://parts.example.com/accept-invitation?token=secret",
        config=config,
    )

    assert recorder.started_tls is True
    assert recorder.login_credentials == ("relay-user", "relay-password")
    assert len(recorder.messages) == 1
    message = recorder.messages[0]
    assert message["To"] == "engineer@example.com"
    assert "Example Service" in message["Subject"]
    assert "token=secret" in message.get_content()
    assert "72 hours" in message.get_content()


def test_invitation_email_configuration_and_headers_fail_closed():
    disabled = _delivery_settings(invitation_email_enabled=False)
    assert invitation_delivery_configuration_errors(disabled) == [
        "Invitation email delivery is disabled"
    ]

    with pytest.raises(InvitationDeliveryError, match="invalid_recipient"):
        deliver_invitation_email(
            recipient="engineer@example.com\r\nBcc: attacker@example.com",
            recipient_name="Engineer",
            organization_name="Example Service",
            role="engineer",
            invitation_url="https://parts.example.com/accept-invitation?token=secret",
            config=_delivery_settings(),
        )
