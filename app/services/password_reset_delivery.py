from __future__ import annotations

from email.message import EmailMessage
from email.utils import parseaddr
import smtplib
import ssl

from app.core.config import Settings, settings


class PasswordResetDeliveryError(RuntimeError):
    pass


def password_reset_configuration_errors(config: Settings = settings) -> list[str]:
    if not config.password_reset_email_enabled:
        return ["Password reset email delivery is disabled"]
    errors: list[str] = []
    _, sender = parseaddr(config.auth_email_from)
    if not sender or "@" not in sender or "\r" in config.auth_email_from or "\n" in config.auth_email_from:
        errors.append("AUTH_EMAIL_FROM must be a valid email sender")
    if not config.smtp_host.strip() or any(character.isspace() for character in config.smtp_host):
        errors.append("SMTP_HOST must be configured without whitespace")
    if not 1 <= config.smtp_port <= 65535:
        errors.append("SMTP_PORT must be between 1 and 65535")
    if config.smtp_use_ssl == config.smtp_use_starttls:
        errors.append("Exactly one of SMTP_USE_SSL or SMTP_USE_STARTTLS must be true")
    if not 1 <= config.smtp_timeout_seconds <= 60:
        errors.append("SMTP_TIMEOUT_SECONDS must be between 1 and 60")
    if bool(config.smtp_username) != bool(config.smtp_password):
        errors.append("SMTP_USERNAME and SMTP_PASSWORD must be configured together")
    return errors


def password_reset_delivery_available(config: Settings = settings) -> bool:
    return not password_reset_configuration_errors(config)


def deliver_password_reset_email(
    *,
    recipient: str,
    recipient_name: str,
    reset_url: str,
    config: Settings = settings,
) -> None:
    errors = password_reset_configuration_errors(config)
    if errors:
        raise PasswordResetDeliveryError("password_reset_delivery_unavailable")

    _, recipient_address = parseaddr(recipient)
    if (
        not recipient_address
        or "@" not in recipient_address
        or "\r" in recipient
        or "\n" in recipient
    ):
        raise PasswordResetDeliveryError("invalid_recipient")
    safe_name = recipient_name.replace("\r", " ").replace("\n", " ").strip()[:120]
    try:
        message = EmailMessage()
        message["From"] = config.auth_email_from
        message["To"] = recipient_address
        message["Subject"] = "Reset your OpenPartsFlow password"
        message.set_content(
            f"Hello {safe_name},\n\n"
            "A password reset was requested for your OpenPartsFlow account.\n\n"
            f"Open this single-use link within {config.password_reset_expire_minutes} minutes:\n"
            f"{reset_url}\n\n"
            "If you did not request this, ignore this email. Your current password remains unchanged.\n"
        )
    except ValueError as exc:
        raise PasswordResetDeliveryError("invalid_message") from exc

    context = ssl.create_default_context()
    try:
        if config.smtp_use_ssl:
            client = smtplib.SMTP_SSL(
                config.smtp_host,
                config.smtp_port,
                timeout=config.smtp_timeout_seconds,
                context=context,
            )
        else:
            client = smtplib.SMTP(
                config.smtp_host,
                config.smtp_port,
                timeout=config.smtp_timeout_seconds,
            )
        with client:
            if config.smtp_use_starttls:
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            if config.smtp_username:
                client.login(config.smtp_username, config.smtp_password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise PasswordResetDeliveryError(type(exc).__name__.lower()) from exc
